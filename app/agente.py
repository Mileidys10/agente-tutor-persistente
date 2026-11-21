"""AgenteTutor: el agente persistente.

Ciclo autónomo (cada TUTOR_INTERVALO_S segundos, en un hilo de fondo):
  1. PERCIBIR  lee su memoria: temas vencidos, preguntas pendientes, mazos activos, tarjetas nuevas de hoy.
  2. DECIDIR   prioriza qué repasar (retraso + dificultad) y si toca presentar una DevCard nueva.
  3. ACTUAR    prepara las preguntas y deja registrado en la bitácora por qué lo decidió.
Al responder la persona: corrige, actualiza SM-2 y programa el próximo repaso.
Todo el estado está en la base de datos: si el proceso muere, al volver retoma donde iba.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import timedelta
from typing import Any, Optional

from app.banco_devcards import LETRAS, BancoDevCards
from app.cerebro import Cerebro, _normalizar
from app.config import Config
from app.memoria import Memoria, ahora
from app import sm2

log = logging.getLogger("tutor.agente")
LATIDO_BITACORA_CADA = 20  # ciclos sin novedades entre dos anotaciones de "sigo vivo"


def _hace(minutos: float) -> str:
    if minutos < 1:
        return "hace menos de un minuto"
    if minutos < 60:
        return f"hace {minutos:.0f} min"
    if minutos < 60 * 48:
        return f"hace {minutos / 60:.1f} h"
    return f"hace {minutos / 1440:.1f} días"


class AgenteTutor:
    def __init__(self, config: Config, memoria: Optional[Memoria] = None, cerebro: Optional[Cerebro] = None,
                 banco: Optional[BancoDevCards] = None) -> None:
        self.config = config
        self.memoria = memoria or Memoria(config.database_url)
        self.cerebro = cerebro or Cerebro(config.gemini_api_key, config.gemini_modelo)
        self.banco = banco if banco is not None else BancoDevCards()
        self._lock = threading.RLock()  # un solo flujo a la vez toca la memoria: ciclo, API y MCP
        self._stop = threading.Event()
        self._hilo: Optional[threading.Thread] = None
        self._inicio_proceso = time.time()
        self._ciclos_sin_novedad = 0

    # ---- ciclo de vida --------------------------------------------------------
    def despertar(self) -> dict[str, Any]:
        """Se ejecuta al arrancar el proceso: registra el arranque y anota lo que recuerda."""
        with self._lock:
            lat = self.memoria.registrar_arranque()
            temas = self.memoria.listar_temas()
            pend = self.memoria.pendientes()
            if lat.get("arranques", 1) <= 1:
                texto = "Primer arranque: mi memoria está vacía. Agrega temas o activa mazos de DevCards."
            else:
                ultimo = lat.get("ultimo_ciclo")
                desde = _hace((ahora() - ultimo).total_seconds() / 60) if ultimo else "nunca"
                texto = (
                    f"Desperté por {lat['arranques']}.ª vez. Recuerdo {len(temas)} temas, {len(pend)} preguntas "
                    f"pendientes y {lat.get('ciclos', 0)} ciclos de trabajo; mi último ciclo fue {desde}."
                )
            self.memoria.anotar("sistema", texto)
            return lat

    def iniciar(self) -> None:
        if self._hilo and self._hilo.is_alive():
            return
        self.despertar()
        self._stop.clear()
        self._hilo = threading.Thread(target=self._bucle, name="agente-tutor", daemon=True)
        self._hilo.start()

    def detener(self) -> None:
        self._stop.set()
        if self._hilo:
            self._hilo.join(timeout=10)

    @property
    def vivo(self) -> bool:
        return bool(self._hilo and self._hilo.is_alive())

    def _bucle(self) -> None:
        while not self._stop.is_set():
            try:
                self.ciclo()
            except Exception as exc:
                log.exception("Ciclo fallido")
                try:
                    self.memoria.anotar("error", f"Un ciclo falló ({type(exc).__name__}); sigo funcionando.")
                except Exception:
                    pass
            self._stop.wait(self.config.intervalo_ciclo_s)

    # ---- ciclo autónomo: percibir → decidir → actuar ---------------------------
    def ciclo(self) -> dict[str, Any]:
        with self._lock:
            t = ahora()
            # PERCIBIR
            pendientes = self.memoria.pendientes()
            con_pendiente = {int(p["tema_id"]) for p in pendientes}
            temas = self.memoria.listar_temas()
            vencidos = [x for x in temas if x["proximo_repaso"] <= t and int(x["id"]) not in con_pendiente]
            cupo = max(0, self.config.max_pendientes - len(pendientes))
            acciones: list[dict[str, Any]] = []

            # DECIDIR (1): repasos vencidos, primero los más atrasados y los más difíciles.
            def prioridad(x: dict[str, Any]) -> float:
                dias_retraso = (t - x["proximo_repaso"]).total_seconds() / 60 / self.config.minutos_por_dia
                return dias_retraso + 2 * (2.5 - float(x["facilidad"])) + 0.5 * int(x["fallos"])

            for tema in sorted(vencidos, key=prioridad, reverse=True)[:cupo]:
                retraso = (t - tema["proximo_repaso"]).total_seconds() / 60
                if tema["repeticiones"] == 0 and tema["aciertos"] + tema["fallos"] == 0:
                    motivo = f"Tema nuevo «{tema['nombre']}»: primera pregunta."
                else:
                    motivo = (
                        f"Repaso de «{tema['nombre']}»: le tocaba {_hace(retraso)}; facilidad {tema['facilidad']:.2f}, "
                        f"{tema['fallos']} fallos y {tema['aciertos']} aciertos (prioridad {prioridad(tema):.2f})."
                    )
                acciones.append(self._preparar_pregunta(tema, motivo))
            cupo -= len(acciones)

            # DECIDIR (2): ¿presentar una DevCard nueva? Solo si sobra cupo y no se pasó el límite del "día".
            activos = self.memoria.mazos_activos()
            if cupo > 0 and activos and len(self.banco):
                hoy = self.memoria.introducidas_desde(self.config.minutos_por_dia)
                if hoy < self.config.nuevas_por_dia:
                    tarjeta = self.banco.siguiente(activos, self.memoria.refs_introducidas())
                    if tarjeta is not None:
                        tema = self.memoria.crear_tema(
                            str(tarjeta["title"]), BancoDevCards.notas_de(tarjeta), origen="devcards",
                            categoria=str(tarjeta.get("category", "")), ref_externa=str(tarjeta["id"]),
                        )
                        motivo = (
                            f"DevCard nueva del mazo «{tema['categoria']}» ({tarjeta.get('difficulty', '')}): "
                            f"{hoy + 1} de {self.config.nuevas_por_dia} nuevas por día."
                        )
                        acciones.append(self._preparar_pregunta(tema, motivo))
                    elif not acciones:
                        self._anotar_una_vez("decision", "Ya presenté todas las tarjetas de los mazos activos.")
                elif not acciones:
                    self._anotar_una_vez(
                        "decision", f"Límite de {self.config.nuevas_por_dia} DevCards nuevas por día alcanzado: espero."
                    )

            # ACTUAR ya ocurrió en _preparar_pregunta; ahora queda el latido.
            self.memoria.registrar_ciclo()
            if acciones:
                self._ciclos_sin_novedad = 0
            else:
                self._ciclos_sin_novedad += 1
                if self._ciclos_sin_novedad % LATIDO_BITACORA_CADA == 1:
                    proximo = min((x["proximo_repaso"] for x in temas), default=None)
                    falta = (
                        f"el próximo repaso es en {max(0.0, (proximo - t).total_seconds() / 60):.0f} min"
                        if proximo and proximo > t else "no hay repasos programados"
                    )
                    self.memoria.anotar("ciclo", f"Sigo vivo: {len(pendientes)} preguntas esperando respuesta; {falta}.")
            return {"preguntas_creadas": acciones, "pendientes": len(pendientes) + len(acciones), "vencidos": len(vencidos)}

    def _anotar_una_vez(self, tipo: str, detalle: str) -> None:
        ultimas = self.memoria.leer_bitacora(limite=1)
        if not ultimas or ultimas[0]["detalle"] != detalle:
            self.memoria.anotar(tipo, detalle)

    def _preparar_pregunta(self, tema: dict[str, Any], motivo: str) -> dict[str, Any]:
        self.memoria.anotar("decision", motivo)
        tarjeta = self.banco.por_id.get(str(tema.get("ref_externa"))) if tema.get("origen") == "devcards" else None
        if tarjeta is not None:
            vista_antes = int(tema["aciertos"]) + int(tema["fallos"])
            datos = BancoDevCards.pregunta_de(tarjeta, vista_antes)
            # Solo la primera vez se lee la tarjeta; en los repasos se responde de memoria (recuerdo activo).
            p = self.memoria.crear_pregunta(
                int(tema["id"]), datos["texto"], datos["respuesta_esperada"], motivo, "devcards",
                opciones=datos["opciones"], explicacion=datos["explicacion"],
                requiere_lectura=self.config.leer_antes and vista_antes == 0,
            )
        else:
            preg = self.cerebro.generar_pregunta(
                str(tema["nombre"]), str(tema["notas"]), self.memoria.fallos_recientes(int(tema["id"]))
            )
            p = self.memoria.crear_pregunta(int(tema["id"]), preg.texto, preg.respuesta_esperada, motivo, preg.fuente)
        self.memoria.anotar("pregunta", f"Preparé una pregunta sobre «{tema['nombre']}» ({p['fuente']}).")
        return p

    # ---- responder -------------------------------------------------------------
    def responder(self, pregunta_id: int, texto: str) -> dict[str, Any]:
        with self._lock:
            p = self.memoria.obtener_pregunta(pregunta_id)
            if p is None:
                raise LookupError("No existe esa pregunta")
            if p["estado"] != "pendiente":
                raise ValueError("La pregunta ya fue respondida")
            if p.get("requiere_lectura"):
                raise ValueError("Primero lee la tarjeta")
            tema = self.memoria.obtener_tema(int(p["tema_id"]))
            if tema is None:
                raise LookupError("El tema de esa pregunta ya no existe")

            if p.get("opciones"):
                nota, retro, fuente = self._corregir_opcion_multiple(p, texto)
            else:
                ev = self.cerebro.evaluar(str(p["texto"]), str(p["respuesta_esperada"]), texto)
                nota, retro, fuente = ev.nota, ev.retroalimentacion, ev.fuente
                if p.get("explicacion"):
                    retro = f"{retro} Idea clave: {p['explicacion']}"

            self.memoria.registrar_respuesta(pregunta_id, texto, nota, retro)
            nuevo = sm2.actualizar(
                sm2.EstadoSM2(int(tema["repeticiones"]), float(tema["intervalo_dias"]), float(tema["facilidad"])), nota
            )
            proximo = ahora() + timedelta(minutes=nuevo.intervalo_dias * self.config.minutos_por_dia)
            self.memoria.actualizar_repaso(
                int(tema["id"]), nuevo.repeticiones, nuevo.intervalo_dias, nuevo.facilidad, proximo, acierto=nota >= 3
            )
            self.memoria.anotar(
                "evaluacion",
                f"«{tema['nombre']}»: nota {nota}/5 ({fuente}). Próximo repaso en {nuevo.intervalo_dias:g} día(s) "
                f"de estudio; facilidad {nuevo.facilidad:.2f}.",
            )
            return {
                "pregunta_id": pregunta_id,
                "tema": tema["nombre"],
                "nota": nota,
                "correcta": nota >= 3,
                "retroalimentacion": retro,
                "respuesta_esperada": p["respuesta_esperada"],
                "evaluado_por": fuente,
                "intervalo_dias": nuevo.intervalo_dias,
                "facilidad": nuevo.facilidad,
                "proximo_repaso": proximo,
            }

    def marcar_leida(self, pregunta_id: int) -> dict[str, Any]:
        with self._lock:
            p = self.memoria.obtener_pregunta(pregunta_id)
            ya_leida = bool(p and p.get("leida_en"))
            leida_en = self.memoria.marcar_leida(pregunta_id)  # LookupError / ValueError si no aplica
            if p is not None and not ya_leida:
                self.memoria.anotar(
                    "decision", f"Leíste la DevCard «{p['tema']}» (me lo confirmaste): ahora sí te hago su pregunta."
                )
            return {"pregunta_id": pregunta_id, "leida_en": leida_en}

    def lectura_de(self, p: dict[str, Any]) -> Optional[dict[str, str]]:
        """La tarjeta completa para leer, solo mientras la pregunta la exige."""
        if not p.get("requiere_lectura"):
            return None
        t = self.banco.por_id.get(str(p.get("ref_externa")))
        if t is None:
            return None
        return {
            "titulo": str(t.get("title", "")), "categoria": str(t.get("category", "")),
            "dificultad": str(t.get("difficulty", "")), "definicion": str(t.get("definition", "")),
            "analogia": str(t.get("analogy", "")), "codigo": str(t.get("code_example", "") or ""),
            "idea_clave": str(t.get("key_takeaway", "")),
        }

    @staticmethod
    def _corregir_opcion_multiple(p: dict[str, Any], texto: str) -> tuple[int, str, str]:
        opciones: list[str] = p["opciones"]
        correcta = opciones.index(p["respuesta_esperada"]) if p["respuesta_esperada"] in opciones else -1
        r = texto.strip()
        elegida: Optional[int] = None
        if re.fullmatch(r"[A-Ha-h][).]?", r):
            elegida = LETRAS.index(r[0].upper())
        elif re.fullmatch(r"\d+", r):
            elegida = int(r) - 1
        else:
            norm = _normalizar(r)
            elegida = next((i for i, o in enumerate(opciones) if _normalizar(o) == norm), None)
        idea = f" Idea clave: {p['explicacion']}" if p.get("explicacion") else ""
        if elegida == correcta:
            return 5, f"¡Correcto! {LETRAS[correcta]}) {opciones[correcta]}.{idea}", "devcards"
        return 1, f"Incorrecto. La respuesta era {LETRAS[correcta]}) {opciones[correcta]}.{idea}", "devcards"

    # ---- consultas -------------------------------------------------------------
    def agregar_tema(self, nombre: str, notas: str) -> dict[str, Any]:
        with self._lock:
            tema = self.memoria.crear_tema(nombre.strip(), notas.strip())
            self.memoria.anotar("sistema", f"Aprendí un tema nuevo: «{tema['nombre']}». Lo preguntaré en mi próximo ciclo.")
            return tema

    def activar_mazo(self, categoria: str, activo: bool) -> None:
        if not self.banco.existe_categoria(categoria):
            raise LookupError(f"No existe el mazo «{categoria}»")
        with self._lock:
            self.memoria.activar_mazo(categoria, activo)
            self.memoria.anotar("sistema", f"Mazo «{categoria}» {'activado' if activo else 'pausado'}.")

    def mazos(self) -> list[dict[str, Any]]:
        activos = set(self.memoria.mazos_activos())
        introducidas = self.memoria.refs_introducidas()
        vistas: dict[str, int] = {}
        for ref in introducidas:
            t = self.banco.por_id.get(ref)
            if t:
                vistas[str(t.get("category"))] = vistas.get(str(t.get("category")), 0) + 1
        return [{**m, "activo": m["categoria"] in activos, "introducidas": vistas.get(m["categoria"], 0)}
                for m in self.banco.categorias()]

    def progreso(self) -> dict[str, Any]:
        temas = self.memoria.listar_temas()
        respondidas = sum(int(x["aciertos"]) + int(x["fallos"]) for x in temas)
        aciertos = sum(int(x["aciertos"]) for x in temas)
        return {
            "temas": len(temas),
            "dominados": sum(1 for x in temas if float(x["intervalo_dias"]) >= 6),
            "respuestas": respondidas,
            "aciertos": aciertos,
            "porcentaje_aciertos": round(100 * aciertos / respondidas, 1) if respondidas else None,
            "mas_dificiles": [
                {"tema": x["nombre"], "facilidad": x["facilidad"], "fallos": x["fallos"]}
                for x in sorted(temas, key=lambda x: (float(x["facilidad"]), -int(x["fallos"])))[:5]
                if int(x["fallos"]) > 0
            ],
        }

    def estado(self) -> dict[str, Any]:
        lat = self.memoria.leer_latido()
        return {
            "vivo": self.vivo,
            "proceso_activo_hace_s": round(time.time() - self._inicio_proceso, 1),
            "latido": lat,
            "cerebro": "Gemini " + self.config.gemini_modelo if self.cerebro.usa_gemini else "Motor local (sin clave de Gemini)",
            "base_de_datos": self.memoria.engine.dialect.name,
            "banco_devcards": len(self.banco),
            "mazos_activos": self.memoria.mazos_activos(),
            "pendientes": len(self.memoria.pendientes()),
            "configuracion": {
                "intervalo_ciclo_s": self.config.intervalo_ciclo_s,
                "minutos_por_dia": self.config.minutos_por_dia,
                "max_pendientes": self.config.max_pendientes,
                "nuevas_por_dia": self.config.nuevas_por_dia,
            },
            "progreso": self.progreso(),
        }

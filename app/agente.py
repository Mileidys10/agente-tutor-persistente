# Archivo app/agente.py: coordina todo el comportamiento autónomo del tutor.
# Conecta Memoria (base de datos), Cerebro (Gemini/local), BancoDevCards (1 295 tarjetas) y SM-2.
# Tanto la API web (app/main.py) como el servidor MCP (app/mcp_tools.py) llaman a esta clase.
"""AgenteTutor: el agente persistente.

Ciclo autónomo (cada TUTOR_INTERVALO_S segundos, en un hilo de fondo):
  1. PERCIBIR  lee su memoria: temas vencidos, preguntas pendientes, mazos activos, tarjetas nuevas de hoy.
  2. DECIDIR   prioriza qué repasar (retraso + dificultad) y si toca presentar una DevCard nueva.
  3. ACTUAR    prepara las preguntas y deja registrado en la bitácora por qué lo decidió.
Al responder la persona: corrige, actualiza SM-2 y programa el próximo repaso.
Todo el estado está en la base de datos: si el proceso muere, al volver retoma donde iba.
"""

from __future__ import annotations

import json
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


# Convierte una cantidad de minutos en texto legible en español ("hace 5 min") para los motivos y la bitácora.
def _hace(minutos: float) -> str:
    if minutos < 1:
        return "hace menos de un minuto"
    if minutos < 60:
        return f"hace {minutos:.0f} min"
    if minutos < 60 * 48:
        return f"hace {minutos / 60:.1f} h"
    return f"hace {minutos / 1440:.1f} días"


# Clase principal del agente persistente; app/main.py crea una sola instancia compartida para la web y MCP.
class AgenteTutor:
    # Inicializa memoria, cerebro y banco de DevCards, además de un candado (RLock) para evitar choques entre hilos.
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
    # Se llama dentro de iniciar() al arrancar el servidor; suma +1 a arranques y resume en bitácora lo que recuerda.
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

    # Lo llama lifespan() en app/main.py al encender FastAPI: registra el arranque y lanza el hilo en segundo plano.
    def iniciar(self) -> None:
        if self._hilo and self._hilo.is_alive():
            return
        self.despertar()
        self._stop.clear()
        self._hilo = threading.Thread(target=self._bucle, name="agente-tutor", daemon=True)
        self._hilo.start()

    # Lo llama lifespan() en app/main.py al apagar el servidor para detener el hilo ordenadamente.
    def detener(self) -> None:
        self._stop.set()
        if self._hilo:
            self._hilo.join(timeout=10)

    # Responde True si el hilo autónomo está vivo; se reporta en /health y /api/estado.
    @property
    def vivo(self) -> bool:
        return bool(self._hilo and self._hilo.is_alive())

    # Bucle infinito del hilo de fondo: ejecuta self.ciclo() cada TUTOR_INTERVALO_S segundos sin caerse ante errores.
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
    # Corazón del agente: lo llama _bucle cada TUTOR_INTERVALO_S segundos, POST /api/ciclo y MCP en stdio.
    def ciclo(self) -> dict[str, Any]:
        with self._lock:
            t = ahora()
            # PERCIBIR
            # Mira cuántas preguntas esperan respuesta, qué temas ya vencieron y cuántos huecos libres hay.
            pendientes = self.memoria.pendientes()
            con_pendiente = {int(p["tema_id"]) for p in pendientes}
            temas = self.memoria.listar_temas()
            pausadas = {int(c["id"]) for c in self.memoria.listar_colecciones() if not c.get("activa", True)}
            vencidos = [
                x for x in temas
                if x["proximo_repaso"] <= t
                and int(x["id"]) not in con_pendiente
                and (x.get("coleccion_id") is None or int(x["coleccion_id"]) not in pausadas)
            ]
            cupo = max(0, self.config.max_pendientes - len(pendientes))
            acciones: list[dict[str, Any]] = []

            # REFLEXIONAR: detecta temas con fallos persistentes y activa refuerzo guiado
            self._reflexionar(temas)

            # DECIDIR (1): repasos vencidos, primero los más atrasados y los más difíciles.
            # Calcula una puntuación combinando días de atraso, facilidad baja y cantidad de fallos.
            def prioridad(x: dict[str, Any]) -> float:
                dias_retraso = (t - x["proximo_repaso"]).total_seconds() / 60 / self.config.minutos_por_dia
                return dias_retraso + 2 * (2.5 - float(x["facilidad"])) + 0.5 * int(x["fallos"])

            # Genera preguntas para los temas vencidos más urgentes mientras haya cupo disponible.
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

    # Evita llenar la bitácora con el mismo aviso repetido cada 20 segundos cuando nada cambia.
    def _anotar_una_vez(self, tipo: str, detalle: str) -> None:
        ultimas = self.memoria.leer_bitacora(limite=1)
        if not ultimas or ultimas[0]["detalle"] != detalle:
            self.memoria.anotar(tipo, detalle)

    # Fase REFLEXIONAR: identifica brechas persistentes (fallos >= 3 o facilidad <= 1.6) y activa lectura previa.
    def _reflexionar(self, temas: list[dict[str, Any]]) -> list[int]:
        marcados: list[int] = []
        for tema in temas:
            if tema.get("en_refuerzo"):
                continue
            fallos = int(tema.get("fallos") or 0)
            facilidad = float(tema.get("facilidad") or 2.5)
            if fallos >= 3 or (fallos >= 1 and facilidad <= 1.6):
                tid = int(tema["id"])
                self.memoria.marcar_refuerzo(tid, True)
                tema["en_refuerzo"] = True
                self.memoria.anotar(
                    "reflexion",
                    f"Detecté brecha persistente en «{tema['nombre']}» ({fallos} fallos, facilidad {facilidad:.2f}). "
                    "Activo lectura guiada previa y cambio de ángulo.",
                )
                marcados.append(tid)
        return marcados

    # Anota el motivo en bitácora y guarda la pregunta pendiente usando DevCards o Cerebro (Gemini/local).
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
            vista_antes = int(tema["aciertos"]) + int(tema["fallos"])
            es_ficha_rica = (
                tema.get("tipo") in ("codigo", "material")
                or bool(tema.get("codigo") or tema.get("analogia") or tema.get("idea_clave"))
            )
            requiere_lectura = bool(
                self.config.leer_antes and ((es_ficha_rica and vista_antes == 0) or tema.get("en_refuerzo"))
            )
            fallos_prev = self.memoria.fallos_recientes(int(tema["id"]))
            if tema.get("tipo") == "codigo" or tema.get("codigo"):
                preg = self.cerebro.generar_pregunta_codigo(tema, fallos_prev, vista_antes)
            else:
                preg = self.cerebro.generar_pregunta(str(tema["nombre"]), str(tema["notas"]), fallos_prev)
            p = self.memoria.crear_pregunta(
                int(tema["id"]), preg.texto, preg.respuesta_esperada, motivo, preg.fuente,
                explicacion=str(tema.get("idea_clave") or ""),
                requiere_lectura=requiere_lectura,
            )
        self.memoria.anotar("pregunta", f"Preparé una pregunta sobre «{tema['nombre']}» ({p['fuente']}).")
        return p

    # ---- responder -------------------------------------------------------------
    # La llaman POST /api/preguntas/{id}/responder (main.py) y responder_pregunta (mcp_tools.py).
    # Corrige la respuesta, recalcula SM-2, programa el próximo repaso en Memoria y devuelve el resultado.
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
            res_rep = self.memoria.actualizar_repaso(
                int(tema["id"]), nuevo.repeticiones, nuevo.intervalo_dias, nuevo.facilidad,
                proximo, acierto=nota >= 3, nota=nota,
            )
            self.memoria.registrar_actividad_diaria(acierto=nota >= 3)
            self.memoria.anotar(
                "evaluacion",
                f"«{tema['nombre']}»: nota {nota}/5 ({fuente}). Próximo repaso en {nuevo.intervalo_dias:g} día(s) "
                f"de estudio; facilidad {nuevo.facilidad:.2f}.",
            )
            if res_rep.get("supero_refuerzo"):
                self.memoria.anotar(
                    "reflexion",
                    f"«{tema['nombre']}» superó la brecha tras 2 aciertos sólidos seguidos; sale de modo refuerzo.",
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

    # La llaman POST /api/preguntas/{id}/leida y la herramienta MCP marcar_tarjeta_leida cuando pulsas "Ya la leí".
    # Desbloquea la pregunta guardando la hora en leida_en y deja constancia en la bitácora.
    def marcar_leida(self, pregunta_id: int) -> dict[str, Any]:
        with self._lock:
            p = self.memoria.obtener_pregunta(pregunta_id)
            ya_leida = bool(p and p.get("leida_en"))
            leida_en = self.memoria.marcar_leida(pregunta_id)  # LookupError / ValueError si no aplica
            if p is not None and not ya_leida:
                etiqueta = "DevCard" if p.get("origen") == "devcards" else "ficha"
                self.memoria.anotar(
                    "decision", f"Leíste la {etiqueta} «{p['tema']}» (me lo confirmaste): ahora sí te hago su pregunta."
                )
            return {"pregunta_id": pregunta_id, "leida_en": leida_en}

    # Usada por GET /api/preguntas/pendientes (main.py) y ver_preguntas_pendientes (mcp_tools.py)
    # para entregar la ficha completa (definición, analogía, código, idea clave) mientras requiere_lectura es True.
    def lectura_de(self, p: dict[str, Any]) -> Optional[dict[str, str]]:
        """La tarjeta completa para leer, solo mientras la pregunta la exige."""
        if not p.get("requiere_lectura"):
            return None
        ref = str(p.get("ref_externa") or "")
        t = self.banco.por_id.get(ref) if ref else None
        if t is not None:
            return {
                "titulo": str(t.get("title", "")), "categoria": str(t.get("category", "")),
                "dificultad": str(t.get("difficulty", "")), "definicion": str(t.get("definition", "")),
                "analogia": str(t.get("analogy", "")), "codigo": str(t.get("code_example", "") or ""),
                "idea_clave": str(t.get("key_takeaway", "")),
            }
        tema = None
        if not p.get("notas") and not p.get("codigo") and p.get("tema_id"):
            tema = self.memoria.obtener_tema(int(p["tema_id"]))
        src = tema or p
        tipo = str(src.get("tipo") or "nota")
        etiqueta = {"codigo": "Código", "material": "Apuntes", "nota": "Nota"}.get(tipo, "Estudio")
        return {
            "titulo": str(p.get("tema") or src.get("nombre") or ""),
            "categoria": str(src.get("lenguaje") or src.get("categoria") or etiqueta),
            "dificultad": "Refuerzo" if src.get("en_refuerzo") else etiqueta,
            "definicion": str(src.get("notas") or ""),
            "analogia": str(src.get("analogia") or ""),
            "codigo": str(src.get("codigo") or ""),
            "idea_clave": str(src.get("idea_clave") or ""),
            "lenguaje": str(src.get("lenguaje") or ""),
            "tipo": tipo,
        }

    # Corrige tarjetas de opción múltiple comparando letra ("A".."H"), número o texto completo; da nota 5 o 1.
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

    # ---- consultas y gestión v2 -----------------------------------------------
    # Guarda un tema propio con tus notas (POST /api/temas o MCP agregar_tema) y deja aviso en la bitácora.
    def agregar_tema(
        self, nombre: str, notas: str, coleccion_id: Optional[int] = None, tipo: str = "nota",
        codigo: str = "", lenguaje: str = "", analogia: str = "", idea_clave: str = "", etiquetas: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            if coleccion_id is not None and self.memoria.obtener_coleccion(coleccion_id) is None:
                raise LookupError("No existe esa colección")
            tema = self.memoria.crear_tema(
                nombre.strip(), notas.strip(), tipo=tipo, coleccion_id=coleccion_id,
                codigo=codigo.strip(), lenguaje=lenguaje.strip(), analogia=analogia.strip(),
                idea_clave=idea_clave.strip(), etiquetas=etiquetas.strip(),
            )
            self.memoria.anotar("sistema", f"Aprendí un tema nuevo: «{tema['nombre']}». Lo preguntaré en mi próximo ciclo.")
            return tema

    # ---- ingesta universal v2.0: estudiar código y apuntes libres -----------
    def estudiar_codigo(
        self, codigo: str, titulo: str = "", lenguaje: str = "",
        coleccion: str = "Código estudiado", objetivo: str = "", max_fichas: int = 5,
    ) -> dict[str, Any]:
        limpio = codigo.strip()
        if len(limpio) < 10:
            raise ValueError("El código debe tener al menos 10 caracteres")
        if len(limpio) > 12000:
            raise ValueError("El código supera el máximo de 12 000 caracteres")
        fichas, fuente = self.cerebro.descomponer_codigo(
            limpio, titulo=titulo, lenguaje=lenguaje, objetivo=objetivo, max_fichas=max_fichas
        )
        return self._guardar_fichas_ingesta(fichas, fuente, coleccion or "Código estudiado", "código")

    def ingestar_material(
        self, contenido: str, titulo: str = "",
        coleccion: str = "Material de estudio", max_fichas: int = 5,
    ) -> dict[str, Any]:
        limpio = contenido.strip()
        if len(limpio) < 20:
            raise ValueError("El material debe tener al menos 20 caracteres")
        if len(limpio) > 25000:
            raise ValueError("El material supera el máximo de 25 000 caracteres")
        fichas, fuente = self.cerebro.descomponer_material(limpio, titulo=titulo, max_fichas=max_fichas)
        return self._guardar_fichas_ingesta(fichas, fuente, coleccion or "Material de estudio", "material")

    def _guardar_fichas_ingesta(
        self, fichas: list[Any], fuente: str, nombre_coleccion: str, etiqueta: str,
    ) -> dict[str, Any]:
        with self._lock:
            col = self.memoria.obtener_o_crear_coleccion(nombre_coleccion.strip()[:120] or "Estudio libre")
            creadas: list[dict[str, Any]] = []
            omitidas = 0
            for f in fichas:
                try:
                    tema = self.memoria.crear_tema(
                        f.nombre, f.notas, tipo=f.tipo, coleccion_id=int(col["id"]),
                        codigo=f.codigo, lenguaje=f.lenguaje, analogia=f.analogia,
                        idea_clave=f.idea_clave, etiquetas=f.etiquetas,
                    )
                    creadas.append(tema)
                except ValueError:
                    omitidas += 1
            self.memoria.anotar(
                "sistema",
                f"Ingesta de {etiqueta} ({fuente}): {len(creadas)} ficha(s) guardada(s) en «{col['nombre']}».",
            )
            return {
                "coleccion": self.memoria.obtener_coleccion(int(col["id"])),
                "fuente": fuente,
                "creadas": creadas,
                "omitidas": omitidas,
            }

    def buscar_temas(
        self, q: str = "", coleccion_id: Optional[int] = None, tipo: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        return self.memoria.buscar_temas(q=q, coleccion_id=coleccion_id, tipo=tipo)

    def editar_tema(self, tema_id: int, **campos: Any) -> dict[str, Any]:
        with self._lock:
            if "coleccion_id" in campos and campos["coleccion_id"] is not None:
                if self.memoria.obtener_coleccion(int(campos["coleccion_id"])) is None:
                    raise LookupError("No existe esa colección")
            tema = self.memoria.actualizar_tema(tema_id, **campos)
            self.memoria.anotar("sistema", f"Actualicé el tema «{tema['nombre']}».")
            return tema

    def borrar_tema(self, tema_id: int) -> bool:
        with self._lock:
            borrado = self.memoria.borrar_tema(tema_id)
            if borrado:
                self.memoria.anotar("sistema", f"Olvidé el tema {tema_id} a pedido de la persona.")
            return borrado

    def posponer_tema(self, tema_id: int, dias: float = 1.0) -> dict[str, Any]:
        if dias <= 0 or dias > 365:
            raise ValueError("Los días para posponer deben estar entre 0 y 365")
        with self._lock:
            tema = self.memoria.obtener_tema(tema_id)
            if tema is None:
                raise LookupError("No existe ese tema")
            base = max(ahora(), tema["proximo_repaso"])
            nuevo_repaso = base + timedelta(minutes=dias * self.config.minutos_por_dia)
            actualizado = self.memoria.actualizar_tema(tema_id, proximo_repaso=nuevo_repaso)
            self.memoria.anotar("decision", f"Pospuse «{tema['nombre']}» {dias:g} día(s) de estudio.")
            return actualizado

    # ---- colecciones personalizadas y portabilidad ----------------------------
    def crear_coleccion(self, nombre: str, descripcion: str = "") -> dict[str, Any]:
        with self._lock:
            col = self.memoria.crear_coleccion(nombre, descripcion)
            self.memoria.anotar("sistema", f"Creé la colección «{col['nombre']}».")
            return col

    def listar_colecciones(self) -> list[dict[str, Any]]:
        return self.memoria.listar_colecciones()

    def actualizar_coleccion(
        self, coleccion_id: int, nombre: Optional[str] = None,
        descripcion: Optional[str] = None, activa: Optional[bool] = None,
    ) -> dict[str, Any]:
        with self._lock:
            col = self.memoria.actualizar_coleccion(coleccion_id, nombre=nombre, descripcion=descripcion, activa=activa)
            estado_txt = ""
            if activa is not None:
                estado_txt = f" ({'activada' if col['activa'] else 'pausada'})"
            self.memoria.anotar("sistema", f"Actualicé la colección «{col['nombre']}»{estado_txt}.")
            return col

    def borrar_coleccion(self, coleccion_id: int, borrar_temas: bool = False) -> bool:
        with self._lock:
            col = self.memoria.obtener_coleccion(coleccion_id)
            if col is None:
                return False
            ok = self.memoria.borrar_coleccion(coleccion_id, borrar_temas=borrar_temas)
            if ok:
                self.memoria.anotar("sistema", f"Eliminé la colección «{col['nombre']}».")
            return ok

    def exportar_coleccion(self, coleccion_id: int, formato: str = "json") -> dict[str, Any] | str:
        col = self.memoria.obtener_coleccion(coleccion_id)
        if col is None:
            raise LookupError("No existe esa colección")
        fichas = self.memoria.buscar_temas(coleccion_id=coleccion_id)
        fmt = formato.strip().lower()
        if fmt == "json":
            return {
                "version": "2.0",
                "coleccion": {"nombre": col["nombre"], "descripcion": col["descripcion"]},
                "fichas": [
                    {
                        "nombre": f["nombre"],
                        "notas": f["notas"],
                        "tipo": f.get("tipo", "nota"),
                        "codigo": f.get("codigo", ""),
                        "lenguaje": f.get("lenguaje", ""),
                        "analogia": f.get("analogia", ""),
                        "idea_clave": f.get("idea_clave", ""),
                        "etiquetas": f.get("etiquetas", ""),
                    }
                    for f in fichas
                ],
            }
        if fmt in ("md", "markdown"):
            lineas = [f"# {col['nombre']}"]
            if col["descripcion"]:
                lineas.extend(["", col["descripcion"]])
            for f in fichas:
                lineas.extend(["", f"## {f['nombre']}", ""])
                if f.get("notas"):
                    lineas.append(str(f["notas"]))
                if f.get("codigo"):
                    lang = str(f.get("lenguaje") or "")
                    lineas.extend(["", f"```{lang}", str(f["codigo"]), "```"])
                if f.get("analogia"):
                    lineas.extend(["", f"> Analogía: {f['analogia']}"])
                if f.get("idea_clave"):
                    lineas.extend(["", f"**Idea clave:** {f['idea_clave']}"])
            return "\n".join(lineas).strip() + "\n"
        raise ValueError("Formato no soportado; usa 'json' o 'md'")

    def importar_coleccion(
        self, datos: dict[str, Any] | str, formato: str = "json", nombre_coleccion: str = "",
    ) -> dict[str, Any]:
        fmt = formato.strip().lower()
        fichas_entrada: list[dict[str, Any]] = []
        descripcion = ""
        nombre_destino = nombre_coleccion.strip()

        if fmt == "json":
            payload = json.loads(datos) if isinstance(datos, str) else datos
            if not isinstance(payload, dict) or not isinstance(payload.get("fichas"), list):
                raise ValueError("El JSON debe incluir una lista 'fichas'")
            col_meta = payload.get("coleccion") if isinstance(payload.get("coleccion"), dict) else {}
            if not nombre_destino:
                nombre_destino = str(col_meta.get("nombre") or "Colección importada").strip()
            descripcion = str(col_meta.get("descripcion") or "").strip()
            fichas_entrada = [f for f in payload["fichas"] if isinstance(f, dict)]
        elif fmt in ("md", "markdown"):
            texto = datos if isinstance(datos, str) else json.dumps(datos, ensure_ascii=False)
            secciones = re.split(r"(?m)^##\s+", texto)
            cabecera = secciones[0].strip().splitlines()
            if not nombre_destino:
                titulo_h1 = next((l[2:].strip() for l in cabecera if l.startswith("# ")), "")
                nombre_destino = titulo_h1 or "Colección Markdown"
            for sec in secciones[1:]:
                lineas = sec.strip().splitlines()
                if not lineas:
                    continue
                titulo = lineas[0].strip()[:200]
                cuerpo = "\n".join(lineas[1:]).strip()
                codigo = ""
                lenguaje = ""
                m_cod = re.search(r"```([a-zA-Z0-9_-]*)\n([\s\S]*?)```", cuerpo)
                if m_cod:
                    lenguaje = m_cod.group(1).strip()
                    codigo = m_cod.group(2).strip()
                    cuerpo = (cuerpo[:m_cod.start()] + cuerpo[m_cod.end():]).strip()
                idea = ""
                m_idea = re.search(r"\*\*Idea clave:\*\*\s*(.+)", cuerpo)
                if m_idea:
                    idea = m_idea.group(1).strip()
                    cuerpo = cuerpo.replace(m_idea.group(0), "").strip()
                analogia = ""
                m_ana = re.search(r"(?m)^>\s*Analog[ií]a:\s*(.+)$", cuerpo)
                if m_ana:
                    analogia = m_ana.group(1).strip()
                    cuerpo = cuerpo.replace(m_ana.group(0), "").strip()
                fichas_entrada.append({
                    "nombre": titulo,
                    "notas": cuerpo,
                    "tipo": "codigo" if codigo else "material",
                    "codigo": codigo,
                    "lenguaje": lenguaje,
                    "analogia": analogia,
                    "idea_clave": idea,
                })
        else:
            raise ValueError("Formato no soportado; usa 'json' o 'md'")

        if not fichas_entrada:
            raise ValueError("No se encontraron fichas válidas para importar")

        with self._lock:
            col = self.memoria.obtener_o_crear_coleccion(nombre_destino or "Colección importada", descripcion)
            importados = []
            omitidos = 0
            for item in fichas_entrada[:100]:
                titulo = str(item.get("nombre") or "").strip()[:200]
                if len(titulo) < 2:
                    omitidos += 1
                    continue
                try:
                    t_creado = self.memoria.crear_tema(
                        titulo,
                        str(item.get("notas") or "")[:8000],
                        tipo=str(item.get("tipo") or "nota")[:20],
                        coleccion_id=int(col["id"]),
                        codigo=str(item.get("codigo") or "")[:12000],
                        lenguaje=str(item.get("lenguaje") or "")[:40],
                        analogia=str(item.get("analogia") or "")[:2000],
                        idea_clave=str(item.get("idea_clave") or "")[:1000],
                        etiquetas=str(item.get("etiquetas") or "")[:500],
                    )
                    importados.append(t_creado)
                except ValueError:
                    omitidos += 1
            self.memoria.anotar(
                "sistema", f"Importé {len(importados)} ficha(s) en «{col['nombre']}» ({omitidos} omitida(s))."
            )
            return {"coleccion": self.memoria.obtener_coleccion(int(col["id"])), "importados": importados, "omitidos": omitidos}

    # Activa o pausa un mazo de DevCards (PUT /api/mazos/{categoria} o MCP activar_mazo) tras comprobar que existe.
    def activar_mazo(self, categoria: str, activo: bool) -> None:
        if not self.banco.existe_categoria(categoria):
            raise LookupError(f"No existe el mazo «{categoria}»")
        with self._lock:
            self.memoria.activar_mazo(categoria, activo)
            self.memoria.anotar("sistema", f"Mazo «{categoria}» {'activado' if activo else 'pausado'}.")

    # Combina las 42 categorías del banco con cuáles están activas y cuántas ya introdujo el agente (GET /api/mazos).
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

    # Calcula estadísticas globales de estudio (dominados = intervalo >= 6 días) para GET /api/progreso y MCP.
    def progreso(self) -> dict[str, Any]:
        temas = self.memoria.listar_temas()
        respondidas = sum(int(x["aciertos"]) + int(x["fallos"]) for x in temas)
        aciertos = sum(int(x["aciertos"]) for x in temas)
        en_refuerzo = sum(1 for x in temas if x.get("en_refuerzo"))
        return {
            "temas": len(temas),
            "dominados": sum(1 for x in temas if float(x["intervalo_dias"]) >= 6),
            "en_refuerzo": en_refuerzo,
            "racha_dias": self.memoria.calcular_racha_dias(),
            "respuestas": respondidas,
            "aciertos": aciertos,
            "porcentaje_aciertos": round(100 * aciertos / respondidas, 1) if respondidas else None,
            "mas_dificiles": [
                {"tema": x["nombre"], "facilidad": x["facilidad"], "fallos": x["fallos"], "en_refuerzo": bool(x.get("en_refuerzo"))}
                for x in sorted(temas, key=lambda x: (float(x["facilidad"]), -int(x["fallos"])))[:5]
                if int(x["fallos"]) > 0
            ],
        }

    def diagnosticar_brechas(self, limite: int = 10) -> dict[str, Any]:
        temas = self.memoria.listar_temas()
        en_refuerzo = [
            {
                "id": t["id"],
                "nombre": t["nombre"],
                "tipo": t.get("tipo", "nota"),
                "facilidad": t["facilidad"],
                "fallos": t["fallos"],
                "aciertos": t["aciertos"],
            }
            for t in sorted(temas, key=lambda x: (float(x["facilidad"]), -int(x["fallos"])))
            if t.get("en_refuerzo")
        ][:max(1, min(limite, 50))]
        dificiles = [
            {
                "id": t["id"],
                "nombre": t["nombre"],
                "tipo": t.get("tipo", "nota"),
                "facilidad": t["facilidad"],
                "fallos": t["fallos"],
                "en_refuerzo": bool(t.get("en_refuerzo")),
            }
            for t in sorted(temas, key=lambda x: (float(x["facilidad"]), -int(x["fallos"])))
            if int(t["fallos"]) > 0
        ][:max(1, min(limite, 50))]
        racha = self.memoria.calcular_racha_dias()
        if en_refuerzo:
            rec = f"Prioriza repasar los {len(en_refuerzo)} tema(s) en refuerzo guiado antes de incorporar material nuevo."
        elif dificiles:
            rec = f"Revisa «{dificiles[0]['nombre']}» (facilidad {dificiles[0]['facilidad']:.2f}) en tu próxima sesión."
        else:
            rec = "Sin brechas críticas detectadas. Buen momento para agregar código nuevo o activar otro mazo."
        return {
            "racha_dias": racha,
            "en_refuerzo": en_refuerzo,
            "mas_dificiles": dificiles,
            "recomendacion": rec,
        }

    # Resume en un diccionario todo el estado vivo del agente (latido, cerebro, BD, config) para GET /api/estado.
    def estado(self) -> dict[str, Any]:
        lat = self.memoria.leer_latido()
        cols = self.memoria.listar_colecciones()
        return {
            "vivo": self.vivo,
            "proceso_activo_hace_s": round(time.time() - self._inicio_proceso, 1),
            "latido": lat,
            "cerebro": "Gemini " + self.config.gemini_modelo if self.cerebro.usa_gemini else "Motor local (sin clave de Gemini)",
            "base_de_datos": self.memoria.engine.dialect.name,
            "banco_devcards": len(self.banco),
            "mazos_activos": self.memoria.mazos_activos(),
            "colecciones_activas": [c["nombre"] for c in cols if c.get("activa")],
            "pendientes": len(self.memoria.pendientes()),
            "configuracion": {
                "intervalo_ciclo_s": self.config.intervalo_ciclo_s,
                "minutos_por_dia": self.config.minutos_por_dia,
                "max_pendientes": self.config.max_pendientes,
                "nuevas_por_dia": self.config.nuevas_por_dia,
            },
            "progreso": self.progreso(),
        }

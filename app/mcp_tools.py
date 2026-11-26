# Archivo app/mcp_tools.py: servidor MCP v2.0 completo (19 Tools anotadas, 6 Resources y 5 Prompts).
# App/main.py lo monta en /mcp para acceso remoto y también puede ejecutarse directo por stdio en local.
"""Servidor MCP del tutor: cualquier cliente MCP (Claude Desktop, Claude Code, Cursor, Antigravity, Codex...)
puede estudiar código recién generado, ingestar apuntes y repasar con repetición espaciada SM-2.

Dos formas de conectarse:
  - Remoto (Render): Streamable HTTP en https://<servicio>.onrender.com/mcp  (cabecera Authorization: Bearer <TUTOR_TOKEN>)
  - Local:           agente-tutor-mcp   o   python -m app.mcp_tools   (transporte stdio)
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from app.agente import AgenteTutor


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o))


def _serializar_tema(t: dict[str, Any]) -> dict[str, Any]:
    return {
        k: (v.isoformat() if hasattr(v, "isoformat") else v)
        for k, v in t.items()
    }


# Quita "respuesta_esperada" y otros campos internos antes de mandar una pregunta al cliente MCP.
def _limpiar(p: dict[str, Any]) -> dict[str, Any]:
    # Nunca se revela la respuesta esperada antes de que la persona conteste.
    return {
        "pregunta_id": p["id"],
        "tema": p.get("tema"),
        "tipo": p.get("tipo", "nota"),
        "lenguaje": p.get("lenguaje", ""),
        "pregunta": p["texto"],
        "opciones": p.get("opciones"),
        "motivo": p.get("motivo"),
        "pistas_usadas": int(p.get("pistas_usadas") or 0),
        "sesion_examen_id": p.get("sesion_examen_id"),
        "requiere_lectura": bool(p.get("requiere_lectura")),
    }


# Registra el servidor MCP completo (19 Tools, 6 Resources y 5 Prompts) conectado a AgenteTutor.
def crear_servidor_mcp(agente: AgenteTutor) -> MCPServer:
    mcp = MCPServer(
        name="agente-tutor-persistente",
        instructions=(
            "Tutor de estudio persistente v2.0 («Aprende lo que Construyes») con repetición espaciada (SM-2), "
            "banco de 1 295 DevCards, estudio de código generado e ingesta universal de apuntes. "
            "Usa estudiar_codigo cuando escribas o expliques código que la persona quiera aprender; "
            "usa ingestar_material para convertir apuntes/Markdown en fichas; "
            "usa ver_preguntas_pendientes y marcar_tarjeta_leida para repasar, y envía SU respuesta con responder_pregunta "
            "sin responder tú por ella. Puedes consultar los Resources tutor://* y los Prompts pedagógicos."
        ),
    )

    # =========================================================================
    # 19 TOOLS (todas con las 4 banderas booleanas de ToolAnnotations)
    # =========================================================================

    # 1. agregar_tema
    @mcp.tool(
        description="Agrega un tema propio con tus notas de estudio (y opcionalmente colección, código o idea clave). El agente lo preguntará en su próximo ciclo.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    def agregar_tema(
        nombre: str,
        notas: str,
        coleccion_id: Optional[int] = None,
        codigo: str = "",
        lenguaje: str = "",
        analogia: str = "",
        idea_clave: str = "",
    ) -> dict[str, Any]:
        tipo = "codigo" if codigo.strip() else "nota"
        tema = agente.agregar_tema(
            nombre[:200],
            notas[:8000],
            coleccion_id=coleccion_id,
            tipo=tipo,
            codigo=codigo[:12000],
            lenguaje=lenguaje[:40],
            analogia=analogia[:2000],
            idea_clave=idea_clave[:1000],
        )
        return {"tema_id": tema["id"], "nombre": tema["nombre"], "tipo": tema["tipo"], "coleccion_id": tema["coleccion_id"]}

    # 2. ver_preguntas_pendientes
    @mcp.tool(
        description="Preguntas que el agente preparó y esperan respuesta (sin revelar la respuesta).",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def ver_preguntas_pendientes() -> list[dict[str, Any]]:
        if not agente.vivo:  # modo stdio sin hilo de fondo: se ejecuta un ciclo al consultar
            agente.ciclo()
        return [{**_limpiar(p), "lectura": agente.lectura_de(p)} for p in agente.memoria.pendientes()]

    # 3. marcar_tarjeta_leida
    @mcp.tool(
        description="Marca como leída la ficha o DevCard de una pregunta (paso previo obligatorio si requiere_lectura es true).",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def marcar_tarjeta_leida(pregunta_id: int) -> dict[str, Any]:
        r = agente.marcar_leida(pregunta_id)
        return {**r, "leida_en": r["leida_en"].isoformat()}

    # 4. responder_pregunta
    @mcp.tool(
        description="Envía la respuesta de la persona a una pregunta pendiente. Para opción múltiple vale la letra (A, B, C...).",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    def responder_pregunta(pregunta_id: int, respuesta: str) -> dict[str, Any]:
        r = agente.responder(pregunta_id, respuesta[:2000])
        return {**r, "proximo_repaso": r["proximo_repaso"].isoformat()}

    # 5. ver_mazos
    @mcp.tool(
        description="Lista los mazos de DevCards con cuántas tarjetas tienen y si están activos.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def ver_mazos() -> list[dict[str, Any]]:
        return agente.mazos()

    # 6. activar_mazo
    @mcp.tool(
        description="Activa o pausa un mazo de DevCards por su nombre exacto de categoría.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def activar_mazo(categoria: str, activo: bool = True) -> dict[str, Any]:
        agente.activar_mazo(categoria, activo)
        return {"categoria": categoria, "activo": activo}

    # 7. ver_progreso
    @mcp.tool(
        description="Progreso de estudio: temas, dominados, racha diaria, porcentaje de aciertos y temas más difíciles.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def ver_progreso() -> dict[str, Any]:
        return agente.progreso()

    # 8. ver_estado
    @mcp.tool(
        description="Estado del agente: si está vivo, ciclos, arranques, colecciones activas y configuración.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def ver_estado() -> dict[str, Any]:
        e = agente.estado()
        lat = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in (e.get("latido") or {}).items()}
        return {**e, "latido": lat}

    # 9. ver_bitacora
    @mcp.tool(
        description="Últimas decisiones, reflexiones y acciones que el agente anotó en su bitácora.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def ver_bitacora(limite: int = 15) -> list[dict[str, Any]]:
        return [
            {"fecha": b["fecha"].isoformat(), "tipo": b["tipo"], "detalle": b["detalle"]}
            for b in agente.memoria.leer_bitacora(max(1, min(limite, 100)))
        ]

    # 10. estudiar_codigo
    @mcp.tool(
        description="Convierte cualquier fragmento de código (propio o generado por IA) en fichas atómicas de estudio con lectura guiada y preguntas SM-2.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    def estudiar_codigo(
        codigo: str,
        titulo: str = "",
        lenguaje: str = "",
        coleccion: str = "Código estudiado",
        objetivo: str = "",
        max_fichas: int = 5,
    ) -> dict[str, Any]:
        res = agente.estudiar_codigo(
            codigo[:12000],
            titulo=titulo[:200],
            lenguaje=lenguaje[:40],
            coleccion=coleccion[:120],
            objetivo=objetivo[:500],
            max_fichas=max(1, min(max_fichas, 10)),
        )
        return {
            "coleccion": _serializar_tema(res["coleccion"]) if res.get("coleccion") else None,
            "fuente": res["fuente"],
            "creadas": [{"id": t["id"], "nombre": t["nombre"], "lenguaje": t.get("lenguaje", "")} for t in res["creadas"]],
            "omitidas": res["omitidas"],
        }

    # 11. ingestar_material
    @mcp.tool(
        description="Ingesta apuntes, resúmenes en Markdown o textos libres de cualquier materia y los divide en fichas atómicas listas para SM-2.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    def ingestar_material(
        contenido: str,
        titulo: str = "",
        coleccion: str = "Material de estudio",
        max_fichas: int = 5,
    ) -> dict[str, Any]:
        res = agente.ingestar_material(
            contenido[:25000],
            titulo=titulo[:200],
            coleccion=coleccion[:120],
            max_fichas=max(1, min(max_fichas, 15)),
        )
        return {
            "coleccion": _serializar_tema(res["coleccion"]) if res.get("coleccion") else None,
            "fuente": res["fuente"],
            "creadas": [{"id": t["id"], "nombre": t["nombre"]} for t in res["creadas"]],
            "omitidas": res["omitidas"],
        }

    # 12. gestionar_coleccion
    @mcp.tool(
        description="Administra colecciones personalizadas: accion='listar' | 'crear' | 'activar' | 'pausar' | 'renombrar' | 'eliminar'.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    def gestionar_coleccion(
        accion: str,
        nombre: str = "",
        descripcion: str = "",
        coleccion_id: Optional[int] = None,
        borrar_temas: bool = False,
    ) -> dict[str, Any]:
        op = accion.strip().lower()
        if op == "listar":
            return {"colecciones": [_serializar_tema(c) for c in agente.listar_colecciones()]}
        if op == "crear":
            return {"coleccion": _serializar_tema(agente.crear_coleccion(nombre, descripcion))}
        if coleccion_id is None:
            raise ValueError("Debes indicar coleccion_id para esta acción")
        if op == "activar":
            return {"coleccion": _serializar_tema(agente.actualizar_coleccion(coleccion_id, activa=True))}
        if op == "pausar":
            return {"coleccion": _serializar_tema(agente.actualizar_coleccion(coleccion_id, activa=False))}
        if op == "renombrar":
            return {"coleccion": _serializar_tema(agente.actualizar_coleccion(coleccion_id, nombre=nombre, descripcion=descripcion or None))}
        if op == "eliminar":
            ok = agente.borrar_coleccion(coleccion_id, borrar_temas=borrar_temas)
            if not ok:
                raise LookupError("No existe esa colección")
            return {"borrado": coleccion_id, "borrar_temas": borrar_temas}
        raise ValueError("Acción no válida; usa listar, crear, activar, pausar, renombrar o eliminar")

    # 13. buscar_temas
    @mcp.tool(
        description="Busca temas o fichas por texto libre, colección o tipo ('nota', 'codigo', 'material', 'devcard').",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def buscar_temas(
        consulta: str = "",
        coleccion_id: Optional[int] = None,
        tipo: str = "",
    ) -> list[dict[str, Any]]:
        encontrados = agente.buscar_temas(q=consulta, coleccion_id=coleccion_id, tipo=tipo or None)
        return [_serializar_tema(t) for t in encontrados[:50]]

    # 14. editar_tema
    @mcp.tool(
        description="Edita una ficha existente: nombre, notas, código, lenguaje, analogía, idea clave, etiquetas o colección.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def editar_tema(
        tema_id: int,
        nombre: Optional[str] = None,
        notas: Optional[str] = None,
        codigo: Optional[str] = None,
        lenguaje: Optional[str] = None,
        analogia: Optional[str] = None,
        idea_clave: Optional[str] = None,
        etiquetas: Optional[str] = None,
        coleccion_id: Optional[int] = None,
    ) -> dict[str, Any]:
        campos: dict[str, Any] = {}
        for k, val in (
            ("nombre", nombre),
            ("notas", notas),
            ("codigo", codigo),
            ("lenguaje", lenguaje),
            ("analogia", analogia),
            ("idea_clave", idea_clave),
            ("etiquetas", etiquetas),
            ("coleccion_id", coleccion_id),
        ):
            if val is not None:
                campos[k] = val
        return _serializar_tema(agente.editar_tema(tema_id, **campos))

    # 15. borrar_tema
    @mcp.tool(
        description="Elimina definitivamente un tema de la base de datos junto con sus preguntas y respuestas.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def borrar_tema(tema_id: int) -> dict[str, Any]:
        if not agente.borrar_tema(tema_id):
            raise LookupError("No existe ese tema")
        return {"borrado": tema_id}

    # 16. posponer_tema
    @mcp.tool(
        description="Pospone el próximo repaso SM-2 de un tema N días hacia adelante.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    def posponer_tema(tema_id: int, dias: float = 1.0) -> dict[str, Any]:
        t = agente.posponer_tema(tema_id, dias=dias)
        return {"tema_id": t["id"], "nombre": t["nombre"], "proximo_repaso": t["proximo_repaso"].isoformat()}

    # 17. diagnosticar_brechas
    @mcp.tool(
        description="Diagnostica brechas persistentes (temas en refuerzo), temas con mayor tasa de fallos, racha diaria y recomendación.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def diagnosticar_brechas(limite: int = 10) -> dict[str, Any]:
        return agente.diagnosticar_brechas(limite=limite)

    # 18. exportar_mazo
    @mcp.tool(
        description="Exporta una colección completa y todas sus fichas en formato 'json', 'md' (Markdown) o 'anki' (TSV).",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def exportar_mazo(coleccion_id: int, formato: str = "json") -> dict[str, Any]:
        contenido = agente.exportar_coleccion(coleccion_id, formato=formato)
        return {"formato": formato, "contenido": contenido}

    # 19. importar_mazo
    @mcp.tool(
        description="Importa un mazo portable en formato 'json' o 'md' (Markdown) creando la colección y omitiendo duplicados.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def importar_mazo(contenido: str, formato: str = "json", nombre_coleccion: str = "") -> dict[str, Any]:
        res = agente.importar_coleccion(contenido, formato=formato, nombre_coleccion=nombre_coleccion)
        return {
            "coleccion": _serializar_tema(res["coleccion"]) if res.get("coleccion") else None,
            "importados": len(res["importados"]),
            "omitidos": res["omitidos"],
        }

    # 20. estudiar_diff (v3.0)
    @mcp.tool(
        description="Convierte un git diff real (entre commits o PR) en fichas de estudio por archivo modificado.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    def estudiar_diff(
        diff_texto: str,
        titulo: str = "",
        coleccion: str = "Cambios Git (Diff)",
        max_fichas: int = 5,
    ) -> dict[str, Any]:
        res = agente.estudiar_diff(
            diff_texto[:30000], titulo=titulo[:200], coleccion=coleccion[:120], max_fichas=max(1, min(max_fichas, 10))
        )
        return {
            "coleccion": _serializar_tema(res["coleccion"]) if res.get("coleccion") else None,
            "fuente": res["fuente"],
            "creadas": [{"id": t["id"], "nombre": t["nombre"], "lenguaje": t.get("lenguaje", "")} for t in res["creadas"]],
            "omitidas": res["omitidas"],
        }

    # 21. pedir_pista (v3.0)
    @mcp.tool(
        description="Entrega una pista socrática progresiva (niveles 1 a 3) para una pregunta pendiente sin regalar la respuesta literal.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    def pedir_pista(pregunta_id: int) -> dict[str, Any]:
        return agente.pedir_pista(pregunta_id)

    # 22. iniciar_simulacro (v3.0)
    @mcp.tool(
        description="Inicia un simulacro de examen cronometrado (1-20 preguntas) filtrado por colección, DevCards o brechas.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    def iniciar_simulacro(
        titulo: str = "Simulacro de estudio",
        cantidad: int = 5,
        coleccion_id: Optional[int] = None,
        categoria_devcards: str = "",
        solo_brechas: bool = False,
    ) -> dict[str, Any]:
        res = agente.iniciar_simulacro(
            titulo=titulo[:160],
            cantidad=cantidad,
            coleccion_id=coleccion_id,
            categoria_devcards=categoria_devcards,
            solo_brechas=solo_brechas,
        )
        return {"sesion": _serializar_tema(res["sesion"]), "preguntas": res["preguntas"]}

    # 23. ver_simulacros (v3.0)
    @mcp.tool(
        description="Lista los últimos simulacros de examen con porcentaje de aciertos, nota promedio y duración.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def ver_simulacros(limite: int = 10) -> list[dict[str, Any]]:
        return [_serializar_tema(s) for s in agente.ver_simulacros(limite=limite)]

    # 24. vincular_temas (v3.0)
    @mcp.tool(
        description="Crea una relación entre dos temas en el grafo de conocimiento ('prerrequisito' o 'relacionado').",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def vincular_temas(origen_id: int, destino_id: int, tipo: str = "prerrequisito") -> dict[str, Any]:
        return _serializar_tema(agente.vincular_temas(origen_id, destino_id, tipo=tipo))

    # 25. plan_estudio_hoy (v3.0)
    @mcp.tool(
        description="Devuelve el plan de estudio diario, meta diaria, tiempo estimado, racha y pronóstico de los próximos 7 días.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def plan_estudio_hoy() -> dict[str, Any]:
        return agente.plan_estudio_hoy()

    # =========================================================================
    # 8 MCP RESOURCES (contexto vivo en solo lectura)
    # =========================================================================

    @mcp.resource("tutor://estado", mime_type="application/json", description="Estado técnico, racha y progreso del tutor.")
    def recurso_estado() -> str:
        return _json_dumps(agente.estado())

    @mcp.resource("tutor://pendientes", mime_type="application/json", description="Cola de preguntas pendientes sin revelar respuestas.")
    def recurso_pendientes() -> str:
        datos = [{**_limpiar(p), "lectura": agente.lectura_de(p)} for p in agente.memoria.pendientes()]
        return _json_dumps(datos)

    @mcp.resource("tutor://colecciones", mime_type="application/json", description="Colecciones personalizadas y métricas por mazo.")
    def recurso_colecciones() -> str:
        return _json_dumps(agente.listar_colecciones())

    @mcp.resource("tutor://tema/{tema_id}", mime_type="application/json", description="Detalle completo de una ficha por ID.")
    def recurso_tema(tema_id: str) -> str:
        t = agente.memoria.obtener_tema(int(tema_id))
        if t is None:
            raise ValueError(f"No existe el tema {tema_id}")
        return _json_dumps(t)

    @mcp.resource("tutor://brechas", mime_type="application/json", description="Brechas en refuerzo y recomendación de estudio.")
    def recurso_brechas() -> str:
        return _json_dumps(agente.diagnosticar_brechas())

    @mcp.resource("tutor://bitacora/reciente", mime_type="application/json", description="Últimos 25 eventos y reflexiones de la bitácora.")
    def recurso_bitacora() -> str:
        return _json_dumps(agente.memoria.leer_bitacora(25))

    @mcp.resource("tutor://plan/hoy", mime_type="application/json", description="Meta diaria, tiempo estimado y pronóstico de 7 días.")
    def recurso_plan_hoy() -> str:
        return _json_dumps(agente.plan_estudio_hoy())

    @mcp.resource("tutor://examenes", mime_type="application/json", description="Historial de simulacros de examen recientes.")
    def recurso_examenes() -> str:
        return _json_dumps(agente.ver_simulacros(10))

    # =========================================================================
    # 7 MCP PROMPTS (flujos pedagógicos reutilizables)
    # =========================================================================

    @mcp.prompt(description="Guía una sesión interactiva de repaso SM-2 sin revelar respuestas.")
    def sesion_repaso(coleccion: str = "") -> str:
        foco = f" enfocándote en la colección «{coleccion}»" if coleccion.strip() else ""
        return (
            f"Inicia una sesión de estudio con el usuario{foco}. "
            "1) Llama a ver_preguntas_pendientes. "
            "2) Si requiere_lectura es true, muestra primero la ficha completa (incluyendo el código) y espera a que confirme para llamar a marcar_tarjeta_leida. "
            "3) Haz UNA pregunta a la vez sin revelar ni sugerir la respuesta. "
            "4) Cuando el usuario responda, llama a responder_pregunta y comparte la calificación y próxima fecha SM-2."
        )

    @mcp.prompt(description="Guarda en el tutor el código recién generado para estudiarlo luego.")
    def aprender_codigo_generado(lenguaje: str = "", coleccion: str = "Código estudiado") -> str:
        lang_txt = f" en {lenguaje}" if lenguaje.strip() else ""
        return (
            f"Toma el código{lang_txt} que acabamos de escribir o revisar, resume brevemente su propósito y "
            f"llama a la herramienta estudiar_codigo guardándolo en la colección «{coleccion}». "
            "Al terminar, indica al usuario cuántas fichas quedaron programadas para su próximo repaso SM-2."
        )

    @mcp.prompt(description="Convierte apuntes o notas de conversación en fichas atómicas.")
    def ingestar_apuntes(coleccion: str = "Material de estudio") -> str:
        return (
            f"Organiza los apuntes o conceptos clave proporcionados en Markdown limpio por secciones y "
            f"llama a ingestar_material para guardarlos en la colección «{coleccion}». "
            "Confirma al final cuántas fichas nuevas se crearon."
        )

    @mcp.prompt(description="Modo tutor socrático: ayuda al estudiante a razonar sin darle la respuesta directa.")
    def tutor_socratico(tema: str = "") -> str:
        foco = f" sobre «{tema}»" if tema.strip() else ""
        return (
            f"Actúa como tutor socrático{foco}. Consulta tutor://pendientes o ver_preguntas_pendientes, "
            "presenta la pregunta y si el estudiante duda, dale una pista conceptual mínima sin revelar la respuesta esperada "
            "hasta que envíe su intento real a responder_pregunta."
        )

    @mcp.prompt(description="Genera un resumen semanal con racha, progreso y plan para superar brechas.")
    def resumen_semanal() -> str:
        return (
            "Lee los recursos tutor://estado, tutor://brechas, tutor://plan/hoy, tutor://colecciones y tutor://bitacora/reciente. "
            "Entrega al estudiante un informe claro con su racha actual, meta diaria, temas dominados, brechas en refuerzo "
            "y un plan concreto para los próximos 7 días."
        )

    @mcp.prompt(description="Convierte el git diff reciente del repositorio en fichas de estudio guiadas.")
    def estudiar_ultimo_diff(coleccion: str = "Cambios Git (Diff)") -> str:
        return (
            f"Toma el git diff proporcionado por el usuario (o de su último commit) y llama a estudiar_diff "
            f"guardándolo en la colección «{coleccion}». Luego explica en 3 líneas qué partes clave conviene repasar."
        )

    @mcp.prompt(description="Simula una entrevista técnica cronometrada usando el modo simulacro del tutor.")
    def entrevista_tecnica(cantidad: int = 5, tema_foco: str = "") -> str:
        foco = f" centrada en «{tema_foco}»" if tema_foco.strip() else ""
        return (
            f"Conduce un simulacro de entrevista técnica de {cantidad} preguntas{foco}. "
            "1) Llama a iniciar_simulacro. 2) Haz cada pregunta una por una sin revelar respuestas. "
            "3) Si el estudiante se bloquea, ofrece llamar a pedir_pista antes de rendirse. "
            "4) Evalúa cada intento con responder_pregunta y al terminar muestra el puntaje final de ver_simulacros."
        )

    return mcp


def main_cli(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="agente-tutor-mcp",
        description="Servidor MCP del Agente Tutor Persistente v2.0 (transporte stdio).",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio"],
        default="stdio",
        help="Transporte MCP local (por defecto: stdio).",
    )
    args = parser.parse_args(argv)
    from app.config import Config

    crear_servidor_mcp(AgenteTutor(Config.desde_entorno())).run(args.transport)


# Punto de entrada directo si ejecutas "python -m app.mcp_tools" o "agente-tutor-mcp".
if __name__ == "__main__":  # modo local por stdio; el ciclo autónomo corre en el servidor web
    main_cli()

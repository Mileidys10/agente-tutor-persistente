# Archivo app/mcp_tools.py: expone 9 herramientas MCP para que Claude Desktop o Claude Code estudien contigo.
# App/main.py lo monta en /mcp para acceso remoto y también puede ejecutarse directo por stdio en local.
"""Servidor MCP del tutor: cualquier cliente MCP (Claude Desktop, Claude Code, Gemini CLI...) puede
estudiar con el agente. Las herramientas usan la misma memoria persistente que la web.

Dos formas de conectarse:
  - Remoto (Render): Streamable HTTP en https://<servicio>.onrender.com/mcp  (cabecera Authorization: Bearer <TUTOR_TOKEN>)
  - Local:           python -m app.mcp_tools   (transporte stdio)
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from app.agente import AgenteTutor


# Quita "respuesta_esperada" y otros campos internos antes de mandar una pregunta al cliente MCP.
def _limpiar(p: dict[str, Any]) -> dict[str, Any]:
    # Nunca se revela la respuesta esperada antes de que la persona conteste.
    return {
        "pregunta_id": p["id"], "tema": p.get("tema"), "pregunta": p["texto"], "opciones": p.get("opciones"),
        "motivo": p.get("motivo"), "requiere_lectura": bool(p.get("requiere_lectura")),
    }


# Registra el servidor MCP y conecta cada herramienta con los métodos de AgenteTutor (app/agente.py).
# La llama app/main.py al arrancar la web o el bloque __main__ si se ejecuta por terminal (stdio).
def crear_servidor_mcp(agente: AgenteTutor) -> MCPServer:
    mcp = MCPServer(
        name="agente-tutor-persistente",
        instructions=(
            "Tutor de estudio persistente con repetición espaciada (SM-2) y el banco de 1 295 DevCards. "
            "Usa ver_preguntas_pendientes para saber qué toca repasar, muestra la pregunta a la persona, "
            "y envía SU respuesta con responder_pregunta. No respondas tú por ella."
        ),
    )

    # Herramienta 1: guarda un tema propio del estudiante delegando en agente.agregar_tema().
    @mcp.tool(
        description="Agrega un tema propio con tus notas de estudio. El agente lo preguntará en su próximo ciclo.",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    def agregar_tema(nombre: str, notas: str) -> dict[str, Any]:
        tema = agente.agregar_tema(nombre[:200], notas[:8000])
        return {"tema_id": tema["id"], "nombre": tema["nombre"]}

    # Herramienta 2: lista preguntas pendientes junto con su ficha de lectura si requiere_lectura es True.
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

    # Herramienta 3: equivale al botón "Ya la leí" de la web; desbloquea la pregunta en la base de datos.
    @mcp.tool(
        description="Marca como leída la DevCard de una pregunta (paso previo obligatorio si requiere_lectura es true).",
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

    # Herramienta 4: evalúa la respuesta del estudiante y reprograma el tema con SM-2.
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

    # Herramienta 5: muestra las 42 categorías DevCards y cuántas tarjetas has visto de cada una.
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

    # Herramienta 6: activa o pausa una categoría DevCards igual que los interruptores de la página web.
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

    # Herramienta 7: devuelve métricas de estudio (temas, dominados, aciertos y temas más difíciles).
    @mcp.tool(
        description="Progreso de estudio: temas, dominados, porcentaje de aciertos y temas más difíciles.",
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    def ver_progreso() -> dict[str, Any]:
        return agente.progreso()

    # Herramienta 8: resume estado vivo, latido (arranques y ciclos), cerebro y configuración actual.
    @mcp.tool(
        description="Estado del agente: si está vivo, ciclos, arranques y configuración.",
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

    # Herramienta 9: lee el historial reciente de decisiones guardadas en la tabla bitacora.
    @mcp.tool(
        description="Últimas decisiones y acciones que el agente anotó en su bitácora.",
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

    return mcp


# Punto de entrada directo si ejecutas "python -m app.mcp_tools" desde Claude Desktop por entrada/salida estándar (stdio).
if __name__ == "__main__":  # modo local por stdio; el ciclo autónomo corre en el servidor web
    from app.config import Config

    crear_servidor_mcp(AgenteTutor(Config.desde_entorno())).run("stdio")

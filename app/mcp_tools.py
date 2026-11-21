"""Servidor MCP del tutor: cualquier cliente MCP (Claude Desktop, Claude Code, Gemini CLI...) puede
estudiar con el agente. Las herramientas usan la misma memoria persistente que la web.

Dos formas de conectarse:
  - Remoto (Render): Streamable HTTP en https://<servicio>.onrender.com/mcp  (cabecera Authorization: Bearer <TUTOR_TOKEN>)
  - Local:           python -m app.mcp_tools   (transporte stdio)
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from app.agente import AgenteTutor


def _limpiar(p: dict[str, Any]) -> dict[str, Any]:
    # Nunca se revela la respuesta esperada antes de que la persona conteste.
    return {
        "pregunta_id": p["id"], "tema": p.get("tema"), "pregunta": p["texto"], "opciones": p.get("opciones"),
        "motivo": p.get("motivo"),
    }


def crear_servidor_mcp(agente: AgenteTutor) -> MCPServer:
    mcp = MCPServer(
        name="agente-tutor-persistente",
        instructions=(
            "Tutor de estudio persistente con repetición espaciada (SM-2) y el banco de 1 295 DevCards. "
            "Usa ver_preguntas_pendientes para saber qué toca repasar, muestra la pregunta a la persona, "
            "y envía SU respuesta con responder_pregunta. No respondas tú por ella."
        ),
    )

    @mcp.tool(description="Agrega un tema propio con tus notas de estudio. El agente lo preguntará en su próximo ciclo.")
    def agregar_tema(nombre: str, notas: str) -> dict[str, Any]:
        tema = agente.agregar_tema(nombre[:200], notas[:8000])
        return {"tema_id": tema["id"], "nombre": tema["nombre"]}

    @mcp.tool(description="Preguntas que el agente preparó y esperan respuesta (sin revelar la respuesta).")
    def ver_preguntas_pendientes() -> list[dict[str, Any]]:
        if not agente.vivo:  # modo stdio sin hilo de fondo: se ejecuta un ciclo al consultar
            agente.ciclo()
        return [_limpiar(p) for p in agente.memoria.pendientes()]

    @mcp.tool(description="Envía la respuesta de la persona a una pregunta pendiente. Para opción múltiple vale la letra (A, B, C...).")
    def responder_pregunta(pregunta_id: int, respuesta: str) -> dict[str, Any]:
        r = agente.responder(pregunta_id, respuesta[:2000])
        return {**r, "proximo_repaso": r["proximo_repaso"].isoformat()}

    @mcp.tool(description="Lista los mazos de DevCards con cuántas tarjetas tienen y si están activos.")
    def ver_mazos() -> list[dict[str, Any]]:
        return agente.mazos()

    @mcp.tool(description="Activa o pausa un mazo de DevCards por su nombre exacto de categoría.")
    def activar_mazo(categoria: str, activo: bool = True) -> dict[str, Any]:
        agente.activar_mazo(categoria, activo)
        return {"categoria": categoria, "activo": activo}

    @mcp.tool(description="Progreso de estudio: temas, dominados, porcentaje de aciertos y temas más difíciles.")
    def ver_progreso() -> dict[str, Any]:
        return agente.progreso()

    @mcp.tool(description="Estado del agente: si está vivo, ciclos, arranques y configuración.")
    def ver_estado() -> dict[str, Any]:
        e = agente.estado()
        lat = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in (e.get("latido") or {}).items()}
        return {**e, "latido": lat}

    @mcp.tool(description="Últimas decisiones y acciones que el agente anotó en su bitácora.")
    def ver_bitacora(limite: int = 15) -> list[dict[str, Any]]:
        return [
            {"fecha": b["fecha"].isoformat(), "tipo": b["tipo"], "detalle": b["detalle"]}
            for b in agente.memoria.leer_bitacora(max(1, min(limite, 100)))
        ]

    return mcp


if __name__ == "__main__":  # modo local por stdio; el ciclo autónomo corre en el servidor web
    from app.config import Config

    crear_servidor_mcp(AgenteTutor(Config.desde_entorno())).run("stdio")

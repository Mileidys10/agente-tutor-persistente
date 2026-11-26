"""Pruebas completas del servidor MCP v3.0: 25 Tools con 4 ToolAnnotations booleanos, 8 Resources y 7 Prompts."""

from __future__ import annotations

import asyncio
import importlib
import json
import random
from pathlib import Path

from fastapi.testclient import TestClient

from app.agente import AgenteTutor
from app.cerebro import Cerebro
from app.config import Config
from app.mcp_tools import crear_servidor_mcp

TODAS_25_TOOLS = {
    "agregar_tema",
    "ver_preguntas_pendientes",
    "marcar_tarjeta_leida",
    "responder_pregunta",
    "ver_mazos",
    "activar_mazo",
    "ver_progreso",
    "ver_estado",
    "ver_bitacora",
    "estudiar_codigo",
    "ingestar_material",
    "gestionar_coleccion",
    "buscar_temas",
    "editar_tema",
    "borrar_tema",
    "posponer_tema",
    "diagnosticar_brechas",
    "exportar_mazo",
    "importar_mazo",
    "estudiar_diff",
    "pedir_pista",
    "iniciar_simulacro",
    "ver_simulacros",
    "vincular_temas",
    "plan_estudio_hoy",
}


def _rpc(metodo: str, params: dict | None = None, id_: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "method": metodo, "params": params or {}}


MCP_H = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "Authorization": "Bearer tok-mcp-v3",
}


def test_mcp_v3_25_tools_annotations_y_llamadas(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'mcpv3.db'}")
    monkeypatch.setenv("TUTOR_AUTONOMO", "0")
    monkeypatch.setenv("TUTOR_TOKEN", "tok-mcp-v3")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import app.main as main

    main = importlib.reload(main)
    main.agente.cerebro = Cerebro("", rng=random.Random(4))

    with TestClient(main.app) as c:
        init = _rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "v3", "version": "3"}})
        assert c.post("/mcp", json=init, headers=MCP_H).status_code == 200

        lista = c.post("/mcp", json=_rpc("tools/list", id_=2), headers=MCP_H).json()["result"]["tools"]
        nombres = {t["name"] for t in lista}
        assert TODAS_25_TOOLS == nombres

        for tool in lista:
            ann = tool.get("annotations") or {}
            for campo in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
                assert isinstance(ann.get(campo), bool), f"{tool['name']} falta hint {campo}"

        def call(name: str, arguments: dict | None = None, req_id: int = 10) -> dict:
            r = c.post("/mcp", json=_rpc("tools/call", {"name": name, "arguments": arguments or {}}, req_id), headers=MCP_H)
            assert r.status_code == 200, r.text
            res = r.json()["result"]
            assert not res.get("isError"), res
            return res

        # 20. estudiar_diff
        r_diff = call(
            "estudiar_diff",
            {"diff_texto": "diff --git a/srv.py b/srv.py\n+++ b/srv.py\n+def ping():\n+    return 'pong'"},
            20,
        )
        t1_id = json.loads(r_diff["content"][0]["text"])["creadas"][0]["id"]
        t2_id = json.loads(call("agregar_tema", {"nombre": "FastAPI Lifespan", "notas": "Gestiona arranque y cierre."}, 21)["content"][0]["text"])["tema_id"]

        # 24. vincular_temas
        call("vincular_temas", {"origen_id": t1_id, "destino_id": t2_id, "tipo": "prerrequisito"}, 22)

        # 22. iniciar_simulacro + 21. pedir_pista + 23. ver_simulacros
        r_sim = call("iniciar_simulacro", {"titulo": "Sim MCP", "cantidad": 2}, 23)
        sim_pregs = json.loads(r_sim["content"][0]["text"])["preguntas"]
        assert sim_pregs
        r_pista = call("pedir_pista", {"pregunta_id": sim_pregs[0]["id"]}, 24)
        assert json.loads(r_pista["content"][0]["text"])["nivel"] == 1
        call("ver_simulacros", {"limite": 5}, 25)

        # 25. plan_estudio_hoy
        r_plan = call("plan_estudio_hoy", {}, 26)
        assert len(json.loads(r_plan["content"][0]["text"])["pronostico_7_dias"]) == 7

        # Exportar en formato anki
        cols = json.loads(call("gestionar_coleccion", {"accion": "listar"}, 27)["content"][0]["text"])["colecciones"]
        r_anki = call("exportar_mazo", {"coleccion_id": cols[0]["id"], "formato": "anki"}, 28)
        assert "\t" in json.loads(r_anki["content"][0]["text"])["contenido"]


def test_mcp_v3_8_resources_y_7_prompts(tmp_path: Path) -> None:
    cfg = Config(
        database_url=f"sqlite:///{tmp_path / 'res3.db'}", gemini_api_key="", gemini_modelo="x",
        intervalo_ciclo_s=1.0, minutos_por_dia=1440, max_pendientes=3, nuevas_por_dia=0, token="", autonomo=False,
    )
    ag = AgenteTutor(cfg, cerebro=Cerebro("", rng=random.Random(1)))
    ag.agregar_tema("HTTP", "Protocolo sin estado sobre TCP.")
    ag.iniciar_simulacro(cantidad=1)
    srv = crear_servidor_mcp(ag)

    async def verificar() -> None:
        uris = {str(r.uri) for r in await srv.list_resources()}
        assert {
            "tutor://estado",
            "tutor://pendientes",
            "tutor://colecciones",
            "tutor://brechas",
            "tutor://bitacora/reciente",
            "tutor://plan/hoy",
            "tutor://examenes",
        } <= uris
        for uri in ("tutor://plan/hoy", "tutor://examenes"):
            contenido = list(await srv.read_resource(uri))[0].content
            assert json.loads(contenido) is not None

        prompts = {p.name for p in await srv.list_prompts()}
        assert {
            "sesion_repaso",
            "aprender_codigo_generado",
            "ingestar_apuntes",
            "tutor_socratico",
            "resumen_semanal",
            "estudiar_ultimo_diff",
            "entrevista_tecnica",
        } == prompts
        assert (await srv.get_prompt("estudiar_ultimo_diff", {"coleccion": "Git"})).messages
        assert (await srv.get_prompt("entrevista_tecnica", {"cantidad": 3, "tema_foco": "SQL"})).messages

    asyncio.run(verificar())

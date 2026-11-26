"""Pruebas completas del servidor MCP v2.0: 19 Tools, 4 ToolAnnotations booleanos, 6 Resources y 5 Prompts."""

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
from app.mcp_tools import crear_servidor_mcp, main_cli

TODAS_LAS_TOOLS = {
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
}


def _rpc(metodo: str, params: dict | None = None, id_: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "method": metodo, "params": params or {}}


MCP_H = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "Authorization": "Bearer tok-mcp-v2",
}


def test_mcp_annotations_19_tools_y_cobertura_completa(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'mcpv2.db'}")
    monkeypatch.setenv("TUTOR_AUTONOMO", "0")
    monkeypatch.setenv("TUTOR_TOKEN", "tok-mcp-v2")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import app.main as main

    main = importlib.reload(main)
    main.agente.cerebro = Cerebro("", rng=random.Random(3))

    with TestClient(main.app) as c:
        init = _rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "v2", "version": "2"}})
        assert c.post("/mcp", json=init, headers=MCP_H).status_code == 200

        lista = c.post("/mcp", json=_rpc("tools/list", id_=2), headers=MCP_H).json()["result"]["tools"]
        nombres = {t["name"] for t in lista}
        assert TODAS_LAS_TOOLS <= nombres

        # Verificar que TODAS las herramientas tienen los 4 hints como booleanos explícitos (M8ven / OpenAI spec)
        for tool in lista:
            ann = tool.get("annotations") or {}
            for campo in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
                assert isinstance(ann.get(campo), bool), f"{tool['name']} falta hint booleano {campo}: {ann}"

        def call(name: str, arguments: dict | None = None, req_id: int = 10) -> dict:
            r = c.post("/mcp", json=_rpc("tools/call", {"name": name, "arguments": arguments or {}}, req_id), headers=MCP_H)
            assert r.status_code == 200, r.text
            res = r.json()["result"]
            assert not res.get("isError"), res
            return res

        # 1. gestionar_coleccion (crear + listar)
        r_col = call("gestionar_coleccion", {"accion": "crear", "nombre": "Python Core", "descripcion": "POO"}, 10)
        col_id = json.loads(r_col["content"][0]["text"])["coleccion"]["id"]
        call("gestionar_coleccion", {"accion": "listar"}, 11)

        # 2. agregar_tema
        call("agregar_tema", {"nombre": "Generadores", "notas": "Usan yield para evaluación perezosa.", "coleccion_id": col_id}, 12)

        # 3. estudiar_codigo
        r_cod = call(
            "estudiar_codigo",
            {"codigo": "def filtrar(items):\n    return [x for x in items if x > 0]", "titulo": "Filtro", "coleccion": "Python Core"},
            13,
        )
        cod_id = json.loads(r_cod["content"][0]["text"])["creadas"][0]["id"]

        # 4. ingestar_material
        call(
            "ingestar_material",
            {"contenido": "## Decoradores\nPermiten envolver funciones.\n## Context Managers\nGestionan recursos con with.", "coleccion": "Python Core"},
            14,
        )

        # 5. buscar_temas
        r_bus = call("buscar_temas", {"consulta": "Filtro"}, 15)
        assert "Filtro" in r_bus["content"][0]["text"]

        # 6. editar_tema
        call("editar_tema", {"tema_id": cod_id, "idea_clave": "List comprehension filtra positivos"}, 16)

        # 7. ver_preguntas_pendientes (ejecuta ciclo en modo no vivo / consulta)
        c.post("/api/ciclo", headers={"X-Tutor-Token": "tok-mcp-v2"})
        r_pend = call("ver_preguntas_pendientes", {}, 17)
        pendientes = (r_pend.get("structuredContent") or {}).get("result") or [
            json.loads(item["text"]) for item in r_pend["content"]
        ]
        assert pendientes

        # 8. marcar_tarjeta_leida + 9. responder_pregunta
        con_lectura = next((p for p in pendientes if p["requiere_lectura"]), pendientes[0])
        if con_lectura["requiere_lectura"]:
            call("marcar_tarjeta_leida", {"pregunta_id": con_lectura["pregunta_id"]}, 18)
        call("responder_pregunta", {"pregunta_id": con_lectura["pregunta_id"], "respuesta": "filtra"}, 19)

        # 10. ver_mazos + 11. activar_mazo
        r_maz = call("ver_mazos", {}, 20)
        mazos = (r_maz.get("structuredContent") or {}).get("result") or [
            json.loads(item["text"]) for item in r_maz["content"]
        ]
        assert mazos
        call("activar_mazo", {"categoria": mazos[0]["categoria"], "activo": True}, 21)

        # 12. ver_progreso + 13. ver_estado + 14. ver_bitacora + 15. diagnosticar_brechas
        call("ver_progreso", {}, 22)
        call("ver_estado", {}, 23)
        call("ver_bitacora", {"limite": 5}, 24)
        call("diagnosticar_brechas", {"limite": 5}, 25)

        # 16. exportar_mazo + 17. importar_mazo
        r_exp = call("exportar_mazo", {"coleccion_id": col_id, "formato": "json"}, 26)
        paquete_json = json.loads(r_exp["content"][0]["text"])["contenido"]
        call("importar_mazo", {"contenido": json.dumps(paquete_json), "formato": "json", "nombre_coleccion": "Python Copia"}, 27)

        # 18. posponer_tema + 19. borrar_tema
        call("posponer_tema", {"tema_id": cod_id, "dias": 2.0}, 28)
        call("borrar_tema", {"tema_id": cod_id}, 29)


def test_mcp_6_resources_y_5_prompts(tmp_path: Path) -> None:
    cfg = Config(
        database_url=f"sqlite:///{tmp_path / 'res.db'}", gemini_api_key="", gemini_modelo="x",
        intervalo_ciclo_s=1.0, minutos_por_dia=1440, max_pendientes=3, nuevas_por_dia=0, token="", autonomo=False,
    )
    ag = AgenteTutor(cfg, cerebro=Cerebro("", rng=random.Random(1)))
    res_cod = ag.estudiar_codigo("def doble(n):\n    return n * 2", titulo="Doble", coleccion="Mat")
    tid = res_cod["creadas"][0]["id"]
    ag.ciclo()
    srv = crear_servidor_mcp(ag)

    async def verificar() -> None:
        uris = {str(r.uri) for r in await srv.list_resources()}
        assert {
            "tutor://estado",
            "tutor://pendientes",
            "tutor://colecciones",
            "tutor://brechas",
            "tutor://bitacora/reciente",
        } <= uris
        templates = {t.uri_template for t in await srv.list_resource_templates()}
        assert "tutor://tema/{tema_id}" in templates

        for uri in ("tutor://estado", "tutor://pendientes", "tutor://colecciones", f"tutor://tema/{tid}", "tutor://brechas", "tutor://bitacora/reciente"):
            contenido = list(await srv.read_resource(uri))[0].content
            datos = json.loads(contenido)
            if uri == "tutor://pendientes":
                assert all("respuesta_esperada" not in item for item in datos)

        prompts = {p.name for p in await srv.list_prompts()}
        assert {"sesion_repaso", "aprender_codigo_generado", "ingestar_apuntes", "tutor_socratico", "resumen_semanal"} <= prompts
        for nombre, args in (
            ("sesion_repaso", {"coleccion": "Mat"}),
            ("aprender_codigo_generado", {"lenguaje": "python"}),
            ("ingestar_apuntes", {"coleccion": "Mat"}),
            ("tutor_socratico", {"tema": "Doble"}),
            ("resumen_semanal", {}),
        ):
            gp = await srv.get_prompt(nombre, args)
            assert gp.messages

    asyncio.run(verificar())


def test_cli_help(capsys) -> None:
    try:
        main_cli(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    out = capsys.readouterr().out
    assert "agente-tutor-mcp" in out

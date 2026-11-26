"""Pruebas de la API web, la seguridad por token y el servidor MCP remoto."""

from __future__ import annotations

import importlib
import random
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agente import AgenteTutor
from app.cerebro import Cerebro


@pytest.fixture()
def cliente(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("TUTOR_AUTONOMO", "0")
    monkeypatch.setenv("TUTOR_TOKEN", "secreto-de-prueba")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import app.main as main

    main = importlib.reload(main)
    main.agente.cerebro = Cerebro("", rng=random.Random(2))
    with TestClient(main.app) as c:
        yield c, main


H = {"X-Tutor-Token": "secreto-de-prueba"}


def test_lectura_publica_y_escritura_protegida(cliente) -> None:
    c, _ = cliente
    assert c.get("/health").json()["ok"] is True
    assert c.get("/api/estado").status_code == 200
    assert c.post("/api/temas", json={"nombre": "SQL", "notas": "x"}).status_code == 401
    assert c.post("/api/temas", json={"nombre": "SQL", "notas": "x"}, headers={"X-Tutor-Token": "mal"}).status_code == 401
    assert c.post("/api/temas", json={"nombre": "SQL", "notas": "JOIN combina filas de dos tablas."}, headers=H).status_code == 201
    assert c.post("/api/temas", json={"nombre": "sql", "notas": "x"}, headers=H).status_code == 409
    assert c.get("/api/acceso", headers={"Authorization": "Bearer secreto-de-prueba"}).json()["ok"] is True


def test_flujo_completo_por_api(cliente) -> None:
    c, main = cliente
    c.post("/api/temas", json={"nombre": "Fotosíntesis", "notas": "Ocurre en los cloroplastos de las hojas verdes."}, headers=H)
    c.post("/api/ciclo", headers=H)
    pend = c.get("/api/preguntas/pendientes").json()
    assert len(pend) == 1 and "respuesta_esperada" not in pend[0]  # la API no revela la respuesta
    esperada = main.agente.memoria.obtener_pregunta(pend[0]["id"])["respuesta_esperada"]
    r = c.post(f"/api/preguntas/{pend[0]['id']}/responder", json={"respuesta": esperada}, headers=H).json()
    assert r["nota"] == 5
    assert c.post(f"/api/preguntas/{pend[0]['id']}/responder", json={"respuesta": "x"}, headers=H).status_code == 409
    assert c.post("/api/preguntas/999/responder", json={"respuesta": "x"}, headers=H).status_code == 404
    assert c.get("/api/historial").json()[0]["nota"] == 5
    assert any(b["tipo"] == "evaluacion" for b in c.get("/api/bitacora").json())


def test_mazos_por_api(cliente) -> None:
    c, _ = cliente
    mazos = c.get("/api/mazos").json()
    assert len(mazos) > 20 and sum(m["tarjetas"] for m in mazos) == 1295
    assert c.put("/api/mazos/Angular", json={"activo": True}, headers=H).status_code == 200
    assert c.put("/api/mazos/No existe", json={"activo": True}, headers=H).status_code == 404
    c.post("/api/ciclo", headers=H)
    pend = c.get("/api/preguntas/pendientes").json()
    assert pend and pend[0]["opciones"] and pend[0]["fuente"] == "devcards"


def test_validacion_de_tamano(cliente) -> None:
    c, _ = cliente
    assert c.post("/api/temas", json={"nombre": "x" * 201, "notas": ""}, headers=H).status_code == 422
    assert c.post("/api/temas", json={"nombre": "ok", "notas": "x" * 8001}, headers=H).status_code == 422


def _rpc(metodo: str, params: dict | None = None, id_: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "method": metodo, "params": params or {}}


MCP_H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def test_mcp_remoto_exige_token_y_lista_herramientas(cliente) -> None:
    c, _ = cliente
    init = _rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "prueba", "version": "1"}})
    assert c.post("/mcp", json=init, headers=MCP_H).status_code == 401
    h = {**MCP_H, "Authorization": "Bearer secreto-de-prueba"}
    r = c.post("/mcp", json=init, headers=h)
    assert r.status_code == 200, r.text
    herramientas = c.post("/mcp", json=_rpc("tools/list", id_=2), headers=h)
    assert herramientas.status_code == 200, herramientas.text
    nombres = {t["name"] for t in herramientas.json()["result"]["tools"]}
    assert {"ver_preguntas_pendientes", "responder_pregunta", "agregar_tema", "ver_mazos"} <= nombres
    llamada = c.post("/mcp", json=_rpc("tools/call", {"name": "agregar_tema",
                                                     "arguments": {"nombre": "MCP", "notas": "Protocolo de contexto."}}, 3), headers=h)
    assert llamada.status_code == 200 and not llamada.json()["result"].get("isError"), llamada.text
    assert any(t["nombre"] == "MCP" for t in c.get("/api/temas").json())


def test_modo_lectura_por_api(cliente) -> None:
    c, _ = cliente
    c.put("/api/mazos/POO", json={"activo": True}, headers=H)
    c.post("/api/ciclo", headers=H)
    p = c.get("/api/preguntas/pendientes").json()[0]
    assert p["requiere_lectura"] is True and p["lectura"]["definicion"]
    assert c.post(f"/api/preguntas/{p['id']}/responder", json={"respuesta": "A"}, headers=H).status_code == 409
    assert c.post(f"/api/preguntas/{p['id']}/leida").status_code == 401  # escribe: exige token
    assert c.post(f"/api/preguntas/{p['id']}/leida", headers=H).status_code == 200
    assert c.post(f"/api/preguntas/{p['id']}/leida", headers=H).status_code == 200  # idempotente
    despues = c.get("/api/preguntas/pendientes").json()[0]
    assert despues["requiere_lectura"] is False and despues["lectura"] is None
    assert c.post(f"/api/preguntas/{p['id']}/responder", json={"respuesta": "A"}, headers=H).status_code == 200
    assert c.post("/api/preguntas/999/leida", headers=H).status_code == 404


def test_forzar_ciclo_no_revela_la_respuesta(cliente) -> None:
    c, _ = cliente
    c.post("/api/temas", json={"nombre": "Redes", "notas": "TCP garantiza la entrega ordenada de los paquetes."}, headers=H)
    creadas = c.post("/api/ciclo", headers=H).json()["preguntas_creadas"]
    assert creadas and all("respuesta_esperada" not in p for p in creadas)


def test_cobertura_completa_nueve_herramientas_mcp(cliente) -> None:
    c, main = cliente
    h = {**MCP_H, "Authorization": "Bearer secreto-de-prueba"}
    init = _rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
    c.post("/mcp", json=init, headers=h)

    # 1. agregar_tema
    r_agr = c.post("/mcp", json=_rpc("tools/call", {"name": "agregar_tema", "arguments": {"nombre": "Docker", "notas": "Contenedores ligeros."}}, 10), headers=h)
    assert r_agr.status_code == 200

    # Forzar ciclo para generar una pregunta
    c.post("/api/ciclo", headers=H)

    # 2. ver_preguntas_pendientes
    r_pend = c.post("/mcp", json=_rpc("tools/call", {"name": "ver_preguntas_pendientes", "arguments": {}}, 11), headers=h)
    assert r_pend.status_code == 200
    pendientes = r_pend.json()["result"]["content"][0]["text"]
    assert "pregunta_id" in pendientes

    preg_id = main.agente.memoria.pendientes()[0]["id"]

    # 3. marcar_tarjeta_leida
    r_lei = c.post("/mcp", json=_rpc("tools/call", {"name": "marcar_tarjeta_leida", "arguments": {"pregunta_id": preg_id}}, 12), headers=h)
    assert r_lei.status_code == 200

    # 4. responder_pregunta
    r_resp = c.post("/mcp", json=_rpc("tools/call", {"name": "responder_pregunta", "arguments": {"pregunta_id": preg_id, "respuesta": "Contenedores"}}, 13), headers=h)
    assert r_resp.status_code == 200

    # 5. ver_mazos
    r_maz = c.post("/mcp", json=_rpc("tools/call", {"name": "ver_mazos", "arguments": {}}, 14), headers=h)
    assert r_maz.status_code == 200

    # 6. activar_mazo
    r_act = c.post("/mcp", json=_rpc("tools/call", {"name": "activar_mazo", "arguments": {"categoria": "Docker", "activo": True}}, 15), headers=h)
    assert r_act.status_code == 200

    # 7. ver_progreso
    r_prog = c.post("/mcp", json=_rpc("tools/call", {"name": "ver_progreso", "arguments": {}}, 16), headers=h)
    assert r_prog.status_code == 200

    # 8. ver_estado
    r_est = c.post("/mcp", json=_rpc("tools/call", {"name": "ver_estado", "arguments": {}}, 17), headers=h)
    assert r_est.status_code == 200

    # 9. ver_bitacora
    r_bit = c.post("/mcp", json=_rpc("tools/call", {"name": "ver_bitacora", "arguments": {"limite": 5}}, 18), headers=h)
    assert r_bit.status_code == 200


def test_colecciones_busqueda_edicion_posponer_exportar_importar(cliente) -> None:
    c, _ = cliente
    assert c.post("/api/colecciones", json={"nombre": "Backend"}).status_code == 401
    col = c.post("/api/colecciones", json={"nombre": "Backend", "descripcion": "APIs"}, headers=H)
    assert col.status_code == 201
    cid = col.json()["id"]
    assert c.post("/api/colecciones", json={"nombre": "backend"}, headers=H).status_code == 409

    t = c.post(
        "/api/temas",
        json={"nombre": "FastAPI Depends", "notas": "Inyección de dependencias.", "coleccion_id": cid, "etiquetas": "api,python"},
        headers=H,
    )
    assert t.status_code == 201
    tid = t.json()["id"]

    # Buscar y editar
    assert len(c.get("/api/temas?q=depends").json()) == 1
    assert len(c.get(f"/api/temas?coleccion_id={cid}").json()) == 1
    ed = c.patch(f"/api/temas/{tid}", json={"idea_clave": "Usa Depends() para desacoplar"}, headers=H)
    assert ed.status_code == 200 and ed.json()["idea_clave"] == "Usa Depends() para desacoplar"

    # Posponer
    posp = c.post(f"/api/temas/{tid}/posponer", json={"dias": 2}, headers=H)
    assert posp.status_code == 200

    # Exportar JSON y Markdown
    exp_json = c.get(f"/api/colecciones/{cid}/exportar?formato=json")
    assert exp_json.status_code == 200 and len(exp_json.json()["fichas"]) == 1
    exp_md = c.get(f"/api/colecciones/{cid}/exportar?formato=md")
    assert exp_md.status_code == 200 and "## FastAPI Depends" in exp_md.text

    # Importar Markdown en nueva colección
    imp = c.post(
        "/api/colecciones/importar",
        json={"datos": exp_md.text, "formato": "md", "nombre_coleccion": "Backend Copia"},
        headers=H,
    )
    assert imp.status_code == 201 and len(imp.json()["importados"]) == 1

    # Pausar y borrar colección
    assert c.patch(f"/api/colecciones/{cid}", json={"activa": False}, headers=H).json()["activa"] is False
    assert c.delete(f"/api/colecciones/{cid}", headers=H).status_code == 200
    assert c.get("/api/colecciones").status_code == 200
    b = c.get("/api/brechas")
    assert b.status_code == 200 and "recomendacion" in b.json() and "racha_dias" in b.json()


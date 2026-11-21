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

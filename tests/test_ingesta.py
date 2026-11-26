"""Pruebas de ingesta universal: código propio/IA, Markdown y respaldo determinista local."""

from __future__ import annotations

import importlib
import json
import random
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.agente import AgenteTutor
from app.cerebro import Cerebro
from app.config import Config
from app.ingesta import (
    descomponer_codigo_local,
    descomponer_material_local,
    detectar_lenguaje,
    generar_pregunta_codigo_local,
)


def test_codigo_local_multilenguaje_y_preguntas() -> None:
    py_code = (
        "def validar_edad(edad: int) -> bool:\n"
        "    if edad < 18:\n"
        "        return False\n"
        "    return True\n\n"
        "def saludar(nombre: str) -> str:\n"
        "    return f'Hola {nombre}'\n"
    )
    assert detectar_lenguaje(py_code) == "python"
    fichas = descomponer_codigo_local(py_code, titulo="Validación", max_fichas=5)
    assert len(fichas) == 2
    assert all(f.tipo == "codigo" and f.lenguaje == "python" and f.codigo and f.idea_clave for f in fichas)

    sql_code = "SELECT id, nombre FROM temas WHERE fallos > 2; UPDATE temas SET en_refuerzo = 1 WHERE fallos > 2;"
    assert detectar_lenguaje(sql_code) == "sql"
    assert len(descomponer_codigo_local(sql_code)) == 2

    js_code = "function sumar(a, b) {\n  return a + b;\n}\nconst restar = (a, b) => {\n  return a - b;\n};"
    assert detectar_lenguaje(js_code) == "javascript"

    tema = {"nombre": fichas[0].nombre, "lenguaje": "python", "codigo": fichas[0].codigo, "notas": fichas[0].notas, "idea_clave": fichas[0].idea_clave}
    for modo in ("explica_codigo", "predice_salida", "detecta_bug", "concepto"):
        preg, esp = generar_pregunta_codigo_local(tema, modo, rng=random.Random(1))
        assert preg and esp


def test_material_local_markdown_y_texto_libre() -> None:
    md = (
        "# Patrón Repository\n\nSepara el acceso a datos de la lógica de negocio.\n\n"
        "```python\nclass Repo:\n    def obtener(self, id): pass\n```\n\n"
        "## Ventajas\nFacilita pruebas unitarias y desacopla el ORM."
    )
    fichas = descomponer_material_local(md, titulo="Arquitectura", max_fichas=5)
    assert len(fichas) == 2
    assert fichas[0].tipo == "material" and "class Repo" in fichas[0].codigo
    assert "desacopla" in fichas[1].notas


def test_cerebro_codigo_y_material_con_gemini_y_respaldo() -> None:
    def ok_transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        texto = body["contents"][0]["parts"][0]["text"]
        if "<codigo>" in texto and "descompónlo" in texto:
            payload = {"fichas": [{"nombre": "Parser JWT", "notas": "Valida firma.", "analogia": "Como un sello.", "idea_clave": "Verifica exp y firma"}]}
        elif "<material>" in texto:
            payload = {"fichas": [{"nombre": "CAP Theorem", "notas": "Consistencia vs disponibilidad.", "idea_clave": "Elige 2 bajo partición"}]}
        else:
            payload = {"pregunta": "¿Qué valida el Parser JWT?", "respuesta_esperada": "La firma y expiración"}
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]})

    c_ok = Cerebro("clave", cliente=httpx.Client(transport=httpx.MockTransport(ok_transport)))
    f_cod, src_c = c_ok.descomponer_codigo("def verify(token):\n    return True")
    assert src_c == "gemini" and f_cod[0].nombre == "Parser JWT"
    f_mat, src_m = c_ok.descomponer_material("# CAP\nTeorema de sistemas distribuidos.")
    assert src_m == "gemini" and f_mat[0].nombre == "CAP Theorem"
    p_cod = c_ok.generar_pregunta_codigo({"nombre": "Parser JWT", "lenguaje": "python", "codigo": "return True", "notas": "Valida"}, [], 0)
    assert p_cod.fuente == "gemini"

    c_caido = Cerebro("clave", cliente=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    f_loc, src_loc = c_caido.descomponer_codigo("def f(x):\n    return x * 2")
    assert src_loc == "local" and len(f_loc) == 1
    f_mat_loc, src_mat_loc = c_caido.descomponer_material("# Tema\nContenido suficiente para probar respaldo local.")
    assert src_mat_loc == "local" and len(f_mat_loc) == 1
    assert c_caido.generar_pregunta_codigo({"nombre": "f", "lenguaje": "python", "codigo": "return x", "notas": "doble"}, [], 1).fuente == "local"


def test_api_estudiar_codigo_y_material_y_deduplicacion(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ing.db'}")
    monkeypatch.setenv("TUTOR_AUTONOMO", "0")
    monkeypatch.setenv("TUTOR_TOKEN", "tok-v2")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import app.main as main

    main = importlib.reload(main)
    h = {"X-Tutor-Token": "tok-v2"}
    with TestClient(main.app) as c:
        assert c.post("/api/estudiar/codigo", json={"codigo": "def a(): return 1"}).status_code == 401
        assert c.post("/api/estudiar/codigo", json={"codigo": "x"}, headers=h).status_code == 422
        r1 = c.post(
            "/api/estudiar/codigo",
            json={"codigo": "def calcular_iva(valor: float) -> float:\n    return round(valor * 0.19, 2)", "titulo": "IVA"},
            headers=h,
        )
        assert r1.status_code == 201 and len(r1.json()["creadas"]) == 1
        # Reenvío del mismo código omite duplicado sin fallar
        r2 = c.post(
            "/api/estudiar/codigo",
            json={"codigo": "def calcular_iva(valor: float) -> float:\n    return round(valor * 0.19, 2)", "titulo": "IVA"},
            headers=h,
        )
        assert r2.status_code == 201 and r2.json()["omitidas"] == 1

        r_mat = c.post(
            "/api/estudiar/material",
            json={"contenido": "## Indice B-Tree\nAcelera búsquedas por rango.\n## Hash Index\nSolo igualdad exacta.", "coleccion": "Postgres"},
            headers=h,
        )
        assert r_mat.status_code == 201 and len(r_mat.json()["creadas"]) == 2
        ciclo = c.post("/api/ciclo", headers=h)
        assert len(ciclo.json()["preguntas_creadas"]) == 3
        pend = c.get("/api/preguntas/pendientes").json()
        assert all(p["requiere_lectura"] is True and p["lectura"] is not None for p in pend)

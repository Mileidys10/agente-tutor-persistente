"""Pruebas v3.0: estudiar_diff, pistas socráticas, simulacros, grafo de prerrequisitos, plan 7d, Anki y webhooks."""

from __future__ import annotations

import importlib
import json
import random
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.agente import AgenteTutor
from app.cerebro import Cerebro
from app.config import Config
from app.ingesta import generar_pista_progresiva, parsear_git_diff_local
from app.memoria import Memoria, ahora


def _agente_v3(tmp_path: Path, **kw) -> AgenteTutor:
    cfg = Config(
        database_url=f"sqlite:///{tmp_path / 'v3.db'}",
        gemini_api_key="",
        gemini_modelo="x",
        intervalo_ciclo_s=0.05,
        minutos_por_dia=1,
        max_pendientes=5,
        nuevas_por_dia=5,
        token="",
        autonomo=False,
        meta_diaria=int(kw.pop("meta_diaria", 10)),
        webhook_url=str(kw.pop("webhook_url", "")),
    )
    return AgenteTutor(cfg, **kw)


def test_git_diff_local_y_pistas_progresivas() -> None:
    diff = (
        "diff --git a/app/auth.py b/app/auth.py\n"
        "index 111..222 100644\n"
        "--- a/app/auth.py\n"
        "+++ b/app/auth.py\n"
        "@@ -1,3 +1,5 @@\n"
        "+def verificar_token(t: str) -> bool:\n"
        "+    return bool(t and len(t) >= 8)\n"
        "diff --git a/queries.sql b/queries.sql\n"
        "--- a/queries.sql\n"
        "+++ b/queries.sql\n"
        "@@ -1 +1,2 @@\n"
        "+SELECT id FROM usuarios WHERE activo = 1;\n"
    )
    fichas = parsear_git_diff_local(diff, titulo="PR #12")
    assert len(fichas) == 2
    assert fichas[0].lenguaje == "python" and "diff" in fichas[0].etiquetas
    assert fichas[1].lenguaje == "sql"

    preg = {
        "tema": "Auth",
        "tipo": "codigo",
        "lenguaje": "python",
        "respuesta_esperada": "Verifica longitud minima",
        "explicacion": "Exige al menos 8 caracteres",
        "analogia": "Como un portero que revisa el pase",
    }
    p1 = generar_pista_progresiva(preg, 1)
    p2 = generar_pista_progresiva(preg, 2)
    p3 = generar_pista_progresiva(preg, 3)
    assert "Pista 1/3" in p1 and "Verifica longitud minima" not in p1
    assert "Pista 2/3" in p2 and "8 caracteres" in p2
    assert "Pista 3/3" in p3 and "V******" in p3 and "longitud minima" not in p3


def test_pistas_aplican_tope_sm2_en_responder(tmp_path: Path) -> None:
    a = _agente_v3(tmp_path)
    t = a.agregar_tema("JWT", "Token firmado con clave secreta para autenticar peticiones.")
    a.ciclo()
    preg = a.memoria.pendientes()[0]
    r1 = a.pedir_pista(preg["id"])
    assert r1["nivel"] == 1 and r1["pistas_restantes"] == 2
    r2 = a.pedir_pista(preg["id"])
    assert r2["nivel"] == 2 and r2["pistas_restantes"] == 1
    res = a.responder(preg["id"], preg["respuesta_esperada"])
    assert res["pistas_usadas"] == 2 and res["nota"] <= 3


def test_simulacro_persistente_y_anki_tsv(tmp_path: Path) -> None:
    a = _agente_v3(tmp_path)
    col = a.crear_coleccion("Backend", "Python y SQL")
    a.agregar_tema("FastAPI", "Framework ASGI rápido con Pydantic.", coleccion_id=col["id"], idea_clave="Usa validación de tipos")
    a.agregar_tema("SQLAlchemy", "ORM y Core para bases relacionales.", coleccion_id=col["id"], idea_clave="Usa sesiones seguras")

    sim = a.iniciar_simulacro(titulo="Parcial 1", cantidad=2, coleccion_id=col["id"])
    assert sim["sesion"]["total_preguntas"] == 2
    assert all("respuesta_esperada" not in p for p in sim["preguntas"])

    for p in sim["preguntas"]:
        real = a.memoria.obtener_pregunta(p["id"])["respuesta_esperada"]
        a.responder(p["id"], real)

    final = a.obtener_simulacro(sim["sesion"]["id"])
    assert final["estado"] == "completada" and final["respondidas"] == 2 and final["porcentaje_aciertos"] == 100.0
    assert a.ver_simulacros()[0]["id"] == sim["sesion"]["id"]

    tsv = a.exportar_coleccion(col["id"], formato="anki")
    assert isinstance(tsv, str) and "\t" in tsv and "FastAPI" in tsv


def test_grafo_prerrequisitos_ciclo_boost_y_plan_7_dias(tmp_path: Path) -> None:
    a = _agente_v3(tmp_path, meta_diaria=5)
    t_base = a.agregar_tema("Funciones puras", "No mutan estado externo y siempre devuelven lo mismo.")
    t_avanzado = a.agregar_tema("Decoradores", "Reciben una función y devuelven otra función.")

    rel = a.vincular_temas(t_base["id"], t_avanzado["id"], tipo="prerrequisito")
    assert rel["tipo"] == "prerrequisito"
    with pytest.raises(ValueError, match="Ciclo"):
        a.vincular_temas(t_avanzado["id"], t_base["id"], tipo="prerrequisito")
    with pytest.raises(ValueError):
        a.vincular_temas(t_base["id"], t_base["id"], tipo="prerrequisito")

    # Hacer que t_avanzado parezca más difícil por fallos, pero t_base es prerrequisito vencido no dominado
    a.memoria.actualizar_repaso(t_avanzado["id"], 0, 1.0, 1.8, ahora() - timedelta(minutes=2), acierto=False, nota=2)
    a.memoria.actualizar_repaso(t_base["id"], 0, 0.0, 2.5, ahora() - timedelta(minutes=1), acierto=True, nota=3)
    a_single = AgenteTutor(a.config, memoria=a.memoria, cerebro=a.cerebro)
    a_single.config = Config(**{**a.config.__dict__, "max_pendientes": 1})
    res = a_single.ciclo()
    assert res["preguntas_creadas"][0]["tema_id"] == t_base["id"]
    assert "Prerrequisito" in res["preguntas_creadas"][0]["motivo"]

    plan = a.plan_estudio_hoy()
    assert plan["meta_diaria"] == 5 and len(plan["pronostico_7_dias"]) == 7


def test_webhook_proactivo_una_vez_al_dia(tmp_path: Path) -> None:
    envios: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        envios.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    cerebro = Cerebro("", rng=random.Random(1), cliente=httpx.Client(transport=httpx.MockTransport(handler)))
    a = _agente_v3(tmp_path, webhook_url="https://hooks.ejemplo.local/tutor", cerebro=cerebro)
    a.despertar()
    a.agregar_tema("Docker", "Empaqueta código y dependencias en contenedores.")
    a.ciclo()
    a.ciclo()  # segundo ciclo el mismo día NO debe reenviar webhook
    assert len(envios) == 1 and envios[0]["evento"] == "recordatorio_diario"


def test_migracion_v1_a_v3_y_rutas_rest_v3(tmp_path: Path, monkeypatch) -> None:
    url = f"sqlite:///{tmp_path / 'v1tov3.db'}"
    motor = sa.create_engine(url)
    with motor.begin() as c:
        c.execute(sa.text("CREATE TABLE temas (id INTEGER PRIMARY KEY, nombre VARCHAR(200) NOT NULL, notas TEXT NOT NULL, origen VARCHAR(20) NOT NULL, categoria VARCHAR(120) NOT NULL, ref_externa VARCHAR(60) UNIQUE, repeticiones INTEGER NOT NULL, intervalo_dias FLOAT NOT NULL, facilidad FLOAT NOT NULL, proximo_repaso DATETIME NOT NULL, aciertos INTEGER NOT NULL, fallos INTEGER NOT NULL, creado DATETIME NOT NULL)"))
        c.execute(sa.text("CREATE TABLE preguntas (id INTEGER PRIMARY KEY, tema_id INTEGER NOT NULL, texto TEXT NOT NULL, respuesta_esperada TEXT NOT NULL, motivo TEXT NOT NULL, estado VARCHAR(20) NOT NULL, fuente VARCHAR(20) NOT NULL, opciones TEXT, explicacion TEXT NOT NULL, creada DATETIME NOT NULL, respondida_en DATETIME)"))
        c.execute(sa.text("CREATE TABLE latido (id INTEGER PRIMARY KEY, primer_arranque DATETIME NOT NULL, ultimo_arranque DATETIME NOT NULL, ultimo_ciclo DATETIME, ciclos INTEGER NOT NULL, arranques INTEGER NOT NULL)"))
    motor.dispose()

    m = Memoria(url)
    assert {"pistas_usadas", "sesion_examen_id"} <= {c["name"] for c in sa.inspect(m.engine).get_columns("preguntas")}
    assert "ultima_notificacion" in {c["name"] for c in sa.inspect(m.engine).get_columns("latido")}
    assert {"relaciones_temas", "sesiones_examen"} <= set(sa.inspect(m.engine).get_table_names())

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api3.db'}")
    monkeypatch.setenv("TUTOR_AUTONOMO", "0")
    monkeypatch.setenv("TUTOR_TOKEN", "tok3")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import app.main as main

    main = importlib.reload(main)
    h = {"X-Tutor-Token": "tok3"}
    with TestClient(main.app) as c:
        r_diff = c.post(
            "/api/estudiar/diff",
            json={"diff_texto": "diff --git a/a.py b/a.py\n+++ b/a.py\n+def hola():\n+    return 1"},
            headers=h,
        )
        assert r_diff.status_code == 201 and len(r_diff.json()["creadas"]) == 1
        col_id = r_diff.json()["coleccion"]["id"]
        assert c.get(f"/api/colecciones/{col_id}/exportar?formato=anki").status_code == 200
        assert c.get("/api/plan").status_code == 200
        r_ex = c.post("/api/examenes", json={"titulo": "Test", "cantidad": 1}, headers=h)
        assert r_ex.status_code == 201
        pid = r_ex.json()["preguntas"][0]["id"]
        assert c.post(f"/api/preguntas/{pid}/pista", headers=h).json()["nivel"] == 1
        assert c.get("/api/examenes").status_code == 200

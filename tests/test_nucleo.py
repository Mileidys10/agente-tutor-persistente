"""Pruebas del núcleo: SM-2, memoria persistente, ciclo autónomo, DevCards y corrección."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from app import sm2
from app.agente import AgenteTutor
from app.banco_devcards import BancoDevCards
from app.cerebro import Cerebro
from app.config import Config, _url_base_datos
from app.memoria import Memoria, ahora


def _config(tmp_path: Path, **kw) -> Config:
    base = Config(
        database_url=f"sqlite:///{tmp_path / 'tutor.db'}", gemini_api_key="", gemini_modelo="x",
        intervalo_ciclo_s=0.05, minutos_por_dia=1440, max_pendientes=3, nuevas_por_dia=2, token="", autonomo=False,
    )
    return replace(base, **kw)


def _agente(tmp_path: Path, **kw) -> AgenteTutor:
    cfg = _config(tmp_path, **kw)
    return AgenteTutor(cfg, cerebro=Cerebro("", rng=random.Random(1)))


NOTAS = "La fotosíntesis transforma la energía lumínica en energía química. Ocurre en los cloroplastos de las plantas."


# ---- SM-2 ----------------------------------------------------------------------
def test_sm2_progresion_y_fallo() -> None:
    e = sm2.EstadoSM2()
    e = sm2.actualizar(e, 5)
    assert (e.repeticiones, e.intervalo_dias) == (1, 1.0)
    e = sm2.actualizar(e, 5)
    assert (e.repeticiones, e.intervalo_dias) == (2, 6.0)
    e = sm2.actualizar(e, 4)
    assert e.repeticiones == 3 and e.intervalo_dias == pytest.approx(6.0 * e.facilidad, rel=1e-3)
    f = sm2.actualizar(e, 1)
    assert (f.repeticiones, f.intervalo_dias) == (0, 1.0) and f.facilidad < e.facilidad
    assert sm2.actualizar(sm2.EstadoSM2(facilidad=1.3), 0).facilidad == sm2.FACILIDAD_MINIMA
    with pytest.raises(ValueError):
        sm2.actualizar(e, 6)


def test_url_de_render_se_convierte_a_psycopg() -> None:
    assert _url_base_datos("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert _url_base_datos("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert _url_base_datos("sqlite:///x.db") == "sqlite:///x.db"


# ---- persistencia: lo esencial de un agente persistente ------------------------
def test_la_memoria_sobrevive_a_un_reinicio(tmp_path: Path) -> None:
    a1 = _agente(tmp_path)
    a1.despertar()
    a1.agregar_tema("Fotosíntesis", NOTAS)
    a1.ciclo()
    pendiente = a1.memoria.pendientes()[0]
    del a1  # el proceso "muere"

    a2 = _agente(tmp_path)  # nuevo proceso, misma base de datos
    lat = a2.despertar()
    assert lat["arranques"] == 2 and lat["ciclos"] == 1
    assert [p["id"] for p in a2.memoria.pendientes()] == [pendiente["id"]]
    assert "Desperté por 2.ª vez" in a2.memoria.leer_bitacora(1)[0]["detalle"]
    r = a2.responder(pendiente["id"], pendiente["respuesta_esperada"])
    assert r["nota"] == 5


def test_el_hilo_autonomo_trabaja_solo(tmp_path: Path) -> None:
    a = _agente(tmp_path)
    a.agregar_tema("Fotosíntesis", NOTAS)
    a.iniciar()
    try:
        for _ in range(100):
            if a.memoria.pendientes():
                break
            import time
            time.sleep(0.05)
        assert a.vivo and a.memoria.pendientes(), "el agente debió preparar la pregunta sin intervención"
    finally:
        a.detener()
    assert not a.vivo


# ---- ciclo: decidir qué repasar ----------------------------------------------
def test_ciclo_respeta_el_cupo_y_no_duplica(tmp_path: Path) -> None:
    a = _agente(tmp_path, max_pendientes=2)
    for i in range(4):
        a.agregar_tema(f"Tema {i}", NOTAS)
    assert len(a.ciclo()["preguntas_creadas"]) == 2
    assert a.ciclo()["preguntas_creadas"] == []  # cupo lleno
    temas_con_pregunta = [p["tema_id"] for p in a.memoria.pendientes()]
    assert len(temas_con_pregunta) == len(set(temas_con_pregunta)) == 2


def test_prioriza_el_tema_mas_atrasado_y_dificil(tmp_path: Path) -> None:
    a = _agente(tmp_path, max_pendientes=1)
    facil = a.agregar_tema("Fácil", NOTAS)
    dificil = a.agregar_tema("Difícil", NOTAS)
    t = ahora()
    a.memoria.actualizar_repaso(facil["id"], 3, 10, 2.8, t - timedelta(hours=1), acierto=True)
    a.memoria.actualizar_repaso(dificil["id"], 0, 1, 1.4, t - timedelta(days=2), acierto=False)
    creada = a.ciclo()["preguntas_creadas"][0]
    assert creada["tema_id"] == dificil["id"]
    assert "Repaso de «Difícil»" in creada["motivo"] and "prioridad" in creada["motivo"]


def test_no_pregunta_temas_que_aun_no_vencen(tmp_path: Path) -> None:
    a = _agente(tmp_path)
    tema = a.agregar_tema("Fotosíntesis", NOTAS)
    a.memoria.actualizar_repaso(tema["id"], 1, 1, 2.5, ahora() + timedelta(days=1), acierto=True)
    assert a.ciclo()["preguntas_creadas"] == []


def test_responder_programa_el_proximo_repaso_con_la_escala(tmp_path: Path) -> None:
    a = _agente(tmp_path, minutos_por_dia=1)  # modo demo: 1 "día" = 1 minuto
    a.agregar_tema("Fotosíntesis", NOTAS)
    p = a.ciclo()["preguntas_creadas"][0]
    antes = ahora()
    r = a.responder(p["id"], p["respuesta_esperada"])
    assert r["correcta"] and r["intervalo_dias"] == 1.0
    assert timedelta(seconds=50) < r["proximo_repaso"] - antes < timedelta(seconds=70)
    with pytest.raises(ValueError):
        a.responder(p["id"], "otra vez")
    with pytest.raises(LookupError):
        a.responder(9999, "x")


def test_fallar_hace_que_el_tema_vuelva_y_baje_la_facilidad(tmp_path: Path) -> None:
    a = _agente(tmp_path)
    tema = a.agregar_tema("Fotosíntesis", NOTAS)
    p = a.ciclo()["preguntas_creadas"][0]
    r = a.responder(p["id"], "no me acuerdo")
    assert not r["correcta"]
    t = a.memoria.obtener_tema(tema["id"])
    assert t["fallos"] == 1 and t["facilidad"] < 2.5 and t["repeticiones"] == 0
    assert a.memoria.fallos_recientes(tema["id"]) == [p["texto"]]


# ---- DevCards ------------------------------------------------------------------
def test_banco_devcards_completo() -> None:
    banco = BancoDevCards()
    assert len(banco) == 1295
    cats = {c["categoria"]: c["tarjetas"] for c in banco.categorias()}
    assert cats["Angular"] == 16 and sum(cats.values()) == 1295


def test_devcards_nuevas_respetan_el_limite_diario_y_alternan_mazos(tmp_path: Path) -> None:
    a = _agente(tmp_path, max_pendientes=10, nuevas_por_dia=2)
    a.activar_mazo("Angular", True)
    a.activar_mazo("Bases de Datos y SQL", True)
    for _ in range(5):
        a.ciclo()
    pend = a.memoria.pendientes()
    assert len(pend) == 2  # límite de 2 nuevas por "día"
    assert {p["tema"] for p in pend} and {a.memoria.obtener_tema(p["tema_id"])["categoria"] for p in pend} == {
        "Angular", "Bases de Datos y SQL"}
    assert all(p["fuente"] == "devcards" and p["opciones"] for p in pend)
    assert "Límite de 2 DevCards" in a.memoria.leer_bitacora(1)[0]["detalle"]
    mazos = {m["categoria"]: m for m in a.mazos()}
    assert mazos["Angular"]["activo"] and mazos["Angular"]["introducidas"] == 1
    with pytest.raises(LookupError):
        a.activar_mazo("No existe", True)


@pytest.mark.parametrize("forma", ["letra", "numero", "texto"])
def test_opcion_multiple_acepta_letra_numero_o_texto(tmp_path: Path, forma: str) -> None:
    a = _agente(tmp_path, nuevas_por_dia=1)
    a.activar_mazo("POO", True)
    p = a.ciclo()["preguntas_creadas"][0]
    a.marcar_leida(p["id"])  # DevCard nueva: se lee antes del quiz
    i = p["opciones"].index(p["respuesta_esperada"])
    resp = {"letra": "ABCD"[i], "numero": str(i + 1), "texto": p["respuesta_esperada"].upper()}[forma]
    r = a.responder(p["id"], resp)
    assert r["nota"] == 5 and "Idea clave" in r["retroalimentacion"]


def test_opcion_multiple_incorrecta(tmp_path: Path) -> None:
    a = _agente(tmp_path, nuevas_por_dia=1)
    a.activar_mazo("POO", True)
    p = a.ciclo()["preguntas_creadas"][0]
    a.marcar_leida(p["id"])  # DevCard nueva: se lee antes del quiz
    i = p["opciones"].index(p["respuesta_esperada"])
    r = a.responder(p["id"], "ABCD"[(i + 1) % len(p["opciones"])])
    assert r["nota"] == 1 and "Incorrecto" in r["retroalimentacion"]


def test_devcard_alterna_quiz_y_pregunta_abierta() -> None:
    t = BancoDevCards().por_id["poo-01"]
    assert BancoDevCards.pregunta_de(t, 0)["opciones"]
    assert BancoDevCards.pregunta_de(t, 1)["opciones"] is None


# ---- cerebro local (sin Gemini) ------------------------------------------------
def test_cerebro_local_crea_huecos_y_corrige() -> None:
    c = Cerebro("", rng=random.Random(3))
    p = c.generar_pregunta("Fotosíntesis", NOTAS, [])
    assert p.fuente == "local" and "_____" in p.texto
    assert c.evaluar(p.texto, p.respuesta_esperada, p.respuesta_esperada).nota == 5
    assert c.evaluar(p.texto, p.respuesta_esperada, "").nota == 0
    assert c.generar_pregunta("Vacío", "", []).texto.startswith("Explica")


def test_cerebro_usa_gemini_y_cae_al_local_si_falla() -> None:
    import httpx

    def manejador(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "clave" and "key=" not in str(request.url)
        texto = '{"pregunta": "¿Dónde ocurre la fotosíntesis?", "respuesta_esperada": "En los cloroplastos"}'
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": texto}]}}]})

    c = Cerebro("clave", cliente=httpx.Client(transport=httpx.MockTransport(manejador)))
    assert c.generar_pregunta("Fotosíntesis", NOTAS, []).fuente == "gemini"

    caido = Cerebro("clave", cliente=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    assert caido.generar_pregunta("Fotosíntesis", NOTAS, []).fuente == "local"
    assert caido.evaluar("p", "cloroplastos", "cloroplastos").fuente == "local"


def test_borrar_tema_borra_sus_preguntas_y_respuestas(tmp_path: Path) -> None:
    a = _agente(tmp_path)
    tema = a.agregar_tema("Fotosíntesis", NOTAS)
    p = a.ciclo()["preguntas_creadas"][0]
    a.responder(p["id"], "algo")
    assert a.memoria.borrar_tema(tema["id"])
    assert a.memoria.historial() == [] and a.memoria.pendientes() == []


def test_tema_duplicado_rechazado(tmp_path: Path) -> None:
    m = Memoria(f"sqlite:///{tmp_path / 'm.db'}")
    m.crear_tema("SQL", "x")
    with pytest.raises(ValueError):
        m.crear_tema("sql", "y")
    m.crear_tema("SQL", "z", origen="devcards", ref_externa="sql-1")  # una DevCard puede llamarse igual


# ---- modo "leer antes de responder" (v1.1) --------------------------------------
def test_devcard_nueva_exige_lectura_y_el_repaso_no(tmp_path: Path) -> None:
    a = _agente(tmp_path, nuevas_por_dia=1, minutos_por_dia=1)
    a.activar_mazo("POO", True)
    p = a.ciclo()["preguntas_creadas"][0]
    assert p["requiere_lectura"] is True
    lectura = a.lectura_de(a.memoria.obtener_pregunta(p["id"]))
    assert lectura and lectura["definicion"] and lectura["idea_clave"] and "titulo" in lectura
    with pytest.raises(ValueError, match="Primero lee"):
        a.responder(p["id"], "A")
    primera = a.marcar_leida(p["id"])
    assert a.marcar_leida(p["id"])["leida_en"] == primera["leida_en"]  # idempotente
    assert a.lectura_de(a.memoria.obtener_pregunta(p["id"])) is None
    assert sum("Leíste la DevCard" in b["detalle"] for b in a.memoria.leer_bitacora()) == 1
    a.responder(p["id"], p["respuesta_esperada"])
    with pytest.raises(ValueError):
        a.marcar_leida(p["id"])  # ya respondida
    with pytest.raises(LookupError):
        a.marcar_leida(9999)
    tema = a.memoria.obtener_tema(p["tema_id"])  # forzar que el repaso venza ya
    a.memoria.actualizar_repaso(tema["id"], 1, 1, 2.5, ahora() - timedelta(seconds=1), acierto=True)
    repaso = a.ciclo()["preguntas_creadas"][0]
    assert repaso["tema_id"] == p["tema_id"] and repaso["requiere_lectura"] is False


def test_modo_lectura_desactivable_y_temas_propios_no_lo_usan(tmp_path: Path) -> None:
    a = _agente(tmp_path, nuevas_por_dia=1, leer_antes=False)
    a.activar_mazo("POO", True)
    assert a.ciclo()["preguntas_creadas"][0]["requiere_lectura"] is False
    (tmp_path / "otro").mkdir()
    b = _agente(tmp_path / "otro", nuevas_por_dia=0)
    b.agregar_tema("Fotosíntesis", NOTAS)
    assert b.ciclo()["preguntas_creadas"][0]["requiere_lectura"] is False


def test_migracion_agrega_columnas_a_una_base_v1_sin_perder_datos(tmp_path: Path) -> None:
    import sqlalchemy as sa

    url = f"sqlite:///{tmp_path / 'v1.db'}"
    motor = sa.create_engine(url)
    with motor.begin() as c:  # esquema exacto de la v1.0 (sin requiere_lectura ni leida_en)
        c.execute(sa.text("CREATE TABLE temas (id INTEGER PRIMARY KEY, nombre VARCHAR(200) NOT NULL, notas TEXT NOT NULL, "
                          "origen VARCHAR(20) NOT NULL, categoria VARCHAR(120) NOT NULL, ref_externa VARCHAR(60) UNIQUE, "
                          "repeticiones INTEGER NOT NULL, intervalo_dias FLOAT NOT NULL, facilidad FLOAT NOT NULL, "
                          "proximo_repaso DATETIME NOT NULL, aciertos INTEGER NOT NULL, fallos INTEGER NOT NULL, creado DATETIME NOT NULL)"))
        c.execute(sa.text("CREATE TABLE preguntas (id INTEGER PRIMARY KEY, tema_id INTEGER NOT NULL, texto TEXT NOT NULL, "
                          "respuesta_esperada TEXT NOT NULL, motivo TEXT NOT NULL, estado VARCHAR(20) NOT NULL, "
                          "fuente VARCHAR(20) NOT NULL, opciones TEXT, explicacion TEXT NOT NULL, creada DATETIME NOT NULL, respondida_en DATETIME)"))
        c.execute(sa.text("INSERT INTO temas VALUES (1,'Viejo','notas','usuario','',NULL,0,0,2.5,'2026-01-01 00:00:00',0,0,'2026-01-01 00:00:00')"))
        c.execute(sa.text("INSERT INTO preguntas VALUES (1,1,'¿Pregunta vieja?','resp','m','pendiente','local',NULL,'','2026-01-01 00:00:00',NULL)"))
    motor.dispose()
    m = Memoria(url)  # al abrirla, migra
    columnas = {c["name"] for c in sa.inspect(m.engine).get_columns("preguntas")}
    assert {"requiere_lectura", "leida_en"} <= columnas
    vieja = m.pendientes()[0]
    assert vieja["texto"] == "¿Pregunta vieja?" and vieja["requiere_lectura"] is False
    Memoria(url)  # una segunda apertura no vuelve a migrar ni falla

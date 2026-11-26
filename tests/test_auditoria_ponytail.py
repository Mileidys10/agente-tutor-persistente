"""Pruebas de auditoría Ponytail: ciclos transitivos, webhooks fríos, pistas, simulacros, Anki, rachas, seguridad y UI."""

from __future__ import annotations

import asyncio
import importlib
import json
import random
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agente import AgenteTutor
from app.cerebro import Cerebro
from app.config import Config
from app.ingesta import (
    descomponer_codigo_local,
    descomponer_material_local,
    generar_pista_progresiva,
    parsear_git_diff_local,
)
from app.mcp_tools import crear_servidor_mcp
from app.memoria import ahora


def _ag(tmp_path: Path, **kw) -> AgenteTutor:
    cfg = Config(
        database_url=f"sqlite:///{tmp_path / 'pony.db'}",
        gemini_api_key="",
        gemini_modelo="x",
        intervalo_ciclo_s=0.05,
        minutos_por_dia=1,
        max_pendientes=int(kw.pop("max_pendientes", 5)),
        nuevas_por_dia=int(kw.pop("nuevas_por_dia", 5)),
        token="",
        autonomo=False,
        meta_diaria=int(kw.pop("meta_diaria", 10)),
        webhook_url=str(kw.pop("webhook_url", "")),
    )
    return AgenteTutor(cfg, **kw)


# ---- 1. Grafo transitivo de prerrequisitos y limpieza en cascada -----------
def test_grafo_transitivo_rechaza_ciclos_e_idempotencia(tmp_path: Path) -> None:
    a = _ag(tmp_path)
    t1 = a.agregar_tema("Variables", "Almacenan referencias a valores.")
    t2 = a.agregar_tema("Funciones", "Bloques reutilizables con def.")
    t3 = a.agregar_tema("Decoradores", "Reciben una función y devuelven otra.")

    r1 = a.vincular_temas(t1["id"], t2["id"], tipo="prerrequisito")
    r1_dup = a.vincular_temas(t1["id"], t2["id"], tipo="prerrequisito")
    assert r1["id"] == r1_dup["id"]  # idempotente
    a.vincular_temas(t2["id"], t3["id"], tipo="prerrequisito")

    # Ciclo transitivo: t3 -> t1 debe fallar
    with pytest.raises(ValueError, match="Ciclo"):
        a.vincular_temas(t3["id"], t1["id"], tipo="prerrequisito")
    with pytest.raises(ValueError):
        a.vincular_temas(t1["id"], t2["id"], tipo="invalido")
    with pytest.raises(LookupError):
        a.vincular_temas(t1["id"], 99999, tipo="prerrequisito")

    assert len(a.listar_relaciones(t2["id"])) == 2
    assert a.borrar_tema(t2["id"]) is True
    assert a.listar_relaciones() == []


# ---- 2. Webhooks proactivos en arranque frío, fallos de red y filtros -------
def test_webhook_arranque_frio_sin_despertar_y_tolerancia_a_fallos(tmp_path: Path) -> None:
    envios: list[dict] = []

    def ok_handler(request: httpx.Request) -> httpx.Response:
        envios.append(json.loads(request.content))
        return httpx.Response(200)

    c_ok = Cerebro("", rng=random.Random(1), cliente=httpx.Client(transport=httpx.MockTransport(ok_handler)))
    a = _ag(tmp_path, webhook_url="https://hooks.local/ok", cerebro=c_ok)
    # NO llamamos a despertar() (arranque frío tipo stdio)
    a.agregar_tema("HTTP", "Protocolo de transferencia de hipertexto.")
    a.ciclo()
    a.ciclo()
    assert len(envios) == 1
    assert a.memoria.leer_latido()["ultima_notificacion"] != ""

    # URL inválida o sin pendientes no envía
    (tmp_path / "b").mkdir()
    b = _ag(tmp_path / "b", webhook_url="ftp://invalido.local/x", nuevas_por_dia=0)
    b.agregar_tema("TCP", "Protocolo orientado a conexión.")
    assert b.ciclo()["preguntas_creadas"]
    assert b.memoria.leer_latido()["ultima_notificacion"] == ""

    # Error 500 en webhook NO rompe el ciclo
    (tmp_path / "c").mkdir()
    c_fail = Cerebro("", cliente=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    c_ag = _ag(tmp_path / "c", webhook_url="https://hooks.local/fail", cerebro=c_fail, nuevas_por_dia=0)
    c_ag.agregar_tema("UDP", "Protocolo sin conexión.")
    assert len(c_ag.ciclo()["preguntas_creadas"]) == 1


# ---- 3. Pistas progresivas y límites SM-2 ----------------------------------
def test_pistas_bloqueadas_por_lectura_tope_nivel_3_y_opcion_multiple(tmp_path: Path) -> None:
    a = _ag(tmp_path, nuevas_por_dia=1)
    a.activar_mazo("POO", True)
    p_dev = a.ciclo()["preguntas_creadas"][0]
    assert p_dev["requiere_lectura"] is True
    with pytest.raises(ValueError, match="Primero lee"):
        a.pedir_pista(p_dev["id"])
    a.marcar_leida(p_dev["id"])

    # Nivel 3 para opción múltiple en diferentes índices nunca filtra respuesta literal
    opciones = ["Alfa", "Beta", "Gamma", "Delta", "Epsilon"]
    for idx, esp in enumerate(opciones):
        txt = generar_pista_progresiva({"opciones": opciones, "respuesta_esperada": esp}, 3)
        assert "Pista 3/3" in txt and esp not in txt

    # 4ta pista consecutiva mantiene nivel 3 y pistas_restantes == 0
    for esperado_nivel in (1, 2, 3, 3):
        res_p = a.pedir_pista(p_dev["id"])
        assert res_p["nivel"] == esperado_nivel
    assert res_p["pistas_restantes"] == 0

    a.responder(p_dev["id"], p_dev["respuesta_esperada"])
    with pytest.raises(ValueError):
        a.pedir_pista(p_dev["id"])
    with pytest.raises(LookupError):
        a.pedir_pista(99999)

    # Verificar tope 4 con exactamente 1 pista
    t_uno = a.agregar_tema("TLS", "Cifra el tráfico en tránsito con certificados.")
    a.ciclo()
    p_uno = next(x for x in a.memoria.pendientes() if x["tema_id"] == t_uno["id"])
    a.pedir_pista(p_uno["id"])
    r_uno = a.responder(p_uno["id"], p_uno["respuesta_esperada"])
    assert r_uno["pistas_usadas"] == 1 and r_uno["nota"] == 4


# ---- 4. Simulacros: filtros, fallados, duración y errores ------------------
def test_simulacro_filtros_devcards_brechas_y_errores(tmp_path: Path) -> None:
    a = _ag(tmp_path, nuevas_por_dia=0)
    with pytest.raises(ValueError, match="No hay temas"):
        a.iniciar_simulacro(cantidad=3)
    with pytest.raises(LookupError):
        a.iniciar_simulacro(coleccion_id=999)
    with pytest.raises(LookupError):
        a.iniciar_simulacro(categoria_devcards="Inexistente")
    with pytest.raises(LookupError):
        a.obtener_simulacro(999)

    # Filtro por categoría DevCards introduce tarjetas automáticamente sin activar mazo
    sim_dev = a.iniciar_simulacro(titulo="Quiz POO", cantidad=2, categoria_devcards="POO")
    assert len(sim_dev["preguntas"]) == 2
    # Responder 1 mal y 1 bien
    p_mal, p_bien = sim_dev["preguntas"]
    a.responder(p_mal["id"], "respuesta totalmente equivocada xyz")
    a.responder(p_bien["id"], a.memoria.obtener_pregunta(p_bien["id"])["respuesta_esperada"])
    fin = a.obtener_simulacro(sim_dev["sesion"]["id"])
    assert fin["estado"] == "completada" and fin["porcentaje_aciertos"] == 50.0
    assert fin["duracion_s"] is not None and fin["duracion_s"] >= 0
    assert p_mal["tema"] in fin["resumen"]["fallados"]

    # Filtro solo_brechas=True toma el tema que acaba de fallar
    sim_brecha = a.iniciar_simulacro(titulo="Repaso brechas", cantidad=2, solo_brechas=True)
    assert any(p["tema"] == p_mal["tema"] for p in sim_brecha["preguntas"])


# ---- 5. Exportación Anki TSV y validación de importación --------------------
def test_anki_tsv_escapa_html_y_importacion_valida_limites(tmp_path: Path) -> None:
    a = _ag(tmp_path)
    col = a.crear_coleccion("C++ & Web", "Templates y HTML")
    a.agregar_tema(
        "Vector\tSTL",
        "Lista dinámica\ncon redimensionado",
        coleccion_id=col["id"],
        tipo="codigo",
        codigo="std::vector<int> v;\nif (a < b && b > 0) {}",
        lenguaje="cpp",
        idea_clave="Crece exponencialmente",
    )
    tsv = a.exportar_coleccion(col["id"], formato="anki")
    assert isinstance(tsv, str)
    assert "&lt;int&gt;" in tsv and "<br>" in tsv
    assert tsv.count("\t") == 2  # exactamente 3 columnas TSV en 1 fila

    # Round-trip JSON
    exp_json = a.exportar_coleccion(col["id"], formato="json")
    imp = a.importar_coleccion(exp_json, formato="json", nombre_coleccion="Copia C++")
    assert len(imp["importados"]) == 1 and imp["importados"][0]["idea_clave"] == "Crece exponencialmente"

    # Errores de importación/exportación
    with pytest.raises(ValueError):
        a.exportar_coleccion(col["id"], formato="xml")
    with pytest.raises(ValueError):
        a.importar_coleccion("{mal json", formato="json")
    with pytest.raises(ValueError):
        a.importar_coleccion("Texto sin encabezados de nivel dos", formato="md")
    with pytest.raises(ValueError):
        a.importar_coleccion("x" * 200_001, formato="md")
    with pytest.raises(ValueError):
        a.importar_coleccion("   ", formato="json")


# ---- 6. Colecciones: borrado selectivo y renombrado -------------------------
def test_colecciones_borrado_selectivo_y_renombrado(tmp_path: Path) -> None:
    a = _ag(tmp_path)
    c1 = a.crear_coleccion("Temporal", "Desc")
    c2 = a.crear_coleccion("Fija", "Desc")
    t1 = a.agregar_tema("Tema Libre", "Notas", coleccion_id=c1["id"])
    t2 = a.agregar_tema("Tema Borrable", "Notas", coleccion_id=c2["id"])

    with pytest.raises(ValueError):
        a.actualizar_coleccion(c1["id"], nombre="fija")
    assert a.borrar_coleccion(c1["id"], borrar_temas=False) is True
    assert a.memoria.obtener_tema(t1["id"])["coleccion_id"] is None

    assert a.borrar_coleccion(c2["id"], borrar_temas=True) is True
    assert a.memoria.obtener_tema(t2["id"]) is None
    assert a.borrar_coleccion(9999) is False


# ---- 7. Rachas diarias consecutivas y huecos -------------------------------
def test_rachas_diarias_consecutivas_y_huecos(tmp_path: Path) -> None:
    a = _ag(tmp_path)
    hoy = ahora()
    ayer = hoy - timedelta(days=1)
    anteayer = hoy - timedelta(days=2)

    a.memoria.registrar_actividad_diaria(True, fecha_dt=anteayer)
    a.memoria.registrar_actividad_diaria(False, fecha_dt=ayer)
    a.memoria.registrar_actividad_diaria(True, fecha_dt=ayer)  # múltiples el mismo día = 1 día
    assert a.memoria.calcular_racha_dias(hoy_dt=hoy) == 2  # sigue viva si estudió ayer

    a.memoria.registrar_actividad_diaria(True, fecha_dt=hoy)
    assert a.memoria.calcular_racha_dias(hoy_dt=hoy) == 3

    # Si pasan 2 días sin estudiar, la racha vuelve a 0
    futuro = hoy + timedelta(days=2)
    assert a.memoria.calcular_racha_dias(hoy_dt=futuro) == 0


# ---- 8. Ingesta avanzada (diff parcial, compactación, viñetas, Gemini diff) -
def test_ingesta_casos_borde_y_gemini_diff() -> None:
    diff_parcial = "--- a/web/app.ts\n+++ b/web/app.ts\n@@ -1 +1,2 @@\n+const ok: boolean = true;\n"
    f_parcial = parsear_git_diff_local(diff_parcial)
    assert len(f_parcial) == 1 and f_parcial[0].lenguaje == "typescript"

    py_grande = "\n\n".join(f"def fn_{i}(x):\n    return x + {i}" for i in range(6))
    f_comp = descomponer_codigo_local(py_grande, max_fichas=3)
    assert len(f_comp) == 3 and "complementario" in f_comp[-1].nombre

    f_vin = descomponer_material_local("- Primer concepto clave\n- Segundo concepto clave", max_fichas=5)
    assert len(f_vin) == 2

    def gemini_ok(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps({
            "fichas": [{"nombre": "Cambio Auth", "notas": "Valida token.", "codigo": "return True", "lenguaje": "python"}]
        })}]}}]})

    c_ok = Cerebro("k", cliente=httpx.Client(transport=httpx.MockTransport(gemini_ok)))
    fichas_g, src_g = c_ok.descomponer_diff(diff_parcial)
    assert src_g == "gemini" and fichas_g[0].nombre == "Cambio Auth"

    c_err = Cerebro("k", cliente=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    fichas_l, src_l = c_err.descomponer_diff(diff_parcial)
    assert src_l == "local" and len(fichas_l) == 1


# ---- 9. Seguridad HTTP (401/422/404) y estáticos sin XSS (innerHTML) --------
def test_seguridad_endpoints_v3_estaticos_y_mcp_resource_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'sec.db'}")
    monkeypatch.setenv("TUTOR_AUTONOMO", "0")
    monkeypatch.setenv("TUTOR_TOKEN", "clave-segura")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import app.main as main

    main = importlib.reload(main)
    h = {"X-Tutor-Token": "clave-segura"}
    with TestClient(main.app) as c:
        # 401 en todas las rutas de escritura sin token
        for metodo, ruta, payload in (
            ("post", "/api/estudiar/diff", {"diff_texto": "+++ b/a.py\n+return 1\n+return 2"}),
            ("post", "/api/preguntas/1/pista", None),
            ("post", "/api/examenes", {"cantidad": 1}),
            ("post", "/api/temas/relaciones", {"origen_id": 1, "destino_id": 2}),
            ("delete", "/api/temas/relaciones/1", None),
            ("patch", "/api/temas/1", {"nombre": "Nuevo"}),
            ("post", "/api/temas/1/posponer", {"dias": 1}),
            ("post", "/api/colecciones/importar", {"datos": "{}", "formato": "json"}),
            ("delete", "/api/colecciones/1", None),
        ):
            r = getattr(c, metodo)(ruta, json=payload) if payload is not None else getattr(c, metodo)(ruta)
            assert r.status_code == 401, f"{metodo.upper()} {ruta} debió exigir token"

        # 422 en literales inválidos y valores fuera de rango
        assert c.post("/api/temas", json={"nombre": "X1", "notas": "a", "tipo": "invalido"}, headers=h).status_code == 422
        assert c.post("/api/temas/relaciones", json={"origen_id": 1, "destino_id": 2, "tipo": "otro"}, headers=h).status_code == 422
        assert c.post("/api/temas/1/posponer", json={"dias": 0}, headers=h).status_code == 422
        assert c.post("/api/temas/1/posponer", json={"dias": 500}, headers=h).status_code == 422
        assert c.get("/api/examenes/9999").status_code == 404

        # Estáticos y cero innerHTML en app.js
        for ruta in ("/", "/privacidad", "/static/app.js", "/static/estilos.css"):
            assert c.get(ruta).status_code == 200
        app_js = (Path(__file__).resolve().parent.parent / "app" / "static" / "app.js").read_text(encoding="utf-8")
        assert ".innerHTML" not in app_js

    # Resource MCP inexistente lanza error controlado
    srv = crear_servidor_mcp(main.agente)
    with pytest.raises(Exception):
        asyncio.run(srv.read_resource("tutor://tema/99999"))

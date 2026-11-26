# Archivo app/config.py: lee todas las variables de entorno del sistema al iniciar el servidor (main.py)
# o el cliente MCP local (mcp_tools.py), para que el código nunca guarde contraseñas ni rutas fijas.
"""Configuración por variables de entorno. Ningún secreto vive en el repositorio."""

from __future__ import annotations

import os
from dataclasses import dataclass


# Convierte la URL de PostgreSQL que entrega Render al formato que necesita SQLAlchemy con psycopg 3.
# La llama Config.desde_entorno() antes de pasar database_url a Memoria en app/memoria.py.
def _url_base_datos(url: str) -> str:
    # Render entrega "postgres://..." o "postgresql://..."; SQLAlchemy necesita el driver psycopg 3.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


# Caja inmutable (frozen=True) con toda la configuración del tutor.
# Se crea una vez al arrancar en app/main.py y app/mcp_tools.py y se entrega a AgenteTutor(config).
@dataclass(frozen=True)
class Config:
    database_url: str
    gemini_api_key: str
    gemini_modelo: str
    intervalo_ciclo_s: float
    minutos_por_dia: float
    max_pendientes: int
    nuevas_por_dia: int
    token: str
    autonomo: bool
    leer_antes: bool = True
    meta_diaria: int = 10
    webhook_url: str = ""

    # Construye una instancia de Config leyendo os.environ; si falta una variable usa un valor seguro por defecto.
    @staticmethod
    def desde_entorno() -> "Config":
        return Config(
            # SQLite local por defecto; en Render recibe automáticamente la URL de PostgreSQL (tutor-memoria).
            database_url=_url_base_datos(os.environ.get("DATABASE_URL", "sqlite:///./tutor.db")),
            # Clave opcional de Google AI Studio; si está vacía el agente funciona igual con motor local y DevCards.
            gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
            gemini_modelo=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip(),
            # Cada cuánto el agente despierta, revisa su memoria y decide qué hacer.
            intervalo_ciclo_s=float(os.environ.get("TUTOR_INTERVALO_S", "30")),
            # Escala de tiempo de la repetición espaciada. 1440 = tiempo real (1 día = 1440 min).
            # En la demo de clase se usa 1: "1 día" de SM-2 dura 1 minuto y el agente trae los temas de vuelta en vivo.
            minutos_por_dia=float(os.environ.get("TUTOR_MINUTOS_POR_DIA", "1440")),
            # Límite de preguntas sin responder al mismo tiempo para no saturar al estudiante.
            max_pendientes=int(os.environ.get("TUTOR_MAX_PENDIENTES", "3")),
            # Cuántas DevCards nuevas puede presentar el agente por "día" (como Anki).
            nuevas_por_dia=int(os.environ.get("TUTOR_NUEVAS_POR_DIA", "5")),
            # Si se define, las operaciones que escriben exigen este token (cabecera X-Tutor-Token o Bearer).
            token=os.environ.get("TUTOR_TOKEN", "").strip(),
            # Si vale "1", main.py arranca el hilo autónomo en segundo plano; con "0" solo responde bajo demanda.
            autonomo=os.environ.get("TUTOR_AUTONOMO", "1") != "0",
            # Modo "leer antes de responder": una DevCard nueva se muestra completa antes de su quiz.
            leer_antes=os.environ.get("TUTOR_LEER_ANTES", "1") != "0",
            meta_diaria=max(1, int(os.environ.get("TUTOR_META_DIARIA", "10"))),
            webhook_url=os.environ.get("TUTOR_WEBHOOK_URL", "").strip(),
        )

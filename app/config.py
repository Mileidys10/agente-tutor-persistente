"""Configuración por variables de entorno. Ningún secreto vive en el repositorio."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _url_base_datos(url: str) -> str:
    # Render entrega "postgres://..." o "postgresql://..."; SQLAlchemy necesita el driver psycopg 3.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


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

    @staticmethod
    def desde_entorno() -> "Config":
        return Config(
            database_url=_url_base_datos(os.environ.get("DATABASE_URL", "sqlite:///./tutor.db")),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
            gemini_modelo=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip(),
            # Cada cuánto el agente despierta, revisa su memoria y decide qué hacer.
            intervalo_ciclo_s=float(os.environ.get("TUTOR_INTERVALO_S", "30")),
            # Escala de tiempo de la repetición espaciada. 1440 = tiempo real (1 día = 1440 min).
            # En la demo de clase se usa 1: "1 día" de SM-2 dura 1 minuto y el agente trae los temas de vuelta en vivo.
            minutos_por_dia=float(os.environ.get("TUTOR_MINUTOS_POR_DIA", "1440")),
            max_pendientes=int(os.environ.get("TUTOR_MAX_PENDIENTES", "3")),
            # Cuántas DevCards nuevas puede presentar el agente por "día" (como Anki).
            nuevas_por_dia=int(os.environ.get("TUTOR_NUEVAS_POR_DIA", "5")),
            # Si se define, las operaciones que escriben exigen este token (cabecera X-Tutor-Token o Bearer).
            token=os.environ.get("TUTOR_TOKEN", "").strip(),
            autonomo=os.environ.get("TUTOR_AUTONOMO", "1") != "0",
            # Modo "leer antes de responder": una DevCard nueva se muestra completa antes de su quiz.
            leer_antes=os.environ.get("TUTOR_LEER_ANTES", "1") != "0",
        )

"""Servidor web del agente: API REST, página de estudio y servidor MCP remoto en /mcp."""

from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from app.agente import AgenteTutor
from app.config import Config
from app.mcp_tools import crear_servidor_mcp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
STATIC_DIR = Path(__file__).resolve().parent / "static"

config = Config.desde_entorno()
agente = AgenteTutor(config)
mcp = crear_servidor_mcp(agente)

_hosts = ["127.0.0.1:*", "localhost:*", "testserver"]
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):  # Render define esta variable con el dominio público
    _hosts.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=_hosts,
                                                 allowed_origins=[f"https://{h}" for h in _hosts if "*" not in h]),
)


def _token_valido(valor: Optional[str]) -> bool:
    if not config.token:
        return True  # sin TUTOR_TOKEN (desarrollo local) la API queda abierta
    return bool(valor) and hmac.compare_digest(valor, config.token)


def _extraer_token(x_tutor_token: Optional[str], authorization: Optional[str]) -> Optional[str]:
    if x_tutor_token:
        return x_tutor_token
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def exigir_token(
    x_tutor_token: Optional[str] = Header(default=None), authorization: Optional[str] = Header(default=None)
) -> None:
    if not _token_valido(_extraer_token(x_tutor_token, authorization)):
        raise HTTPException(status_code=401, detail="Falta la clave de acceso o es incorrecta")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if config.autonomo:
        agente.iniciar()
    async with mcp.session_manager.run():
        try:
            yield
        finally:
            agente.detener()


app = FastAPI(title="Agente Tutor Persistente", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def proteger_mcp(request, call_next):  # el endpoint MCP exige el mismo token que la API
    if request.url.path.startswith("/mcp"):
        token = _extraer_token(request.headers.get("x-tutor-token"), request.headers.get("authorization"))
        if not _token_valido(token):
            return JSONResponse({"detail": "Falta la clave de acceso o es incorrecta"}, status_code=401)
    return await call_next(request)


# ---- modelos ------------------------------------------------------------------
class TemaNuevo(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=200)
    notas: str = Field("", max_length=8000)


class Respuesta(BaseModel):
    respuesta: str = Field(..., max_length=2000)


class MazoCambio(BaseModel):
    activo: bool = True


# ---- rutas públicas (solo lectura) --------------------------------------------
@app.get("/health")
def health() -> dict[str, Any]:
    """Lo visita el "despertador" para que Render no duerma el servicio, y muestra que el agente sigue vivo."""
    lat = agente.memoria.leer_latido()
    return {"ok": True, "agente_vivo": agente.vivo, "ciclos": lat.get("ciclos", 0), "arranques": lat.get("arranques", 0),
            "ultimo_ciclo": lat.get("ultimo_ciclo")}


@app.get("/api/estado")
def estado() -> dict[str, Any]:
    return agente.estado()


@app.get("/api/temas")
def temas() -> list[dict[str, Any]]:
    return agente.memoria.listar_temas()


@app.get("/api/preguntas/pendientes")
def pendientes() -> list[dict[str, Any]]:
    return [
        {k: p[k] for k in ("id", "tema_id", "tema", "texto", "opciones", "motivo", "fuente", "creada")}
        for p in agente.memoria.pendientes()
    ]


@app.get("/api/historial")
def historial(limite: int = 20) -> list[dict[str, Any]]:
    return agente.memoria.historial(max(1, min(limite, 100)))


@app.get("/api/bitacora")
def bitacora(limite: int = 40) -> list[dict[str, Any]]:
    return agente.memoria.leer_bitacora(max(1, min(limite, 200)))


@app.get("/api/mazos")
def mazos() -> list[dict[str, Any]]:
    return agente.mazos()


@app.get("/api/progreso")
def progreso() -> dict[str, Any]:
    return agente.progreso()


# ---- rutas que escriben (requieren token si TUTOR_TOKEN está definido) -----------
@app.post("/api/temas", status_code=201, dependencies=[Depends(exigir_token)])
def crear_tema(body: TemaNuevo) -> dict[str, Any]:
    try:
        return agente.agregar_tema(body.nombre, body.notas)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.delete("/api/temas/{tema_id}", dependencies=[Depends(exigir_token)])
def borrar_tema(tema_id: int) -> dict[str, Any]:
    if not agente.memoria.borrar_tema(tema_id):
        raise HTTPException(status_code=404, detail="No existe ese tema")
    agente.memoria.anotar("sistema", f"Olvidé el tema {tema_id} a pedido de la persona.")
    return {"borrado": tema_id}


@app.post("/api/preguntas/{pregunta_id}/responder", dependencies=[Depends(exigir_token)])
def responder(pregunta_id: int, body: Respuesta) -> dict[str, Any]:
    try:
        return agente.responder(pregunta_id, body.respuesta)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.put("/api/mazos/{categoria}", dependencies=[Depends(exigir_token)])
def cambiar_mazo(categoria: str, body: MazoCambio) -> dict[str, Any]:
    try:
        agente.activar_mazo(categoria, body.activo)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"categoria": categoria, "activo": body.activo}


@app.post("/api/ciclo", dependencies=[Depends(exigir_token)])
def forzar_ciclo() -> dict[str, Any]:
    """Para la exposición: ejecuta un ciclo del agente ya, sin esperar al temporizador."""
    return agente.ciclo()


@app.get("/api/acceso", dependencies=[Depends(exigir_token)])
def comprobar_acceso() -> dict[str, Any]:
    return {"ok": True, "requiere_token": bool(config.token)}


# ---- página -------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def inicio() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/privacidad", include_in_schema=False)
def privacidad() -> FileResponse:
    return FileResponse(STATIC_DIR / "privacidad.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/", mcp_app)  # al final: sirve /mcp sin tapar las rutas anteriores

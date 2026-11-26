# Archivo app/main.py: punto de entrada web con FastAPI.
# Sirve la página HTML/JS/CSS, recibe peticiones HTTP de estudio, arranca AgenteTutor y expone MCP en /mcp.
"""Servidor web del agente: API REST, página de estudio y servidor MCP remoto en /mcp."""

from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field

from app.agente import AgenteTutor
from app.config import Config
from app.mcp_tools import crear_servidor_mcp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# Carpeta donde viven index.html, privacidad.html, app.js y estilos.css.
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Crea una única instancia global de Config, AgenteTutor y el servidor MCP al importar este módulo.
config = Config.desde_entorno()
agente = AgenteTutor(config)
mcp = crear_servidor_mcp(agente)

# Prepara la aplicación MCP remota (Streamable HTTP) restringiendo qué dominios (Host/Origin) pueden conectarse.
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


# Verifica si la clave enviada coincide con TUTOR_TOKEN usando compare_digest (protege contra ataques de tiempo).
def _token_valido(valor: Optional[str]) -> bool:
    if not config.token:
        return True  # sin TUTOR_TOKEN (desarrollo local) la API queda abierta
    return bool(valor) and hmac.compare_digest(valor, config.token)


# Lee la clave ya sea desde la cabecera "X-Tutor-Token" (web) o desde "Authorization: Bearer ..." (MCP/curl).
def _extraer_token(x_tutor_token: Optional[str], authorization: Optional[str]) -> Optional[str]:
    if x_tutor_token:
        return x_tutor_token
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


# Dependencia de FastAPI usada en todas las rutas que escriben (POST, PUT, DELETE) y en /api/acceso;
# si la clave falta o falla, corta la petición devolviendo HTTP 401.
def exigir_token(
    x_tutor_token: Optional[str] = Header(default=None), authorization: Optional[str] = Header(default=None)
) -> None:
    if not _token_valido(_extraer_token(x_tutor_token, authorization)):
        raise HTTPException(status_code=401, detail="Falta la clave de acceso o es incorrecta")


# Ciclo de vida de FastAPI: al arrancar enciende el hilo autónomo del agente y MCP; al apagar lo detiene limpio.
@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if config.autonomo:
        agente.iniciar()
    async with mcp.session_manager.run():
        try:
            yield
        finally:
            agente.detener()


# Instancia principal de FastAPI (expone automáticamente Swagger UI en /docs).
app = FastAPI(title="Agente Tutor Persistente", version="3.0.0", lifespan=lifespan)


# Middleware HTTP que intercepta cualquier llamada hacia /mcp para exigir la misma clave TUTOR_TOKEN.
@app.middleware("http")
async def proteger_mcp(request, call_next):  # el endpoint MCP exige el mismo token que la API
    if request.url.path.startswith("/mcp"):
        token = _extraer_token(request.headers.get("x-tutor-token"), request.headers.get("authorization"))
        if not _token_valido(token):
            return JSONResponse({"detail": "Falta la clave de acceso o es incorrecta"}, status_code=401)
    return await call_next(request)


# ---- modelos ------------------------------------------------------------------
# Esquemas Pydantic que validan automáticamente el JSON recibido desde la web (si fallan devuelven 422).
class TemaNuevo(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=200)
    notas: str = Field("", max_length=8000)
    coleccion_id: Optional[int] = None
    tipo: str = Field("nota", max_length=20)
    codigo: str = Field("", max_length=12000)
    lenguaje: str = Field("", max_length=40)
    analogia: str = Field("", max_length=2000)
    idea_clave: str = Field("", max_length=1000)
    etiquetas: str = Field("", max_length=500)


class TemaEdicion(BaseModel):
    nombre: Optional[str] = Field(None, min_length=2, max_length=200)
    notas: Optional[str] = Field(None, max_length=8000)
    coleccion_id: Optional[int] = None
    codigo: Optional[str] = Field(None, max_length=12000)
    lenguaje: Optional[str] = Field(None, max_length=40)
    analogia: Optional[str] = Field(None, max_length=2000)
    idea_clave: Optional[str] = Field(None, max_length=1000)
    etiquetas: Optional[str] = Field(None, max_length=500)


class PosponerBody(BaseModel):
    dias: float = Field(1.0, gt=0, le=365)


class ColeccionNueva(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=120)
    descripcion: str = Field("", max_length=500)


class ColeccionCambio(BaseModel):
    nombre: Optional[str] = Field(None, min_length=2, max_length=120)
    descripcion: Optional[str] = Field(None, max_length=500)
    activa: Optional[bool] = None


class ImportacionBody(BaseModel):
    datos: Any
    formato: str = Field("json", max_length=20)
    nombre_coleccion: str = Field("", max_length=120)


class CodigoEstudio(BaseModel):
    codigo: str = Field(..., min_length=10, max_length=12000)
    titulo: str = Field("", max_length=200)
    lenguaje: str = Field("", max_length=40)
    coleccion: str = Field("Código estudiado", max_length=120)
    objetivo: str = Field("", max_length=500)
    max_fichas: int = Field(5, ge=1, le=10)


class MaterialEstudio(BaseModel):
    contenido: str = Field(..., min_length=20, max_length=25000)
    titulo: str = Field("", max_length=200)
    coleccion: str = Field("Material de estudio", max_length=120)
    max_fichas: int = Field(5, ge=1, le=15)


class DiffEstudio(BaseModel):
    diff_texto: str = Field(..., min_length=15, max_length=30000)
    titulo: str = Field("", max_length=200)
    coleccion: str = Field("Cambios Git (Diff)", max_length=120)
    max_fichas: int = Field(5, ge=1, le=10)


class SimulacroBody(BaseModel):
    titulo: str = Field("Simulacro de estudio", max_length=160)
    cantidad: int = Field(5, ge=1, le=20)
    coleccion_id: Optional[int] = None
    categoria_devcards: str = Field("", max_length=120)
    solo_brechas: bool = False


class RelacionBody(BaseModel):
    origen_id: int
    destino_id: int
    tipo: str = Field("prerrequisito", max_length=20)


# Valida la respuesta enviada por el estudiante en POST /api/preguntas/{id}/responder.
class Respuesta(BaseModel):
    respuesta: str = Field(..., max_length=2000)


# Valida el interruptor booleano para activar o pausar una categoría en PUT /api/mazos/{categoria}.
class MazoCambio(BaseModel):
    activo: bool = True


# ---- rutas públicas (solo lectura) --------------------------------------------
# Ruta de salud sin token: Render la consulta al arrancar y GitHub Actions la visita cada 10 min.
@app.get("/health")
def health() -> dict[str, Any]:
    """Lo visita el "despertador" para que Render no duerma el servicio, y muestra que el agente sigue vivo."""
    lat = agente.memoria.leer_latido()
    return {"ok": True, "agente_vivo": agente.vivo, "ciclos": lat.get("ciclos", 0), "arranques": lat.get("arranques", 0),
            "ultimo_ciclo": lat.get("ultimo_ciclo")}


# Devuelve el estado técnico completo para la cabecera de index.html cada 5 segundos.
@app.get("/api/estado")
def estado() -> dict[str, Any]:
    return agente.estado()


# Lista y filtra temas y DevCards en estudio con sus métricas SM-2 para "Mis temas".
@app.get("/api/temas")
def temas(q: str = "", coleccion_id: Optional[int] = None, tipo: Optional[str] = None) -> list[dict[str, Any]]:
    if q or coleccion_id is not None or tipo:
        return agente.buscar_temas(q=q, coleccion_id=coleccion_id, tipo=tipo)
    return agente.memoria.listar_temas()


@app.get("/api/colecciones")
def listar_colecciones() -> list[dict[str, Any]]:
    return agente.listar_colecciones()


@app.get("/api/colecciones/{coleccion_id}/exportar")
def exportar_coleccion(coleccion_id: int, formato: str = "json") -> Any:
    try:
        resultado = agente.exportar_coleccion(coleccion_id, formato=formato)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(resultado, str):
        fmt = formato.strip().lower()
        media = "text/tab-separated-values; charset=utf-8" if fmt == "anki" else "text/markdown; charset=utf-8"
        return PlainTextResponse(resultado, media_type=media)
    return resultado


# Devuelve preguntas pendientes; añade si exige lectura previa y, en ese caso, la ficha completa sin la respuesta.
@app.get("/api/preguntas/pendientes")
def pendientes() -> list[dict[str, Any]]:
    return [
        {
            **{k: p[k] for k in ("id", "tema_id", "tema", "texto", "opciones", "motivo", "fuente", "creada")},
            "requiere_lectura": bool(p.get("requiere_lectura")),
            "lectura": agente.lectura_de(p),
        }
        for p in agente.memoria.pendientes()
    ]


# Devuelve las últimas evaluaciones (nota y retroalimentación) para el bloque "Últimas evaluaciones".
@app.get("/api/historial")
def historial(limite: int = 20) -> list[dict[str, Any]]:
    return agente.memoria.historial(max(1, min(limite, 100)))


# Devuelve los registros recientes de la tabla bitacora para mostrar cómo piensa y decide el agente.
@app.get("/api/bitacora")
def bitacora(limite: int = 40) -> list[dict[str, Any]]:
    return agente.memoria.leer_bitacora(max(1, min(limite, 200)))


# Lista las 42 categorías del banco DevCards con su estado activo/pausado y progreso de tarjetas vistas.
@app.get("/api/mazos")
def mazos() -> list[dict[str, Any]]:
    return agente.mazos()


# Devuelve el resumen numérico de progreso (dominados, porcentaje de aciertos y temas más difíciles).
@app.get("/api/progreso")
def progreso() -> dict[str, Any]:
    return agente.progreso()


@app.get("/api/brechas")
def brechas(limite: int = 10) -> dict[str, Any]:
    return agente.diagnosticar_brechas(limite=limite)


@app.get("/api/plan")
def plan_hoy() -> dict[str, Any]:
    return agente.plan_estudio_hoy()


@app.get("/api/examenes")
def listar_examenes(limite: int = 10) -> list[dict[str, Any]]:
    return agente.ver_simulacros(limite=limite)


@app.get("/api/examenes/{sesion_id}")
def detalle_examen(sesion_id: int) -> dict[str, Any]:
    try:
        return agente.obtener_simulacro(sesion_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/temas/{tema_id}/relaciones")
def relaciones_tema(tema_id: int) -> list[dict[str, Any]]:
    return agente.listar_relaciones(tema_id=tema_id)


# ---- rutas que escriben (requieren token si TUTOR_TOKEN está definido) -----------
# Crea un tema nuevo con notas propias (POST /api/temas) delegando en AgenteTutor.agregar_tema().
@app.post("/api/temas", status_code=201, dependencies=[Depends(exigir_token)])
def crear_tema(body: TemaNuevo) -> dict[str, Any]:
    try:
        return agente.agregar_tema(
            body.nombre,
            body.notas,
            coleccion_id=body.coleccion_id,
            tipo=body.tipo,
            codigo=body.codigo,
            lenguaje=body.lenguaje,
            analogia=body.analogia,
            idea_clave=body.idea_clave,
            etiquetas=body.etiquetas,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.patch("/api/temas/{tema_id}", dependencies=[Depends(exigir_token)])
def editar_tema(tema_id: int, body: TemaEdicion) -> dict[str, Any]:
    campos = body.model_dump(exclude_unset=True)
    try:
        return agente.editar_tema(tema_id, **campos)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/temas/{tema_id}/posponer", dependencies=[Depends(exigir_token)])
def posponer_tema(tema_id: int, body: PosponerBody) -> dict[str, Any]:
    try:
        return agente.posponer_tema(tema_id, dias=body.dias)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# Borra un tema de la base de datos en cascada y deja constancia en la bitácora.
@app.delete("/api/temas/{tema_id}", dependencies=[Depends(exigir_token)])
def borrar_tema(tema_id: int) -> dict[str, Any]:
    if not agente.borrar_tema(tema_id):
        raise HTTPException(status_code=404, detail="No existe ese tema")
    return {"borrado": tema_id}


@app.post("/api/colecciones", status_code=201, dependencies=[Depends(exigir_token)])
def crear_coleccion(body: ColeccionNueva) -> dict[str, Any]:
    try:
        return agente.crear_coleccion(body.nombre, body.descripcion)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.patch("/api/colecciones/{coleccion_id}", dependencies=[Depends(exigir_token)])
def actualizar_coleccion(coleccion_id: int, body: ColeccionCambio) -> dict[str, Any]:
    try:
        return agente.actualizar_coleccion(
            coleccion_id, nombre=body.nombre, descripcion=body.descripcion, activa=body.activa
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.delete("/api/colecciones/{coleccion_id}", dependencies=[Depends(exigir_token)])
def borrar_coleccion(coleccion_id: int, borrar_temas: bool = False) -> dict[str, Any]:
    if not agente.borrar_coleccion(coleccion_id, borrar_temas=borrar_temas):
        raise HTTPException(status_code=404, detail="No existe esa colección")
    return {"borrado": coleccion_id}


@app.post("/api/colecciones/importar", status_code=201, dependencies=[Depends(exigir_token)])
def importar_coleccion(body: ImportacionBody) -> dict[str, Any]:
    try:
        return agente.importar_coleccion(body.datos, formato=body.formato, nombre_coleccion=body.nombre_coleccion)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/estudiar/codigo", status_code=201, dependencies=[Depends(exigir_token)])
def estudiar_codigo(body: CodigoEstudio) -> dict[str, Any]:
    try:
        return agente.estudiar_codigo(
            body.codigo,
            titulo=body.titulo,
            lenguaje=body.lenguaje,
            coleccion=body.coleccion,
            objetivo=body.objetivo,
            max_fichas=body.max_fichas,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/estudiar/material", status_code=201, dependencies=[Depends(exigir_token)])
def ingestar_material(body: MaterialEstudio) -> dict[str, Any]:
    try:
        return agente.ingestar_material(
            body.contenido,
            titulo=body.titulo,
            coleccion=body.coleccion,
            max_fichas=body.max_fichas,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/estudiar/diff", status_code=201, dependencies=[Depends(exigir_token)])
def estudiar_diff(body: DiffEstudio) -> dict[str, Any]:
    try:
        return agente.estudiar_diff(
            body.diff_texto, titulo=body.titulo, coleccion=body.coleccion, max_fichas=body.max_fichas
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/preguntas/{pregunta_id}/pista", dependencies=[Depends(exigir_token)])
def pedir_pista(pregunta_id: int) -> dict[str, Any]:
    try:
        return agente.pedir_pista(pregunta_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/examenes", status_code=201, dependencies=[Depends(exigir_token)])
def crear_examen(body: SimulacroBody) -> dict[str, Any]:
    try:
        return agente.iniciar_simulacro(
            titulo=body.titulo,
            cantidad=body.cantidad,
            coleccion_id=body.coleccion_id,
            categoria_devcards=body.categoria_devcards,
            solo_brechas=body.solo_brechas,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/temas/relaciones", status_code=201, dependencies=[Depends(exigir_token)])
def crear_relacion(body: RelacionBody) -> dict[str, Any]:
    try:
        return agente.vincular_temas(body.origen_id, body.destino_id, tipo=body.tipo)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/temas/relaciones/{relacion_id}", dependencies=[Depends(exigir_token)])
def borrar_relacion(relacion_id: int) -> dict[str, Any]:
    if not agente.borrar_relacion(relacion_id):
        raise HTTPException(status_code=404, detail="No existe esa relación")
    return {"borrado": relacion_id}


# Evalúa tu respuesta con AgenteTutor.responder() y devuelve nota, explicación y nueva fecha SM-2.
@app.post("/api/preguntas/{pregunta_id}/responder", dependencies=[Depends(exigir_token)])
def responder(pregunta_id: int, body: Respuesta) -> dict[str, Any]:
    try:
        return agente.responder(pregunta_id, body.respuesta)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# Se llama cuando pulsas "Ya la leí, hazme la pregunta"; desbloquea la pregunta guardando leida_en.
@app.post("/api/preguntas/{pregunta_id}/leida", dependencies=[Depends(exigir_token)])
def marcar_leida(pregunta_id: int) -> dict[str, Any]:
    try:
        return agente.marcar_leida(pregunta_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# Activa o pausa un mazo de DevCards al pulsar su interruptor en la sección "Mazos DevCards".
@app.put("/api/mazos/{categoria}", dependencies=[Depends(exigir_token)])
def cambiar_mazo(categoria: str, body: MazoCambio) -> dict[str, Any]:
    try:
        agente.activar_mazo(categoria, body.activo)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"categoria": categoria, "activo": body.activo}


# Ejecuta un ciclo del agente de inmediato al pulsar el botón "Ejecutar un ciclo ahora" en la web.
@app.post("/api/ciclo", dependencies=[Depends(exigir_token)])
def forzar_ciclo() -> dict[str, Any]:
    """Para la exposición: ejecuta un ciclo del agente ya, sin esperar al temporizador."""
    res = agente.ciclo()
    # Igual que en /pendientes: la respuesta esperada nunca sale antes de que la persona conteste.
    res["preguntas_creadas"] = [
        {k: p[k] for k in ("id", "tema_id", "texto", "opciones", "motivo", "fuente", "creada")}
        for p in res["preguntas_creadas"]
    ]
    return res


# Sirve para que el diálogo "Clave de acceso" de app.js compruebe si el token introducido es válido.
@app.get("/api/acceso", dependencies=[Depends(exigir_token)])
def comprobar_acceso() -> dict[str, Any]:
    return {"ok": True, "requiere_token": bool(config.token)}


# ---- página -------------------------------------------------------------------
# Entrega la página principal (app/static/index.html) al entrar a "/".
@app.get("/", include_in_schema=False)
def inicio() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# Entrega la página informativa de privacidad (/privacidad).
@app.get("/privacidad", include_in_schema=False)
def privacidad() -> FileResponse:
    return FileResponse(STATIC_DIR / "privacidad.html")


# Publica CSS/JS bajo /static y deja el servidor MCP montado al final en /mcp sin tapar las rutas anteriores.
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/", mcp_app)  # al final: sirve /mcp sin tapar las rutas anteriores

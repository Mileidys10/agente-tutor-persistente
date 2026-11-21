"""Memoria persistente del agente (SQLAlchemy Core): PostgreSQL en Render, SQLite en local y en pruebas.

Todo lo que el agente sabe vive aquí, no en variables de Python: si el proceso se reinicia
(Render lo duerme, se redepliega o se cae), el agente retoma exactamente donde iba.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    func,
    inspect,
    text,
    select,
    update,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

temas = Table(
    "temas",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("nombre", String(200), nullable=False),
    Column("notas", Text, nullable=False, default=""),
    Column("origen", String(20), nullable=False, default="usuario"),  # usuario | devcards
    Column("categoria", String(120), nullable=False, default=""),
    Column("ref_externa", String(60), unique=True),  # id de la DevCard (p. ej. "poo-01")
    Column("repeticiones", Integer, nullable=False, default=0),
    Column("intervalo_dias", Float, nullable=False, default=0.0),
    Column("facilidad", Float, nullable=False, default=2.5),
    Column("proximo_repaso", DateTime(timezone=True), nullable=False),
    Column("aciertos", Integer, nullable=False, default=0),
    Column("fallos", Integer, nullable=False, default=0),
    Column("creado", DateTime(timezone=True), nullable=False),
)

preguntas = Table(
    "preguntas",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("tema_id", Integer, ForeignKey("temas.id", ondelete="CASCADE"), nullable=False),
    Column("texto", Text, nullable=False),
    Column("respuesta_esperada", Text, nullable=False),
    Column("motivo", Text, nullable=False, default=""),  # por qué el agente decidió preguntar esto ahora
    Column("estado", String(20), nullable=False, default="pendiente"),  # pendiente | respondida
    Column("fuente", String(20), nullable=False, default="local"),  # gemini | local | devcards
    Column("opciones", Text),  # JSON con las opciones si es de opción múltiple
    Column("explicacion", Text, nullable=False, default=""),  # idea clave que se muestra al corregir
    Column("requiere_lectura", Integer, nullable=False, default=0),  # 1: DevCard nueva que se lee antes del quiz
    Column("leida_en", DateTime(timezone=True)),  # cuándo la persona marcó la tarjeta como leída
    Column("creada", DateTime(timezone=True), nullable=False),
    Column("respondida_en", DateTime(timezone=True)),
)

respuestas = Table(
    "respuestas",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("pregunta_id", Integer, ForeignKey("preguntas.id", ondelete="CASCADE"), nullable=False),
    Column("texto", Text, nullable=False),
    Column("nota", Integer, nullable=False),
    Column("retroalimentacion", Text, nullable=False, default=""),
    Column("fecha", DateTime(timezone=True), nullable=False),
)

mazos = Table(  # categorías de DevCards que la persona eligió estudiar
    "mazos",
    metadata,
    Column("categoria", String(120), primary_key=True),
    Column("activo", Integer, nullable=False, default=1),
    Column("activado_en", DateTime(timezone=True), nullable=False),
)

bitacora = Table(
    "bitacora",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("fecha", DateTime(timezone=True), nullable=False),
    Column("tipo", String(20), nullable=False),  # sistema | ciclo | decision | pregunta | evaluacion | error
    Column("detalle", Text, nullable=False),
)

latido = Table(
    "latido",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("primer_arranque", DateTime(timezone=True), nullable=False),
    Column("ultimo_arranque", DateTime(timezone=True), nullable=False),
    Column("ultimo_ciclo", DateTime(timezone=True)),
    Column("ciclos", Integer, nullable=False, default=0),
    Column("arranques", Integer, nullable=False, default=0),
)


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def _utc(valor: Optional[datetime]) -> Optional[datetime]:
    # SQLite devuelve fechas sin zona horaria: se normalizan a UTC.
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def _fila(row: Any) -> dict[str, Any]:
    datos = dict(row._mapping)
    for k, v in datos.items():
        if isinstance(v, datetime):
            datos[k] = _utc(v)
    if "opciones" in datos:
        datos["opciones"] = json.loads(datos["opciones"]) if datos["opciones"] else None
    if "requiere_lectura" in datos:  # solo "requiere" mientras no se haya marcado como leída
        datos["requiere_lectura"] = bool(datos["requiere_lectura"]) and datos.get("leida_en") is None
    return datos


class Memoria:
    def __init__(self, url: str) -> None:
        kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        self.engine: Engine = create_engine(url, **kwargs)
        metadata.create_all(self.engine)
        self._migrar()

    # Columnas añadidas después de la v1.0. create_all() no altera tablas que ya existen, así que una base
    # que ya está en uso (la de Render) recibe aquí las columnas nuevas sin perder ningún dato.
    _COLUMNAS_NUEVAS = {
        "preguntas": {
            "requiere_lectura": "INTEGER NOT NULL DEFAULT 0",
            "leida_en": {"postgresql": "TIMESTAMP WITH TIME ZONE", "default": "TIMESTAMP"},
        },
    }

    def _migrar(self) -> None:
        dialecto = self.engine.dialect.name
        existentes = {t: {c["name"] for c in inspect(self.engine).get_columns(t)} for t in self._COLUMNAS_NUEVAS}
        with self.engine.begin() as c:
            for tabla, columnas in self._COLUMNAS_NUEVAS.items():
                for nombre, tipo in columnas.items():
                    if nombre in existentes[tabla]:
                        continue
                    ddl = tipo if isinstance(tipo, str) else tipo.get(dialecto, tipo["default"])
                    c.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {ddl}"))

    # ---- latido: demuestra la persistencia entre reinicios -------------------
    def registrar_arranque(self) -> dict[str, Any]:
        t = ahora()
        with self.engine.begin() as c:
            fila = c.execute(select(latido).where(latido.c.id == 1)).first()
            if fila is None:
                c.execute(latido.insert().values(id=1, primer_arranque=t, ultimo_arranque=t, ciclos=0, arranques=1))
            else:
                c.execute(update(latido).where(latido.c.id == 1).values(ultimo_arranque=t, arranques=latido.c.arranques + 1))
        return self.leer_latido()

    def registrar_ciclo(self) -> None:
        with self.engine.begin() as c:
            c.execute(update(latido).where(latido.c.id == 1).values(ultimo_ciclo=ahora(), ciclos=latido.c.ciclos + 1))

    def leer_latido(self) -> dict[str, Any]:
        with self.engine.connect() as c:
            fila = c.execute(select(latido).where(latido.c.id == 1)).first()
        return _fila(fila) if fila else {}

    # ---- temas --------------------------------------------------------------
    def crear_tema(
        self, nombre: str, notas: str, origen: str = "usuario", categoria: str = "", ref_externa: Optional[str] = None,
    ) -> dict[str, Any]:
        t = ahora()
        with self.engine.begin() as c:
            if origen == "usuario":
                existe = c.execute(
                    select(temas.c.id).where(temas.c.origen == "usuario", func.lower(temas.c.nombre) == nombre.lower())
                ).first()
                if existe:
                    raise ValueError(f"Ya existe un tema llamado «{nombre}»")
            tid = c.execute(
                temas.insert().values(
                    nombre=nombre, notas=notas, origen=origen, categoria=categoria, ref_externa=ref_externa,
                    repeticiones=0, intervalo_dias=0.0, facilidad=2.5,
                    proximo_repaso=t, aciertos=0, fallos=0, creado=t,
                )
            ).inserted_primary_key[0]
        return self.obtener_tema(int(tid))  # type: ignore[return-value]

    def obtener_tema(self, tema_id: int) -> Optional[dict[str, Any]]:
        with self.engine.connect() as c:
            fila = c.execute(select(temas).where(temas.c.id == tema_id)).first()
        return _fila(fila) if fila else None

    def listar_temas(self) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            return [_fila(f) for f in c.execute(select(temas).order_by(temas.c.proximo_repaso))]

    def borrar_tema(self, tema_id: int) -> bool:
        with self.engine.begin() as c:  # borrado explícito en cascada (SQLite no aplica ON DELETE por defecto)
            ids = select(preguntas.c.id).where(preguntas.c.tema_id == tema_id)
            c.execute(respuestas.delete().where(respuestas.c.pregunta_id.in_(ids)))
            c.execute(preguntas.delete().where(preguntas.c.tema_id == tema_id))
            return c.execute(temas.delete().where(temas.c.id == tema_id)).rowcount > 0

    def actualizar_repaso(
        self, tema_id: int, repeticiones: int, intervalo_dias: float, facilidad: float,
        proximo_repaso: datetime, acierto: bool,
    ) -> None:
        with self.engine.begin() as c:
            c.execute(
                update(temas).where(temas.c.id == tema_id).values(
                    repeticiones=repeticiones, intervalo_dias=intervalo_dias, facilidad=facilidad,
                    proximo_repaso=proximo_repaso,
                    aciertos=temas.c.aciertos + (1 if acierto else 0),
                    fallos=temas.c.fallos + (0 if acierto else 1),
                )
            )

    # ---- preguntas y respuestas ---------------------------------------------
    def crear_pregunta(
        self, tema_id: int, texto: str, esperada: str, motivo: str, fuente: str,
        opciones: Optional[list[str]] = None, explicacion: str = "", requiere_lectura: bool = False,
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            pid = c.execute(
                preguntas.insert().values(
                    tema_id=tema_id, texto=texto, respuesta_esperada=esperada, motivo=motivo,
                    estado="pendiente", fuente=fuente, creada=ahora(),
                    opciones=json.dumps(opciones, ensure_ascii=False) if opciones else None, explicacion=explicacion,
                    requiere_lectura=1 if requiere_lectura else 0,
                )
            ).inserted_primary_key[0]
        return self.obtener_pregunta(int(pid))  # type: ignore[return-value]

    def obtener_pregunta(self, pregunta_id: int) -> Optional[dict[str, Any]]:
        with self.engine.connect() as c:
            fila = c.execute(
                select(preguntas, temas.c.nombre.label("tema"), temas.c.ref_externa)
                .join(temas, temas.c.id == preguntas.c.tema_id)
                .where(preguntas.c.id == pregunta_id)
            ).first()
        return _fila(fila) if fila else None

    def pendientes(self) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            filas = c.execute(
                select(preguntas, temas.c.nombre.label("tema"), temas.c.ref_externa)
                .join(temas, temas.c.id == preguntas.c.tema_id)
                .where(preguntas.c.estado == "pendiente")
                .order_by(preguntas.c.creada)
            )
            return [_fila(f) for f in filas]

    def marcar_leida(self, pregunta_id: int) -> datetime:
        """Idempotente: si ya estaba leída, devuelve la fecha original."""
        with self.engine.begin() as c:
            fila = c.execute(select(preguntas.c.estado, preguntas.c.leida_en).where(preguntas.c.id == pregunta_id)).first()
            if fila is None:
                raise LookupError("No existe esa pregunta")
            if fila.estado != "pendiente":
                raise ValueError("La pregunta ya fue respondida")
            if fila.leida_en is not None:
                return _utc(fila.leida_en)  # type: ignore[return-value]
            t = ahora()
            c.execute(update(preguntas).where(preguntas.c.id == pregunta_id).values(leida_en=t))
            return t

    def registrar_respuesta(self, pregunta_id: int, texto: str, nota: int, retro: str) -> dict[str, Any]:
        t = ahora()
        with self.engine.begin() as c:
            hecho = c.execute(
                update(preguntas)
                .where(preguntas.c.id == pregunta_id, preguntas.c.estado == "pendiente")
                .values(estado="respondida", respondida_en=t)
            ).rowcount
            if not hecho:  # otra petición la respondió primero
                raise ValueError("La pregunta ya fue respondida")
            rid = c.execute(
                respuestas.insert().values(pregunta_id=pregunta_id, texto=texto, nota=nota, retroalimentacion=retro, fecha=t)
            ).inserted_primary_key[0]
        return {"id": int(rid), "pregunta_id": pregunta_id, "nota": nota, "retroalimentacion": retro, "fecha": t}

    def historial(self, limite: int = 20) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            filas = c.execute(
                select(
                    respuestas, preguntas.c.texto.label("pregunta"), preguntas.c.respuesta_esperada,
                    temas.c.nombre.label("tema"),
                )
                .join(preguntas, preguntas.c.id == respuestas.c.pregunta_id)
                .join(temas, temas.c.id == preguntas.c.tema_id)
                .order_by(respuestas.c.id.desc())
                .limit(limite)
            )
            return [_fila(f) for f in filas]

    def fallos_recientes(self, tema_id: int, limite: int = 3) -> list[str]:
        with self.engine.connect() as c:
            filas = c.execute(
                select(preguntas.c.texto)
                .join(respuestas, respuestas.c.pregunta_id == preguntas.c.id)
                .where(preguntas.c.tema_id == tema_id, respuestas.c.nota < 3)
                .order_by(respuestas.c.id.desc())
                .limit(limite)
            )
            return [str(f[0]) for f in filas]

    # ---- banco DevCards: mazos activos y tarjetas ya introducidas ---------------
    def activar_mazo(self, categoria: str, activo: bool) -> None:
        with self.engine.begin() as c:
            if c.execute(select(mazos.c.categoria).where(mazos.c.categoria == categoria)).first():
                c.execute(update(mazos).where(mazos.c.categoria == categoria).values(activo=1 if activo else 0))
            else:
                c.execute(mazos.insert().values(categoria=categoria, activo=1 if activo else 0, activado_en=ahora()))

    def mazos_activos(self) -> list[str]:
        with self.engine.connect() as c:
            return [str(f[0]) for f in c.execute(select(mazos.c.categoria).where(mazos.c.activo == 1).order_by(mazos.c.activado_en))]

    def refs_introducidas(self) -> set[str]:
        with self.engine.connect() as c:
            return {str(f[0]) for f in c.execute(select(temas.c.ref_externa).where(temas.c.ref_externa.is_not(None)))}

    def introducidas_desde(self, minutos: float) -> int:
        desde = ahora() - timedelta(minutes=minutos)
        with self.engine.connect() as c:
            return int(c.execute(
                select(func.count()).select_from(temas).where(temas.c.origen == "devcards", temas.c.creado >= desde)
            ).scalar_one())

    # ---- bitácora: cada decisión del agente queda registrada ----------------
    def anotar(self, tipo: str, detalle: str) -> None:
        with self.engine.begin() as c:
            c.execute(bitacora.insert().values(fecha=ahora(), tipo=tipo, detalle=detalle[:2000]))

    def leer_bitacora(self, limite: int = 50) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            return [_fila(f) for f in c.execute(select(bitacora).order_by(bitacora.c.id.desc()).limit(limite))]

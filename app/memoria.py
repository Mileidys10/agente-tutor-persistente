# Archivo app/memoria.py: capa de base de datos con SQLAlchemy Core (PostgreSQL en Render o SQLite en local).
# Define las 6 tablas permanentes del agente y todas las operaciones de lectura y escritura.
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
    delete,
    func,
    inspect,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine

# Catálogo de esquemas (MetaData) con las tablas que SQLAlchemy crea automáticamente al arrancar.
metadata = MetaData()

# Tabla de colecciones personalizadas para agrupar apuntes, fragmentos de código o materias.
colecciones = Table(
    "colecciones",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("nombre", String(120), nullable=False),
    Column("descripcion", Text, nullable=False, default=""),
    Column("activa", Integer, nullable=False, default=1),
    Column("creada", DateTime(timezone=True), nullable=False),
)

# Tabla 1: guarda tanto tus temas propios, código, material y DevCards presentadas, junto con su estado SM-2.
temas = Table(
    "temas",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("nombre", String(200), nullable=False),
    Column("notas", Text, nullable=False, default=""),
    Column("origen", String(20), nullable=False, default="usuario"),  # usuario | devcards
    Column("tipo", String(20), nullable=False, default="nota"),  # nota | codigo | devcard | material
    Column("coleccion_id", Integer, ForeignKey("colecciones.id", ondelete="SET NULL"), nullable=True),
    Column("categoria", String(120), nullable=False, default=""),
    Column("ref_externa", String(60), unique=True),  # id de la DevCard (p. ej. "poo-01")
    Column("codigo", Text, nullable=False, default=""),
    Column("lenguaje", String(40), nullable=False, default=""),
    Column("analogia", Text, nullable=False, default=""),
    Column("idea_clave", Text, nullable=False, default=""),
    Column("etiquetas", Text, nullable=False, default=""),
    Column("en_refuerzo", Integer, nullable=False, default=0),
    Column("aciertos_seguidos", Integer, nullable=False, default=0),
    Column("repeticiones", Integer, nullable=False, default=0),
    Column("intervalo_dias", Float, nullable=False, default=0.0),
    Column("facilidad", Float, nullable=False, default=2.5),
    Column("proximo_repaso", DateTime(timezone=True), nullable=False),
    Column("aciertos", Integer, nullable=False, default=0),
    Column("fallos", Integer, nullable=False, default=0),
    Column("creado", DateTime(timezone=True), nullable=False),
)

# Tabla de sesiones de simulacro/examen cronometrado.
sesiones_examen = Table(
    "sesiones_examen",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("titulo", String(160), nullable=False),
    Column("filtro", String(160), nullable=False, default=""),
    Column("total_preguntas", Integer, nullable=False),
    Column("respondidas", Integer, nullable=False, default=0),
    Column("correctas", Integer, nullable=False, default=0),
    Column("nota_promedio", Float, nullable=False, default=0.0),
    Column("estado", String(20), nullable=False, default="activa"),  # activa | completada
    Column("creada", DateTime(timezone=True), nullable=False),
    Column("completada_en", DateTime(timezone=True)),
    Column("resumen_json", Text, nullable=False, default="{}"),
)

# Tabla de relaciones/grafo de prerrequisitos entre temas.
relaciones_temas = Table(
    "relaciones_temas",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("origen_id", Integer, ForeignKey("temas.id", ondelete="CASCADE"), nullable=False),
    Column("destino_id", Integer, ForeignKey("temas.id", ondelete="CASCADE"), nullable=False),
    Column("tipo", String(20), nullable=False, default="prerrequisito"),  # prerrequisito | relacionado
    Column("creado", DateTime(timezone=True), nullable=False),
)

# Tabla 2: cola de preguntas creadas por el agente; quedan en "pendiente" hasta que las respondes.
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
    Column("pistas_usadas", Integer, nullable=False, default=0),
    Column("sesion_examen_id", Integer, ForeignKey("sesiones_examen.id", ondelete="SET NULL"), nullable=True),
    Column("creada", DateTime(timezone=True), nullable=False),
    Column("respondida_en", DateTime(timezone=True)),
)

# Tabla 3: historial permanente de respuestas enviadas, nota obtenida (0-5) y retroalimentación.
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

# Tabla 4: recuerda qué categorías del banco DevCards dejaste activas (1) o pausadas (0).
mazos = Table(  # categorías de DevCards que la persona eligió estudiar
    "mazos",
    metadata,
    Column("categoria", String(120), primary_key=True),
    Column("activo", Integer, nullable=False, default=1),
    Column("activado_en", DateTime(timezone=True), nullable=False),
)

# Tabla 5: diario cronológico de decisiones y eventos del agente; se ve en la sección "Bitácora" de la web.
bitacora = Table(
    "bitacora",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("fecha", DateTime(timezone=True), nullable=False),
    Column("tipo", String(20), nullable=False),  # sistema | ciclo | decision | pregunta | evaluacion | error
    Column("detalle", Text, nullable=False),
)

# Tabla 6: fila única (id=1) que cuenta cuántas veces despertó el servidor y cuántos ciclos ejecutó.
latido = Table(
    "latido",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("primer_arranque", DateTime(timezone=True), nullable=False),
    Column("ultimo_arranque", DateTime(timezone=True), nullable=False),
    Column("ultimo_ciclo", DateTime(timezone=True)),
    Column("ciclos", Integer, nullable=False, default=0),
    Column("arranques", Integer, nullable=False, default=0),
    Column("ultima_notificacion", String(10), nullable=False, default=""),
)

# Tabla 7: registro por fecha UTC para calcular rachas de estudio diarias.
actividad_diaria = Table(
    "actividad_diaria",
    metadata,
    Column("fecha", String(10), primary_key=True),  # YYYY-MM-DD en UTC
    Column("respuestas", Integer, nullable=False, default=0),
    Column("aciertos", Integer, nullable=False, default=0),
    Column("actualizado", DateTime(timezone=True), nullable=False),
)


# Devuelve la hora actual siempre en UTC para evitar desfases entre el servidor de Render y el navegador.
def ahora() -> datetime:
    return datetime.now(timezone.utc)


# Asegura que toda fecha leída de base de datos tenga zona horaria UTC antes de restarla con ahora().
def _utc(valor: Optional[datetime]) -> Optional[datetime]:
    # SQLite devuelve fechas sin zona horaria: se normalizan a UTC.
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


# Convierte una fila SQL en diccionario Python limpio: normaliza fechas, decodifica opciones JSON
# y calcula si la pregunta todavía exige lectura previa.
def _fila(row: Any) -> dict[str, Any]:
    datos = dict(row._mapping)
    for k, v in datos.items():
        if isinstance(v, datetime):
            datos[k] = _utc(v)
    if "opciones" in datos:
        datos["opciones"] = json.loads(datos["opciones"]) if datos["opciones"] else None
    if "requiere_lectura" in datos:  # solo "requiere" mientras no se haya marcado como leída
        datos["requiere_lectura"] = bool(datos["requiere_lectura"]) and datos.get("leida_en") is None
    if "activa" in datos:
        datos["activa"] = bool(datos["activa"])
    if "en_refuerzo" in datos:
        datos["en_refuerzo"] = bool(datos["en_refuerzo"])
    return datos


# Objeto central de persistencia; AgenteTutor (app/agente.py) guarda y lee aquí todo su estado.
class Memoria:
    # Conecta el motor SQLAlchemy, crea las tablas si la base es nueva y aplica migraciones pendientes.
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
            "pistas_usadas": "INTEGER NOT NULL DEFAULT 0",
            "sesion_examen_id": "INTEGER",
        },
        "temas": {
            "tipo": "VARCHAR(20) NOT NULL DEFAULT 'nota'",
            "coleccion_id": "INTEGER",
            "codigo": "TEXT NOT NULL DEFAULT ''",
            "lenguaje": "VARCHAR(40) NOT NULL DEFAULT ''",
            "analogia": "TEXT NOT NULL DEFAULT ''",
            "idea_clave": "TEXT NOT NULL DEFAULT ''",
            "etiquetas": "TEXT NOT NULL DEFAULT ''",
            "en_refuerzo": "INTEGER NOT NULL DEFAULT 0",
            "aciertos_seguidos": "INTEGER NOT NULL DEFAULT 0",
        },
        "latido": {
            "ultima_notificacion": "VARCHAR(10) NOT NULL DEFAULT ''",
        },
    }

    # Inspecciona las tablas existentes y añade solo las columnas nuevas que falten (ALTER TABLE seguro).
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
    # Lo llama AgenteTutor.despertar() al iniciar FastAPI; crea la fila id=1 o suma +1 al contador de arranques.
    def registrar_arranque(self) -> dict[str, Any]:
        t = ahora()
        with self.engine.begin() as c:
            fila = c.execute(select(latido).where(latido.c.id == 1)).first()
            if fila is None:
                c.execute(latido.insert().values(id=1, primer_arranque=t, ultimo_arranque=t, ciclos=0, arranques=1))
            else:
                c.execute(update(latido).where(latido.c.id == 1).values(ultimo_arranque=t, arranques=latido.c.arranques + 1))
        return self.leer_latido()

    # Lo llama AgenteTutor.ciclo() al final de cada ronda autónoma para guardar último ciclo y total acumulado.
    def registrar_ciclo(self) -> None:
        with self.engine.begin() as c:
            c.execute(update(latido).where(latido.c.id == 1).values(ultimo_ciclo=ahora(), ciclos=latido.c.ciclos + 1))

    # Lee el estado del latido para GET /health (main.py) y GET /api/estado (agente.estado).
    def leer_latido(self) -> dict[str, Any]:
        with self.engine.connect() as c:
            fila = c.execute(select(latido).where(latido.c.id == 1)).first()
        return _fila(fila) if fila else {}

    # ---- colecciones personalizadas -----------------------------------------
    def crear_coleccion(self, nombre: str, descripcion: str = "") -> dict[str, Any]:
        limpio = nombre.strip()
        if len(limpio) < 2:
            raise ValueError("El nombre de la colección debe tener al menos 2 caracteres")
        t = ahora()
        with self.engine.begin() as c:
            existe = c.execute(
                select(colecciones.c.id).where(func.lower(colecciones.c.nombre) == limpio.lower())
            ).first()
            if existe:
                raise ValueError(f"Ya existe una colección llamada «{limpio}»")
            cid = c.execute(
                colecciones.insert().values(nombre=limpio[:120], descripcion=descripcion.strip()[:500], activa=1, creada=t)
            ).inserted_primary_key[0]
        return self.obtener_coleccion(int(cid))  # type: ignore[return-value]

    def obtener_coleccion(self, coleccion_id: int) -> Optional[dict[str, Any]]:
        with self.engine.connect() as c:
            fila = c.execute(select(colecciones).where(colecciones.c.id == coleccion_id)).first()
            if not fila:
                return None
            datos = _fila(fila)
            conteo = c.execute(
                select(
                    func.count(temas.c.id).label("total"),
                    func.sum(func.coalesce(temas.c.en_refuerzo, 0)).label("refuerzo"),
                ).where(temas.c.coleccion_id == coleccion_id)
            ).first()
            dominados = c.execute(
                select(func.count(temas.c.id)).where(temas.c.coleccion_id == coleccion_id, temas.c.intervalo_dias >= 6)
            ).scalar_one()
        datos["temas"] = int(conteo.total or 0) if conteo else 0
        datos["en_refuerzo"] = int(conteo.refuerzo or 0) if conteo else 0
        datos["dominados"] = int(dominados or 0)
        return datos

    def obtener_coleccion_por_nombre(self, nombre: str) -> Optional[dict[str, Any]]:
        limpio = nombre.strip()
        if not limpio:
            return None
        with self.engine.connect() as c:
            fila = c.execute(select(colecciones.c.id).where(func.lower(colecciones.c.nombre) == limpio.lower())).first()
        return self.obtener_coleccion(int(fila[0])) if fila else None

    def obtener_o_crear_coleccion(self, nombre: str, descripcion: str = "") -> dict[str, Any]:
        existente = self.obtener_coleccion_por_nombre(nombre)
        if existente is not None:
            return existente
        return self.crear_coleccion(nombre, descripcion)

    def listar_colecciones(self) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            filas = c.execute(select(colecciones).order_by(colecciones.c.id.asc())).all()
            todos_temas = c.execute(
                select(temas.c.coleccion_id, temas.c.intervalo_dias, temas.c.en_refuerzo)
                .where(temas.c.coleccion_id.is_not(None))
            ).all()
        totales: dict[int, int] = {}
        dominados: dict[int, int] = {}
        refuerzos: dict[int, int] = {}
        for cid, intervalo, ref in todos_temas:
            k = int(cid)
            totales[k] = totales.get(k, 0) + 1
            if float(intervalo or 0) >= 6:
                dominados[k] = dominados.get(k, 0) + 1
            if ref:
                refuerzos[k] = refuerzos.get(k, 0) + 1
        resultado = []
        for f in filas:
            d = _fila(f)
            cid = int(d["id"])
            d["temas"] = totales.get(cid, 0)
            d["dominados"] = dominados.get(cid, 0)
            d["en_refuerzo"] = refuerzos.get(cid, 0)
            resultado.append(d)
        return resultado

    def actualizar_coleccion(
        self, coleccion_id: int, nombre: Optional[str] = None,
        descripcion: Optional[str] = None, activa: Optional[bool] = None,
    ) -> dict[str, Any]:
        valores: dict[str, Any] = {}
        with self.engine.begin() as c:
            actual = c.execute(select(colecciones).where(colecciones.c.id == coleccion_id)).first()
            if actual is None:
                raise LookupError("No existe esa colección")
            if nombre is not None:
                limpio = nombre.strip()
                if len(limpio) < 2:
                    raise ValueError("El nombre de la colección debe tener al menos 2 caracteres")
                dup = c.execute(
                    select(colecciones.c.id).where(
                        func.lower(colecciones.c.nombre) == limpio.lower(),
                        colecciones.c.id != coleccion_id,
                    )
                ).first()
                if dup:
                    raise ValueError(f"Ya existe una colección llamada «{limpio}»")
                valores["nombre"] = limpio[:120]
            if descripcion is not None:
                valores["descripcion"] = descripcion.strip()[:500]
            if activa is not None:
                valores["activa"] = 1 if activa else 0
            if valores:
                c.execute(update(colecciones).where(colecciones.c.id == coleccion_id).values(**valores))
        return self.obtener_coleccion(coleccion_id)  # type: ignore[return-value]

    def borrar_coleccion(self, coleccion_id: int, borrar_temas: bool = False) -> bool:
        with self.engine.begin() as c:
            existe = c.execute(select(colecciones.c.id).where(colecciones.c.id == coleccion_id)).first()
            if not existe:
                return False
            ids_temas = [int(r[0]) for r in c.execute(select(temas.c.id).where(temas.c.coleccion_id == coleccion_id)).all()]
            if borrar_temas and ids_temas:
                ids_preg = select(preguntas.c.id).where(preguntas.c.tema_id.in_(ids_temas))
                c.execute(respuestas.delete().where(respuestas.c.pregunta_id.in_(ids_preg)))
                c.execute(preguntas.delete().where(preguntas.c.tema_id.in_(ids_temas)))
                c.execute(temas.delete().where(temas.c.coleccion_id == coleccion_id))
            elif ids_temas:
                c.execute(update(temas).where(temas.c.coleccion_id == coleccion_id).values(coleccion_id=None))
            c.execute(delete(colecciones).where(colecciones.c.id == coleccion_id))
            return True

    # ---- temas --------------------------------------------------------------
    # Inserta un tema propio (origen="usuario", rechazando duplicados en la misma colección) o una DevCard nueva.
    # Lo llaman AgenteTutor.agregar_tema(), estudiar_codigo(), ingestar_material() y el ciclo autónomo.
    def crear_tema(
        self, nombre: str, notas: str, origen: str = "usuario", categoria: str = "",
        ref_externa: Optional[str] = None, tipo: str = "nota", coleccion_id: Optional[int] = None,
        codigo: str = "", lenguaje: str = "", analogia: str = "", idea_clave: str = "", etiquetas: str = "",
    ) -> dict[str, Any]:
        t = ahora()
        with self.engine.begin() as c:
            if origen == "usuario":
                cond_col = temas.c.coleccion_id.is_(None) if coleccion_id is None else temas.c.coleccion_id == coleccion_id
                existe = c.execute(
                    select(temas.c.id).where(
                        temas.c.origen == "usuario",
                        cond_col,
                        func.lower(temas.c.nombre) == nombre.lower(),
                    )
                ).first()
                if existe:
                    raise ValueError(f"Ya existe un tema llamado «{nombre}»")
            tid = c.execute(
                temas.insert().values(
                    nombre=nombre[:200], notas=notas, origen=origen, tipo=tipo,
                    coleccion_id=coleccion_id, categoria=categoria, ref_externa=ref_externa,
                    codigo=codigo, lenguaje=lenguaje[:40], analogia=analogia, idea_clave=idea_clave,
                    etiquetas=etiquetas, en_refuerzo=0, aciertos_seguidos=0,
                    repeticiones=0, intervalo_dias=0.0, facilidad=2.5,
                    proximo_repaso=t, aciertos=0, fallos=0, creado=t,
                )
            ).inserted_primary_key[0]
        return self.obtener_tema(int(tid))  # type: ignore[return-value]

    # Busca un tema por su ID; lo usa AgenteTutor.responder() antes de recalcular SM-2.
    def obtener_tema(self, tema_id: int) -> Optional[dict[str, Any]]:
        with self.engine.connect() as c:
            fila = c.execute(select(temas).where(temas.c.id == tema_id)).first()
        return _fila(fila) if fila else None

    # Devuelve todos los temas ordenados por próximo repaso; sirve para GET /api/temas, ciclo() y progreso().
    def listar_temas(self) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            return [_fila(f) for f in c.execute(select(temas).order_by(temas.c.proximo_repaso))]

    def buscar_temas(
        self, q: str = "", coleccion_id: Optional[int] = None, tipo: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        stmt = select(temas)
        if coleccion_id is not None:
            stmt = stmt.where(temas.c.coleccion_id == coleccion_id)
        if tipo:
            stmt = stmt.where(temas.c.tipo == tipo.strip())
        termino = q.strip().lower()
        if termino:
            patron = f"%{termino}%"
            stmt = stmt.where(
                or_(
                    func.lower(temas.c.nombre).like(patron),
                    func.lower(temas.c.notas).like(patron),
                    func.lower(temas.c.etiquetas).like(patron),
                    func.lower(temas.c.lenguaje).like(patron),
                    func.lower(temas.c.categoria).like(patron),
                )
            )
        with self.engine.connect() as c:
            return [_fila(f) for f in c.execute(stmt.order_by(temas.c.proximo_repaso))]

    def actualizar_tema(self, tema_id: int, **campos: Any) -> dict[str, Any]:
        permitidos = {
            "nombre", "notas", "codigo", "lenguaje", "analogia",
            "idea_clave", "etiquetas", "coleccion_id", "tipo", "en_refuerzo", "proximo_repaso",
        }
        valores: dict[str, Any] = {}
        for k, v in campos.items():
            if k not in permitidos or v is None and k != "coleccion_id":
                continue
            if k == "nombre":
                limpio = str(v).strip()
                if len(limpio) < 2:
                    raise ValueError("El nombre del tema debe tener al menos 2 caracteres")
                valores[k] = limpio[:200]
            elif k == "lenguaje":
                valores[k] = str(v).strip()[:40]
            elif k == "en_refuerzo":
                valores[k] = 1 if v else 0
            else:
                valores[k] = v
        with self.engine.begin() as c:
            actual = c.execute(select(temas).where(temas.c.id == tema_id)).first()
            if actual is None:
                raise LookupError("No existe ese tema")
            if valores:
                c.execute(update(temas).where(temas.c.id == tema_id).values(**valores))
        return self.obtener_tema(tema_id)  # type: ignore[return-value]

    def marcar_refuerzo(self, tema_id: int, en_refuerzo: bool) -> None:
        with self.engine.begin() as c:
            c.execute(
                update(temas)
                .where(temas.c.id == tema_id)
                .values(en_refuerzo=1 if en_refuerzo else 0, aciertos_seguidos=0 if en_refuerzo else temas.c.aciertos_seguidos)
            )

    # Elimina un tema junto con sus preguntas y respuestas (DELETE /api/temas/{id} en app/main.py).
    def borrar_tema(self, tema_id: int) -> bool:
        with self.engine.begin() as c:  # borrado explícito en cascada (SQLite no aplica ON DELETE por defecto)
            c.execute(
                relaciones_temas.delete().where(
                    or_(relaciones_temas.c.origen_id == tema_id, relaciones_temas.c.destino_id == tema_id)
                )
            )
            ids = select(preguntas.c.id).where(preguntas.c.tema_id == tema_id)
            c.execute(respuestas.delete().where(respuestas.c.pregunta_id.in_(ids)))
            c.execute(preguntas.delete().where(preguntas.c.tema_id == tema_id))
            return c.execute(temas.delete().where(temas.c.id == tema_id)).rowcount > 0

    # Guarda los nuevos valores SM-2 y suma +1 en aciertos o fallos; lo llama AgenteTutor.responder().
    def actualizar_repaso(
        self, tema_id: int, repeticiones: int, intervalo_dias: float, facilidad: float,
        proximo_repaso: datetime, acierto: bool, nota: Optional[int] = None,
    ) -> dict[str, Any]:
        buen_acierto = (nota >= 4) if nota is not None else acierto
        with self.engine.begin() as c:
            actual = c.execute(
                select(temas.c.aciertos_seguidos, temas.c.en_refuerzo).where(temas.c.id == tema_id)
            ).first()
            seguidos_prev = int(actual.aciertos_seguidos or 0) if actual else 0
            refuerzo_prev = bool(actual.en_refuerzo) if actual else False
            seguidos = seguidos_prev + 1 if buen_acierto else 0
            supero_refuerzo = refuerzo_prev and seguidos >= 2
            nuevo_refuerzo = 0 if supero_refuerzo else (1 if refuerzo_prev else 0)
            c.execute(
                update(temas).where(temas.c.id == tema_id).values(
                    repeticiones=repeticiones, intervalo_dias=intervalo_dias, facilidad=facilidad,
                    proximo_repaso=proximo_repaso,
                    aciertos=temas.c.aciertos + (1 if acierto else 0),
                    fallos=temas.c.fallos + (0 if acierto else 1),
                    aciertos_seguidos=seguidos,
                    en_refuerzo=nuevo_refuerzo,
                )
            )
        return {"supero_refuerzo": supero_refuerzo, "aciertos_seguidos": seguidos}

    # ---- preguntas y respuestas ---------------------------------------------
    # Guarda en la tabla preguntas una nueva pregunta pendiente creada por AgenteTutor._preparar_pregunta().
    def crear_pregunta(
        self, tema_id: int, texto: str, esperada: str, motivo: str, fuente: str,
        opciones: Optional[list[str]] = None, explicacion: str = "", requiere_lectura: bool = False,
        sesion_examen_id: Optional[int] = None,
    ) -> dict[str, Any]:
        with self.engine.begin() as c:
            pid = c.execute(
                preguntas.insert().values(
                    tema_id=tema_id, texto=texto, respuesta_esperada=esperada, motivo=motivo,
                    estado="pendiente", fuente=fuente, creada=ahora(),
                    opciones=json.dumps(opciones, ensure_ascii=False) if opciones else None, explicacion=explicacion,
                    requiere_lectura=1 if requiere_lectura else 0,
                    pistas_usadas=0,
                    sesion_examen_id=sesion_examen_id,
                )
            ).inserted_primary_key[0]
        return self.obtener_pregunta(int(pid))  # type: ignore[return-value]

    # Consulta una pregunta unida con los metadatos de su tema (usada en responder, marcar_leida y lectura_de).
    def obtener_pregunta(self, pregunta_id: int) -> Optional[dict[str, Any]]:
        with self.engine.connect() as c:
            fila = c.execute(
                select(
                    preguntas,
                    temas.c.nombre.label("tema"),
                    temas.c.origen,
                    temas.c.tipo,
                    temas.c.coleccion_id,
                    temas.c.categoria,
                    temas.c.ref_externa,
                    temas.c.notas,
                    temas.c.codigo,
                    temas.c.lenguaje,
                    temas.c.analogia,
                    temas.c.idea_clave,
                    temas.c.en_refuerzo,
                )
                .join(temas, temas.c.id == preguntas.c.tema_id)
                .where(preguntas.c.id == pregunta_id)
            ).first()
        return _fila(fila) if fila else None

    # Lista todas las preguntas sin responder en orden de creación; alimenta /api/preguntas/pendientes, MCP y ciclo().
    def pendientes(self) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            filas = c.execute(
                select(
                    preguntas,
                    temas.c.nombre.label("tema"),
                    temas.c.origen,
                    temas.c.tipo,
                    temas.c.coleccion_id,
                    temas.c.categoria,
                    temas.c.ref_externa,
                    temas.c.notas,
                    temas.c.codigo,
                    temas.c.lenguaje,
                    temas.c.analogia,
                    temas.c.idea_clave,
                    temas.c.en_refuerzo,
                )
                .join(temas, temas.c.id == preguntas.c.tema_id)
                .where(preguntas.c.estado == "pendiente")
                .order_by(preguntas.c.creada)
            )
            return [_fila(f) for f in filas]

    # Registra cuándo se pulsó "Ya la leí" en la columna leida_en; lo llama AgenteTutor.marcar_leida().
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

    # Marca la pregunta como "respondida" de forma atómica (evita doble respuesta) e inserta el registro en respuestas.
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

    # Lee las últimas respuestas evaluadas con su pregunta y tema para GET /api/historial (web).
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

    # Busca las últimas preguntas donde obtuviste nota < 3 en un tema para que Gemini pregunte desde otro ángulo.
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
    # Activa o pausa una categoría de DevCards en la tabla mazos (PUT /api/mazos/{categoria} y MCP activar_mazo).
    def activar_mazo(self, categoria: str, activo: bool) -> None:
        with self.engine.begin() as c:
            if c.execute(select(mazos.c.categoria).where(mazos.c.categoria == categoria)).first():
                c.execute(update(mazos).where(mazos.c.categoria == categoria).values(activo=1 if activo else 0))
            else:
                c.execute(mazos.insert().values(categoria=categoria, activo=1 if activo else 0, activado_en=ahora()))

    # Devuelve la lista de nombres de categorías actualmente activas para que agente.ciclo() tome tarjetas nuevas.
    def mazos_activos(self) -> list[str]:
        with self.engine.connect() as c:
            return [str(f[0]) for f in c.execute(select(mazos.c.categoria).where(mazos.c.activo == 1).order_by(mazos.c.activado_en))]

    # Devuelve el conjunto de IDs de DevCards que ya pasaron a temas (para no repetir tarjetas nuevas).
    def refs_introducidas(self) -> set[str]:
        with self.engine.connect() as c:
            return {str(f[0]) for f in c.execute(select(temas.c.ref_externa).where(temas.c.ref_externa.is_not(None)))}

    # Cuenta cuántas DevCards nuevas se presentaron en el "día" actual (ventana de minutos_por_dia minutos).
    def introducidas_desde(self, minutos: float) -> int:
        desde = ahora() - timedelta(minutes=minutos)
        with self.engine.connect() as c:
            return int(c.execute(
                select(func.count()).select_from(temas).where(temas.c.origen == "devcards", temas.c.creado >= desde)
            ).scalar_one())

    # ---- bitácora: cada decisión del agente queda registrada ----------------
    # Escribe una línea en el diario de decisiones del agente; la web y MCP la muestran después.
    def anotar(self, tipo: str, detalle: str) -> None:
        with self.engine.begin() as c:
            c.execute(bitacora.insert().values(fecha=ahora(), tipo=tipo, detalle=detalle[:2000]))

    # Lee las últimas entradas de bitacora empezando por la más reciente (GET /api/bitacora y MCP ver_bitacora).
    def leer_bitacora(self, limite: int = 50) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            return [_fila(f) for f in c.execute(select(bitacora).order_by(bitacora.c.id.desc()).limit(limite))]

    # ---- actividad diaria y rachas ------------------------------------------
    def registrar_actividad_diaria(self, acierto: bool, fecha_dt: Optional[datetime] = None) -> None:
        momento = _utc(fecha_dt) or ahora()
        clave = momento.strftime("%Y-%m-%d")
        with self.engine.begin() as c:
            fila = c.execute(select(actividad_diaria).where(actividad_diaria.c.fecha == clave)).first()
            if fila is None:
                c.execute(
                    actividad_diaria.insert().values(
                        fecha=clave, respuestas=1, aciertos=1 if acierto else 0, actualizado=momento
                    )
                )
            else:
                c.execute(
                    update(actividad_diaria)
                    .where(actividad_diaria.c.fecha == clave)
                    .values(
                        respuestas=actividad_diaria.c.respuestas + 1,
                        aciertos=actividad_diaria.c.aciertos + (1 if acierto else 0),
                        actualizado=momento,
                    )
                )

    def calcular_racha_dias(self, hoy_dt: Optional[datetime] = None) -> int:
        ref = (_utc(hoy_dt) or ahora()).date()
        with self.engine.connect() as c:
            fechas = {
                str(r[0])
                for r in c.execute(select(actividad_diaria.c.fecha).where(actividad_diaria.c.respuestas > 0)).all()
            }
        if not fechas:
            return 0
        cursor = ref if ref.isoformat() in fechas else ref - timedelta(days=1)
        racha = 0
        while cursor.isoformat() in fechas:
            racha += 1
            cursor = cursor - timedelta(days=1)
        return racha

    def actividad_de_hoy(self, hoy_dt: Optional[datetime] = None) -> dict[str, int]:
        clave = (_utc(hoy_dt) or ahora()).strftime("%Y-%m-%d")
        with self.engine.connect() as c:
            fila = c.execute(select(actividad_diaria).where(actividad_diaria.c.fecha == clave)).first()
        if not fila:
            return {"respuestas": 0, "aciertos": 0}
        return {"respuestas": int(fila.respuestas or 0), "aciertos": int(fila.aciertos or 0)}

    def registrar_notificacion(self, fecha_str: str) -> None:
        with self.engine.begin() as c:
            c.execute(update(latido).where(latido.c.id == 1).values(ultima_notificacion=fecha_str[:10]))

    # ---- pistas progresivas, relaciones de temas y simulacros (v3.0) --------
    def incrementar_pistas(self, pregunta_id: int) -> int:
        with self.engine.begin() as c:
            fila = c.execute(
                select(preguntas.c.estado, preguntas.c.pistas_usadas).where(preguntas.c.id == pregunta_id)
            ).first()
            if fila is None:
                raise LookupError("No existe esa pregunta")
            if fila.estado != "pendiente":
                raise ValueError("La pregunta ya fue respondida")
            actual = int(fila.pistas_usadas or 0)
            nuevo = min(3, actual + 1)
            if nuevo != actual:
                c.execute(update(preguntas).where(preguntas.c.id == pregunta_id).values(pistas_usadas=nuevo))
            return nuevo

    def crear_relacion(self, origen_id: int, destino_id: int, tipo: str = "prerrequisito") -> dict[str, Any]:
        if origen_id == destino_id:
            raise ValueError("Un tema no puede ser prerrequisito de sí mismo")
        tipo_limpio = tipo.strip().lower()
        if tipo_limpio not in ("prerrequisito", "relacionado"):
            raise ValueError("El tipo debe ser 'prerrequisito' o 'relacionado'")
        with self.engine.begin() as c:
            if not c.execute(select(temas.c.id).where(temas.c.id == origen_id)).first():
                raise LookupError(f"No existe el tema origen {origen_id}")
            if not c.execute(select(temas.c.id).where(temas.c.id == destino_id)).first():
                raise LookupError(f"No existe el tema destino {destino_id}")
            dup = c.execute(
                select(relaciones_temas.c.id).where(
                    relaciones_temas.c.origen_id == origen_id,
                    relaciones_temas.c.destino_id == destino_id,
                    relaciones_temas.c.tipo == tipo_limpio,
                )
            ).first()
            if dup:
                return _fila(c.execute(select(relaciones_temas).where(relaciones_temas.c.id == dup[0])).first())
            if tipo_limpio == "prerrequisito":
                ciclo = c.execute(
                    select(relaciones_temas.c.id).where(
                        relaciones_temas.c.origen_id == destino_id,
                        relaciones_temas.c.destino_id == origen_id,
                        relaciones_temas.c.tipo == "prerrequisito",
                    )
                ).first()
                if ciclo:
                    raise ValueError("Ciclo detectado: el tema destino ya es prerrequisito del origen")
            rid = c.execute(
                relaciones_temas.insert().values(
                    origen_id=origen_id, destino_id=destino_id, tipo=tipo_limpio, creado=ahora()
                )
            ).inserted_primary_key[0]
            fila = c.execute(select(relaciones_temas).where(relaciones_temas.c.id == rid)).first()
            return _fila(fila)

    def listar_relaciones(self, tema_id: Optional[int] = None) -> list[dict[str, Any]]:
        stmt = select(relaciones_temas)
        if tema_id is not None:
            stmt = stmt.where(
                or_(relaciones_temas.c.origen_id == tema_id, relaciones_temas.c.destino_id == tema_id)
            )
        with self.engine.connect() as c:
            return [_fila(f) for f in c.execute(stmt.order_by(relaciones_temas.c.id.asc()))]

    def borrar_relacion(self, relacion_id: int) -> bool:
        with self.engine.begin() as c:
            return c.execute(relaciones_temas.delete().where(relaciones_temas.c.id == relacion_id)).rowcount > 0

    def crear_sesion_examen(self, titulo: str, filtro: str, total_preguntas: int) -> dict[str, Any]:
        with self.engine.begin() as c:
            sid = c.execute(
                sesiones_examen.insert().values(
                    titulo=titulo.strip()[:160] or "Simulacro",
                    filtro=filtro.strip()[:160],
                    total_preguntas=total_preguntas,
                    respondidas=0,
                    correctas=0,
                    nota_promedio=0.0,
                    estado="activa",
                    creada=ahora(),
                    resumen_json=json.dumps({"fallados": []}, ensure_ascii=False),
                )
            ).inserted_primary_key[0]
        return self.obtener_sesion_examen(int(sid))  # type: ignore[return-value]

    def obtener_sesion_examen(self, sesion_id: int) -> Optional[dict[str, Any]]:
        with self.engine.connect() as c:
            fila = c.execute(select(sesiones_examen).where(sesiones_examen.c.id == sesion_id)).first()
        if not fila:
            return None
        d = _fila(fila)
        try:
            d["resumen"] = json.loads(d.get("resumen_json") or "{}")
        except json.JSONDecodeError:
            d["resumen"] = {}
        return d

    def listar_sesiones_examen(self, limite: int = 10) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            filas = c.execute(select(sesiones_examen).order_by(sesiones_examen.c.id.desc()).limit(limite)).all()
        res = []
        for f in filas:
            d = _fila(f)
            try:
                d["resumen"] = json.loads(d.get("resumen_json") or "{}")
            except json.JSONDecodeError:
                d["resumen"] = {}
            res.append(d)
        return res

    def registrar_avance_examen(self, sesion_id: int, nota: int, tema_nombre: str) -> Optional[dict[str, Any]]:
        with self.engine.begin() as c:
            fila = c.execute(select(sesiones_examen).where(sesiones_examen.c.id == sesion_id)).first()
            if fila is None:
                return None
            resp_prev = int(fila.respondidas or 0)
            corr_prev = int(fila.correctas or 0)
            prom_prev = float(fila.nota_promedio or 0.0)
            total = int(fila.total_preguntas or 1)
            nuevo_resp = resp_prev + 1
            nuevo_corr = corr_prev + (1 if nota >= 3 else 0)
            nuevo_prom = round(((prom_prev * resp_prev) + nota) / nuevo_resp, 2)
            try:
                resumen = json.loads(fila.resumen_json or "{}")
            except json.JSONDecodeError:
                resumen = {}
            fallados = list(resumen.get("fallados") or [])
            if nota < 3 and tema_nombre not in fallados:
                fallados.append(tema_nombre)
            resumen["fallados"] = fallados
            completo = nuevo_resp >= total
            c.execute(
                update(sesiones_examen)
                .where(sesiones_examen.c.id == sesion_id)
                .values(
                    respondidas=nuevo_resp,
                    correctas=nuevo_corr,
                    nota_promedio=nuevo_prom,
                    estado="completada" if completo else "activa",
                    completada_en=ahora() if completo else fila.completada_en,
                    resumen_json=json.dumps(resumen, ensure_ascii=False),
                )
            )
        return self.obtener_sesion_examen(sesion_id)

# PRD v2.0 — Aprende lo que Construyes (Agente Tutor Persistente & MCP Universal)

**Versión:** 2.0 (Especificación y Hoja de Ruta)  
**Repositorio:** `Mileidys10/agente-tutor-persistente`  
**Fecha:** 2026-11-26  
**Estado:** Implementado y verificado (v2.0.0)

---

## 1. Visión y Problema (El Dolor)

### El dolor real
1. **La "amnesia del vibe-coding"**: Hoy los desarrolladores generan funciones, endpoints, consultas SQL o algoritmos completos con asistentes de IA (Claude Code, Cursor, Antigravity, Codex), los copian al proyecto y a los dos días olvidan cómo funcionan, por qué se eligió ese patrón o qué casos borde manejan.
2. **Estudio fragmentado sin memoria ni repetición espaciada**: Cuando una persona toma apuntes en clase, lee documentación técnica o resume un libro en Markdown, los chats de IA tradicionales olvidan todo al cerrar la pestaña y no agendan repasos reales basados en olvido.
3. **Limitación de la v1.1 actual**:
   - El banco fijo de `1 295` DevCards (`app/data/devcards.json`) cuenta con lectura previa rica (`titulo`, `definicion`, `analogia`, `codigo`, `idea_clave`), pero los temas propios (`origen="usuario"`) en `app/agente.py::lectura_de()` devuelven `None` y solo aceptan un `nombre` + `notas` planas.
   - El servidor MCP (`app/mcp_tools.py`) expone únicamente 9 *Tools*; todavía no expone **Resources (`@mcp.resource`)**, **Prompts (`@mcp.prompt`)** ni herramientas nativas para capturar código generado o material libre y transformarlo automáticamente en fichas de estudio.
   - El ciclo autónomo (`percibir → decidir → actuar`) no detecta aún brechas recurrentes (*leeches*) ni activa refuerzo guiado automático.

### Visión v2.0
Convertir al **Agente Tutor Persistente** en un **compañero de aprendizaje universal y servidor MCP de primera clase** bajo el lema: **«Aprende lo que construyes y domina cualquier tema que quieras estudiar»**.

---

## 2. Los 4 Pilares de la Versión 2.0

### Pilar 1 — Estudia lo que construyes (*Code-to-Study*)
Cualquier fragmento de código escrito por el usuario o recién generado por un asistente de IA en su IDE puede enviarse al tutor (vía MCP o desde la Web) para descomponerse en **fichas atómicas de código** con:
- Bloque de código (`codigo`) y lenguaje (`lenguaje`),
- Explicación clara, analogía y concepto clave (`analogia`, `idea_clave`),
- Lectura previa obligatoria la primera vez (`requiere_lectura`),
- Rotación de estilos de pregunta: **explica el código**, **predice la salida / traza**, **detecta el error / caso borde** y **completa el concepto**.

### Pilar 2 — Aprende cualquier cosa (*Ingesta Universal y Colecciones*)
Además del banco fijo de DevCards, el estudiante puede organizar su aprendizaje en **colecciones personalizadas** (`colecciones`: ej. *"Backend FastAPI"*, *"Parcial Bases de Datos"*, *"Inglés B2"*, *"Patrones de Diseño"*):
- Ingestar apuntes largos, resúmenes en Markdown o textos de estudio (`ingestar_material`), dividiéndolos automáticamente en múltiples fichas atómicas listas para SM-2.
- Buscar, editar, posponer, activar/pausar, exportar e importar mazos en **JSON** y **Markdown**.

### Pilar 3 — Servidor MCP Nativo Completo (*MCP-First*)
Aprovechar los tres pilares oficiales de `mcp==2.3.0` (`MCPServer` en `app/mcp_tools.py`) para que cualquier cliente compatible (Claude Desktop, Claude Code, Cursor, Antigravity, Gemini CLI, Codex) interactúe de forma natural:
1. **Tools (19 herramientas totales)**: las 9 actuales + 10 nuevas (`estudiar_codigo`, `ingestar_material`, `gestionar_coleccion`, `buscar_temas`, `editar_tema`, `borrar_tema`, `posponer_tema`, `diagnosticar_brechas`, `exportar_mazo`, `importar_mazo`), **todas** declarando explícitamente las 4 banderas booleanas de `ToolAnnotations` (`read_only_hint`, `destructive_hint`, `idempotent_hint`, `open_world_hint`) y probadas al 100% para mantener calificación máxima en **M8ven Trust Index**.
2. **Resources (`@mcp.resource`)**: 6 recursos de contexto vivo (`tutor://estado`, `tutor://pendientes`, `tutor://colecciones`, `tutor://tema/{tema_id}`, `tutor://brechas`, `tutor://bitacora/reciente`).
3. **Prompts (`@mcp.prompt`)**: 5 flujos pedagógicos reutilizables (`sesion_repaso`, `aprender_codigo_generado`, `ingestar_apuntes`, `tutor_socratico`, `resumen_semanal`).
4. **Empaquetado CLI**: `pyproject.toml` con punto de entrada `agente-tutor-mcp` para instalación y ejecución local inmediata.

### Pilar 4 — Agente Persistente Autónomo v2 (`Percibir → Reflexionar → Decidir → Actuar`)
El bucle de `AgenteTutor` añade una fase explícita de **Reflexión**:
- Detecta temas con dificultades persistentes (`fallos >= 3` o `facilidad <= 1.6`), los marca en refuerzo (`en_refuerzo = 1`), anota una entrada `reflexion` en `bitacora`, reactiva la lectura guiada previa y cambia el ángulo de la siguiente pregunta.
- Registra **rachas diarias** (`actividad_diaria`) y metas de repaso sin perder compatibilidad con PostgreSQL en Render ni SQLite en local.

---

## 3. Mapa de Capacidades (Phase 0 — Capability Map)

| Module ID | Responsabilidad | Depende de |
|---|---|---|
| `modelo-colecciones-fichas` | Tablas `colecciones` y `actividad_diaria`, columnas enriquecidas en `temas`, migración segura `_migrar()`, CRUD de colecciones, búsqueda/edición/posposición, `lectura_de()` unificada y exportación/importación JSON/Markdown. | — |
| `ingesta-codigo-y-material` | Módulo `app/ingesta.py` + extensiones en `app/cerebro.py` y `AgenteTutor` para descomponer código y material libre/Markdown con Gemini y respaldo determinista local 100% funcional sin API key. | `modelo-colecciones-fichas` |
| `mcp-nativo-completo` | 10 nuevas Tools con `ToolAnnotations`, 6 Resources, 5 Prompts en `app/mcp_tools.py`, empaquetado `pyproject.toml` (`agente-tutor-mcp`), cobertura 100% en tests y guía `docs/CONECTAR_MCP.md`. | `modelo-colecciones-fichas`, `ingesta-codigo-y-material` |
| `agente-autonomo-v2` | Fase `reflexionar` en `AgenteTutor.ciclo()`, detección de brechas/leeches, refuerzo automático, racha diaria (`racha_dias`) y diagnóstico proactivo (`/api/brechas`). | `modelo-colecciones-fichas`, `ingesta-codigo-y-material` |
| `interfaz-estudio-v2` | Actualización de `app/static/` (`index.html`, `app.js`, `estilos.css`, `privacidad.html`) con formularios de código y material, colecciones, panel de brechas/racha, búsqueda/edición y exportar/importar cumpliendo WCAG 2.1 AA. | `modelo-colecciones-fichas`, `ingesta-codigo-y-material`, `agente-autonomo-v2` |

**Orden de construcción:** `modelo-colecciones-fichas` → `ingesta-codigo-y-material` → (`mcp-nativo-completo` ‖ `agente-autonomo-v2`) → `interfaz-estudio-v2`.

---

## 4. Stack Tecnológico y Comandos

- **Stack base (sin añadir dependencias pesadas innecesarias)**:
  - Python 3.12+ (entorno actual `.venv` con Python 3.14.3)
  - `fastapi==0.165.0`, `uvicorn[standard]==0.54.0`
  - `SQLAlchemy==2.1.9`, `psycopg[binary]==3.3.9` (PostgreSQL en Render / SQLite en local)
  - `httpx==0.28.1`, `mcp==2.3.0`, `pydantic==2.14.4`
  - `pytest==9.2.0` (`requirements-dev.txt`)
- **Comandos estándar del proyecto**:
  - **Ejecutar pruebas completas**: `.\.venv\Scripts\python -m pytest -v` (en Linux/CI: `python -m pytest -q`)
  - **Levantar servidor web + hilo autónomo + `/mcp`**: `.\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`
  - **Levantar servidor MCP por stdio**: `.\.venv\Scripts\python -m app.mcp_tools` (y en v2 tras empaquetado: `agente-tutor-mcp`)
  - **Levantar stack Docker (App + PostgreSQL 16)**: `docker compose up --build`

---

## 5. Estructura de Archivos (Actual y Proyectada en v2.0)

```text
app/
├── __init__.py
├── agente.py          # Ciclo Percibir-Reflexionar-Decidir-Actuar, SM-2, lectura_de() unificada
├── banco_devcards.py  # Catálogo de solo lectura (1 295 DevCards)
├── cerebro.py         # Motor dual Gemini + local determinista (preguntas, evaluación, descomposición)
├── config.py          # Configuración por variables de entorno
├── ingesta.py         # [NUEVO v2] Parser determinista local de código, Markdown y texto libre
├── main.py            # FastAPI REST + archivos estáticos + montaje /mcp
├── mcp_tools.py       # Servidor MCP completo: Tools, Resources y Prompts
├── memoria.py         # Esquema SQLAlchemy Core + migración segura _migrar()
├── sm2.py             # Algoritmo puro SuperMemo 2
├── data/devcards.json # 1 295 DevCards (MIT)
└── static/            # index.html, app.js, estilos.css, privacidad.html
docs/                  # PRD_V2.md, CASOS_DE_USO.md, CASOS_DE_USO_V2.md, CONTRATO_API.md, CONECTAR_MCP.md, COMO_FUNCIONA.md
tasks/                 # plan.md, todo.md
tests/                 # test_nucleo.py, test_api.py, test_ingesta.py, test_mcp_v2.py
pyproject.toml         # [NUEVO v2] Metadatos de paquete y script CLI agente-tutor-mcp
```

---

## 6. Estrategia de Pruebas y Seguridad

### Estrategia de pruebas
1. **Unitarias y de dominio (`tests/test_nucleo.py`, `tests/test_ingesta.py`)**:
   - Migración de base de datos v1.1 → v2.0 conservando todos los datos previos sin pérdida.
   - Descomposición de código (Python, JS/TS, SQL, genérico) y de Markdown tanto con respuestas simuladas de Gemini como en modo 100% local determinista.
   - Detección de brechas (*leeches*) y cálculo de rachas diarias.
2. **API y Seguridad (`tests/test_api.py`)**:
   - Protección de todas las rutas de escritura y `/mcp` con `TUTOR_TOKEN` (`401` si falta o es inválido).
   - Validación estricta de tamaños Pydantic (`422`) y rechazo de duplicados (`409`).
3. **Cobertura MCP 100% (`tests/test_mcp_v2.py`)**:
   - Cada herramienta MCP verificada por nombre (requisitos M8ven) y validando que sus 4 hints en `ToolAnnotations` sean booleanos explícitos.
   - Pruebas funcionales de los 6 Resources y 5 Prompts vía `MCPServer`.

### Seguridad, Privacidad y Compliance (20 Directivas)
- **Aislamiento de prompts**: todo código o apunte de usuario enviado a Gemini irá delimitado en etiquetas `<codigo>` / `<material>` indicando explícitamente que es material de estudio y no instrucciones ejecutables.
- **Sin SSRF**: la v2.0 procesa código, texto y Markdown pegados o enviados por herramienta/API; no realiza descargas HTTP automáticas a URLs arbitrarias ingresadas por usuarios.
- **Cero secretos en el repo**: `GEMINI_API_KEY` y `TUTOR_TOKEN` únicamente en entorno; nunca en código ni logs.
- **Portabilidad y Derecho al Olvido**: exportación completa en JSON/Markdown, borrado en cascada por tema o colección, y `/privacidad` actualizada.
- **Accesibilidad WCAG 2.1 AA**: contraste mínimo `4.5:1`, navegación completa por teclado, foco visible, bloques `<pre><code>` con desplazamiento propio y construcción DOM segura usando `textContent` (cero `innerHTML` con contenido de usuario).

---

## 7. Límites Operativos (Boundaries)

- **Siempre hacer**:
  - Ejecutar `pytest` completo tras cada bloque de cambios y verificar que pase al 100% en modo sin `GEMINI_API_KEY`.
  - Declarar los 4 booleanos de `ToolAnnotations` en cada nueva herramienta MCP.
  - Usar `_migrar()` aditivo en `app/memoria.py` para no romper instancias existentes en Render PostgreSQL o SQLite.
  - Mantener la construcción DOM segura sin inyección HTML en `app/static/app.js`.
- **Preguntar primero**:
  - Antes de agregar cualquier librería externa nueva a `requirements.txt`.
  - Antes de introducir soporte multiusuario / cuentas con autenticación distinta a `TUTOR_TOKEN`.
  - Antes de habilitar descarga automática de URLs externas o lectura directa del sistema de archivos del servidor desde `/mcp` remoto.
- **Nunca hacer**:
  - Romper compatibilidad con las rutas API v1.1 o con las 9 herramientas MCP existentes.
  - Exponer `respuesta_esperada` en respuestas de consultas pendientes o recursos `tutor://pendientes`.
  - Committear `.env`, claves de API o bases `.db` locales al repositorio.

---

## 8. Criterios de Éxito Medibles (Release v2.0)

1. Un desarrollador puede enviar un fragmento de código desde Claude Code / Cursor / Antigravity usando `estudiar_codigo` y recibir en menos de 2 s (modo local) o en una llamada a Gemini (modo IA) fichas atómicas guardadas en una colección con lectura previa (`codigo`, `analogia`, `idea_clave`).
2. Un estudiante puede pegar apuntes en Markdown de cualquier materia (`ingestar_material`), generar múltiples fichas atómicas y estudiarlas por Web o MCP con SM-2.
3. El servidor MCP expone **19 Tools** (todas con 4 `ToolAnnotations` booleanos y 100% cubiertas en tests), **6 Resources** y **5 Prompts**, instalable en local con `agente-tutor-mcp`.
4. El ciclo autónomo detecta automáticamente temas difíciles (`en_refuerzo`), registra reflexiones en `bitacora` y mantiene la racha diaria persistida en base de datos tras reinicios.
5. Toda la suite de pruebas (`pytest -v`) pasa al 100% sin `GEMINI_API_KEY`, cumpliendo las 20 directivas de compliance y manteniendo el estándar **M8ven Trust Index**.

---

## 9. Preguntas Abiertas para Validar antes del Sprint 1

1. **Modelo de acceso / usuarios**: ¿Mantenemos en v2.0 el modelo personal con una sola clave `TUTOR_TOKEN` (ideal para servidor propio en Render / uso local MCP) o quieres planear desde ya espacios separados por perfil/usuario?
2. **Fuentes de ingesta externa**: En v2.0 proponemos que el código/texto/Markdown llegue pegado en la Web o enviado directamente por tu asistente de código vía MCP (cero riesgo SSRF). ¿Estás de acuerdo con dejar la captura de URLs externas fuera de v2.0, o la consideras indispensable?
3. **Prioridad de arranque**: ¿Aprobamos esta especificación y arrancamos de inmediato con el **Sprint 1** (Colecciones, Fichas Enriquecidas y CRUD Completo)?

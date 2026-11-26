# Product Backlog & Sprint Backlog — Agente Tutor Persistente v2.0

Convención de tamaños: **XS** (1 archivo / cambio puntual), **S** (1–2 archivos), **M** (3–5 archivos / rebanada vertical completa).  
Convención de prioridad: **P0** (Crítico / Bloqueante), **P1** (Alto / Núcleo v2), **P2** (Medio / Valor agregado).

---

## Sprint 1 — Cimientos de Colecciones, Fichas Enriquecidas y CRUD Completo
**Objetivo del Sprint:** Soportar colecciones personalizadas, fichas con código/analogía/idea clave, lectura guiada unificada, búsqueda/edición/posposición y exportación/importación.

### T-01: Esquema de BD v2 y migración segura v1 → v2
- **Prioridad:** P0 | **Tamaño:** M | **Módulo:** `modelo-colecciones-fichas` | **Dependencias:** Ninguna
- **Descripción:** Añadir en `app/memoria.py` las tablas `colecciones` y `actividad_diaria`, además de las columnas enriquecidas en `temas` (`tipo`, `coleccion_id`, `codigo`, `lenguaje`, `analogia`, `idea_clave`, `etiquetas`, `en_refuerzo`) mediante `_migrar()` compatible con SQLite y PostgreSQL.
- **Criterios de aceptación:**
  - [x] `metadata.create_all()` crea `colecciones` y `actividad_diaria`.
  - [x] `_migrar()` agrega las columnas nuevas a bases v1 existentes sin perder filas ni fallar si ya existen.
  - [x] `crear_tema()` acepta campos enriquecidos opcionales manteniendo 100% compatibilidad con llamadas v1.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_nucleo.py -k "migracion" -v`
- **Archivos probables:** `app/memoria.py`, `tests/test_nucleo.py`

### T-02: CRUD completo de colecciones personalizadas
- **Prioridad:** P0 | **Tamaño:** S | **Módulo:** `modelo-colecciones-fichas` | **Dependencias:** `T-01`
- **Descripción:** Implementar operaciones de creación, listado con conteos, activación/pausa, renombrado y borrado de colecciones en `Memoria`, `AgenteTutor` y endpoints `/api/colecciones` en `app/main.py`, integrando colecciones activas/pausadas en `AgenteTutor.ciclo()`.
- **Criterios de aceptación:**
  - [x] Endpoints `GET /api/colecciones`, `POST /api/colecciones`, `PATCH /api/colecciones/{id}`, `DELETE /api/colecciones/{id}` operativos y protegidos con `TUTOR_TOKEN` en escritura.
  - [x] Los temas pertenecientes a una colección pausada (`activa=0`) no se preguntan en `ciclo()`.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_api.py -k "colecciones" -v`
- **Archivos probables:** `app/memoria.py`, `app/agente.py`, `app/main.py`, `tests/test_api.py`

### T-03: Lectura guiada unificada (`lectura_de`) para temas propios y de código
- **Prioridad:** P1 | **Tamaño:** S | **Módulo:** `modelo-colecciones-fichas` | **Dependencias:** `T-01`
- **Descripción:** Extender `AgenteTutor.lectura_de()` y `_preparar_pregunta()` para que cualquier tema con contenido enriquecido (`codigo`, `analogia`, `idea_clave` o `tipo in ("codigo", "material")`) active `requiere_lectura` la primera vez igual que las DevCards.
- **Criterios de aceptación:**
  - [x] `lectura_de()` construye la ficha completa para temas de usuario/código cuando `requiere_lectura` es `True`.
  - [x] Al marcar lectura (`marcar_leida`) se desbloquea la pregunta y en repasos siguientes ya no exige lectura previa.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_nucleo.py -k "lectura" -v`
- **Archivos probables:** `app/agente.py`, `tests/test_nucleo.py`

### T-04: Búsqueda, edición y posposición de temas
- **Prioridad:** P1 | **Tamaño:** S | **Módulo:** `modelo-colecciones-fichas` | **Dependencias:** `T-02`
- **Descripción:** Agregar filtros de búsqueda (`q`, `coleccion_id`, `tipo`) en `GET /api/temas`, endpoint `PATCH /api/temas/{id}` para editar notas/código/colección y `POST /api/temas/{id}/posponer` para mover `proximo_repaso` N días adelante.
- **Criterios de aceptación:**
  - [x] Búsqueda insensible a mayúsculas por nombre, notas o etiquetas.
  - [x] Edición y posposición protegidas por `TUTOR_TOKEN` y registradas en `bitacora`.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_api.py -k "buscar or editar or posponer" -v`
- **Archivos probables:** `app/memoria.py`, `app/agente.py`, `app/main.py`, `tests/test_api.py`

### T-05: Exportación e importación de mazos en JSON y Markdown
- **Prioridad:** P1 | **Tamaño:** S | **Módulo:** `modelo-colecciones-fichas` | **Dependencias:** `T-02`
- **Descripción:** Implementar `GET /api/colecciones/{id}/exportar?formato=json|md` y `POST /api/colecciones/importar` para exportar e importar colecciones portables con sus fichas.
- **Criterios de aceptación:**
  - [x] La exportación JSON/Markdown incluye colección y fichas sin datos sensibles ni claves.
  - [x] La importación valida esquema, crea fichas nuevas y omite duplicados informando el resumen.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_api.py -k "exportar or importar" -v`
- **Archivos probables:** `app/agente.py`, `app/main.py`, `tests/test_api.py`

### T-06: Actualización de `docs/CONTRATO_API.md` (Sprint 1)
- **Prioridad:** P2 | **Tamaño:** XS | **Módulo:** `modelo-colecciones-fichas` | **Dependencias:** `T-02`, `T-04`, `T-05`
- **Descripción:** Documentar en `docs/CONTRATO_API.md` los nuevos campos de tema, endpoints de colecciones, filtros, edición, posposición y exportación/importación.
- **Criterios de aceptación:**
  - [x] Todas las nuevas rutas HTTP, parámetros, códigos de error y payloads JSON documentados con precisión.
- **Verificación:** `.\.venv\Scripts\python -m pytest -v`
- **Archivos probables:** `docs/CONTRATO_API.md`

### Checkpoint Sprint 1
- [x] Todas las pruebas unitarias y de API pasan (`pytest -v`).
- [x] Migración v1 → v2 verificada sin pérdida de datos.
- [x] Retrocompatibilidad total con endpoints y clientes v1.1 confirmada.

---

## Sprint 2 — «Estudia lo que Construyes»: Ingesta de Código y Material Libre
**Objetivo del Sprint:** Permitir estudiar código propio/generado por IA y apuntes/Markdown de cualquier tema, tanto con Gemini como en modo 100% local determinista.

### T-07: Motor determinista local para análisis de código (`app/ingesta.py`)
- **Prioridad:** P0 | **Tamaño:** M | **Módulo:** `ingesta-codigo-y-material` | **Dependencias:** `T-01`, `T-03`
- **Descripción:** Crear `app/ingesta.py` capaz de analizar fragmentos de código (Python, JavaScript/TypeScript, SQL, genérico) sin llamadas externas: detectar símbolos (`def`, `class`, `function`, `const`, sentencias SQL), dividir bloques largos en unidades estudiables y construir ficha base + preguntas deterministas (completado/traza/concepto).
- **Criterios de aceptación:**
  - [x] Extrae de 1 a 5 fichas válidas desde código Python, JS/TS, SQL o texto técnico sin `GEMINI_API_KEY`.
  - [x] Cada ficha incluye `nombre`, `notas`, `codigo`, `lenguaje` e `idea_clave`.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_ingesta.py -k "codigo_local" -v`
- **Archivos probables:** `app/ingesta.py`, `tests/test_ingesta.py`

### T-08: Descomposición y preguntas de código asistidas por Gemini (`app/cerebro.py`)
- **Prioridad:** P0 | **Tamaño:** M | **Módulo:** `ingesta-codigo-y-material` | **Dependencias:** `T-07`
- **Descripción:** Añadir a `Cerebro` los métodos `descomponer_codigo()` y `generar_pregunta_codigo()` soportando modalidades (`explica_codigo`, `predice_salida`, `detecta_bug`, `concepto`), con validación JSON estricta y respaldo inmediato a `app/ingesta.py` si no hay clave o falla la API.
- **Criterios de aceptación:**
  - [x] Usa delimitadores `<codigo>` anti-prompt-injection al consultar Gemini.
  - [x] Ante fallo HTTP, timeout o JSON inválido, cae al motor determinista local sin lanzar excepciones.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_ingesta.py -k "cerebro_codigo" -v`
- **Archivos probables:** `app/cerebro.py`, `app/ingesta.py`, `tests/test_ingesta.py`

### T-09: Ingesta universal de apuntes y Markdown (`ingestar_material`)
- **Prioridad:** P0 | **Tamaño:** M | **Módulo:** `ingesta-codigo-y-material` | **Dependencias:** `T-07`, `T-08`
- **Descripción:** Implementar segmentación y síntesis de apuntes libres o Markdown por encabezados/párrafos en `app/ingesta.py` y `app/cerebro.py` para convertir cualquier documento pegado en hasta `max_fichas` tarjetas atómicas (`tipo="material"`).
- **Criterios de aceptación:**
  - [x] Funciona tanto con Markdown estructurado (`#`, `##`, listas) como con texto corrido.
  - [x] Opera con Gemini (si hay clave) y con extractor determinista local (si no hay clave).
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_ingesta.py -k "material" -v`
- **Archivos probables:** `app/ingesta.py`, `app/cerebro.py`, `tests/test_ingesta.py`

### T-10: Orquestación en `AgenteTutor` y endpoints REST de ingesta
- **Prioridad:** P0 | **Tamaño:** S | **Módulo:** `ingesta-codigo-y-material` | **Dependencias:** `T-08`, `T-09`
- **Descripción:** Exponer `AgenteTutor.estudiar_codigo()`, `AgenteTutor.ingestar_material()` y rotación de preguntas de código en `_preparar_pregunta()`, junto con los endpoints `POST /api/estudiar/codigo` y `POST /api/estudiar/material` en `app/main.py`.
- **Criterios de aceptación:**
  - [x] `POST /api/estudiar/codigo` y `POST /api/estudiar/material` crean la colección si no existe, guardan fichas y devuelven `201`.
  - [x] `_preparar_pregunta()` alterna modalidades de código y activa `requiere_lectura` en el primer repaso.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_api.py -k "estudiar" -v`
- **Archivos probables:** `app/agente.py`, `app/main.py`, `tests/test_api.py`

### T-11: Validación de seguridad, límites y deduplicación en ingesta
- **Prioridad:** P1 | **Tamaño:** S | **Módulo:** `ingesta-codigo-y-material` | **Dependencias:** `T-10`
- **Descripción:** Aplicar límites Pydantic estrictos (`codigo` hasta `12 000` chars, `material` hasta `25 000` chars, `max_fichas` entre `1` y `15`), protección `TUTOR_TOKEN` y omisión elegante de fichas duplicadas dentro de la misma colección.
- **Criterios de aceptación:**
  - [x] Entradas fuera de rango devuelven `422`.
  - [x] Reenviar el mismo material no duplica fichas ni rompe el lote.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_api.py -k "estudiar" -v`
- **Archivos probables:** `app/main.py`, `app/agente.py`, `tests/test_api.py`

### T-12: Suite integral de pruebas de ingesta (`tests/test_ingesta.py`)
- **Prioridad:** P1 | **Tamaño:** S | **Módulo:** `ingesta-codigo-y-material` | **Dependencias:** `T-11`
- **Descripción:** Completar casos borde en `tests/test_ingesta.py`: código mínimo, multilenguaje, fallos de red simulados en `httpx`, textos sin encabezados y rotación de preguntas de código.
- **Criterios de aceptación:**
  - [x] Cobertura completa de casos válidos, vacíos, errores simulados de Gemini y generación local.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_ingesta.py -v`
- **Archivos probables:** `tests/test_ingesta.py`

### Checkpoint Sprint 2
- [x] `pytest -v` pasa al 100% sin `GEMINI_API_KEY`.
- [x] Un bloque de código y un documento Markdown se convierten en fichas con lectura previa y preguntas rotativas SM-2.

---

## Sprint 3 — Servidor MCP Completo (Tools, Resources, Prompts y Empaquetado CLI)
**Objetivo del Sprint:** Convertir al tutor en un MCP universal de primera clase con 19 Tools anotadas, 6 Resources, 5 Prompts, CLI instalable y 100% de cobertura verificada.

### T-13: Nuevas Tools MCP con `ToolAnnotations` completas
- **Prioridad:** P0 | **Tamaño:** M | **Módulo:** `mcp-nativo-completo` | **Dependencias:** `T-04`, `T-05`, `T-10`
- **Descripción:** Añadir en `app/mcp_tools.py` las 10 nuevas herramientas (`estudiar_codigo`, `ingestar_material`, `gestionar_coleccion`, `buscar_temas`, `editar_tema`, `borrar_tema`, `posponer_tema`, `diagnosticar_brechas`, `exportar_mazo`, `importar_mazo`), todas con las 4 banderas booleanas de `ToolAnnotations`.
- **Criterios de aceptación:**
  - [x] Las 19 Tools declaran valores booleanos explícitos (`True`/`False`) en `read_only_hint`, `destructive_hint`, `idempotent_hint` y `open_world_hint`.
  - [x] `borrar_tema` y `gestionar_coleccion(eliminar)` declaran `destructive_hint=True`.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_mcp_v2.py -k "annotations" -v`
- **Archivos probables:** `app/mcp_tools.py`, `tests/test_mcp_v2.py`

### T-14: Implementación de los 6 MCP Resources
- **Prioridad:** P0 | **Tamaño:** M | **Módulo:** `mcp-nativo-completo` | **Dependencias:** `T-13`
- **Descripción:** Registrar con `@mcp.resource(...)` en `app/mcp_tools.py` los recursos `tutor://estado`, `tutor://pendientes`, `tutor://colecciones`, `tutor://tema/{tema_id}`, `tutor://brechas` y `tutor://bitacora/reciente`.
- **Criterios de aceptación:**
  - [x] Todos los Resources devuelven JSON válido y UTF-8.
  - [x] `tutor://pendientes` nunca expone `respuesta_esperada`.
  - [x] `tutor://tema/{tema_id}` maneja IDs inexistentes limpiamente.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_mcp_v2.py -k "resources" -v`
- **Archivos probables:** `app/mcp_tools.py`, `tests/test_mcp_v2.py`

### T-15: Implementación de los 5 MCP Prompts
- **Prioridad:** P1 | **Tamaño:** S | **Módulo:** `mcp-nativo-completo` | **Dependencias:** `T-13`, `T-14`
- **Descripción:** Registrar con `@mcp.prompt(...)` los flujos `sesion_repaso`, `aprender_codigo_generado`, `ingestar_apuntes`, `tutor_socratico` y `resumen_semanal` para guiar a clientes como Claude Code, Cursor o Antigravity.
- **Criterios de aceptación:**
  - [x] `prompts/list` y `prompts/get` funcionan tanto en `MCPServer` directo como sobre `/mcp`.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_mcp_v2.py -k "prompts" -v`
- **Archivos probables:** `app/mcp_tools.py`, `tests/test_mcp_v2.py`

### T-16: Empaquetado CLI (`pyproject.toml` + `agente-tutor-mcp`)
- **Prioridad:** P1 | **Tamaño:** S | **Módulo:** `mcp-nativo-completo` | **Dependencias:** `T-13`
- **Descripción:** Crear `pyproject.toml` definiendo metadatos del paquete y el entrypoint `[project.scripts] agente-tutor-mcp = "app.mcp_tools:main_cli"`, asegurando ejecución limpia en `stdio`.
- **Criterios de aceptación:**
  - [x] `pip install -e .` instala el comando `agente-tutor-mcp` sin errores.
  - [x] `agente-tutor-mcp --help` o ejecución `stdio` arranca sin excepciones.
- **Verificación:** `.\.venv\Scripts\pip install --no-deps -e . ; .\.venv\Scripts\python -c "import app.mcp_tools as m; print(hasattr(m, 'main_cli'))"`
- **Archivos probables:** `pyproject.toml`, `app/mcp_tools.py`

### T-17: Cobertura 100% de herramientas, hints, resources y prompts en `tests/test_mcp_v2.py`
- **Prioridad:** P0 | **Tamaño:** M | **Módulo:** `mcp-nativo-completo` | **Dependencias:** `T-14`, `T-15`
- **Descripción:** Crear `tests/test_mcp_v2.py` invocando explícitamente por nombre cada una de las 19 Tools, verificando `ToolAnnotations` booleanos en todas y probando los 6 Resources y 5 Prompts.
- **Criterios de aceptación:**
  - [x] 19/19 herramientas referenciadas y ejecutadas en tests (100% para auditoría M8ven).
  - [x] Aserción automática sobre todas las tools listadas por `tools/list` para impedir regresiones sin `ToolAnnotations`.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_mcp_v2.py tests/test_api.py -v`
- **Archivos probables:** `tests/test_mcp_v2.py`

### T-18: Documentación de conexión MCP (`docs/CONECTAR_MCP.md` y `README.md`)
- **Prioridad:** P2 | **Tamaño:** S | **Módulo:** `mcp-nativo-completo` | **Dependencias:** `T-16`, `T-17`
- **Descripción:** Redactar `docs/CONECTAR_MCP.md` con configuraciones JSON/TOML listas para copiar y pegar en Claude Desktop, Claude Code, Cursor, Antigravity y Gemini CLI (modo local `stdio` y modo remoto `/mcp` en Render).
- **Criterios de aceptación:**
  - [x] Incluye ejemplos claros de configuración para `stdio` y `Streamable HTTP`, variables requeridas y verificación rápida.
- **Verificación:** Revisión de enlaces y comandos en `docs/CONECTAR_MCP.md` y `README.md`.
- **Archivos probables:** `docs/CONECTAR_MCP.md`, `README.md`

### Checkpoint Sprint 3
- [x] `tests/test_mcp_v2.py` pasa al 100% (19/19 Tools, 4 hints booleanos en todas, 6 Resources, 5 Prompts).
- [x] Comando CLI `agente-tutor-mcp` verificado localmente.

---

## Sprint 4 — Agente Autónomo Reflexivo v2, Experiencia Web y Release v2.0
**Objetivo del Sprint:** Completar la fase `reflexionar` + rachas en el agente, actualizar la interfaz web para estudiar código/apuntes/colecciones y cerrar auditoría de compliance y Docker.

### T-19: Fase `reflexionar` en `AgenteTutor.ciclo()` y refuerzo de brechas
- **Prioridad:** P0 | **Tamaño:** M | **Módulo:** `agente-autonomo-v2` | **Dependencias:** `T-10`
- **Descripción:** Añadir el método `_reflexionar()` dentro de `AgenteTutor.ciclo()` para detectar temas con `fallos >= 3` o `facilidad <= 1.6`, marcar `en_refuerzo=1`, anotar tipo `reflexion` en `bitacora`, reactivar lectura guiada y limpiar `en_refuerzo` tras 2 aciertos seguidos (`nota >= 4`).
- **Criterios de aceptación:**
  - [x] Temas con fallos reiterados pasan automáticamente a `en_refuerzo=1` y muestran ficha de lectura nuevamente al vencer.
  - [x] No duplica entradas `reflexion` repetitivas en ciclos consecutivos.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_nucleo.py -k "reflexion or brecha" -v`
- **Archivos probables:** `app/agente.py`, `app/memoria.py`, `tests/test_nucleo.py`

### T-20: Rachas diarias (`actividad_diaria`) y endpoint `/api/brechas`
- **Prioridad:** P1 | **Tamaño:** S | **Módulo:** `agente-autonomo-v2` | **Dependencias:** `T-19`
- **Descripción:** Registrar actividad diaria de estudio en `actividad_diaria` al responder preguntas, exponer `racha_dias` en `AgenteTutor.progreso()` / `estado()` y añadir `GET /api/brechas` + lógica compartida para `diagnosticar_brechas` MCP.
- **Criterios de aceptación:**
  - [x] `racha_dias` sobrevive a reinicios y calcula días consecutivos en UTC correctamente.
  - [x] `GET /api/brechas` devuelve los temas difíciles y recomendación de estudio.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_nucleo.py tests/test_api.py -k "racha or brechas" -v`
- **Archivos probables:** `app/memoria.py`, `app/agente.py`, `app/main.py`, `tests/test_nucleo.py`, `tests/test_api.py`

### T-21: Interfaz Web v2 — Ingesta de código, apuntes/Markdown y colecciones
- **Prioridad:** P1 | **Tamaño:** M | **Módulo:** `interfaz-estudio-v2` | **Dependencias:** `T-10`, `T-20`
- **Descripción:** Actualizar `app/static/index.html`, `app/static/app.js` y `app/static/estilos.css` para incorporar pestañas en la zona de carga (*Nota simple*, *Estudiar código*, *Ingestar Markdown*), selector de lenguaje, visualización de bloques `<pre><code>` en tarjetas de lectura y panel de **Colecciones** (crear, activar/pausar, filtrar).
- **Criterios de aceptación:**
  - [x] Cero `innerHTML` con datos ingresados por el usuario (todo renderizado vía `textContent`).
  - [x] Responsivo desde `360 px` y navegación por teclado preservada.
- **Verificación:** Inspección en navegador local + `.\.venv\Scripts\python -m pytest tests/test_api.py -v`
- **Archivos probables:** `app/static/index.html`, `app/static/app.js`, `app/static/estilos.css`

### T-22: Interfaz Web v2 — Brechas, racha, búsqueda/edición y exportar/importar
- **Prioridad:** P1 | **Tamaño:** M | **Módulo:** `interfaz-estudio-v2` | **Dependencias:** `T-21`
- **Descripción:** Añadir en la web la métrica de `racha_dias`, la lista de brechas en refuerzo, barra de búsqueda/filtro en **Mis temas**, acciones de editar/posponer tema y botones de **Exportar (JSON/MD)** e **Importar mazo**.
- **Criterios de aceptación:**
  - [x] El usuario puede buscar, editar, posponer y exportar/importar sin recargar la página ni perder foco.
  - [x] Contraste WCAG 2.1 AA (>= `4.5:1`) y objetivos táctiles >= `44 px` conservados.
- **Verificación:** Inspección visual y funcional en navegador + `.\.venv\Scripts\python -m pytest -v`
- **Archivos probables:** `app/static/index.html`, `app/static/app.js`, `app/static/estilos.css`

### T-23: Auditoría de Compliance (20 reglas), `/privacidad` y Docker
- **Prioridad:** P0 | **Tamaño:** S | **Módulo:** `interfaz-estudio-v2` | **Dependencias:** `T-22`
- **Descripción:** Actualizar `app/static/privacidad.html` detallando el tratamiento de fragmentos de código y apuntes, exportación portable y borrado en cascada; auditar las 20 reglas de compliance (accesibilidad, sin patrones oscuros, sin secretos) y validar `Dockerfile` / `docker-compose.yml` incluyendo `app/ingesta.py` y `pyproject.toml`.
- **Criterios de aceptación:**
  - [x] `/privacidad` refleja fielmente v2.0 y cómo exportar/eliminar datos.
  - [x] `Dockerfile` construye correctamente la imagen con todas las rutas nuevas.
- **Verificación:** `docker compose config -q` (o `docker build`) y revisión de `/privacidad`.
- **Archivos probables:** `app/static/privacidad.html`, `Dockerfile`, `docker-compose.yml`

### T-24: Pruebas finales E2E, documentación viva y cierre v2.0
- **Prioridad:** P0 | **Tamaño:** S | **Módulo:** `interfaz-estudio-v2` | **Dependencias:** `T-23`
- **Descripción:** Actualizar `docs/COMO_FUNCIONA.md`, `docs/CONTRATO_API.md` y `README.md` reflejando v2.0, ejecutar toda la suite de pruebas (`pytest -v`), validar inicio real del servidor web y MCP, y preparar el tag/release `v2.0.0`.
- **Criterios de aceptación:**
  - [x] 100% de pruebas pasan en modo local (sin `GEMINI_API_KEY`).
  - [x] Documentación sincronizada con la implementación real.
- **Verificación:** `.\.venv\Scripts\python -m pytest -v`
- **Archivos probables:** `README.md`, `docs/COMO_FUNCIONA.md`, `docs/CONTRATO_API.md`

### Checkpoint Sprint 4 (Release v2.0)
- [x] Todos los casos de uso `CU-01` a `CU-16` verificados.
- [x] Suite completa `pytest -v` al 100% sin fallos ni skips.
- [x] Compliance, seguridad, accesibilidad y M8ven Trust Index validados.

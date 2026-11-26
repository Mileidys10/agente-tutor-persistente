# Product Backlog & Sprint Backlog v3.0 — Sprints 5 a 8 (`T-25` a `T-44`)

Convención: **XS** (cambio puntual), **S** (1–2 archivos), **M** (3–5 archivos / vertical slice).

---

## Sprint 5 — Base de Datos v3, `estudiar_diff` y Pistas Socráticas Progresivas
**Objetivo:** Añadir esquema v3 migrable, estudio de `git diff` reales y pistas progresivas (1–3) con ajuste SM-2.

### T-25: Configuración v3 y esquema BD migrable (`app/config.py`, `app/memoria.py`)
- **Prioridad:** P0 | **Tamaño:** M | **Dependencias:** Base v2.0
- **Criterios de aceptación:**
  - [x] `Config` incorpora `meta_diaria` (`TUTOR_META_DIARIA`, default `10`) y `webhook_url` (`TUTOR_WEBHOOK_URL`, default `""`).
  - [x] `Memoria` define `relaciones_temas`, `sesiones_examen`, `preguntas.pistas_usadas`, `preguntas.sesion_examen_id` y `latido.ultima_notificacion` con `_migrar()` idempotente.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_nucleo.py -k "migracion" -v`

### T-26: Parser determinista de `git diff` y generador de pistas (`app/ingesta.py`)
- **Prioridad:** P0 | **Tamaño:** M | **Dependencias:** `T-25`
- **Criterios de aceptación:**
  - [x] `parsear_git_diff_local()` extrae fichas por archivo modificado detectando lenguaje por extensión y resumiendo líneas `+`/`-`.
  - [x] `generar_pista_progresiva()` produce pistas distintas para niveles 1, 2 y 3 sin exponer la respuesta literal completa.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_v3.py -k "diff or pista" -v`

### T-27: Descomposición de `git diff` asistida por Gemini (`app/cerebro.py`)
- **Prioridad:** P1 | **Tamaño:** S | **Dependencias:** `T-26`
- **Criterios de aceptación:**
  - [x] `Cerebro.descomponer_diff()` usa delimitadores `<diff>` y cae al parser local si falla Gemini o no hay clave.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_v3.py -k "diff" -v`

### T-28: `estudiar_diff` y `pedir_pista` en `AgenteTutor` y API REST (`app/agente.py`, `app/main.py`)
- **Prioridad:** P0 | **Tamaño:** M | **Dependencias:** `T-26`, `T-27`
- **Criterios de aceptación:**
  - [x] `POST /api/estudiar/diff` (201) y `POST /api/preguntas/{id}/pista` (200) protegidos con `TUTOR_TOKEN`.
  - [x] `AgenteTutor.responder()` aplica tope SM-2 justo (`1` pista -> máx `4`, `>=2` pistas -> máx `3`).
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_v3.py -k "pista or diff" -v`

### T-29: Checkpoint y tests de Sprint 5 (`tests/test_v3.py`)
- **Prioridad:** P0 | **Tamaño:** S | **Dependencias:** `T-28`
- **Criterios de aceptación:**
  - [x] Pruebas unitarias y REST para `git diff`, pistas niveles 1–3, tope SM-2 y migración v1->v3 aprobadas.
- **Verificación:** `.\.venv\Scripts\python -m pytest -v`

### Checkpoint Sprint 5
- [x] `pytest -v` 100% verde sin `GEMINI_API_KEY`.

---

## Sprint 6 — Modo Simulacro, Grafo de Prerrequisitos y Planificador Diario 7 Días
**Objetivo:** Evaluar con simulacros persistentes, priorizar bases mediante grafo de temas y proyectar carga diaria/semanal.

### T-30: Modo Simulacro persistente (`iniciar_simulacro`, `ver_simulacros`, `obtener_simulacro`)
- **Prioridad:** P0 | **Tamaño:** M | **Dependencias:** `T-28`
- **Criterios de aceptación:**
  - [x] Permite filtrar por colección, categoría DevCards o `solo_brechas`.
  - [x] Cada respuesta durante el examen actualiza avance, nota promedio, temas fallados y cierra al completar `total_preguntas`.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_v3.py -k "simulacro" -v`

### T-31: Grafo de prerrequisitos en `AgenteTutor` y boost en `ciclo()`
- **Prioridad:** P0 | **Tamaño:** M | **Dependencias:** `T-25`
- **Criterios de aceptación:**
  - [x] `vincular_temas()` rechaza autorreferencias y ciclos directos (`B -> A` si existe `A -> B`).
  - [x] `ciclo()` prioriza el prerrequisito vencido no dominado sobre el tema dependiente.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_v3.py -k "grafo or prerrequisito" -v`

### T-32: Planificador diario y pronóstico de 7 días (`plan_estudio_hoy`)
- **Prioridad:** P1 | **Tamaño:** S | **Dependencias:** `T-25`
- **Criterios de aceptación:**
  - [x] Calcula `respondidas_hoy`, `meta_diaria`, `progreso_meta_pct`, `minutos_estimados`, `racha_dias` y `pronostico_7_dias`.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_v3.py -k "plan" -v`

### T-33: Endpoints REST de exámenes, relaciones y plan (`app/main.py`)
- **Prioridad:** P0 | **Tamaño:** S | **Dependencias:** `T-30`, `T-31`, `T-32`
- **Criterios de aceptación:**
  - [x] `GET /api/plan`, `GET /api/examenes`, `GET /api/examenes/{id}`, `POST /api/examenes`, `GET /api/temas/{id}/relaciones`, `POST /api/temas/relaciones`, `DELETE /api/temas/relaciones/{id}`.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_v3.py -v`

### T-34: Checkpoint Sprint 6
- **Prioridad:** P0 | **Tamaño:** XS | **Dependencias:** `T-33`
- **Criterios de aceptación:**
  - [x] Toda la suite `pytest -v` pasa sin regresiones.
- **Verificación:** `.\.venv\Scripts\python -m pytest -v`

### Checkpoint Sprint 6
- [x] Simulacros, grafo de prerrequisitos y plan diario 7 días verificados al 100%.

---

## Sprint 7 — Exportación Anki TSV, Webhooks Proactivos y MCP v3 (25 Tools, 8 Resources, 7 Prompts)
**Objetivo:** Llevar interoperabilidad al máximo nivel con Anki, recordatorios diarios y MCP v3 completo.

### T-35: Exportación Anki TSV (`formato="anki"`)
- **Prioridad:** P1 | **Tamaño:** S | **Dependencias:** `T-25`
- **Criterios de aceptación:**
  - [x] `exportar_coleccion(..., formato="anki")` genera TSV válido (`Front\tBack\tTags`) y `/api/colecciones/{id}/exportar?formato=anki` responde `text/tab-separated-values`.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_v3.py -k "anki" -v`

### T-36: Notificaciones proactivas vía Webhook (`TUTOR_WEBHOOK_URL`)
- **Prioridad:** P1 | **Tamaño:** S | **Dependencias:** `T-25`, `T-32`
- **Criterios de aceptación:**
  - [x] Envía máximo 1 notificación diaria UTC cuando hay pendientes o vencidos y está configurada una URL `http(s)://`.
  - [x] Errores de red no rompen el ciclo autónomo.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_v3.py -k "webhook" -v`

### T-37: 6 nuevas Tools MCP con `ToolAnnotations`, 2 Resources y 2 Prompts (`app/mcp_tools.py`)
- **Prioridad:** P0 | **Tamaño:** M | **Dependencias:** `T-28`, `T-30`, `T-31`, `T-32`, `T-35`
- **Criterios de aceptación:**
  - [x] Total: **25 Tools** (todas con las 4 `ToolAnnotations` booleanas), **8 Resources** (`+ tutor://plan/hoy`, `tutor://examenes`) y **7 Prompts** (`+ estudiar_ultimo_diff`, `entrevista_tecnica`).
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_mcp_v3.py -v`

### T-38: Suite `tests/test_mcp_v3.py` y compatibilidad de `tests/test_mcp_v2.py`
- **Prioridad:** P0 | **Tamaño:** M | **Dependencias:** `T-37`
- **Criterios de aceptación:**
  - [x] 25/25 Tools invocadas explícitamente por nombre y validadas con los 4 booleanos en `ToolAnnotations`.
  - [x] 8/8 Resources y 7/7 Prompts validados.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_mcp_v2.py tests/test_mcp_v3.py -v`

### T-39: Bump de versión a `3.0.0` (`pyproject.toml`, `app/main.py`)
- **Prioridad:** P2 | **Tamaño:** XS | **Dependencias:** `T-38`
- **Criterios de aceptación:**
  - [x] `pyproject.toml` y FastAPI `app` reportan versión `3.0.0`.
- **Verificación:** `.\.venv\Scripts\python -m pytest -v`

### Checkpoint Sprint 7
- [x] MCP v3 (25 Tools, 8 Resources, 7 Prompts), Anki TSV y Webhooks probados al 100%.

---

## Sprint 8 — Web UI v3, Documentación Viva, Verificación Final y Push `v3.0.0`
**Objetivo:** Exponer todas las capacidades v3.0 en la interfaz web accesible, actualizar documentación y publicar en GitHub sin PDFs ni capturas.

### T-40: Web UI v3 — Pestaña `git diff` y botón «Pedir pista» en tarjetas
- **Prioridad:** P1 | **Tamaño:** M | **Dependencias:** `T-28`
- **Criterios de aceptación:**
  - [x] Pestaña `#tab-diff` -> `#form-diff` operativa.
  - [x] Botón `Pedir pista` en cada pregunta abierta/código/DevCard mostrando hasta 3 niveles sin `innerHTML`.
- **Verificación:** `.\.venv\Scripts\python -m pytest tests/test_v3.py -v`

### T-41: Web UI v3 — Panel Simulacro, Plan Diario 7d y descarga Anki `.tsv`
- **Prioridad:** P1 | **Tamaño:** M | **Dependencias:** `T-33`, `T-35`, `T-40`
- **Criterios de aceptación:**
  - [x] Sección `#seccion-simulacro` muestra progreso de meta diaria, pronóstico 7 días, launcher de simulacro e historial.
  - [x] Botón `Anki` junto a `JSON` y `MD` en colecciones.
- **Verificación:** `.\.venv\Scripts\python -m pytest -v`

### T-42: Privacidad, Contrato API, Guía MCP y README v3.0
- **Prioridad:** P0 | **Tamaño:** S | **Dependencias:** `T-41`
- **Criterios de aceptación:**
  - [x] `app/static/privacidad.html`, `docs/CONTRATO_API.md`, `docs/CONECTAR_MCP.md`, `docs/COMO_FUNCIONA.md` y `README.md` (manteniendo badge M8ven) actualizados a v3.0.
- **Verificación:** Revisión de docs + `.\.venv\Scripts\python -m pytest -v`

### T-43: Cierre de Backlog, `SPRINT_LOG.md`, Docker y archivo de contexto
- **Prioridad:** P0 | **Tamaño:** S | **Dependencias:** `T-42`
- **Criterios de aceptación:**
  - [x] `tasks/todo_v3.md`, `tasks/SPRINT_LOG.md` y `docs/PRD_V3.md` marcados como completados; contexto archivado.
  - [x] `docker compose config -q` retorna código `0`.
- **Verificación:** `.\.venv\Scripts\python -m pytest -v` y `docker compose config -q`

### T-44: Commit y Push `v3.0.0` a GitHub (sin PDFs ni capturas) + Sync Obsidian
- **Prioridad:** P0 | **Tamaño:** XS | **Dependencias:** `T-43`
- **Criterios de aceptación:**
  - [x] `git diff --cached --name-only` sin `.pdf` ni `capturas/`.
  - [x] `git push origin main` exitoso y `sincronizar_wiki_obsidian()` ejecutado.
- **Verificación:** `git status -s` y log de push

### Checkpoint Sprint 8 (Release v3.0.0)
- [x] Todos los casos de uso `CU-01` a `CU-24` implementados y cubiertos por pruebas automatizadas.
- [x] `v3.0.0` publicada en GitHub sin PDFs ni capturas.

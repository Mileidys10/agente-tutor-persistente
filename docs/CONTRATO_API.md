# Contrato de la API del Agente Tutor Persistente

El backend ya existe y está probado (`tests/`). Este documento fija la interfaz para la página web.
Todas las fechas son ISO 8601 en UTC.

## Autenticación
Si el servidor define `TUTOR_TOKEN`, las rutas que **escriben** exigen la cabecera `X-Tutor-Token: <clave>`
(o `Authorization: Bearer <clave>`). Sin la clave responden `401 {"detail": "..."}`. Las rutas de lectura son públicas.
`GET /api/acceso` (con la cabecera) responde `200 {"ok": true, "requiere_token": bool}` si la clave es válida; sirve para comprobarla.

## Lectura (públicas)
| Ruta | Respuesta |
|---|---|
| `GET /health` | `{ok, agente_vivo, ciclos, arranques, ultimo_ciclo}` |
| `GET /api/estado` | `{vivo, proceso_activo_hace_s, latido:{primer_arranque, ultimo_arranque, ultimo_ciclo, ciclos, arranques}, cerebro, base_de_datos, banco_devcards, mazos_activos:[str], pendientes, configuracion:{intervalo_ciclo_s, minutos_por_dia, max_pendientes, nuevas_por_dia}, progreso}` |
| `GET /api/preguntas/pendientes` | `[{id, tema_id, tema, texto, opciones: [str] \| null, motivo, fuente: "gemini"\|"local"\|"devcards", creada}]` (nunca incluye la respuesta) |
| `GET /api/temas` | `[{id, nombre, notas, origen: "usuario"\|"devcards", categoria, ref_externa, repeticiones, intervalo_dias, facilidad, proximo_repaso, aciertos, fallos, creado}]` |
| `GET /api/historial?limite=20` | `[{id, pregunta_id, texto, nota, retroalimentacion, fecha, pregunta, respuesta_esperada, tema}]` |
| `GET /api/bitacora?limite=40` | `[{id, fecha, tipo: "sistema"\|"ciclo"\|"decision"\|"pregunta"\|"evaluacion"\|"error", detalle}]`, el más reciente primero |
| `GET /api/mazos` | `[{categoria, tarjetas, activo, introducidas}]` (unas 30 categorías, 1 295 tarjetas) |
| `GET /api/progreso` | `{temas, dominados, respuestas, aciertos, porcentaje_aciertos: number\|null, mas_dificiles:[{tema, facilidad, fallos}]}` |

## Escritura (requieren token)
| Ruta | Cuerpo | Respuesta |
|---|---|---|
| `POST /api/temas` | `{nombre (2-200), notas (≤8000)}` | `201` tema · `409` si está duplicado · `422` si no es válido |
| `DELETE /api/temas/{id}` | — | `{borrado}` · `404` |
| `POST /api/preguntas/{id}/responder` | `{respuesta (≤2000)}` | `{pregunta_id, tema, nota 0-5, correcta, retroalimentacion, respuesta_esperada, evaluado_por, intervalo_dias, facilidad, proximo_repaso}` · `404` · `409` si ya se respondió |
| `PUT /api/mazos/{categoria}` | `{activo: bool}` | `{categoria, activo}` · `404`. La categoría va con `encodeURIComponent`. |
| `POST /api/ciclo` | — | `{preguntas_creadas:[...], pendientes, vencidos}`: fuerza un ciclo del agente ya |

En las preguntas de opción múltiple (`opciones` no es null), la respuesta se envía como la **letra** (`"A"`, `"B"`...).

## MCP
`POST /mcp` (Streamable HTTP, con `Authorization: Bearer <TUTOR_TOKEN>`). Herramientas: `agregar_tema`,
`ver_preguntas_pendientes`, `responder_pregunta`, `ver_mazos`, `activar_mazo`, `ver_progreso`, `ver_estado` y `ver_bitacora`.
Local por stdio: `python -m app.mcp_tools`.

## Modo "leer antes de responder" (v1.1)
Cuando el agente presenta una DevCard **nueva**, la pregunta exige leer la tarjeta primero.
`TUTOR_LEER_ANTES=0` desactiva el modo (por defecto está activo).

`GET /api/preguntas/pendientes` añade a cada pregunta:
- `requiere_lectura: bool` → `true` si hay que leer la tarjeta antes de responder (todavía no se marcó como leída).
- `lectura: {titulo, categoria, dificultad, definicion, analogia, codigo, idea_clave} | null` → la tarjeta completa
  mientras `requiere_lectura` es `true`; si no, `null`. `codigo` puede ser `""`. Se muestra como texto (nunca como HTML)
  y `codigo` en un `<pre><code>`.

`POST /api/preguntas/{id}/leida` (requiere token) → `{pregunta_id, leida_en}`. `404` si no existe; `409` si ya no está pendiente.
Es idempotente: marcarla dos veces no falla.

`POST /api/preguntas/{id}/responder` sobre una pregunta con `requiere_lectura: true` → `409 {"detail": "Primero lee la tarjeta"}`.

MCP: nueva herramienta `marcar_tarjeta_leida(pregunta_id)`; `ver_preguntas_pendientes` incluye `requiere_lectura` y `lectura`.

Flujo de la interfaz: si `requiere_lectura`, la tarjeta de la pregunta muestra **solo la lectura** (título, definición,
analogía, código e idea clave) y un botón **"Ya la leí, hazme la pregunta"**. Al pulsarlo (`POST .../leida`) la tarjeta pasa
a mostrar la pregunta y sus opciones **sin recargar**, y el foco del teclado va a la pregunta.

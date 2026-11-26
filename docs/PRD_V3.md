# PRD v3.0 — Tutor Adaptativo & Ecosistema MCP Profesional

**Versión:** 3.0.0  
**Repositorio:** `Mileidys10/agente-tutor-persistente`  
**Fecha:** 2026-11-26  
**Estado:** Implementado y verificado (v3.0.0)

---

## 1. Visión y Problema que Resuelve v3.0

La v2.0 resolvió la captura universal de código/apuntes y elevó el servidor MCP a 19 herramientas, 6 recursos y 5 prompts. Sin embargo, para llevar el agente tutor a nivel profesional de estudio continuo faltan cuatro capacidades clave:

1. **Estudiar cambios reales del repositorio (`git diff`)**: Un desarrollador no solo estudia funciones aisladas; aprende revisando los cambios reales entre commits o PRs.
2. **Andamiaje socrático progresivo (*Scaffolding*)**: Cuando un estudiante se bloquea ante una pregunta abierta o de código, la v2.0 solo permitía fallar o adivinar. Necesita **pistas progresivas de 3 niveles** con ajuste justo en la nota SM-2.
3. **Simulacros enfocados y grafo de conocimiento**: Antes de una entrevista o parcial, se necesita un **Modo Simulacro** (`sesiones_examen`) cronometrado con reporte persistente, además de un **grafo de prerrequisitos** (`relaciones_temas`) para que el agente no pregunte temas avanzados antes de dominar sus bases.
4. **Planificación diaria, portabilidad Anki y recordatorios proactivos**: Meta diaria (`TUTOR_META_DIARIA`), pronóstico de carga de los próximos 7 días, exportación directa a **Anki TSV (`.tsv`)** y notificaciones proactivas vía Webhook configurable por entorno (`TUTOR_WEBHOOK_URL`, máximo 1 al día, cero SSRF).

---

## 2. Los 4 Pilares de la Versión 3.0

### Pilar 1 — Ingesta de `git diff` + Pistas Socráticas Progresivas
- **`estudiar_diff`**: Recibe un `git diff` unificado (hasta `30 000` caracteres), detecta archivos modificados, lenguaje por extensión y bloques añadidos/modificados (`+`/`-`), generando fichas `tipo="codigo"` enfocadas en los cambios reales (con Gemini o parser local determinista).
- **`pedir_pista`**: Entrega hasta **3 niveles de pista progresiva** por pregunta pendiente sin regalar la respuesta literal:
  - Nivel 1: Enfoque conceptual / analogía.
  - Nivel 2: Idea clave o contexto técnico.
  - Nivel 3: Esqueleto enmascarado (inicial + longitud de palabras clave).
  - Ajuste SM-2 justo al responder: 1 pista limita la nota máxima a `4/5`; 2 o más pistas limitan la nota máxima a `3/5`.

### Pilar 2 — Modo Simulacro Persistente (`sesiones_examen`)
- **`iniciar_simulacro`**: Genera una sesión de examen de `1` a `20` preguntas enfocada por colección, categoría DevCards, solo brechas (`en_refuerzo`) o mezcla general, sin lectura previa obligatoria para medir recuerdo real.
- **`ver_simulacros` / `GET /api/examenes`**: Historial persistido con total de preguntas, respondidas, correctas, nota promedio, duración en segundos y lista de temas fallados.

### Pilar 3 — Grafo de Prerrequisitos y Planificador Diario + Pronóstico 7 Días
- **`vincular_temas` (`relaciones_temas`)**: Conecta temas (`prerrequisito` o `relacionado`), rechazando autorreferencias y ciclos directos. En `AgenteTutor.ciclo()`, si el tema B vencido depende del tema A aún no dominado (`intervalo_dias < 1` o `en_refuerzo`) y A también está vencido, el agente prioriza A primero (`+50` en prioridad) y lo explica en el `motivo`.
- **`plan_estudio_hoy` (`GET /api/plan`)**: Calcula meta diaria (`TUTOR_META_DIARIA`), avance de hoy (`%`), minutos estimados, racha diaria y pronóstico exacto de repasos por fecha para los próximos **7 días**.

### Pilar 4 — Anki TSV, Webhooks Proactivos, MCP v3 y Web UI v3
- **Exportación Anki TSV (`formato="anki"`)**: Exporta cualquier colección en formato tabular `Front\tBack\tTags` listo para importar en Anki.
- **Notificaciones proactivas (`TUTOR_WEBHOOK_URL`)**: Si se configura en variables de entorno (`http://` o `https://`), el ciclo autónomo envía máximo 1 resumen diario cuando existan pendientes o temas vencidos (cero SSRF al no aceptar URLs de usuario).
- **MCP v3.0 Completo**: **25 Tools** (todas con las 4 banderas booleanas de `ToolAnnotations` y 100% cubiertas en tests), **8 Resources** (`+ tutor://plan/hoy`, `+ tutor://examenes`) y **7 Prompts** (`+ estudiar_ultimo_diff`, `+ entrevista_tecnica`).
- **Web UI v3**: 4.ª pestaña *Estudiar git diff*, botón *Pedir pista* en preguntas, panel *Simulacro y Plan Diario* con barra de progreso y pronóstico 7d, y descarga *Anki (.tsv)*.

---

## 3. Mapa de Capacidades v3.0

| Módulo | Responsabilidad | Depende de |
|---|---|---|
| `diff-y-pistas` | Config v3, tablas/columnas v3 en `Memoria`, `parsear_git_diff_local`, `generar_pista_progresiva`, `estudiar_diff` y `pedir_pista` con tope SM-2. | Base v2.0 |
| `simulacro-grafo-plan` | `sesiones_examen`, `relaciones_temas` con anti-ciclo y boost de prerrequisitos en `ciclo()`, y `plan_estudio_hoy` con pronóstico 7 días. | `diff-y-pistas` |
| `anki-webhooks-mcp-v3` | Exportación `anki` TSV, `_notificar_si_corresponde()` por `TUTOR_WEBHOOK_URL`, 25 Tools anotadas, 8 Resources y 7 Prompts en `app/mcp_tools.py`. | `diff-y-pistas`, `simulacro-grafo-plan` |
| `web-v3-y-cierre` | Web UI v3 (tab diff, pistas, simulacro, plan 7d, Anki), privacidad/docs actualizadas, suite completa `pytest`, Sprint Log y push `v3.0.0`. | `anki-webhooks-mcp-v3` |

---

## 4. Criterios de Éxito v3.0

1. Enviar un `git diff` produce fichas por archivo/bloque vía Web y MCP `estudiar_diff`, funcionando al 100% sin `GEMINI_API_KEY`.
2. Pedir hasta 3 pistas en cualquier pregunta pendiente guía sin regalar la respuesta y aplica el tope justo en SM-2.
3. Los simulacros persisten avance, calificación promedio y duración tras reinicios del servidor.
4. El grafo de prerrequisitos prioriza bases no dominadas sobre temas dependientes y rechaza ciclos.
5. El servidor MCP expone **25 Tools** (4 hints booleanos en todas), **8 Resources** y **7 Prompts**, y toda la suite `pytest -v` pasa al 100%.

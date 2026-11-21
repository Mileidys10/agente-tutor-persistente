# Guion de Exposición en Vivo (5 minutos)

Este guion está pensado para presentar **Agente Tutor Persistente** en clase con una demostración real funcionando frente al público (en local o ya desplegado en Render).

---

## Preparación previa (antes de empezar a hablar)

1. Ten abierta la página principal del agente en el navegador (idealmente con `TUTOR_MINUTOS_POR_DIA=1` y `TUTOR_INTERVALO_S=15` o `20`, como viene configurado en `render.yaml` para la demo).
2. Ten lista una terminal (si la demo es en local o Docker) para poder detener y volver a levantar el servidor en el **Minuto 2:15**, o ten la URL pública de Render + una base limpia/preparada.
3. Si el servidor usa `TUTOR_TOKEN`, deja la clave copiada o ya guardada en el navegador para no perder tiempo tecleando contraseñas.

---

## Minuto 0:00 – 1:00 | Problema y diferencia frente a un chatbot

**Qué mostrar en pantalla**: La cabecera del navegador con la píldora **«Agente vivo»**, el contador de ciclos subiendo y la frase *«Desperté N veces y recuerdo todo»*.

**Qué decir**:
> «Cuando estudiamos con un chat de IA tradicional, en el momento en que cerramos la pestaña el modelo olvida qué estudiamos ayer, qué fallamos hace cinco minutos y qué deberíamos repasar hoy. Eso es un asistente reactivo, no un agente persistente.
>
> Nosotros construimos **Agente Tutor Persistente**. Tiene tres características que lo separan de un chat común: primero, corre con un **reloj propio en segundo plano** mediante el ciclo *percibir → decidir → actuar*; segundo, toda su memoria vive en una base **PostgreSQL** real, no en variables temporales de Python; y tercero, decide por iniciativa propia qué preguntarte aplicando el algoritmo de repetición espaciada **SM-2**.»

---

## Minuto 1:00 – 2:15 | Demo en vivo: ciclo autónomo y DevCards

**Qué hacer en pantalla**:
1. En **«Mis temas»**, escribe rápido un tema propio (por ejemplo: *«Índices B-Tree»* con la nota *«Aceleran búsquedas por rango y mantienen las claves ordenadas»*) y pulsa **«Agregar tema»**.
2. En **«Mazos DevCards»**, busca una categoría (por ejemplo *«SQL»* o *«Python»*) y pulsa su interruptor para dejarla en **«Activo»**.
3. Señala la bitácora y pulsa **«Ejecutar un ciclo ahora»** (o deja que el reloj automático complete el siguiente ciclo en pantalla).

**Qué decir**:
> «Acabo de darle un tema propio y activar un mazo del banco integrado de **1 295 tarjetas DevCards** en 42 categorías. Si observan sin que yo pregunte nada, el hilo autónomo despierta cada pocos segundos, revisa qué temas están vencidos y cuántos huecos quedan disponibles.
>
> Al ejecutarse el ciclo, en la sección **Estudiar** aparece la pregunta y, justo encima, la razón explícita por la que el agente la eligió hoy. Abajo, en la **Bitácora del agente**, queda registrada la decisión con su hora exacta.»

---

## Minuto 2:15 – 3:30 | La prueba de fuego: reinicio en vivo del servidor

**Qué hacer en pantalla**:
1. Cambia un segundo a la terminal donde corre `uvicorn` (o `docker compose`) y detén el proceso (`Ctrl+C`), y vuelve a arrancarlo de inmediato (en Render basta un *Manual Deploy* rápido o mostrar un segundo arranque ya ejecutado si hay poco tiempo).
2. Regresa al navegador y recarga o espera el refresco automático de 5 segundos.

**Qué decir**:
> «Aquí es donde demostramos que no es una sesión en memoria RAM. Acabo de matar el proceso del servidor por completo y volverlo a iniciar. Si fuera un script normal con listas en memoria, todo habría desaparecido.
>
> Sin embargo, al reconectar la página miren la cabecera: el contador acaba de subir a **«Desperté N veces y recuerdo todo»**, y en la bitácora el agente dejó escrito el mensaje de arranque indicando exactamente cuántos temas, preguntas pendientes y ciclos previos recordó de PostgreSQL.»

---

## Minuto 3:30 – 4:30 | Respuesta y reprogramación adaptativa SM-2

**Qué hacer en pantalla**:
1. Responde la pregunta de opción múltiple de la tarjeta DevCard pulsando la letra (`A`, `B`, `C` o `D`) y responde la pregunta abierta de tu tema propio.
2. Señala la tarjeta verde/ámbar de retroalimentación con la **nota (0–5)**, la **respuesta esperada** y el **próximo repaso SM-2**.
3. En **«Progreso»** y **«Mis temas»**, muestra cómo el tema recién respondido ya tiene su nuevo intervalo y facilidad calculados (`1 minuto` en modo demo si acertaste por primera vez, o reinicio a `1 día de estudio` con menor facilidad si fallaste).

**Qué decir**:
> «En las tarjetas DevCards de opción múltiple el agente corrige al instante y muestra la idea clave. En preguntas abiertas evalúa de 0 a 5 —usando Gemini si hay clave configurada, o su motor determinista local si exponemos sin internet—.
>
> Con esa nota ejecuta el algoritmo **SM-2**: calcula la nueva facilidad y reprograma el próximo repaso. Como en la demo configuramos `TUTOR_MINUTOS_POR_DIA=1`, un día de repaso equivale a un minuto real; si esperamos sesenta segundos o bajamos a ver la lista de temas, veremos que el tema vuelve a marcarse como vencido y el agente nos lo vuelve a preguntar por iniciativa propia.»

---

## Minuto 4:30 – 5:00 | Arquitectura 24/7, MCP y cierre

**Qué mostrar en pantalla**: La arquitectura en el `README.md` (opcional) o el enlace al pie hacia `/docs` y `/privacidad`.

**Qué decir**:
> «Para que este agente funcione 24/7 sin pagar servidor dedicado, lo empaquetamos con `render.yaml` sobre PostgreSQL gratuito y añadimos en GitHub Actions un workflow llamado `despertador.yml` que visita `/health` cada diez minutos para evitar que Render lo suspenda. Además, expone el endpoint `/mcp` para estudiar el mismo progreso directamente desde Claude Desktop o Claude Code sin duplicar base de datos. Con esto concluimos; quedamos atentos a sus preguntas.»

---

## Preguntas frecuentes del profesor o jurado (respuestas rápidas)

- **«¿Qué pasa si se cae la API de Gemini o no hay internet en el salón?»**
  El módulo `app/cerebro.py` captura cualquier fallo HTTP o ausencia de `GEMINI_API_KEY` y cambia de forma transparente al motor local determinista para generar preguntas de completado y calificar respuestas por cobertura de conceptos clave. Las DevCards de opción múltiple se corrigen localmente siempre.
- **«¿Cómo evitan que alguien borre temas o consuma cuota sin permiso en Render?»**
  Todas las rutas que escriben (`POST`, `PUT`, `DELETE`) y el endpoint `/mcp` validan la cabecera `X-Tutor-Token` o `Authorization: Bearer` usando comparación en tiempo constante (`hmac.compare_digest`) contra `TUTOR_TOKEN`, autogenerada por `render.yaml`.
- **«¿Cuál es la diferencia entre `docker-compose.yml` y SQLite en pruebas?»**
  `app/memoria.py` usa SQLAlchemy Core: en desarrollo rápido o `pytest` usa SQLite en un archivo local, mientras que en Docker Compose y en Render usa PostgreSQL 16 adaptado automáticamente a `postgresql+psycopg://`.

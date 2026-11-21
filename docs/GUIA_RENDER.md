# Guía paso a paso para desplegar en Render (desde cero)

Esta guía está pensada para quien nunca ha usado **Render** ni desplegado una aplicación en la nube. Si sigues estos pasos en orden, tendrás el **Agente Tutor Persistente** funcionando 24/7 con base de datos PostgreSQL gratuita y listo para la exposición.

---

## Paso 1: Crear tu cuenta en Render entrando con GitHub

1. Entra a [https://render.com/](https://render.com/) y pulsa **Get Started** (o **Sign In**).
2. Elige **Continue with GitHub** e inicia sesión con la cuenta donde está tu repositorio (`Mileidys10`).
3. Autoriza a Render para leer tus repositorios cuando GitHub te lo pida. Entrar con GitHub ahorra pasos porque conecta los despliegues directamente con tu código.

---

## Paso 2: Crear el proyecto con Blueprint (`New > Blueprint`)

Este repositorio ya trae un archivo llamado `render.yaml` con toda la arquitectura escrita, así que no tienes que configurar servidores a mano.

1. En el panel superior de Render, haz clic en el botón **New +** y elige **Blueprint**.
2. Busca en la lista el repositorio **`Mileidys10/agente-tutor-persistente`** y pulsa **Connect**.
3. En **Blueprint Name**, puedes dejar `agente-tutor-persistente` y revisar la pantalla antes de confirmar.

---

## Paso 3: Qué va a crear Render automáticamente (`render.yaml`)

Al usar el Blueprint, Render creará **dos recursos en el plan gratuito (`free`)**:

1. **Servicio web `agente-tutor-persistente`** (`runtime: python`, versión `3.12.8`):
   - Instala las dependencias con `pip install -r requirements.txt`.
   - Arranca el servidor y el hilo autónomo del agente con `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
   - Vigila la salud de la app en la ruta `/health`.
   - Configura `TUTOR_INTERVALO_S=20` (el agente despierta cada 20 segundos) y `TUTOR_MINUTOS_POR_DIA=1` (**modo demo**: 1 «día» de repetición espaciada dura 1 minuto para poder ver regresar los temas en clase; para uso real diario se cambia después a `1440`).
2. **Base de datos PostgreSQL `tutor-memoria`** (`plan: free`):
   - Es la memoria persistente donde viven tus temas, preguntas, respuestas, progreso SM-2, bitácora y contador de arranques.
   - Render conecta automáticamente la variable `DATABASE_URL` del servicio web con esta base (y `app/config.py` adapta el prefijo `postgres://` o `postgresql://` a `postgresql+psycopg://` por ti).

Además, Render generará de forma automática una contraseña aleatoria para `TUTOR_TOKEN`.

---

## Paso 4: Qué poner en `GEMINI_API_KEY` (opcional)

Durante la creación del Blueprint, Render solo te pedirá rellenar una variable: **`GEMINI_API_KEY`** (porque está marcada con `sync: false`). Tienes dos opciones:

- **Opción A — Dejarla vacía (recomendada si quieres cero configuraciones extra)**:
  Puedes escribir nada o continuar sin clave (si la interfaz de Render exige un carácter para avanzar o te deja dejarlo vacío, déjalo vacío; si luego quieres quitarla, en **Environment** basta dejar su valor vacío). Sin clave de Gemini, el agente sigue funcionando completo: genera preguntas con su **motor determinista local** y usa las **1 295 tarjetas DevCards** de opción múltiple con corrección inmediata.
- **Opción B — Poner una clave gratuita de Google AI Studio**:
  1. Entra a [https://aistudio.google.com/](https://aistudio.google.com/) con tu cuenta de Google.
  2. En el menú lateral o botón superior haz clic en **Get API key** y luego **Create API key**.
  3. Copia la clave generada y pégala en el campo `GEMINI_API_KEY` en Render. Con esto las preguntas abiertas y su retroalimentación serán redactadas por el modelo configurado (`gemini-2.5-flash` por defecto en `app/config.py`).

Pulsa **Deploy Blueprint** (o **Apply**) para iniciar el despliegue.

---

## Paso 5: Esperar el build y comprobar que terminó bien

1. Render empezará primero a crear la base de datos `tutor-memoria` y luego a construir el servicio web `agente-tutor-persistente`. Esto suele tardar entre **2 y 5 minutos**.
2. En la pantalla del servicio verás los registros del build. Cuando termine, aparecerá arriba una etiqueta verde que dice **Live** y la URL pública de tu aplicación (algo parecido a `https://agente-tutor-persistente.onrender.com`).
3. Para comprobar que todo arrancó sin fallos, abre en una pestaña nueva:
   `https://<tu-url-de-render>/health`
   Debe responder un JSON parecido a:
   ```json
   {"ok": true, "agente_vivo": true, "ciclos": 1, "arranques": 1, "ultimo_ciclo": "..."}
   ```
4. Después abre la página principal `https://<tu-url-de-render>/`. Deberías ver la cabecera con **«Agente vivo»** y **«Desperté 1 vez y recuerdo todo»**.

---

## Paso 6: Dónde ver el `TUTOR_TOKEN` generado (la clave para usar la página)

Como el repositorio se despliega en una URL pública, nadie externo debería poder borrar tus temas ni consumir ciclos sin permiso. Por eso `render.yaml` genera una clave secreta en **`TUTOR_TOKEN`**.

1. En el panel de Render, entra al servicio web **`agente-tutor-persistente`**.
2. En el menú izquierdo haz clic en **Environment**.
3. Busca la fila **`TUTOR_TOKEN`**, pulsa el icono de ojo (o copiar) para ver su valor y cópialo.
4. En tu página web publicada:
   - Cualquiera puede **ver** el estado, las preguntas y la bitácora, pero cuando intentes **agregar un tema, responder una pregunta, activar un mazo DevCards o pulsar «Ejecutar un ciclo ahora»**, la página te abrirá la ventana **«Clave de acceso»** (o puedes abrirla tú desde el botón superior **«Clave de acceso»**).
   - Pega ese valor de `TUTOR_TOKEN` y pulsa **Verificar y guardar**. El navegador la comprobará contra `/api/acceso` y la recordará localmente para que no tengas que volver a escribirla durante la clase.

---

## Paso 7: Activar el «despertador» en GitHub Actions

En el plan gratuito, Render duerme el servicio web si pasa **15 minutos sin recibir visitas**. Este proyecto incluye el workflow `.github/workflows/despertador.yml` para visitar `/health` cada **10 minutos** y mantener al agente vivo trabajando en segundo plano.

Para activarlo:

1. Ve a tu repositorio en GitHub: **`https://github.com/Mileidys10/agente-tutor-persistente`**.
2. Entra en **Settings** (arriba a la derecha del repositorio).
3. En el menú izquierdo entra en **Secrets and variables > Actions**.
4. Haz clic en la pestaña **Variables** (importante: es **Variables**, no *Secrets*, porque el workflow lee `${{ vars.TUTOR_URL }}`).
5. Pulsa **New repository variable**.
6. Rellena exactamente:
   - **Name**: `TUTOR_URL`
   - **Value**: tu URL pública de Render **sin barra `/` al final** (ejemplo correcto: `https://agente-tutor-persistente.onrender.com`; incorrecto si termina en `/`).
7. Pulsa **Add variable**.
8. Para probarlo al instante sin esperar 10 minutos, ve a la pestaña **Actions** en GitHub, selecciona **`despertador`** en la izquierda, pulsa **Run workflow > Run workflow** y verifica que termine en verde.

---

## Paso 8: Cómo comprobar la persistencia en vivo en la exposición

Durante la presentación en clase puedes demostrar frente al profesor y el público que el agente no pierde la memoria aunque el servidor se apague y vuelva a arrancar:

1. Con la página abierta, muestra un tema recién agregado, una pregunta pendiente y el texto en la cabecera: **«Desperté N veces y recuerdo todo»**.
2. Abre la pestaña de **Render** en tu servicio `agente-tutor-persistente`.
3. Arriba a la derecha haz clic en **Manual Deploy > Restart service**.
4. Espera unos segundos a que Render reinicie el contenedor y vuelva a mostrar **Live**.
5. Regresa a la página web de tu aplicación y recarga (o espera 5 segundos al refresco automático):
   - El contador de la cabecera habrá subido a **`N + 1` veces**.
   - Tus temas, respuestas anteriores, progreso SM-2 y bitácora seguirán intactos.
   - En la primera línea de **«Bitácora del agente»** verás el registro del sistema indicando cuántos temas, preguntas pendientes y ciclos previos recordó de `tutor-memoria`.

---

## Paso 9: Limitaciones reales del plan gratis y qué hacer la mañana de la presentación

Ten en cuenta estas tres condiciones reales del plan **Free** de Render para no llevarte sorpresas:

1. **Primer despertar de ~50 segundos**: si el servicio llegó a suspenderse por inactividad (o si pasó tiempo sin despertador), la primera visita tarda unos **50 segundos** mientras Render enciende el contenedor. Después responde normal.
2. **La base PostgreSQL gratis caduca a los 30 días**: Render mantiene vivas las bases `free` durante **30 días** desde su creación. Para la exposición universitaria funciona sin costo; pasado ese mes habría que crear una nueva o actualizar a plan pago si quieres conservar los datos históricos.
3. **750 horas gratis al mes de servicio web**: alcanza justo para un único servicio web encendido todo el mes (`31 días × 24 horas = 744 horas`), pero si tienes otros servicios web gratuitos en la misma cuenta de Render, todos comparten esa bolsa mensual de 750 horas.

### Checklist rápida la mañana de la presentación

- **Abre tu URL pública al menos 5 minutos antes** de empezar a exponer para despertar el servicio si hiciera falta y verificar que `/health` responde `{"ok": true, ...}`.
- **Guarda tu `TUTOR_TOKEN`** en el navegador que usarás en la presentación pulsando **«Clave de acceso»** y probando agregar o revisar un tema de prueba.
- Ten abierta en una segunda pestaña la consola de Render (`agente-tutor-persistente`) por si quieres hacer el **Manual Deploy > Restart service** en un solo clic durante el minuto de prueba de persistencia.

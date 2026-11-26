// Archivo app/static/app.js: lógica del navegador que conecta index.html con la API de FastAPI (app/main.py).
// Refresca los datos cada 5 segundos sin recargar la página y construye todo usando textContent para evitar XSS.
"use strict";

(() => {
  // Constantes y estado temporal en memoria del navegador.
  const CLAVE_STORAGE = "agente_tutor_token";
  const LETRAS = "ABCDEFGH";
  const INTERVALO_REFRESCO_MS = 5000;

  let tokenEnMemoria = "";
  let mazosCache = [];
  let temasCache = [];
  let coleccionesCache = [];
  let confirmandoBorradoId = null;
  let editandoTemaId = null;
  let accionPendiente = null;
  let temporizadorAviso = null;
  let recargaEnCurso = false;
  const leidasLocalmente = new Set();

  // Formateador de fechas y horas en español para mostrar cuándo ocurrió cada evento.
  const formatoFechaHora = new Intl.DateTimeFormat("es", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  // Atajo para buscar un elemento del HTML por su atributo id.
  function el(id) {
    return document.getElementById(id);
  }

  // Crea un nodo HTML limpio y coloca su texto con textContent (nunca innerHTML) para mayor seguridad.
  function crear(etiqueta, clase, texto) {
    const nodo = document.createElement(etiqueta);
    if (clase) nodo.className = clase;
    if (texto !== undefined && texto !== null) nodo.textContent = String(texto);
    return nodo;
  }

  // Comprueba si el usuario tiene el cursor o foco del teclado dentro de un bloque para no interrumpirlo al refrescar.
  function contieneFoco(contenedor) {
    const activo = document.activeElement;
    return Boolean(activo && contenedor && contenedor.contains(activo));
  }

  // ---- Token y almacenamiento seguro ----------------------------------------
  // Lee la clave de acceso (TUTOR_TOKEN) desde memoria o localStorage para enviarla en la cabecera X-Tutor-Token.
  function obtenerToken() {
    if (tokenEnMemoria) return tokenEnMemoria;
    try {
      tokenEnMemoria = window.localStorage.getItem(CLAVE_STORAGE) || "";
    } catch (_) {
      tokenEnMemoria = "";
    }
    return tokenEnMemoria;
  }

  // Guarda o borra la clave de acceso en localStorage (si el navegador lo bloquea, queda solo en memoria).
  function guardarToken(valor) {
    tokenEnMemoria = valor || "";
    try {
      if (tokenEnMemoria) {
        window.localStorage.setItem(CLAVE_STORAGE, tokenEnMemoria);
      } else {
        window.localStorage.removeItem(CLAVE_STORAGE);
      }
    } catch (_) {
      // Si localStorage está restringido, el token queda en memoria de esta sesión.
    }
  }

  // ---- Formato de fechas y etiquetas ----------------------------------------
  // Convierte una cadena ISO en UTC enviada por FastAPI a un objeto Date válido.
  function parsearFecha(iso) {
    if (!iso) return null;
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  // Convierte una fecha ISO en reloj local legible ("20/11, 21:45:10").
  function formatearFecha(iso) {
    const d = parsearFecha(iso);
    return d ? formatoFechaHora.format(d) : "—";
  }

  // Muestra cuánto falta o cuánto pasó desde una fecha ("en 45 s", "hace 2 min") para demostrar SM-2 en vivo.
  function formatearRelativo(iso) {
    const d = parsearFecha(iso);
    if (!d) return "—";
    const diffS = Math.round((d.getTime() - Date.now()) / 1000);
    if (diffS <= 0) {
      const atras = Math.abs(diffS);
      if (atras < 60) return `hace ${atras} s`;
      if (atras < 3600) return `hace ${Math.round(atras / 60)} min`;
      return `hace ${Math.round(atras / 3600)} h`;
    }
    if (diffS < 60) return `en ${diffS} s`;
    if (diffS < 3600) return `en ${Math.round(diffS / 60)} min`;
    if (diffS < 86400) return `en ${(diffS / 3600).toFixed(1)} h`;
    return `en ${(diffS / 86400).toFixed(1)} días`;
  }

  // Elige el texto y color de la píldora según quién creó la pregunta (Gemini, DevCards o Motor local).
  function formatearFuente(fuente) {
    if (fuente === "gemini") return { texto: "Gemini", clase: "pildora pildora-azul" };
    if (fuente === "devcards") return { texto: "DevCards", clase: "pildora pildora-ok" };
    return { texto: "Motor local", clase: "pildora pildora-neutra" };
  }

  // Asigna color visual a cada tipo de evento de la bitácora del agente.
  function claseTipoBitacora(tipo) {
    switch (tipo) {
      case "evaluacion":
        return "pildora pildora-ok";
      case "decision":
        return "pildora pildora-azul";
      case "pregunta":
        return "pildora pildora-aviso";
      case "reflexion":
        return "pildora pildora-aviso";
      case "error":
        return "pildora pildora-error";
      case "sistema":
        return "pildora pildora-azul";
      default:
        return "pildora pildora-neutra";
    }
  }

  // ---- Avisos en pantalla ---------------------------------------------------
  // Muestra un banner temporal arriba indicando si una operación salió bien o dio error.
  function mostrarAvisoGlobal(texto, esError = false) {
    const aviso = el("aviso-global");
    aviso.textContent = texto;
    aviso.classList.toggle("aviso-error", Boolean(esError));
    aviso.hidden = !texto;
    if (temporizadorAviso) clearTimeout(temporizadorAviso);
    if (texto) {
      temporizadorAviso = setTimeout(() => {
        aviso.hidden = true;
      }, 6500);
    }
  }

  // ---- Cliente HTTP ---------------------------------------------------------
  // Envía todas las peticiones fetch al backend añadiendo X-Tutor-Token; si recibe 401 pide la clave y reintenta.
  async function peticion(ruta, opciones = {}, reintento = null) {
    const headers = new Headers(opciones.headers || {});
    const token = obtenerToken();
    if (token) {
      headers.set("X-Tutor-Token", token);
    }
    if (opciones.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    const resp = await fetch(ruta, { ...opciones, headers });
    if (resp.status === 401) {
      abrirDialogoToken(
        "El servidor requiere la clave de acceso para guardar cambios.",
        reintento
      );
      const err = new Error("Clave de acceso requerida");
      err.status = 401;
      throw err;
    }

    if (!resp.ok) {
      let detalle = `Error HTTP ${resp.status}`;
      try {
        const datos = await resp.json();
        if (datos && datos.detail) {
          detalle = typeof datos.detail === "string" ? datos.detail : JSON.stringify(datos.detail);
        }
      } catch (_) {
        // Sin cuerpo JSON
      }
      const err = new Error(detalle);
      err.status = resp.status;
      throw err;
    }
    return resp.json();
  }

  // ---- Diálogo de clave de acceso -------------------------------------------
  // Abre la ventana modal para escribir TUTOR_TOKEN y guarda la acción que se reintentará al validar.
  function abrirDialogoToken(mensaje, reintento = null) {
    accionPendiente = typeof reintento === "function" ? reintento : null;
    const dlg = el("dialogo-token");
    const errorEl = el("error-token");
    errorEl.hidden = true;
    errorEl.textContent = "";
    el("desc-token").textContent =
      mensaje ||
      "Si el servidor tiene configurada la variable TUTOR_TOKEN, introduce la clave para agregar temas, responder o activar mazos.";
    el("input-token").value = obtenerToken();

    if (typeof dlg.showModal === "function") {
      if (!dlg.open) dlg.showModal();
    } else {
      dlg.setAttribute("open", "open");
    }
    el("input-token").focus();
  }

  // Cierra el diálogo modal de clave de acceso y limpia cualquier acción pendiente.
  function cerrarDialogoToken() {
    const dlg = el("dialogo-token");
    accionPendiente = null;
    if (typeof dlg.close === "function") {
      if (dlg.open) dlg.close();
    } else {
      dlg.removeAttribute("open");
    }
  }

  // Valida la clave escrita llamando a GET /api/acceso; si es correcta la guarda y ejecuta el reintento pendiente.
  async function manejarEnvioToken(evento) {
    evento.preventDefault();
    const input = el("input-token");
    const clave = input.value.trim();
    const errorEl = el("error-token");
    const btn = el("btn-guardar-token");

    errorEl.hidden = true;
    errorEl.textContent = "";
    btn.disabled = true;

    try {
      const headers = new Headers();
      if (clave) {
        headers.set("X-Tutor-Token", clave);
      }
      const resp = await fetch("/api/acceso", { headers });
      if (resp.status === 401) {
        errorEl.textContent = "Clave incorrecta. Verifica TUTOR_TOKEN e inténtalo de nuevo.";
        errorEl.hidden = false;
        input.focus();
        return;
      }
      if (!resp.ok) {
        errorEl.textContent = `No se pudo comprobar la clave (HTTP ${resp.status}).`;
        errorEl.hidden = false;
        return;
      }
      guardarToken(clave);
      const continuar = accionPendiente;
      cerrarDialogoToken();
      mostrarAvisoGlobal(clave ? "Clave verificada y guardada en este navegador." : "Acceso abierto verificado.");
      if (continuar) {
        await continuar();
      } else {
        await cargarTodo(true);
      }
    } catch (_) {
      errorEl.textContent = "Error de conexión al verificar la clave.";
      errorEl.hidden = false;
    } finally {
      btn.disabled = false;
    }
  }

  // ---- Renderizado: Cabecera y Estado ---------------------------------------
  // Actualiza la cabecera con los datos de GET /api/estado ("Desperté N veces...", ciclos, cerebro y BD).
  function renderizarEstado(estado) {
    const vivo = Boolean(estado.vivo);
    const pildoraVida = el("estado-vida");
    pildoraVida.textContent = vivo ? "Agente vivo" : "En pausa";
    pildoraVida.className = vivo ? "pildora pildora-ok" : "pildora pildora-aviso";

    const latido = estado.latido || {};
    const arranques = Number(latido.arranques || 0);
    const ciclos = Number(latido.ciclos || 0);

    el("frase-despertar").textContent =
      arranques === 1
        ? "Desperté 1 vez y recuerdo todo"
        : `Desperté ${arranques} veces y recuerdo todo`;

    el("stat-ciclos").textContent = String(ciclos);
    el("stat-ultimo-ciclo").textContent = latido.ultimo_ciclo
      ? `${formatearRelativo(latido.ultimo_ciclo)} (${formatearFecha(latido.ultimo_ciclo)})`
      : "Aún sin ciclos";
    el("stat-cerebro").textContent = estado.cerebro || "—";
    el("stat-bd").textContent = estado.base_de_datos || "—";

    const cfg = estado.configuracion || {};
    const intervalo = cfg.intervalo_ciclo_s !== undefined ? `${cfg.intervalo_ciclo_s}s` : "?";
    const escala = cfg.minutos_por_dia !== undefined ? `${cfg.minutos_por_dia} min/día` : "?";
    el("stat-ritmo").textContent = `cada ${intervalo} · ${escala}`;

    if (typeof estado.banco_devcards === "number") {
      el("pie-devcards").textContent = estado.banco_devcards.toLocaleString("es");
    }
  }

  // ---- Renderizado: Preguntas pendientes (preservando foco y texto) ----------
  // Mensaje guía cuando no hay ninguna pregunta esperando en el panel "Estudiar".
  function crearVacioPreguntas() {
    return crear(
      "p",
      "estado-vacio",
      "No hay preguntas pendientes ahora mismo. Agrega un tema en «Mis temas», activa un mazo de DevCards o pulsa «Ejecutar un ciclo ahora»."
    );
  }

  // Dibuja la tarjeta verde o ámbar con tu calificación (0-5), respuesta esperada y nueva fecha SM-2.
  function mostrarResultadoRespuesta(res) {
    const caja = el("resultado-respuesta");
    const esCorrecta = Boolean(res.correcta);
    caja.className = `resultado-respuesta ${esCorrecta ? "es-correcta" : "es-repasar"}`;
    caja.hidden = false;

    const cab = crear("div", "resultado-cabecera");
    const meta = crear("div", "resultado-meta");
    meta.appendChild(
      crear("span", `pildora ${esCorrecta ? "pildora-ok" : "pildora-aviso"}`, esCorrecta ? "Correcta" : "Por reforzar")
    );
    meta.appendChild(crear("span", "pildora pildora-neutra", `Nota: ${res.nota}/5`));
    meta.appendChild(crear("span", "pildora pildora-azul", `Evaluado por: ${res.evaluado_por || "tutor"}`));

    const btnCerrar = crear("button", "btn btn-terciario", "Ocultar");
    btnCerrar.type = "button";
    btnCerrar.addEventListener("click", () => {
      caja.hidden = true;
      caja.replaceChildren();
      // El botón enfocado desaparece: el foco pasa a la siguiente pregunta o al título de la sección.
      const siguiente = el("lista-preguntas").querySelector("button:not([disabled]), textarea:not([disabled])");
      enfocar(siguiente || el("titulo-estudiar"));
    });

    cab.append(meta, btnCerrar);

    const pTema = crear("p", "resultado-detalle");
    const strongTema = crear("strong", "", "Tema: ");
    pTema.append(strongTema, document.createTextNode(res.tema || ""));

    const pRetro = crear("p", "resultado-detalle", res.retroalimentacion || "");

    const pEsperada = crear("p", "resultado-detalle");
    const strongEsp = crear("strong", "", "Respuesta esperada: ");
    pEsperada.append(strongEsp, document.createTextNode(res.respuesta_esperada || ""));

    const pSm2 = crear(
      "p",
      "resultado-sm2",
      `Próximo repaso SM-2: ${formatearRelativo(res.proximo_repaso)} (${formatearFecha(res.proximo_repaso)}) · Intervalo: ${res.intervalo_dias} día(s) de estudio · Facilidad: ${Number(res.facilidad).toFixed(2)}`
    );

    caja.replaceChildren(cab, pTema, pRetro, pEsperada, pSm2);
    // La tarjeta respondida se retira de la lista; sin esto el foco del teclado caería en <body> (WCAG 2.4.3).
    caja.tabIndex = -1;
    enfocar(caja);
  }

  // Coloca el foco del teclado en un elemento accesible (necesario cuando cambia la tarjeta sin recargar).
  function enfocar(nodo) {
    if (!nodo) {
      return;
    }
    if (!nodo.hasAttribute("tabindex") && !/^(BUTTON|TEXTAREA|INPUT|A|SELECT)$/.test(nodo.tagName)) {
      nodo.tabIndex = -1;
    }
    nodo.focus({ preventScroll: false });
  }

  // Envía la letra elegida o el texto escrito a POST /api/preguntas/{id}/responder y muestra el resultado SM-2.
  async function enviarRespuesta(preguntaId, textoRespuesta, tarjetaNodo) {
    if (tarjetaNodo) {
      tarjetaNodo.dataset.enviando = "1";
      for (const ctrl of tarjetaNodo.querySelectorAll("button, textarea")) {
        ctrl.disabled = true;
      }
    }

    try {
      const res = await peticion(
        `/api/preguntas/${preguntaId}/responder`,
        {
          method: "POST",
          body: JSON.stringify({ respuesta: textoRespuesta }),
        },
        () => enviarRespuesta(preguntaId, textoRespuesta, tarjetaNodo)
      );
      mostrarResultadoRespuesta(res);
      mostrarAvisoGlobal(`Respuesta evaluada para «${res.tema}» (nota ${res.nota}/5).`);
      if (tarjetaNodo && tarjetaNodo.parentNode) {
        tarjetaNodo.remove();
      }
      await cargarTodo(true);
    } catch (err) {
      if (err.status !== 401) {
        mostrarAvisoGlobal(err.message || "No se pudo enviar la respuesta.", true);
      }
      if (tarjetaNodo) {
        delete tarjetaNodo.dataset.enviando;
        for (const ctrl of tarjetaNodo.querySelectorAll("button, textarea")) {
          ctrl.disabled = false;
        }
      }
    }
  }

  // Decide si una tarjeta pendiente debe mostrar primero la ficha de lectura antes de la pregunta.
  function esModoLectura(p) {
    return Boolean(p && p.requiere_lectura && p.lectura && !leidasLocalmente.has(String(p.id)));
  }

  // Llama a POST /api/preguntas/{id}/leida al pulsar "Ya la leí, hazme la pregunta" y transforma la tarjeta al instante.
  async function marcarTarjetaLeida(p, art, btn) {
    if (btn) btn.disabled = true;
    if (art) art.dataset.enviando = "1";
    try {
      await peticion(
        `/api/preguntas/${p.id}/leida`,
        { method: "POST" },
        () => marcarTarjetaLeida(p, art, btn)
      );
      leidasLocalmente.add(String(p.id));
      p.requiere_lectura = false;
      if (art) {
        delete art.dataset.enviando;
        rellenarTarjetaPregunta(art, p, true);
      }
      mostrarAvisoGlobal("Tarjeta leída. Ya puedes responder la pregunta.");
    } catch (err) {
      if (art) delete art.dataset.enviando;
      if (btn) btn.disabled = false;
      if (err.status !== 401) {
        mostrarAvisoGlobal(err.message || "No se pudo marcar la tarjeta como leída.", true);
      }
    }
  }

  // Rellena la tarjeta con SOLO la ficha de estudio (título, definición, analogía, código en <pre><code> e idea clave).
  function rellenarTarjetaLectura(art, p) {
    const lec = p.lectura || {};
    art.dataset.modo = "lectura";
    art.className = "tarjeta-pregunta tarjeta-lectura";

    const hijos = [];
    const cab = crear("div", "lectura-cabecera");
    cab.appendChild(crear("span", "pildora pildora-azul", "Lectura previa"));
    if (lec.categoria) {
      cab.appendChild(crear("span", "pildora pildora-ok", lec.categoria));
    }
    if (lec.dificultad) {
      cab.appendChild(crear("span", "pildora pildora-neutra", lec.dificultad));
    }
    hijos.push(cab);

    if (p.motivo) {
      hijos.push(crear("p", "pregunta-motivo", `Por qué te la presento: ${p.motivo}`));
    }

    hijos.push(crear("h3", "lectura-titulo", lec.titulo || p.tema || `Tarjeta #${p.tema_id}`));

    if (lec.definicion) {
      hijos.push(crear("p", "lectura-definicion", lec.definicion));
    }

    if (lec.analogia) {
      const bloqueAnalogia = crear("div", "lectura-bloque lectura-analogia");
      bloqueAnalogia.appendChild(crear("span", "lectura-etiqueta", "Piénsalo así"));
      bloqueAnalogia.appendChild(crear("p", "lectura-cuerpo", lec.analogia));
      hijos.push(bloqueAnalogia);
    }

    if (lec.codigo) {
      const pre = crear("pre", "lectura-codigo");
      pre.appendChild(crear("code", "", lec.codigo));
      hijos.push(pre);
    }

    if (lec.idea_clave) {
      const bloqueIdea = crear("div", "lectura-bloque lectura-idea-clave");
      bloqueIdea.appendChild(crear("span", "lectura-etiqueta", "Idea clave"));
      bloqueIdea.appendChild(crear("p", "lectura-cuerpo", lec.idea_clave));
      hijos.push(bloqueIdea);
    }

    const acciones = crear("div", "lectura-acciones");
    const btn = crear("button", "btn btn-primario btn-ya-lei", "Ya la leí, hazme la pregunta");
    btn.type = "button";
    btn.addEventListener("click", () => {
      marcarTarjetaLeida(p, art, btn);
    });
    acciones.appendChild(btn);
    hijos.push(acciones);

    art.replaceChildren(...hijos);
  }

  // Rellena la tarjeta con la pregunta y sus opciones (A/B/C/D) o cuadro de texto; mueve foco si recién pasó de lectura.
  function rellenarTarjetaPregunta(art, p, enfocarPregunta = false) {
    art.dataset.modo = "pregunta";
    art.className = "tarjeta-pregunta";

    const hijos = [];
    const cab = crear("div", "pregunta-cabecera");
    cab.appendChild(crear("span", "pregunta-tema", p.tema || `Tema #${p.tema_id}`));
    const fInfo = formatearFuente(p.fuente);
    cab.appendChild(crear("span", fInfo.clase, fInfo.texto));
    hijos.push(cab);

    if (p.motivo) {
      hijos.push(crear("p", "pregunta-motivo", `Por qué te lo pregunto: ${p.motivo}`));
    }

    const pTexto = crear("p", "pregunta-texto", p.texto);
    pTexto.tabIndex = -1;
    hijos.push(pTexto);

    const cajaPista = crear("p", "caja-pista", "");
    cajaPista.hidden = true;
    const btnPista = crear("button", "btn btn-terciario", "Pedir pista");
    btnPista.type = "button";
    btnPista.addEventListener("click", async () => {
      btnPista.disabled = true;
      try {
        const res = await peticion(
          `/api/preguntas/${p.id}/pista`,
          { method: "POST" },
          () => btnPista.click()
        );
        cajaPista.textContent = res.pista;
        cajaPista.hidden = false;
        btnPista.textContent = res.pistas_restantes > 0 ? `Otra pista (${res.pistas_restantes})` : "Sin más pistas";
        if (res.pistas_restantes <= 0) btnPista.disabled = true;
      } catch (err) {
        if (err.status !== 401) {
          mostrarAvisoGlobal(err.message || "No se pudo obtener la pista.", true);
        }
      } finally {
        if (btnPista.textContent !== "Sin más pistas") btnPista.disabled = false;
      }
    });
    const filaPista = crear("div", "tema-acciones");
    filaPista.appendChild(btnPista);
    hijos.push(filaPista, cajaPista);

    if (Array.isArray(p.opciones) && p.opciones.length > 0) {
      hijos.push(crear("p", "opciones-titulo", "Elige una opción:"));
      const grid = crear("div", "opciones-grid");
      p.opciones.forEach((opcionTexto, idx) => {
        const letra = LETRAS[idx] || String(idx + 1);
        const btn = crear("button", "btn-opcion");
        btn.type = "button";
        btn.dataset.letra = letra;
        btn.appendChild(crear("span", "opcion-letra", letra));
        btn.appendChild(crear("span", "opcion-texto", opcionTexto));
        btn.addEventListener("click", () => {
          enviarRespuesta(p.id, letra, art);
        });
        grid.appendChild(btn);
      });
      hijos.push(grid);
    } else {
      const form = crear("form", "form-respuesta");
      const inputId = `resp-preg-${p.id}`;
      const lbl = crear("label", "", "Tu respuesta");
      lbl.setAttribute("for", inputId);

      const textarea = crear("textarea", "");
      textarea.id = inputId;
      textarea.name = "respuesta";
      textarea.rows = 3;
      textarea.maxLength = 2000;
      textarea.required = true;
      textarea.placeholder = "Escribe lo que recuerdas con tus palabras...";

      const fila = crear("div", "fila-acciones-form");
      const btn = crear("button", "btn btn-primario", "Enviar respuesta");
      btn.type = "submit";
      fila.appendChild(btn);

      form.append(lbl, textarea, fila);
      form.addEventListener("submit", (ev) => {
        ev.preventDefault();
        const valor = textarea.value.trim();
        if (!valor) {
          textarea.focus();
          mostrarAvisoGlobal("Escribe una respuesta antes de enviar.", true);
          return;
        }
        enviarRespuesta(p.id, valor, art);
      });
      hijos.push(form);
    }

    art.replaceChildren(...hijos);
    if (enfocarPregunta) {
      enfocar(pTexto);
    }
  }

  // Crea el contenedor <article> de una pregunta nueva eligiendo vista de lectura o pregunta directa.
  function crearTarjetaPregunta(p) {
    const art = crear("article", "tarjeta-pregunta");
    art.dataset.preguntaId = String(p.id);
    if (esModoLectura(p)) {
      rellenarTarjetaLectura(art, p);
    } else {
      rellenarTarjetaPregunta(art, p, false);
    }
    return art;
  }

  // Sincroniza #lista-preguntas con el servidor sin borrar tarjetas ya abiertas ni quitar el foco al escribir.
  function renderizarPreguntas(pendientes) {
    const cont = el("lista-preguntas");
    el("badge-pendientes").textContent = `${pendientes.length} ${pendientes.length === 1 ? "pendiente" : "pendientes"}`;

    if (pendientes.length === 0) {
      if (!cont.querySelector(".estado-vacio") || cont.querySelector("[data-pregunta-id]")) {
        cont.replaceChildren(crearVacioPreguntas());
      }
      return;
    }

    const vacio = cont.querySelector(".estado-vacio");
    if (vacio) vacio.remove();

    const idsNuevos = new Set(pendientes.map((p) => String(p.id)));
    for (const nodo of Array.from(cont.querySelectorAll("[data-pregunta-id]"))) {
      if (!idsNuevos.has(nodo.dataset.preguntaId) && nodo.dataset.enviando !== "1") {
        nodo.remove();
      }
    }

    for (const p of pendientes) {
      const idStr = String(p.id);
      const existente = cont.querySelector(`[data-pregunta-id="${idStr}"]`);
      if (!existente) {
        cont.appendChild(crearTarjetaPregunta(p));
      } else if (existente.dataset.enviando !== "1") {
        if (existente.dataset.modo === "lectura" && !esModoLectura(p)) {
          rellenarTarjetaPregunta(existente, p, false);
        }
      }
    }
  }

  // ---- Renderizado: Progreso, brechas e historial --------------------------
  // Actualiza los contadores de avance, racha, brechas en refuerzo y últimas evaluaciones.
  function renderizarProgreso(prog, historial, brechas) {
    el("prog-temas").textContent = String(prog.temas ?? 0);
    el("prog-dominados").textContent = String(prog.dominados ?? 0);
    el("prog-respuestas").textContent = String(prog.respuestas ?? 0);
    el("prog-porcentaje").textContent =
      prog.porcentaje_aciertos !== null && prog.porcentaje_aciertos !== undefined
        ? `${prog.porcentaje_aciertos}%`
        : "—";
    if (el("prog-racha")) {
      el("prog-racha").textContent = `${Number(prog.racha_dias ?? 0)} d`;
    }

    const recEl = el("brechas-recomendacion");
    const listaBrechas = el("lista-brechas");
    if (recEl && listaBrechas && brechas) {
      recEl.textContent = brechas.recomendacion || "";
      const refItems = Array.isArray(brechas.en_refuerzo) ? brechas.en_refuerzo : [];
      if (refItems.length === 0) {
        listaBrechas.replaceChildren(crear("li", "texto-suave", "Sin temas en refuerzo guiado."));
      } else {
        const nodos = refItems.map((b) => {
          const li = crear("li", "item-compacto");
          li.appendChild(crear("strong", "", b.nombre));
          li.appendChild(
            crear("span", "pildora pildora-aviso", `${b.fallos} fallo(s) · fac. ${Number(b.facilidad).toFixed(2)}`)
          );
          return li;
        });
        listaBrechas.replaceChildren(...nodos);
      }
    }

    const listaDificiles = el("lista-dificiles");
    const dificiles = Array.isArray(prog.mas_dificiles) ? prog.mas_dificiles : [];
    if (dificiles.length === 0) {
      listaDificiles.replaceChildren(crear("li", "texto-suave", "Todavía no hay fallos registrados."));
    } else {
      const nodos = dificiles.map((d) => {
        const li = crear("li", "item-compacto");
        li.appendChild(crear("strong", "", d.tema));
        li.appendChild(
          crear("span", "pildora pildora-aviso", `${d.fallos} fallo(s) · fac. ${Number(d.facilidad).toFixed(2)}`)
        );
        return li;
      });
      listaDificiles.replaceChildren(...nodos);
    }

    const listaHist = el("lista-historial");
    const items = Array.isArray(historial) ? historial : [];
    if (items.length === 0) {
      listaHist.replaceChildren(crear("li", "texto-suave", "Sin respuestas evaluadas todavía."));
    } else {
      const nodos = items.map((h) => {
        const li = crear("li", "item-compacto");
        li.appendChild(crear("strong", "", h.tema || "Tema"));
        const nota = Number(h.nota);
        li.appendChild(
          crear("span", `pildora ${nota >= 3 ? "pildora-ok" : "pildora-aviso"}`, `${nota}/5`)
        );
        li.appendChild(crear("span", "item-compacto-detalle", `${h.retroalimentacion || h.texto || ""} · ${formatearFecha(h.fecha)}`));
        return li;
      });
      listaHist.replaceChildren(...nodos);
    }
  }

  // ---- Renderizado: Mis temas -----------------------------------------------
  // Envía DELETE /api/temas/{id} una vez confirmada la eliminación para borrar el tema y su historial.
  async function borrarTemaConfirmado(temaId) {
    try {
      await peticion(
        `/api/temas/${temaId}`,
        { method: "DELETE" },
        () => borrarTemaConfirmado(temaId)
      );
      confirmandoBorradoId = null;
      mostrarAvisoGlobal("Tema eliminado de la memoria del agente.");
      await cargarTodo(true);
    } catch (err) {
      if (err.status !== 401) {
        mostrarAvisoGlobal(err.message || "No se pudo borrar el tema.", true);
      }
    }
  }

  async function posponerTema(t) {
    try {
      await peticion(
        `/api/temas/${t.id}/posponer`,
        { method: "POST", body: JSON.stringify({ dias: 1 }) },
        () => posponerTema(t)
      );
      mostrarAvisoGlobal(`Tema «${t.nombre}» pospuesto 1 día de estudio.`);
      await cargarTodo(true);
    } catch (err) {
      if (err.status !== 401) {
        mostrarAvisoGlobal(err.message || "No se pudo posponer el tema.", true);
      }
    }
  }

  async function guardarEdicionTema(t, nombre, notas, ideaClave) {
    try {
      await peticion(
        `/api/temas/${t.id}`,
        {
          method: "PATCH",
          body: JSON.stringify({ nombre, notas, idea_clave: ideaClave }),
        },
        () => guardarEdicionTema(t, nombre, notas, ideaClave)
      );
      editandoTemaId = null;
      mostrarAvisoGlobal(`Tema «${nombre}» actualizado.`);
      await cargarTodo(true);
    } catch (err) {
      if (err.status !== 401) {
        mostrarAvisoGlobal(err.message || "No se pudo editar el tema.", true);
      }
    }
  }

  // Muestra cada tema guardado con filtro, edición inline, posposición y confirmación de borrado.
  function renderizarTemas(temas, forzar = false) {
    temasCache = temas;
    el("badge-temas").textContent = `${temas.length} ${temas.length === 1 ? "tema" : "temas"}`;
    const cont = el("lista-temas");
    if (!forzar && (contieneFoco(cont) || confirmandoBorradoId !== null || editandoTemaId !== null)) {
      return;
    }

    const q = (el("filtro-temas") ? el("filtro-temas").value : "").trim().toLowerCase();
    const tipoFiltro = el("filtro-temas-tipo") ? el("filtro-temas-tipo").value : "";
    const filtrados = temas.filter((t) => {
      if (tipoFiltro && (t.tipo || (t.origen === "devcards" ? "devcard" : "nota")) !== tipoFiltro) {
        return false;
      }
      if (!q) return true;
      const texto = `${t.nombre || ""} ${t.notas || ""} ${t.lenguaje || ""} ${t.etiquetas || ""} ${t.categoria || ""}`.toLowerCase();
      return texto.includes(q);
    });

    if (filtrados.length === 0) {
      cont.replaceChildren(
        crear("p", "estado-vacio", temas.length === 0 ? "Todavía no hay temas en memoria. Agrega uno arriba." : "Ningún tema coincide con el filtro.")
      );
      return;
    }

    const ahoraMs = Date.now();
    const nodos = filtrados.map((t) => {
      const art = crear("article", "tarjeta-tema");
      const filaSup = crear("div", "tema-fila-superior");
      filaSup.appendChild(crear("span", "tema-nombre", t.nombre));

      const pildoras = crear("div", "resultado-meta");
      let etiquetaOrigen = "Propio";
      let claseOrigen = "pildora-azul";
      if (t.origen === "devcards") {
        etiquetaOrigen = `DevCards${t.categoria ? " · " + t.categoria : ""}`;
        claseOrigen = "pildora-ok";
      } else if (t.tipo === "codigo") {
        etiquetaOrigen = `Código${t.lenguaje ? " · " + t.lenguaje : ""}`;
      } else if (t.tipo === "material") {
        etiquetaOrigen = "Apuntes";
      }
      pildoras.appendChild(crear("span", `pildora ${claseOrigen}`, etiquetaOrigen));
      if (t.en_refuerzo) {
        pildoras.appendChild(crear("span", "pildora pildora-aviso", "En refuerzo"));
      }
      filaSup.appendChild(pildoras);
      art.appendChild(filaSup);

      if (t.notas) {
        const resumen = t.notas.length > 220 ? `${t.notas.slice(0, 220)}…` : t.notas;
        art.appendChild(crear("p", "tema-notas", resumen));
      }

      if (t.codigo) {
        const pre = crear("pre", "lectura-codigo");
        const muestra = t.codigo.length > 220 ? `${t.codigo.slice(0, 220)}…` : t.codigo;
        pre.appendChild(crear("code", "", muestra));
        art.appendChild(pre);
      }

      if (editandoTemaId === t.id) {
        const formEd = crear("form", "form-edicion-inline");
        const inNom = crear("input", "");
        inNom.type = "text";
        inNom.value = t.nombre || "";
        inNom.required = true;
        inNom.setAttribute("aria-label", "Nuevo nombre del tema");

        const inNotas = crear("textarea", "");
        inNotas.rows = 2;
        inNotas.value = t.notas || "";
        inNotas.setAttribute("aria-label", "Nuevas notas del tema");

        const inIdea = crear("input", "");
        inIdea.type = "text";
        inIdea.value = t.idea_clave || "";
        inIdea.placeholder = "Idea clave (opcional)";
        inIdea.setAttribute("aria-label", "Idea clave");

        const filaEd = crear("div", "tema-acciones");
        const btnG = crear("button", "btn btn-primario", "Guardar");
        btnG.type = "submit";
        const btnC = crear("button", "btn btn-terciario", "Cancelar");
        btnC.type = "button";
        btnC.addEventListener("click", () => {
          editandoTemaId = null;
          renderizarTemas(temasCache, true);
        });
        filaEd.append(btnG, btnC);
        formEd.append(inNom, inNotas, inIdea, filaEd);
        formEd.addEventListener("submit", (ev) => {
          ev.preventDefault();
          guardarEdicionTema(t, inNom.value.trim(), inNotas.value, inIdea.value);
        });
        art.appendChild(formEd);
        return art;
      }

      const meta = crear("div", "tema-meta");
      const repasoD = parsearFecha(t.proximo_repaso);
      const vencido = repasoD ? repasoD.getTime() <= ahoraMs : false;
      meta.appendChild(
        crear(
          "span",
          "",
          `Repaso: ${vencido ? "ahora (" + formatearRelativo(t.proximo_repaso) + ")" : formatearRelativo(t.proximo_repaso)}`
        )
      );
      meta.appendChild(crear("span", "", `Intervalo: ${Number(t.intervalo_dias).toFixed(1)}d`));
      meta.appendChild(crear("span", "", `Facilidad: ${Number(t.facilidad).toFixed(2)}`));
      meta.appendChild(crear("span", "", `Aciertos/Fallos: ${t.aciertos}/${t.fallos}`));
      art.appendChild(meta);

      const acciones = crear("div", "tema-acciones");
      if (confirmandoBorradoId === t.id) {
        const btnConfirmar = crear("button", "btn btn-peligro", "Confirmar borrado");
        btnConfirmar.type = "button";
        btnConfirmar.addEventListener("click", () => {
          borrarTemaConfirmado(t.id);
        });
        const btnCancelar = crear("button", "btn btn-terciario", "Cancelar");
        btnCancelar.type = "button";
        btnCancelar.addEventListener("click", () => {
          confirmandoBorradoId = null;
          renderizarTemas(temasCache, true);
        });
        acciones.append(btnConfirmar, btnCancelar);
      } else {
        const btnPosponer = crear("button", "btn btn-terciario", "Posponer 1d");
        btnPosponer.type = "button";
        btnPosponer.addEventListener("click", () => posponerTema(t));

        const btnEditar = crear("button", "btn btn-terciario", "Editar");
        btnEditar.type = "button";
        btnEditar.addEventListener("click", () => {
          editandoTemaId = t.id;
          renderizarTemas(temasCache, true);
        });

        const btnBorrar = crear("button", "btn btn-terciario", "Borrar");
        btnBorrar.type = "button";
        btnBorrar.setAttribute("aria-label", `Borrar tema ${t.nombre}`);
        btnBorrar.addEventListener("click", () => {
          confirmandoBorradoId = t.id;
          renderizarTemas(temasCache, true);
        });
        acciones.append(btnPosponer, btnEditar, btnBorrar);
      }
      art.appendChild(acciones);
      return art;
    });

    cont.replaceChildren(...nodos);
  }

  // ---- Renderizado: Colecciones personalizadas ------------------------------
  async function alternarColeccion(col, btn) {
    const nuevo = !col.activa;
    btn.disabled = true;
    try {
      await peticion(
        `/api/colecciones/${col.id}`,
        { method: "PATCH", body: JSON.stringify({ activa: nuevo }) },
        () => alternarColeccion(col, btn)
      );
      mostrarAvisoGlobal(`Colección «${col.nombre}» ${nuevo ? "activada" : "pausada"}.`);
      await cargarTodo(true);
    } catch (err) {
      if (err.status !== 401) {
        mostrarAvisoGlobal(err.message || "No se pudo actualizar la colección.", true);
      }
    } finally {
      btn.disabled = false;
    }
  }

  async function exportarColeccionArchivo(col, formato) {
    try {
      const resp = await fetch(`/api/colecciones/${col.id}/exportar?formato=${formato}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const contenido = formato === "json" ? JSON.stringify(await resp.json(), null, 2) : await resp.text();
      const blob = new Blob([contenido], { type: formato === "json" ? "application/json" : "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const ext = formato === "anki" ? "tsv" : formato;
      a.download = `${col.nombre.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.${ext}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      mostrarAvisoGlobal(`Colección «${col.nombre}» exportada en ${formato.toUpperCase()}.`);
    } catch (err) {
      mostrarAvisoGlobal(err.message || "No se pudo exportar la colección.", true);
    }
  }

  async function borrarColeccion(col) {
    try {
      await peticion(
        `/api/colecciones/${col.id}`,
        { method: "DELETE" },
        () => borrarColeccion(col)
      );
      mostrarAvisoGlobal(`Colección «${col.nombre}» eliminada.`);
      await cargarTodo(true);
    } catch (err) {
      if (err.status !== 401) {
        mostrarAvisoGlobal(err.message || "No se pudo eliminar la colección.", true);
      }
    }
  }

  function renderizarColecciones(cols, forzar = false) {
    coleccionesCache = cols;
    const badge = el("badge-colecciones");
    if (badge) {
      badge.textContent = `${cols.length} ${cols.length === 1 ? "colección" : "colecciones"}`;
    }
    const sel = el("tema-coleccion");
    if (sel && document.activeElement !== sel) {
      const valorPrev = sel.value;
      const opciones = [crear("option", "", "Sin colección")];
      opciones[0].value = "";
      for (const c of cols) {
        const opt = crear("option", "", c.nombre);
        opt.value = String(c.id);
        opciones.push(opt);
      }
      sel.replaceChildren(...opciones);
      sel.value = valorPrev;
    }

    const cont = el("lista-colecciones");
    if (!cont || (!forzar && contieneFoco(cont))) return;
    if (cols.length === 0) {
      cont.replaceChildren(crear("p", "estado-vacio", "Sin colecciones creadas todavía."));
      return;
    }

    const nodos = cols.map((c) => {
      const fila = crear("div", "item-mazo");
      const info = crear("div", "mazo-info");
      info.appendChild(crear("div", "mazo-nombre", c.nombre));
      const desc = c.descripcion ? `${c.descripcion} · ` : "";
      info.appendChild(
        crear("div", "mazo-cifras", `${desc}${c.temas} ficha(s) · ${c.dominados} dominada(s)`)
      );

      const acciones = crear("div", "tema-acciones");
      const btnEst = crear("button", "btn-interruptor", c.activa ? "Activa" : "Pausada");
      btnEst.type = "button";
      btnEst.setAttribute("aria-pressed", c.activa ? "true" : "false");
      btnEst.addEventListener("click", () => alternarColeccion(c, btnEst));

      const btnJson = crear("button", "btn btn-terciario", "JSON");
      btnJson.type = "button";
      btnJson.addEventListener("click", () => exportarColeccionArchivo(c, "json"));

      const btnMd = crear("button", "btn btn-terciario", "MD");
      btnMd.type = "button";
      btnMd.addEventListener("click", () => exportarColeccionArchivo(c, "md"));

      const btnAnki = crear("button", "btn btn-terciario", "Anki");
      btnAnki.type = "button";
      btnAnki.addEventListener("click", () => exportarColeccionArchivo(c, "anki"));

      const btnDel = crear("button", "btn btn-terciario", "Borrar");
      btnDel.type = "button";
      btnDel.addEventListener("click", () => borrarColeccion(c));

      acciones.append(btnEst, btnJson, btnMd, btnAnki, btnDel);
      fila.append(info, acciones);
      return fila;
    });
    cont.replaceChildren(...nodos);
  }

  // ---- Renderizado: Mazos DevCards ------------------------------------------
  // Envía PUT /api/mazos/{categoria} al pulsar el interruptor Activo/Pausado de una categoría DevCards.
  async function alternarMazo(mazo, btn) {
    const nuevoEstado = !mazo.activo;
    btn.disabled = true;
    try {
      await peticion(
        `/api/mazos/${encodeURIComponent(mazo.categoria)}`,
        {
          method: "PUT",
          body: JSON.stringify({ activo: nuevoEstado }),
        },
        () => alternarMazo(mazo, btn)
      );
      mostrarAvisoGlobal(`Mazo «${mazo.categoria}» ${nuevoEstado ? "activado" : "pausado"}.`);
      await cargarTodo(true);
    } catch (err) {
      if (err.status !== 401) {
        mostrarAvisoGlobal(err.message || "No se pudo actualizar el mazo.", true);
      }
    } finally {
      btn.disabled = false;
    }
  }

  // Dibuja la lista de las 42 categorías DevCards aplicando el filtro escrito por el usuario en el buscador.
  function renderizarMazos(mazos, forzar = false) {
    mazosCache = mazos;
    const totalTarjetas = mazos.reduce((acc, m) => acc + Number(m.tarjetas || 0), 0);
    const totalActivos = mazos.filter((m) => m.activo).length;
    el("resumen-mazos").textContent = `${totalActivos} activo(s) de ${mazos.length} · ${totalTarjetas.toLocaleString("es")} tarjetas`;

    const cont = el("lista-mazos");
    if (!forzar && contieneFoco(cont)) {
      return;
    }

    const filtro = (el("filtro-mazos").value || "").trim().toLowerCase();
    const filtrados = filtro
      ? mazos.filter((m) => String(m.categoria).toLowerCase().includes(filtro))
      : mazos;

    if (filtrados.length === 0) {
      cont.replaceChildren(crear("p", "estado-vacio", "Ningún mazo coincide con ese filtro."));
      return;
    }

    const nodos = filtrados.map((m) => {
      const fila = crear("div", "item-mazo");
      const info = crear("div", "mazo-info");
      info.appendChild(crear("div", "mazo-nombre", m.categoria));
      info.appendChild(
        crear("div", "mazo-cifras", `${m.introducidas} / ${m.tarjetas} tarjetas vistas`)
      );

      const btn = crear("button", "btn-interruptor", m.activo ? "Activo" : "Pausado");
      btn.type = "button";
      btn.setAttribute("aria-pressed", m.activo ? "true" : "false");
      btn.setAttribute(
        "aria-label",
        `${m.activo ? "Pausar" : "Activar"} mazo ${m.categoria}`
      );
      btn.addEventListener("click", () => alternarMazo(m, btn));

      fila.append(info, btn);
      return fila;
    });

    cont.replaceChildren(...nodos);
  }

  // ---- Renderizado: Bitácora ------------------------------------------------
  // Pinta las últimas anotaciones del diario interno del agente (de más nueva a más antigua).
  function renderizarBitacora(entradas) {
    const lista = el("lista-bitacora");
    if (!Array.isArray(entradas) || entradas.length === 0) {
      lista.replaceChildren(crear("li", "estado-vacio", "Aún no hay registros en la bitácora."));
      return;
    }

    const nodos = entradas.map((b) => {
      const li = crear("li", "item-bitacora");
      li.appendChild(crear("span", claseTipoBitacora(b.tipo), b.tipo));
      li.appendChild(crear("span", "bitacora-hora", formatearFecha(b.fecha)));
      li.appendChild(crear("p", "bitacora-detalle", b.detalle));
      return li;
    });
    lista.replaceChildren(...nodos);
  }

  // ---- Acciones principales -------------------------------------------------
  // Fuerza una ronda inmediata del agente (POST /api/ciclo) para la demostración en vivo sin esperar al reloj.
  async function ejecutarCicloAhora() {
    const btn = el("btn-ciclo");
    btn.disabled = true;
    try {
      const res = await peticion(
        "/api/ciclo",
        { method: "POST" },
        () => ejecutarCicloAhora()
      );
      const creadas = Array.isArray(res.preguntas_creadas) ? res.preguntas_creadas.length : 0;
      mostrarAvisoGlobal(
        `Ciclo ejecutado: ${creadas} pregunta(s) nueva(s), ${res.pendientes} pendiente(s), ${res.vencidos} tema(s) vencido(s).`
      );
      await cargarTodo(true);
    } catch (err) {
      if (err.status !== 401) {
        mostrarAvisoGlobal(err.message || "Error al ejecutar el ciclo.", true);
      }
    } finally {
      btn.disabled = false;
    }
  }

  // Procesa el formulario de "Mis temas" validando nombre >= 2 letras y enviando POST /api/temas.
  async function manejarAgregarTema(evento) {
    evento.preventDefault();
    const inputNombre = el("tema-nombre");
    const inputNotas = el("tema-notas");
    const selectCol = el("tema-coleccion");
    const btn = el("btn-agregar-tema");
    const estadoInline = el("estado-form-tema");

    const nombre = inputNombre.value.trim();
    const notas = inputNotas.value.trim();
    const coleccionId = selectCol && selectCol.value ? Number(selectCol.value) : null;
    if (nombre.length < 2) {
      estadoInline.textContent = "El nombre debe tener al menos 2 caracteres.";
      estadoInline.className = "estado-inline es-error";
      inputNombre.focus();
      return;
    }

    const enviar = async () => {
      btn.disabled = true;
      estadoInline.textContent = "Guardando tema...";
      estadoInline.className = "estado-inline";
      try {
        const tema = await peticion(
          "/api/temas",
          {
            method: "POST",
            body: JSON.stringify({ nombre, notas, coleccion_id: coleccionId }),
          },
          enviar
        );
        inputNombre.value = "";
        inputNotas.value = "";
        estadoInline.textContent = `Tema «${tema.nombre}» guardado. El agente lo preguntará en su próximo ciclo.`;
        estadoInline.className = "estado-inline";
        mostrarAvisoGlobal(`Tema «${tema.nombre}» agregado.`);
        await cargarTodo(true);
      } catch (err) {
        if (err.status !== 401) {
          estadoInline.textContent = err.message || "No se pudo guardar el tema.";
          estadoInline.className = "estado-inline es-error";
        } else {
          estadoInline.textContent = "";
        }
      } finally {
        btn.disabled = false;
      }
    };

    await enviar();
  }

  async function manejarEstudiarCodigo(evento) {
    evento.preventDefault();
    const titulo = el("codigo-titulo").value.trim();
    const lenguaje = el("codigo-lenguaje").value;
    const coleccion = el("codigo-coleccion").value.trim() || "Código estudiado";
    const codigo = el("codigo-texto").value;
    const btn = el("btn-estudiar-codigo");
    const estado = el("estado-form-codigo");

    const enviar = async () => {
      btn.disabled = true;
      estado.textContent = "Analizando código y creando fichas...";
      estado.className = "estado-inline";
      try {
        const res = await peticion(
          "/api/estudiar/codigo",
          {
            method: "POST",
            body: JSON.stringify({ codigo, titulo, lenguaje, coleccion }),
          },
          enviar
        );
        el("codigo-titulo").value = "";
        el("codigo-texto").value = "";
        const n = Array.isArray(res.creadas) ? res.creadas.length : 0;
        estado.textContent = `${n} ficha(s) de código creadas (${res.fuente}).`;
        mostrarAvisoGlobal(`${n} ficha(s) de código listas para estudiar.`);
        await cargarTodo(true);
      } catch (err) {
        if (err.status !== 401) {
          estado.textContent = err.message || "No se pudo procesar el código.";
          estado.className = "estado-inline es-error";
        } else {
          estado.textContent = "";
        }
      } finally {
        btn.disabled = false;
      }
    };
    await enviar();
  }

  async function manejarIngestarMaterial(evento) {
    evento.preventDefault();
    const titulo = el("material-titulo").value.trim();
    const coleccion = el("material-coleccion").value.trim() || "Material de estudio";
    const contenido = el("material-texto").value;
    const btn = el("btn-ingestar-material");
    const estado = el("estado-form-material");

    const enviar = async () => {
      btn.disabled = true;
      estado.textContent = "Generando fichas desde tus apuntes...";
      estado.className = "estado-inline";
      try {
        const res = await peticion(
          "/api/estudiar/material",
          {
            method: "POST",
            body: JSON.stringify({ contenido, titulo, coleccion }),
          },
          enviar
        );
        el("material-titulo").value = "";
        el("material-texto").value = "";
        const n = Array.isArray(res.creadas) ? res.creadas.length : 0;
        estado.textContent = `${n} ficha(s) generadas (${res.fuente}).`;
        mostrarAvisoGlobal(`${n} ficha(s) de estudio añadidas.`);
        await cargarTodo(true);
      } catch (err) {
        if (err.status !== 401) {
          estado.textContent = err.message || "No se pudo procesar el material.";
          estado.className = "estado-inline es-error";
        } else {
          estado.textContent = "";
        }
      } finally {
        btn.disabled = false;
      }
    };
    await enviar();
  }

  async function manejarCrearColeccion(evento) {
    evento.preventDefault();
    const nombre = el("coleccion-nombre").value.trim();
    const descripcion = el("coleccion-desc").value.trim();
    const btn = el("btn-crear-coleccion");
    const estado = el("estado-form-coleccion");

    const enviar = async () => {
      btn.disabled = true;
      estado.textContent = "Creando colección...";
      estado.className = "estado-inline";
      try {
        const col = await peticion(
          "/api/colecciones",
          { method: "POST", body: JSON.stringify({ nombre, descripcion }) },
          enviar
        );
        el("coleccion-nombre").value = "";
        el("coleccion-desc").value = "";
        estado.textContent = `Colección «${col.nombre}» creada.`;
        mostrarAvisoGlobal(`Colección «${col.nombre}» creada.`);
        await cargarTodo(true);
      } catch (err) {
        if (err.status !== 401) {
          estado.textContent = err.message || "No se pudo crear la colección.";
          estado.className = "estado-inline es-error";
        } else {
          estado.textContent = "";
        }
      } finally {
        btn.disabled = false;
      }
    };
    await enviar();
  }

  async function manejarImportarMazo(evento) {
    evento.preventDefault();
    const formato = el("importar-formato").value;
    const nombreColeccion = el("importar-nombre").value.trim();
    const datos = el("importar-datos").value;
    const btn = el("btn-ejecutar-importar");
    const estado = el("estado-form-importar");

    const enviar = async () => {
      btn.disabled = true;
      estado.textContent = "Importando mazo...";
      estado.className = "estado-inline";
      try {
        const res = await peticion(
          "/api/colecciones/importar",
          { method: "POST", body: JSON.stringify({ datos, formato, nombre_coleccion: nombreColeccion }) },
          enviar
        );
        el("importar-datos").value = "";
        el("importar-nombre").value = "";
        const n = Array.isArray(res.importados) ? res.importados.length : 0;
        estado.textContent = `Importadas ${n} ficha(s) (${res.omitidos} omitida(s)).`;
        mostrarAvisoGlobal(`Importación completada: ${n} ficha(s).`);
        await cargarTodo(true);
      } catch (err) {
        if (err.status !== 401) {
          estado.textContent = err.message || "No se pudo importar el mazo.";
          estado.className = "estado-inline es-error";
        } else {
          estado.textContent = "";
        }
      } finally {
        btn.disabled = false;
      }
    };
    await enviar();
  }

  function renderizarPlanYSimulacros(plan, examenes) {
    if (plan && el("badge-meta-hoy")) {
      el("badge-meta-hoy").textContent = `${plan.respondidas_hoy} / ${plan.meta_diaria} hoy`;
      el("plan-recomendacion").textContent = plan.recomendacion || "";
      el("plan-barra").style.width = `${plan.progreso_meta_pct || 0}%`;
      el("plan-barra-wrap").setAttribute("aria-valuenow", String(plan.progreso_meta_pct || 0));
      const grid = el("plan-pronostico");
      if (grid && Array.isArray(plan.pronostico_7_dias)) {
        const nodos = plan.pronostico_7_dias.map((d, idx) =>
          crear("span", "pildora pildora-neutra", `${idx === 0 ? "Hoy" : d.fecha.slice(5)}: ${d.vencen}`)
        );
        grid.replaceChildren(...nodos);
      }
    }
    const lista = el("lista-examenes");
    if (lista) {
      if (!Array.isArray(examenes) || examenes.length === 0) {
        lista.replaceChildren(crear("li", "texto-suave", "Sin simulacros realizados todavía."));
      } else {
        const nodos = examenes.map((ex) => {
          const li = crear("li", "item-compacto");
          li.appendChild(crear("strong", "", ex.titulo));
          const txt = ex.estado === "completada"
            ? `${ex.correctas}/${ex.total_preguntas} (${ex.porcentaje_aciertos ?? 0}%) · prom. ${ex.nota_promedio}/5`
            : `${ex.respondidas}/${ex.total_preguntas} en curso`;
          li.appendChild(crear("span", `pildora ${ex.estado === "completada" ? "pildora-ok" : "pildora-azul"}`, txt));
          return li;
        });
        lista.replaceChildren(...nodos);
      }
    }
  }

  async function manejarEstudiarDiff(evento) {
    evento.preventDefault();
    const titulo = el("diff-titulo").value.trim();
    const coleccion = el("diff-coleccion").value.trim() || "Cambios Git (Diff)";
    const diffTexto = el("diff-texto").value;
    const btn = el("btn-estudiar-diff");
    const estado = el("estado-form-diff");

    const enviar = async () => {
      btn.disabled = true;
      estado.textContent = "Analizando git diff...";
      estado.className = "estado-inline";
      try {
        const res = await peticion(
          "/api/estudiar/diff",
          { method: "POST", body: JSON.stringify({ diff_texto: diffTexto, titulo, coleccion }) },
          enviar
        );
        el("diff-titulo").value = "";
        el("diff-texto").value = "";
        const n = Array.isArray(res.creadas) ? res.creadas.length : 0;
        estado.textContent = `${n} ficha(s) extraídas del diff (${res.fuente}).`;
        mostrarAvisoGlobal(`${n} ficha(s) de diff guardadas.`);
        await cargarTodo(true);
      } catch (err) {
        if (err.status !== 401) {
          estado.textContent = err.message || "No se pudo procesar el diff.";
          estado.className = "estado-inline es-error";
        } else {
          estado.textContent = "";
        }
      } finally {
        btn.disabled = false;
      }
    };
    await enviar();
  }

  async function manejarIniciarSimulacro(evento) {
    evento.preventDefault();
    const titulo = el("sim-titulo").value.trim() || "Simulacro rápido";
    const cantidad = Number(el("sim-cantidad").value || 5);
    const soloBrechas = Boolean(el("sim-solo-brechas").checked);
    const btn = el("btn-iniciar-simulacro");
    const estado = el("estado-form-simulacro");

    const enviar = async () => {
      btn.disabled = true;
      estado.textContent = "Preparando simulacro...";
      estado.className = "estado-inline";
      try {
        const res = await peticion(
          "/api/examenes",
          { method: "POST", body: JSON.stringify({ titulo, cantidad, solo_brechas: soloBrechas }) },
          enviar
        );
        const n = Array.isArray(res.preguntas) ? res.preguntas.length : 0;
        estado.textContent = `Simulacro creado con ${n} pregunta(s) en «Estudiar».`;
        mostrarAvisoGlobal(`Simulacro «${titulo}» listo (${n} preguntas).`);
        await cargarTodo(true);
      } catch (err) {
        if (err.status !== 401) {
          estado.textContent = err.message || "No se pudo iniciar el simulacro.";
          estado.className = "estado-inline es-error";
        } else {
          estado.textContent = "";
        }
      } finally {
        btn.disabled = false;
      }
    };
    await enviar();
  }

  function activarTabCarga(tabId) {
    const mapa = [
      { tab: "tab-nota", panel: "panel-nota" },
      { tab: "tab-codigo", panel: "panel-codigo" },
      { tab: "tab-material", panel: "panel-material" },
      { tab: "tab-diff", panel: "panel-diff" },
    ];
    for (const item of mapa) {
      const activo = item.tab === tabId;
      const t = el(item.tab);
      const p = el(item.panel);
      if (t) t.setAttribute("aria-selected", activo ? "true" : "false");
      if (p) p.hidden = !activo;
    }
  }

  // Consulta en paralelo los endpoints de lectura para mantener sincronizada toda la página cada 5 segundos.
  async function cargarTodo(forzar = false) {
    if (recargaEnCurso && !forzar) return;
    recargaEnCurso = true;
    try {
      const [estado, pendientes, temas, colecciones, mazos, progreso, brechas, plan, examenes, historial, bitacora] = await Promise.all([
        peticion("/api/estado"),
        peticion("/api/preguntas/pendientes"),
        peticion("/api/temas"),
        peticion("/api/colecciones"),
        peticion("/api/mazos"),
        peticion("/api/progreso"),
        peticion("/api/brechas"),
        peticion("/api/plan"),
        peticion("/api/examenes?limite=5"),
        peticion("/api/historial?limite=6"),
        peticion("/api/bitacora?limite=40"),
      ]);

      renderizarEstado(estado);
      renderizarPreguntas(pendientes);
      renderizarTemas(temas, forzar);
      renderizarColecciones(colecciones, forzar);
      renderizarMazos(mazos, forzar);
      renderizarProgreso(progreso, historial, brechas);
      renderizarPlanYSimulacros(plan, examenes);
      renderizarBitacora(bitacora);
    } catch (err) {
      mostrarAvisoGlobal(err.message || "No se pudo consultar el estado del agente.", true);
    } finally {
      recargaEnCurso = false;
    }
  }

  // Conecta todos los eventos de botones y formularios al cargar la página y arranca el refresco de 5 segundos.
  function iniciar() {
    el("btn-ciclo").addEventListener("click", ejecutarCicloAhora);
    el("btn-token").addEventListener("click", () => abrirDialogoToken(""));
    el("btn-cerrar-token").addEventListener("click", cerrarDialogoToken);
    el("btn-limpiar-token").addEventListener("click", () => {
      guardarToken("");
      el("input-token").value = "";
      mostrarAvisoGlobal("Clave borrada de este navegador.");
      cerrarDialogoToken();
    });
    el("form-token").addEventListener("submit", manejarEnvioToken);
    el("form-tema").addEventListener("submit", manejarAgregarTema);
    if (el("form-codigo")) el("form-codigo").addEventListener("submit", manejarEstudiarCodigo);
    if (el("form-material")) el("form-material").addEventListener("submit", manejarIngestarMaterial);
    if (el("form-diff")) el("form-diff").addEventListener("submit", manejarEstudiarDiff);
    if (el("form-simulacro")) el("form-simulacro").addEventListener("submit", manejarIniciarSimulacro);
    if (el("form-coleccion")) el("form-coleccion").addEventListener("submit", manejarCrearColeccion);
    if (el("form-importar")) el("form-importar").addEventListener("submit", manejarImportarMazo);
    if (el("btn-toggle-importar")) {
      el("btn-toggle-importar").addEventListener("click", () => {
        const panel = el("panel-importar");
        const abierto = !panel.hidden;
        panel.hidden = abierto;
        el("btn-toggle-importar").setAttribute("aria-expanded", abierto ? "false" : "true");
      });
    }
    for (const idTab of ["tab-nota", "tab-codigo", "tab-material", "tab-diff"]) {
      if (el(idTab)) {
        el(idTab).addEventListener("click", () => activarTabCarga(idTab));
      }
    }
    if (el("filtro-temas")) {
      el("filtro-temas").addEventListener("input", () => renderizarTemas(temasCache, true));
    }
    if (el("filtro-temas-tipo")) {
      el("filtro-temas-tipo").addEventListener("change", () => renderizarTemas(temasCache, true));
    }
    el("filtro-mazos").addEventListener("input", () => {
      renderizarMazos(mazosCache, true);
    });

    cargarTodo(true);
    setInterval(() => {
      cargarTodo(false);
    }, INTERVALO_REFRESCO_MS);
  }

  document.addEventListener("DOMContentLoaded", iniciar);
})();

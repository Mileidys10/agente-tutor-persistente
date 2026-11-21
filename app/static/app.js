"use strict";

(() => {
  const CLAVE_STORAGE = "agente_tutor_token";
  const LETRAS = "ABCDEFGH";
  const INTERVALO_REFRESCO_MS = 5000;

  let tokenEnMemoria = "";
  let mazosCache = [];
  let confirmandoBorradoId = null;
  let accionPendiente = null;
  let temporizadorAviso = null;
  let recargaEnCurso = false;
  const leidasLocalmente = new Set();

  const formatoFechaHora = new Intl.DateTimeFormat("es", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  function el(id) {
    return document.getElementById(id);
  }

  function crear(etiqueta, clase, texto) {
    const nodo = document.createElement(etiqueta);
    if (clase) nodo.className = clase;
    if (texto !== undefined && texto !== null) nodo.textContent = String(texto);
    return nodo;
  }

  function contieneFoco(contenedor) {
    const activo = document.activeElement;
    return Boolean(activo && contenedor && contenedor.contains(activo));
  }

  // ---- Token y almacenamiento seguro ----------------------------------------
  function obtenerToken() {
    if (tokenEnMemoria) return tokenEnMemoria;
    try {
      tokenEnMemoria = window.localStorage.getItem(CLAVE_STORAGE) || "";
    } catch (_) {
      tokenEnMemoria = "";
    }
    return tokenEnMemoria;
  }

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
  function parsearFecha(iso) {
    if (!iso) return null;
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function formatearFecha(iso) {
    const d = parsearFecha(iso);
    return d ? formatoFechaHora.format(d) : "—";
  }

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

  function formatearFuente(fuente) {
    if (fuente === "gemini") return { texto: "Gemini", clase: "pildora pildora-azul" };
    if (fuente === "devcards") return { texto: "DevCards", clase: "pildora pildora-ok" };
    return { texto: "Motor local", clase: "pildora pildora-neutra" };
  }

  function claseTipoBitacora(tipo) {
    switch (tipo) {
      case "evaluacion":
        return "pildora pildora-ok";
      case "decision":
        return "pildora pildora-azul";
      case "pregunta":
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

  function cerrarDialogoToken() {
    const dlg = el("dialogo-token");
    accionPendiente = null;
    if (typeof dlg.close === "function") {
      if (dlg.open) dlg.close();
    } else {
      dlg.removeAttribute("open");
    }
  }

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
  function crearVacioPreguntas() {
    return crear(
      "p",
      "estado-vacio",
      "No hay preguntas pendientes ahora mismo. Agrega un tema en «Mis temas», activa un mazo de DevCards o pulsa «Ejecutar un ciclo ahora»."
    );
  }

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

  function enfocar(nodo) {
    if (!nodo) {
      return;
    }
    if (!nodo.hasAttribute("tabindex") && !/^(BUTTON|TEXTAREA|INPUT|A|SELECT)$/.test(nodo.tagName)) {
      nodo.tabIndex = -1;
    }
    nodo.focus({ preventScroll: false });
  }

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

  function esModoLectura(p) {
    return Boolean(p && p.requiere_lectura && p.lectura && !leidasLocalmente.has(String(p.id)));
  }

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

  // ---- Renderizado: Progreso e historial ------------------------------------
  function renderizarProgreso(prog, historial) {
    el("prog-temas").textContent = String(prog.temas ?? 0);
    el("prog-dominados").textContent = String(prog.dominados ?? 0);
    el("prog-respuestas").textContent = String(prog.respuestas ?? 0);
    el("prog-porcentaje").textContent =
      prog.porcentaje_aciertos !== null && prog.porcentaje_aciertos !== undefined
        ? `${prog.porcentaje_aciertos}%`
        : "—";

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

  function renderizarTemas(temas, forzar = false) {
    el("badge-temas").textContent = `${temas.length} ${temas.length === 1 ? "tema" : "temas"}`;
    const cont = el("lista-temas");
    if (!forzar && (contieneFoco(cont) || confirmandoBorradoId !== null)) {
      return;
    }

    if (temas.length === 0) {
      cont.replaceChildren(
        crear("p", "estado-vacio", "Todavía no hay temas en memoria. Agrega uno en el formulario de arriba.")
      );
      return;
    }

    const ahoraMs = Date.now();
    const nodos = temas.map((t) => {
      const art = crear("article", "tarjeta-tema");
      const filaSup = crear("div", "tema-fila-superior");
      filaSup.appendChild(crear("span", "tema-nombre", t.nombre));

      const etiquetaOrigen =
        t.origen === "devcards"
          ? `DevCards${t.categoria ? " · " + t.categoria : ""}`
          : "Propio";
      filaSup.appendChild(
        crear("span", `pildora ${t.origen === "devcards" ? "pildora-ok" : "pildora-azul"}`, etiquetaOrigen)
      );
      art.appendChild(filaSup);

      if (t.notas) {
        const resumen = t.notas.length > 220 ? `${t.notas.slice(0, 220)}…` : t.notas;
        art.appendChild(crear("p", "tema-notas", resumen));
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
          renderizarTemas(temas, true);
        });
        acciones.append(btnConfirmar, btnCancelar);
      } else {
        const btnBorrar = crear("button", "btn btn-terciario", "Borrar");
        btnBorrar.type = "button";
        btnBorrar.setAttribute("aria-label", `Borrar tema ${t.nombre}`);
        btnBorrar.addEventListener("click", () => {
          confirmandoBorradoId = t.id;
          renderizarTemas(temas, true);
        });
        acciones.appendChild(btnBorrar);
      }
      art.appendChild(acciones);
      return art;
    });

    cont.replaceChildren(...nodos);
  }

  // ---- Renderizado: Mazos DevCards ------------------------------------------
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

  async function manejarAgregarTema(evento) {
    evento.preventDefault();
    const inputNombre = el("tema-nombre");
    const inputNotas = el("tema-notas");
    const btn = el("btn-agregar-tema");
    const estadoInline = el("estado-form-tema");

    const nombre = inputNombre.value.trim();
    const notas = inputNotas.value.trim();
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
            body: JSON.stringify({ nombre, notas }),
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

  async function cargarTodo(forzar = false) {
    if (recargaEnCurso && !forzar) return;
    recargaEnCurso = true;
    try {
      const [estado, pendientes, temas, mazos, progreso, historial, bitacora] = await Promise.all([
        peticion("/api/estado"),
        peticion("/api/preguntas/pendientes"),
        peticion("/api/temas"),
        peticion("/api/mazos"),
        peticion("/api/progreso"),
        peticion("/api/historial?limite=6"),
        peticion("/api/bitacora?limite=40"),
      ]);

      renderizarEstado(estado);
      renderizarPreguntas(pendientes);
      renderizarTemas(temas, forzar);
      renderizarMazos(mazos, forzar);
      renderizarProgreso(progreso, historial);
      renderizarBitacora(bitacora);
    } catch (err) {
      mostrarAvisoGlobal(err.message || "No se pudo consultar el estado del agente.", true);
    } finally {
      recargaEnCurso = false;
    }
  }

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

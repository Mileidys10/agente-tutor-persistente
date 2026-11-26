# Archivo app/ingesta.py: analizador determinista local para convertir código y apuntes/Markdown en fichas de estudio.
# Actúa como motor principal cuando no hay GEMINI_API_KEY y como respaldo automático si Gemini falla.
"""Ingesta universal local: descompone fragmentos de código y material Markdown/texto en fichas atómicas."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any, Optional

_ALIAS_LENGUAJE = {
    "py": "python",
    "python3": "python",
    "js": "javascript",
    "node": "javascript",
    "ts": "typescript",
    "tsx": "typescript",
    "jsx": "javascript",
    "postgres": "sql",
    "postgresql": "sql",
    "sqlite": "sql",
    "mysql": "sql",
    "sh": "bash",
    "shell": "bash",
    "powershell": "bash",
    "ps1": "bash",
}

_PALABRAS_RESERVADAS = {
    "return", "import", "from", "class", "async", "await", "const", "let", "var",
    "function", "select", "where", "insert", "update", "delete", "raise",
    "throw", "yield", "elif", "else", "except", "finally", "while", "break",
}


@dataclass(frozen=True)
class FichaExtraida:
    nombre: str
    notas: str
    tipo: str  # codigo | material | nota
    codigo: str = ""
    lenguaje: str = ""
    analogia: str = ""
    idea_clave: str = ""
    etiquetas: str = ""


def detectar_lenguaje(codigo: str, lenguaje_hint: str = "") -> str:
    hint = lenguaje_hint.strip().lower()
    if hint:
        return _ALIAS_LENGUAJE.get(hint, hint[:40])
    muestra = codigo.strip()
    if re.search(r"(?m)^\s*(async\s+)?def\s+\w+\(|^\s*from\s+\w+.*import\s+", muestra):
        return "python"
    if re.search(r"(?i)\b(SELECT|INSERT\s+INTO|UPDATE\s+\w+\s+SET|CREATE\s+TABLE)\b", muestra):
        return "sql"
    if re.search(r"(?m)\b(interface|type)\s+\w+\s*=|:\s*(string|number|boolean|Promise<)", muestra):
        return "typescript"
    if re.search(r"(?m)\b(function\s+\w+|const\s+\w+\s*=|export\s+(default|const|function)|=>\s*\{)", muestra):
        return "javascript"
    if re.search(r"(?m)^\s*(public|private)\s+(class|static|void)\b", muestra):
        return "java"
    if re.search(r"(?m)^\s*func\s+\w+\(", muestra):
        return "go"
    if re.search(r"(?m)^\s*fn\s+\w+\(", muestra):
        return "rust"
    if re.search(r"<[a-zA-Z][^>]*>.*</[a-zA-Z]+>", muestra, re.DOTALL):
        return "html"
    return "generico"


def _extraer_bloques_codigo(codigo: str, lenguaje: str) -> list[tuple[str, str]]:
    """Extrae pares (nombre_bloque, fragmento) según el lenguaje sin dependencias externas."""
    limpio = codigo.strip("\n")
    if not limpio.strip():
        return []

    patron: Optional[str] = None
    if lenguaje == "python":
        patron = r"(?m)^(?:async\s+def|def|class)\s+([a-zA-Z_]\w*)"
    elif lenguaje in ("javascript", "typescript"):
        patron = r"(?m)^(?:export\s+)?(?:async\s+)?(?:function|class)\s+([a-zA-Z_$][\w$]*)|^(?:export\s+)?const\s+([a-zA-Z_$][\w$]*)\s*="
    elif lenguaje in ("go", "rust"):
        patron = r"(?m)^(?:pub\s+)?(?:fn|func|struct|type)\s+([a-zA-Z_]\w*)"

    if patron:
        lineas = limpio.splitlines()
        indices: list[tuple[int, str]] = []
        for idx, linea in enumerate(lineas):
            m = re.match(patron, linea)
            if m:
                simbolo = next((g for g in m.groups() if g), f"Bloque {len(indices) + 1}")
                indices.append((idx, simbolo))
        if len(indices) >= 2:
            bloques: list[tuple[str, str]] = []
            for pos, (inicio, simbolo) in enumerate(indices):
                fin = indices[pos + 1][0] if pos + 1 < len(indices) else len(lineas)
                trozo = "\n".join(lineas[inicio:fin]).strip()
                if trozo:
                    bloques.append((simbolo, trozo))
            if bloques:
                return bloques

    if lenguaje == "sql":
        sentencias = [s.strip() for s in re.split(r";\s*", limpio) if s.strip()]
        if len(sentencias) >= 2:
            return [(f"Consulta SQL {i + 1}", f"{s};") for i, s in enumerate(sentencias)]

    partes = [p.strip() for p in re.split(r"\n\s*\n", limpio) if p.strip()]
    if len(partes) >= 2 and len(limpio.splitlines()) > 16:
        agrupados: list[tuple[str, str]] = []
        for idx, p in enumerate(partes):
            primera = p.splitlines()[0].strip()[:48]
            agrupados.append((primera or f"Sección {idx + 1}", p))
        return agrupados

    return [("Fragmento principal", limpio)]


def _resumir_bloque(nombre: str, trozo: str, lenguaje: str, objetivo: str) -> tuple[str, str, str]:
    """Construye (notas, analogia, idea_clave) describiendo el comportamiento observable del código."""
    lineas = [l.strip() for l in trozo.splitlines() if l.strip()]
    pistas: list[str] = []
    if objetivo:
        pistas.append(f"Objetivo: {objetivo.strip()}.")
    if re.search(r"\b(async|await|Promise)\b", trozo):
        pistas.append("Ejecuta operaciones asíncronas sin bloquear el hilo principal.")
    if re.search(r"\b(if|elif|else|switch|case)\b", trozo):
        pistas.append("Evalúa ramificaciones o validaciones condicionales antes de continuar.")
    if re.search(r"\b(for|while|map|filter|reduce)\b", trozo):
        pistas.append("Itera o transforma una colección de elementos.")
    if re.search(r"\b(try|except|catch|raise|throw)\b", trozo):
        pistas.append("Incluye manejo o lanzamiento explícito de errores/excepciones.")
    if re.search(r"\b(return|yield)\b", trozo):
        ret = re.findall(r"(?:return|yield)\s+([^\n;]+)", trozo)
        if ret:
            pistas.append(f"Devuelve o produce: {ret[-1][:120]}.")
    if re.search(r"(?i)\b(SELECT|INSERT|UPDATE|DELETE|JOIN|WHERE)\b", trozo):
        pistas.append("Consulta o modifica datos persistentes mediante cláusulas SQL.")
    if not pistas:
        pistas.append(f"Implementa la lógica de «{nombre}» en {lenguaje} ({len(lineas)} línea(s)).")

    notas = " ".join(pistas)
    analogia = (
        f"Piensa en «{nombre}» como una estación especializada en {lenguaje}: recibe entradas, "
        "aplica sus reglas internas y entrega un resultado predecible."
    )
    idea_clave = pistas[-1] if len(pistas) > 1 else pistas[0]
    return notas, analogia, idea_clave


def descomponer_codigo_local(
    codigo: str, titulo: str = "", lenguaje: str = "", objetivo: str = "", max_fichas: int = 5,
) -> list[FichaExtraida]:
    lang = detectar_lenguaje(codigo, lenguaje)
    bloques = _extraer_bloques_codigo(codigo, lang)
    limite = max(1, min(int(max_fichas), 10))
    if len(bloques) > limite:
        # Compacta bloques sobrantes al límite pedido para no perder partes del código.
        principales = bloques[: limite - 1]
        resto_txt = "\n\n".join(t for _, t in bloques[limite - 1:])
        principales.append((f"Bloque complementario ({len(bloques) - limite + 1} partes)", resto_txt))
        bloques = principales

    prefijo = f"{titulo.strip()}: " if titulo.strip() else ""
    fichas: list[FichaExtraida] = []
    for idx, (simbolo, trozo) in enumerate(bloques, start=1):
        base_nombre = f"{prefijo}{simbolo}" if not prefijo or simbolo != "Fragmento principal" else titulo.strip()
        if not base_nombre:
            base_nombre = f"Código {lang} ({idx})" if len(bloques) > 1 else f"Código {lang}: {simbolo}"
        notas, analogia, idea_clave = _resumir_bloque(simbolo, trozo, lang, objetivo)
        fichas.append(
            FichaExtraida(
                nombre=base_nombre[:200],
                notas=notas[:8000],
                tipo="codigo",
                codigo=trozo[:12000],
                lenguaje=lang[:40],
                analogia=analogia[:2000],
                idea_clave=idea_clave[:1000],
                etiquetas=f"{lang},codigo",
            )
        )
    return fichas


def generar_pregunta_codigo_local(
    tema: dict[str, Any], modo: str, rng: Optional[random.Random] = None,
) -> tuple[str, str]:
    r = rng or random.Random()
    nombre = str(tema.get("nombre") or "este código")
    lang = str(tema.get("lenguaje") or "código")
    codigo = str(tema.get("codigo") or "")
    notas = str(tema.get("notas") or "")
    idea = str(tema.get("idea_clave") or notas or nombre)

    if modo == "predice_salida":
        rets = re.findall(r"(?:return|yield)\s+([^\n;]+)", codigo)
        if rets:
            expr = rets[-1].strip()[:120]
            return (
                f"En el fragmento «{nombre}» ({lang}), ¿qué resultado o efecto produce la expresión `{expr}` y en qué condición se alcanza?",
                f"{expr}. {idea}"[:1000],
            )
    if modo == "detecta_bug":
        conds = re.findall(r"(?:if|elif|while|WHERE)\s+([^\n:{]+)", codigo, flags=re.IGNORECASE)
        if conds:
            cond = conds[0].strip()[:100]
            return (
                f"En «{nombre}» ({lang}), ¿qué fallo o comportamiento incorrecto ocurriría si se omitiera o invirtiera la condición `{cond}`?",
                f"Fallaría el control sobre {cond}. {idea}"[:1000],
            )
    if modo == "concepto":
        tokens = [
            t for t in re.findall(r"\b[a-zA-Z_]\w{3,}\b", codigo)
            if t.lower() not in _PALABRAS_RESERVADAS
        ]
        if tokens:
            clave = r.choice(tokens[:8])
            hueco = re.sub(rf"\b{re.escape(clave)}\b", "_____", codigo, count=1)
            muestra = "\n".join(hueco.splitlines()[:6])
            return (
                f"Completa el identificador o símbolo que falta (`_____`) en «{nombre}» ({lang}):\n{muestra}",
                clave,
            )

    return (
        f"Explica con tus palabras qué hace «{nombre}» ({lang}) y cuál es su idea clave.",
        idea[:1000],
    )


def descomponer_material_local(
    contenido: str, titulo: str = "", max_fichas: int = 5,
) -> list[FichaExtraida]:
    texto = contenido.strip()
    if not texto:
        return []
    limite = max(1, min(int(max_fichas), 15))

    # 1. Intentar segmentar por encabezados Markdown (#, ##, ###)
    secciones = re.split(r"(?m)^#{1,3}\s+", texto)
    candidatos: list[tuple[str, str]] = []
    if len(secciones) > 1:
        intro = secciones[0].strip()
        if intro and len(intro) >= 20:
            candidatos.append((titulo.strip() or "Introducción", intro))
        for sec in secciones[1:]:
            lineas = sec.strip().splitlines()
            if not lineas:
                continue
            cab = lineas[0].strip().strip("#").strip()[:180]
            cuerpo = "\n".join(lineas[1:]).strip() or cab
            candidatos.append((cab, cuerpo))
    else:
        # 2. Segmentar por bloques/párrafos o listas
        bloques = [b.strip() for b in re.split(r"\n\s*\n", texto) if b.strip()]
        if len(bloques) == 1:
            viñetas = [l.strip(" -*•\t") for l in texto.splitlines() if l.strip()]
            if len(viñetas) >= 2:
                bloques = viñetas
        for idx, b in enumerate(bloques, start=1):
            primera = b.splitlines()[0].strip(" -*•#\t")
            nombre = primera[:90] if len(primera) >= 4 else f"{titulo.strip() or 'Concepto'} #{idx}"
            candidatos.append((nombre, b))

    fichas: list[FichaExtraida] = []
    prefijo = f"{titulo.strip()} — " if titulo.strip() and len(candidatos) > 1 else ""
    for nombre, cuerpo in candidatos[:limite]:
        codigo = ""
        lenguaje = ""
        m_cod = re.search(r"```([a-zA-Z0-9_-]*)\n([\s\S]*?)```", cuerpo)
        if m_cod:
            lenguaje = detectar_lenguaje(m_cod.group(2), m_cod.group(1))
            codigo = m_cod.group(2).strip()[:12000]
            cuerpo_limpio = (cuerpo[:m_cod.start()] + cuerpo[m_cod.end():]).strip() or nombre
        else:
            cuerpo_limpio = cuerpo
        frases = [f.strip() for f in re.split(r"(?<=[.!?])\s+|\n+", cuerpo_limpio) if f.strip()]
        idea = frases[-1] if frases else cuerpo_limpio[:200]
        nombre_final = f"{prefijo}{nombre}" if prefijo and not nombre.startswith(titulo.strip()) else nombre
        fichas.append(
            FichaExtraida(
                nombre=nombre_final[:200],
                notas=cuerpo_limpio[:8000],
                tipo="material",
                codigo=codigo,
                lenguaje=lenguaje,
                analogia="",
                idea_clave=idea[:1000],
                etiquetas="material,apuntes",
            )
        )
    return fichas


_EXT_LENGUAJE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".sql": "sql",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".html": "html",
    ".css": "css",
    ".sh": "bash",
    ".ps1": "bash",
}


def _lenguaje_por_ruta(ruta: str, codigo: str) -> str:
    for ext, lang in _EXT_LENGUAJE.items():
        if ruta.lower().endswith(ext):
            return lang
    return detectar_lenguaje(codigo)


def parsear_git_diff_local(
    diff_texto: str, titulo: str = "", max_fichas: int = 5,
) -> list[FichaExtraida]:
    """Convierte un git diff unificado en fichas atómicas por archivo modificado."""
    texto = diff_texto.strip()
    if not texto:
        return []
    limite = max(1, min(int(max_fichas), 10))

    secciones = re.split(r"(?m)^diff --git\s+", texto)
    bloques_archivo: list[tuple[str, str]] = []
    if len(secciones) > 1:
        for sec in secciones[1:]:
            lineas = sec.splitlines()
            cab = lineas[0] if lineas else ""
            m_ruta = re.search(r"b/([^\s]+)", cab)
            ruta = m_ruta.group(1) if m_ruta else cab.split(" ")[-1]
            cuerpo = "\n".join(lineas[1:]).strip()
            if cuerpo:
                bloques_archivo.append((ruta, cuerpo))
    else:
        # Soporta diffs parciales con cabecera +++ b/ruta o sin diff --git
        m_plus = re.search(r"(?m)^\+\+\+\s+(?:b/)?([^\s]+)", texto)
        ruta = m_plus.group(1) if m_plus and m_plus.group(1) != "/dev/null" else (titulo.strip() or "cambio.diff")
        bloques_archivo.append((ruta, texto))

    prefijo = f"{titulo.strip()}: " if titulo.strip() else "Diff: "
    fichas: list[FichaExtraida] = []
    for ruta, cuerpo in bloques_archivo[:limite]:
        agregadas = [
            l[1:] for l in cuerpo.splitlines()
            if l.startswith("+") and not l.startswith("+++")
        ]
        eliminadas = [
            l[1:] for l in cuerpo.splitlines()
            if l.startswith("-") and not l.startswith("---")
        ]
        muestra_codigo = "\n".join(agregadas[:40]).strip() or cuerpo[:3000]
        lang = _lenguaje_por_ruta(ruta, muestra_codigo)
        resumen = (
            f"Archivo «{ruta}» ({lang}): +{len(agregadas)} línea(s) añadida(s), "
            f"-{len(eliminadas)} eliminada(s)."
        )
        notas_extra = ""
        if agregadas:
            ejemplo_linea = next((x.strip() for x in agregadas if x.strip()), "")
            if ejemplo_linea:
                notas_extra = f" Cambio principal incluye: `{ejemplo_linea[:140]}`."
        fichas.append(
            FichaExtraida(
                nombre=f"{prefijo}{ruta}"[:200],
                notas=f"{resumen}{notas_extra}"[:8000],
                tipo="codigo",
                codigo=muestra_codigo[:12000],
                lenguaje=lang[:40],
                analogia=f"Este diff funciona como una cirugía puntual sobre «{ruta}»: cambia solo lo necesario manteniendo el resto intacto.",
                idea_clave=resumen[:1000],
                etiquetas=f"{lang},diff,codigo",
            )
        )
    return fichas


def generar_pista_progresiva(pregunta: dict[str, Any], nivel: int) -> str:
    """Genera una pista gradual (1..3) sin revelar la respuesta esperada literal."""
    nivel_clamped = max(1, min(int(nivel), 3))
    esperada = str(pregunta.get("respuesta_esperada") or "").strip()
    explicacion = str(pregunta.get("explicacion") or pregunta.get("idea_clave") or "").strip()
    analogia = str(pregunta.get("analogia") or "").strip()
    categoria = str(pregunta.get("lenguaje") or pregunta.get("categoria") or pregunta.get("tipo") or "estudio").strip()
    opciones = pregunta.get("opciones")

    if nivel_clamped == 1:
        if analogia:
            return f"Pista 1/3 (enfoque): {analogia[:240]}"
        if opciones:
            return f"Pista 1/3: Hay {len(opciones)} opciones; descarta primero las que contradicen el concepto clave de {categoria}."
        return f"Pista 1/3 (enfoque): Piensa en el propósito central de «{pregunta.get('tema', 'este tema')}» en {categoria}."

    if nivel_clamped == 2:
        if explicacion:
            return f"Pista 2/3 (idea clave): {explicacion[:260]}"
        palabras = [p for p in re.findall(r"\w+", esperada) if len(p) > 3]
        if palabras:
            return f"Pista 2/3: Tu respuesta debería conectar aproximadamente {len(palabras)} concepto(s) clave."
        return "Pista 2/3: Revisa el efecto directo o valor que devuelve la regla/operación preguntada."

    # Nivel 3: esqueleto enmascarado sin entregar la respuesta literal
    if opciones and esperada in opciones:
        idx = opciones.index(esperada)
        zona = "A-B" if idx < 2 else "C-D" if idx < 4 else "E-H"
        return f"Pista 3/3 (estructura): Empieza por «{esperada[0]}…» ({len(esperada)} caracteres) y está en el grupo {zona}."

    tokens = [t for t in re.findall(r"[a-zA-Z0-9áéíóúñÁÉÍÓÚÑ_]+", esperada)]
    if not tokens:
        return "Pista 3/3: Responde con una definición breve y precisa del concepto central."
    primera = tokens[0]
    mascara = primera[0] + ("*" * max(1, min(len(primera) - 1, 6)))
    return f"Pista 3/3 (estructura): Empieza por «{mascara}» ({len(primera)} letras) · total ~{len(tokens)} palabra(s)."


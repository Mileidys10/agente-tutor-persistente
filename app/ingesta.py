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
    "function", "select", "where", "from", "insert", "update", "delete", "raise",
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

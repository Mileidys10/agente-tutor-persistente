"""Banco de tarjetas DevCards (1 295 tarjetas de github.com/Mileidys10/devcards_ai, licencia MIT).

Es de solo lectura: el progreso de cada tarjeta vive en la memoria del agente (tabla temas),
no en este archivo.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional

RUTA_POR_DEFECTO = Path(__file__).resolve().parent / "data" / "devcards.json"
ORDEN_DIFICULTAD = {"Principiante": 0, "Intermedio": 1, "Avanzado": 2}
LETRAS = "ABCDEFGH"


class BancoDevCards:
    def __init__(self, ruta: Path = RUTA_POR_DEFECTO) -> None:
        self.tarjetas: list[dict[str, Any]] = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else []
        self.por_id = {str(t["id"]): t for t in self.tarjetas}
        self._conteo = Counter(str(t.get("category", "")) for t in self.tarjetas)

    def __len__(self) -> int:
        return len(self.tarjetas)

    def categorias(self) -> list[dict[str, Any]]:
        return [{"categoria": c, "tarjetas": n} for c, n in sorted(self._conteo.items())]

    def existe_categoria(self, categoria: str) -> bool:
        return categoria in self._conteo

    def siguiente(self, categorias_activas: list[str], ya_introducidas: set[str]) -> Optional[dict[str, Any]]:
        """Próxima tarjeta nueva: de los mazos activos, primero lo más fácil, alternando mazos."""
        if not categorias_activas:
            return None
        restantes_por_mazo = {
            c: sorted(
                (t for t in self.tarjetas if t.get("category") == c and str(t["id"]) not in ya_introducidas),
                key=lambda t: ORDEN_DIFICULTAD.get(str(t.get("difficulty")), 1),
            )
            for c in categorias_activas
        }
        # Alterna mazos: elige el mazo activo del que menos tarjetas se han introducido.
        introducidas_por_mazo = Counter(
            str(self.por_id[r].get("category")) for r in ya_introducidas if r in self.por_id
        )
        candidatos = [c for c in categorias_activas if restantes_por_mazo[c]]
        if not candidatos:
            return None
        mazo = min(candidatos, key=lambda c: (introducidas_por_mazo[c], categorias_activas.index(c)))
        return restantes_por_mazo[mazo][0]

    @staticmethod
    def notas_de(tarjeta: dict[str, Any]) -> str:
        partes = [tarjeta.get("definition", ""), tarjeta.get("key_takeaway", "")]
        return "\n".join(str(p) for p in partes if p)

    @staticmethod
    def pregunta_de(tarjeta: dict[str, Any], variante: int) -> dict[str, Any]:
        """Alterna entre el quiz de opción múltiple (corrección exacta) y la pregunta abierta de la tarjeta."""
        opciones = tarjeta.get("quiz_options") or []
        explicacion = str(tarjeta.get("key_takeaway") or tarjeta.get("definition") or "")
        if opciones and variante % 2 == 0:
            correcta = opciones[int(tarjeta["quiz_answer"])]
            return {
                "texto": str(tarjeta["quiz_question"]),
                "respuesta_esperada": str(correcta),
                "opciones": [str(o) for o in opciones],
                "explicacion": explicacion,
            }
        return {
            "texto": str(tarjeta.get("question") or f"Explica: {tarjeta.get('title')}"),
            "respuesta_esperada": str(tarjeta.get("definition", "")),
            "opciones": None,
            "explicacion": explicacion,
        }

"""Algoritmo SM-2 (SuperMemo 2) de repetición espaciada, como función pura."""

from __future__ import annotations

from dataclasses import dataclass

FACILIDAD_INICIAL = 2.5
FACILIDAD_MINIMA = 1.3


@dataclass(frozen=True)
class EstadoSM2:
    repeticiones: int = 0
    intervalo_dias: float = 0.0
    facilidad: float = FACILIDAD_INICIAL


def actualizar(estado: EstadoSM2, calidad: int) -> EstadoSM2:
    """Calidad 0-5 (0 = no recordó nada, 5 = respuesta perfecta). Devuelve el nuevo estado."""
    if not 0 <= calidad <= 5:
        raise ValueError("La calidad debe estar entre 0 y 5")
    facilidad = estado.facilidad + 0.1 - (5 - calidad) * (0.08 + (5 - calidad) * 0.02)
    facilidad = max(FACILIDAD_MINIMA, round(facilidad, 4))
    if calidad < 3:  # falló: el tema vuelve pronto y se reinicia la racha
        return EstadoSM2(repeticiones=0, intervalo_dias=1.0, facilidad=facilidad)
    repeticiones = estado.repeticiones + 1
    if repeticiones == 1:
        intervalo = 1.0
    elif repeticiones == 2:
        intervalo = 6.0
    else:
        intervalo = round(estado.intervalo_dias * facilidad, 2)
    return EstadoSM2(repeticiones=repeticiones, intervalo_dias=intervalo, facilidad=facilidad)

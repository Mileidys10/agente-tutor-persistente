# Archivo app/sm2.py: calcula cuándo te toca volver a repasar un tema usando el algoritmo SuperMemo 2.
# Es una función pura (no toca base de datos); la llama AgenteTutor.responder() en app/agente.py cada vez que contestas.
"""Algoritmo SM-2 (SuperMemo 2) de repetición espaciada, como función pura."""

from __future__ import annotations

from dataclasses import dataclass

# Todo tema nuevo arranca con facilidad 2.5 y nunca baja de 1.3 para no quedarse atrapado en repasos infinitos.
FACILIDAD_INICIAL = 2.5
FACILIDAD_MINIMA = 1.3


# Guarda los tres números de memoria espaciada de un tema: racha de aciertos, intervalo y facilidad.
@dataclass(frozen=True)
class EstadoSM2:
    repeticiones: int = 0
    intervalo_dias: float = 0.0
    facilidad: float = FACILIDAD_INICIAL


# Recibe el estado actual del tema y la nota obtenida (0 a 5) y devuelve cuándo volver a preguntarlo.
# La llama AgenteTutor.responder() en app/agente.py justo después de evaluar tu respuesta.
def actualizar(estado: EstadoSM2, calidad: int) -> EstadoSM2:
    """Calidad 0-5 (0 = no recordó nada, 5 = respuesta perfecta). Devuelve el nuevo estado."""
    if not 0 <= calidad <= 5:
        raise ValueError("La calidad debe estar entre 0 y 5")
    # Fórmula oficial de SM-2: sube o baja el factor de facilidad según qué tan seguro respondiste.
    facilidad = estado.facilidad + 0.1 - (5 - calidad) * (0.08 + (5 - calidad) * 0.02)
    facilidad = max(FACILIDAD_MINIMA, round(facilidad, 4))
    if calidad < 3:  # falló: el tema vuelve pronto y se reinicia la racha
        return EstadoSM2(repeticiones=0, intervalo_dias=1.0, facilidad=facilidad)
    # Si acertaste (nota >= 3): 1.ª vez = 1 día, 2.ª = 6 días, siguientes = intervalo anterior × facilidad.
    repeticiones = estado.repeticiones + 1
    if repeticiones == 1:
        intervalo = 1.0
    elif repeticiones == 2:
        intervalo = 6.0
    else:
        intervalo = round(estado.intervalo_dias * facilidad, 2)
    return EstadoSM2(repeticiones=repeticiones, intervalo_dias=intervalo, facilidad=facilidad)

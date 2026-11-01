"""Veredito de um experimento fechado: regra z-score local primeiro, o Jev (experimento_veredito) só na fronteira.

z = (média pós − média dos 7 dias anteriores) / erro padrão, com o desvio padrão dos 7 dias anteriores.
|z| ≥ z_real → 'real'; |z| < z_ruido → 'ruído'; entre os dois → 'fronteira' (vai ao Jev). Amostra abaixo de
n_minimo em qualquer janela → 'sem_dados', que nunca vira evidência. Os limiares estão calibrados em série sintética
(tests/test_veredito_experimento.py): falso positivo ≤ 5% em ruído puro, detecção ≥ 80% com efeito de 2 desvios.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Literal, Sequence

from .decision import Decision

PERGUNTA = "experimento_veredito"
Estado = Literal["sem_dados", "real", "ruído", "fronteira"]


@dataclass(frozen=True)
class Limiares:
    n_minimo: int = 50       # pontos por janela (Spinnaker: ≥ 50 para a análise ser confiável)
    z_real: float = 2.2      # 2,0 dá 5,4% de falso positivo em ruído puro (n=50, 20 mil ensaios); 2,2 dá 3,6%
    z_ruido: float = 1.0
    corte_jev: float = 0.6   # só confiança do Jev acima disto conta como evidência


LIMIARES = Limiares()


@dataclass(frozen=True)
class Veredito:
    estado: Estado
    z: float | None
    n_pos: int
    n_antes: int


def julgar(pos: Sequence[float], antes: Sequence[float], lim: Limiares = LIMIARES) -> Veredito:
    n_pos, n_antes = len(pos), len(antes)
    if min(n_pos, n_antes) < max(lim.n_minimo, 2):
        return Veredito("sem_dados", None, n_pos, n_antes)
    delta = statistics.fmean(pos) - statistics.fmean(antes)
    erro = statistics.stdev(antes) * math.sqrt(1 / n_pos + 1 / n_antes)
    z = delta / erro if erro else (0.0 if delta == 0 else math.copysign(math.inf, delta))
    estado: Estado = "real" if abs(z) >= lim.z_real else "ruído" if abs(z) < lim.z_ruido else "fronteira"
    return Veredito(estado, z, n_pos, n_antes)


def com_jev(v: Veredito, jev: Decision | None, lim: Limiares = LIMIARES) -> str:
    """Veredito final: a regra manda fora da fronteira; na fronteira, só um Jev confiante (> corte) decide."""
    if v.estado != "fronteira":
        return v.estado
    if jev is None or jev.confidence <= lim.corte_jev:
        return "inconclusivo"
    return "real" if float(jev.value) > 0.5 else "ruído"

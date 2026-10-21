"""Contrato de saída JSON de um papel (lição #22): as chaves obrigatórias do esquema chegam inteiras, ou um motivo tipado.

Lê com circulo.json_llm (o primeiro objeto que o papel aceita, inteiro ou cortado pelo limite de tokens no último valor
completo) e devolve só as chaves do esquema. Valor cortado no meio não é fechado nem preenchido: a chave falta, e o
motivo diz qual e se foi o corte, em vez de um "resposta sem JSON válido" que não distingue truncamento de formato.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .json_llm import objeto_ou_corte


class Motivo(str, Enum):
    OK = "ok"
    VAZIA = "vazia"
    SEM_JSON = "sem_json"
    FALTA_CHAVE = "falta_chave"
    RECUSADA = "recusada"


@dataclass(frozen=True)
class Saida:
    dados: dict | None
    motivo: Motivo
    faltam: tuple[str, ...] = ()
    cortada: bool = False

    def __str__(self) -> str:
        s = self.motivo.value + (f": {', '.join(self.faltam)}" if self.faltam else "")
        return s + (" (cortada pelo limite de tokens)" if self.cortada else "")


def ler(texto: str, obrigatorias: tuple[str, ...], opcionais: tuple[str, ...] = (),
        aceita: Callable[[dict, bool], dict | None] | None = None) -> Saida:
    """O primeiro objeto com todas as `obrigatorias` (não vazias) que `aceita(d, cortado)` não recusa, só com as chaves
    do esquema; senão, o motivo do candidato que chegou mais perto."""
    vistos: list[tuple[tuple[str, ...], bool]] = []

    def _contrato(d: dict, cortado: bool):
        faltam = tuple(k for k in obrigatorias if d.get(k) in (None, "", [], {}))
        vistos.append((faltam, cortado))
        if faltam:
            return None
        r = {k: d[k] for k in (*obrigatorias, *opcionais) if k in d}
        r = aceita(r, cortado) if aceita else r
        return None if r is None else (r, cortado)

    achado = objeto_ou_corte(texto, _contrato)
    if achado is not None:
        return Saida(achado[0], Motivo.OK, cortada=achado[1])
    if not (texto or "").strip():
        return Saida(None, Motivo.VAZIA)
    if not vistos:
        return Saida(None, Motivo.SEM_JSON)
    faltam, cortado = min(vistos, key=lambda v: len(v[0]))
    return Saida(None, Motivo.FALTA_CHAVE if faltam else Motivo.RECUSADA, faltam, cortado)

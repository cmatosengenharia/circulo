"""Portão pré-PR (pergunta do conselho #74): não abrir PR enquanto o CI da main está vermelho ou nem iniciou.

7 dos 8 PRs do gate_recente fecharam com os mesmos 7 checks falhando ao mesmo tempo: causa comum e externa ao PR
(main vermelha, lição #50). Como no Chromium (árvore fechada, só entra o conserto dela) e na merge queue do GitHub
(valida contra a base atual e espera os checks rodarem), o developer:abrir_pr lê o último CI da main antes do push e
adia com a causa normalizada. 'CI sem iniciar' (limite de gasto, como no #86) tem causa própria. Mede-se pela
verificação `developer:abrir_pr:adiar` por causa contra os fechamentos no gate_recente.
"""
from __future__ import annotations

import urllib.error
from dataclasses import dataclass

from .merge_gate import CI_NAO_INICIOU as NAO_INICIOU_MSG
from .merge_gate import checks_ok

ABRIR, ADIAR = "abrir", "adiar"
MAIN_VERMELHA, CI_NAO_INICIOU = "main_vermelha", "ci_nao_iniciou"
ADIAR_PONTO = "developer:abrir_pr:adiar"
LICAO_MAIN = "gate:main_vermelha"


@dataclass(frozen=True)
class Decisao:
    acao: str
    causa: str = ""


def decidir(conclusao: str | None, jobs_executaram: bool, conserta_main: bool = False) -> Decisao:
    """Último CI da main → abrir ou adiar. O item que conserta a main vermelha abre (é ele que reabre a árvore);
    com o CI sem iniciar nem ele abre, porque o CI do PR também não rodaria."""
    if conclusao != "failure":
        return Decisao(ABRIR)
    if not jobs_executaram:
        return Decisao(ADIAR, CI_NAO_INICIOU)
    return Decisao(ABRIR) if conserta_main else Decisao(ADIAR, MAIN_VERMELHA)


def ler_main(gh) -> tuple[str | None, bool]:
    """(conclusão do último CI da main, se os jobs executaram passos). Sem como ler: (None, True), não inventa causa."""
    ci = getattr(gh, "main_ci", None)
    if ci is None:
        return None, True
    try:
        sha, conclusao = ci()
        if conclusao != "failure" or not sha:
            return conclusao, True
        _, why = checks_ok(gh.check_runs(sha))
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
        return None, True
    return conclusao, not why.startswith(NAO_INICIOU_MSG)


def conserta_main(store, item_id: int | None) -> bool:
    return item_id is not None and store.one("SELECT 1 FROM licoes WHERE assinatura=? AND item_id=?",
                                             (LICAO_MAIN, item_id)) is not None

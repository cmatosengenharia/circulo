"""Portão pré-PR (pergunta do conselho #74): não abrir PR enquanto o CI da main está vermelho ou nem iniciou.

7 dos 8 PRs do gate_recente fecharam com os mesmos 7 checks falhando ao mesmo tempo: causa comum e externa ao PR
(main vermelha, lição #50). Como no Chromium (árvore fechada, só entra o conserto dela) e na merge queue do GitHub
(valida contra a base atual e espera os checks rodarem), o developer:abrir_pr lê o último CI da main antes do push e
adia com a causa normalizada. 'CI sem iniciar' (limite de gasto, como no #86) tem causa própria. Mede-se pela
verificação `developer:abrir_pr:adiar` por causa contra os fechamentos no gate_recente.

Pergunta do conselho #75: mesmo com a main verde, os últimos MIN_PRS PRs falhando com o mesmo conjunto de checks,
e ele cobrindo todos os obrigatórios (PRs 49 e 80-84: os mesmos 7), é causa sistêmica: adia com 'adiado_sistemico'.
O histórico só vale desde a última main verde e dentro de JANELA, para o próximo PR voltar a ser a sonda.
"""
from __future__ import annotations

import re
import urllib.error
from dataclasses import dataclass

from .merge_gate import CI_NAO_INICIOU as NAO_INICIOU_MSG
from .merge_gate import REQUIRED_CHECKS, checks_ok

ABRIR, ADIAR = "abrir", "adiar"
MAIN_VERMELHA, CI_NAO_INICIOU, SISTEMICO = "main_vermelha", "ci_nao_iniciou", "adiado_sistemico"
ADIAR_PONTO = "developer:abrir_pr:adiar"
LICAO_MAIN = "gate:main_vermelha"
MIN_PRS, JANELA = 3, 24 * 3600
DO_PR, FALHANDO = re.compile(r"PR #(\d+)"), "checks falhando: "


@dataclass(frozen=True)
class Decisao:
    acao: str
    causa: str = ""


def decidir(conclusao: str | None, jobs_executaram: bool, conserta_main: bool = False,
            historico: list[set[str]] = (), obrigatorios=REQUIRED_CHECKS) -> Decisao:
    """Último CI da main e os checks falhando de cada PR recente (do mais recente) → abrir ou adiar. O item que
    conserta a main vermelha abre (é ele que reabre a árvore); com o CI sem iniciar nem ele abre, porque o CI do PR
    também não rodaria."""
    if conclusao == "failure" and not jobs_executaram:
        return Decisao(ADIAR, CI_NAO_INICIOU)
    if conserta_main:
        return Decisao(ABRIR)
    if conclusao == "failure":
        return Decisao(ADIAR, MAIN_VERMELHA)
    ultimos = historico[:MIN_PRS]
    if len(ultimos) == MIN_PRS and all(c == ultimos[0] for c in ultimos) and set(obrigatorios) <= ultimos[0]:
        return Decisao(ADIAR, SISTEMICO)
    return Decisao(ABRIR)


def checks_dos_prs(store, agora: float) -> list[set[str]]:
    """Os checks falhando de cada PR (do mais recente) no gate:ci, desde a última main verde e dentro de JANELA."""
    verde = store.one("SELECT MAX(created_at) t FROM verificacoes WHERE ponto='gate:main' AND ok=1")
    desde = max(agora - JANELA, (verde["t"] if verde else None) or 0)
    vistos, historico = set(), []
    for r in store.q("SELECT sujeito, motivo FROM verificacoes WHERE ponto='gate:ci' AND ok=0 AND created_at>? "
                     "ORDER BY id DESC", (desde,)):
        m, primeira = DO_PR.search(r["sujeito"] or ""), (r["motivo"] or "").split("\n", 1)[0]
        if m and m.group(1) not in vistos and primeira.startswith(FALHANDO):
            vistos.add(m.group(1))
            historico.append({c.strip() for c in primeira[len(FALHANDO):].split(",") if c.strip()})
    return historico


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

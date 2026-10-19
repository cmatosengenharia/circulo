"""Canário de falha: ponto de verificação que nunca falhou pode estar quebrado sem ninguém saber.

Para cada ponto que só passou, o ciclo de saúde injeta a falha de propósito num estado temporário e compara com um
controle sem falha (fault injection com grupo de controle): a falha tem de ser acusada e o controle tem de passar.
O resultado vira um evento em `canarios`; o auditor do conselho só conta como "nunca exercitado" o ponto sem canário
verde recente.
"""
from __future__ import annotations

import time
from typing import Callable

from . import confianca
from .state import Store

INTERVALO = 86400          # um canário por ponto por dia
VALIDADE = 7 * 86400       # canário verde mais velho que isso não prova mais nada


def _ok_do_ultimo(s: Store, ponto: str) -> bool:
    r = s.one("SELECT ok FROM verificacoes WHERE ponto=? ORDER BY id DESC LIMIT 1", (ponto,))
    return bool(r and r["ok"])


def _painel_frescor(velho: bool) -> bool:
    s = Store(":memory:")
    dado_em = time.time() - (60 if velho else 0.2)               # o painel velho mostra um dado de um minuto atrás
    confianca.registrar_frescor(s, (time.time() - dado_em) * 1000)
    return _ok_do_ultimo(s, "painel:frescor")


INJECOES: dict[str, Callable[[bool], bool]] = {"painel:frescor": _painel_frescor}


def injetar(ponto: str) -> dict:
    passa = INJECOES[ponto]
    velho_falhou, fresco_passou = not passa(True), passa(False)
    return {"ponto": ponto, "velho_falhou": velho_falhou, "fresco_passou": fresco_passou,
            "ok": velho_falhou and fresco_passou}


def com_canario(s: Store, now: float | None = None) -> set[str]:
    """Pontos com canário verde dentro da validade."""
    desde = (now or time.time()) - VALIDADE
    return {r["ponto"] for r in s.q("SELECT ponto FROM canarios WHERE em>=? GROUP BY ponto "
                                     "HAVING MAX(id) = MAX(CASE WHEN ok=1 THEN id END)", (desde,))}


def rodar(s: Store, reply=None, now: float | None = None) -> list[dict]:
    """Ciclo de saúde: injeta a falha em cada ponto que nunca falhou e tem injeção conhecida, no máximo 1x por dia."""
    now = now or time.time()
    pontos = [r["ponto"] for r in s.q("SELECT ponto FROM verificacoes GROUP BY ponto HAVING SUM(ok=0)=0")]
    out = []
    for p in pontos:
        if p not in INJECOES or s.one("SELECT 1 FROM canarios WHERE ponto=? AND em>?", (p, now - INTERVALO)):
            continue
        r = injetar(p)
        s.x("INSERT INTO canarios(ponto, ok, velho_falhou, fresco_passou, em) VALUES(?,?,?,?,?)",
            (p, int(r["ok"]), int(r["velho_falhou"]), int(r["fresco_passou"]), now))
        if not r["ok"] and reply:
            reply(f"Canário de {p} falhou: a falha injetada {'não foi acusada' if not r['velho_falhou'] else 'acusou também o controle'}.",
                  "saude")
        out.append(r)
    return out

"""Trilha write-ahead das ações do loop: a intenção é gravada ANTES de a ação rodar.

"Nenhuma ação sem aparecer" fica garantido por construção, e não pelo push do painel:
- `executar` grava a intenção (ator, ação, motivo, regra que decidiu, entradas) e só depois chama a ação; se o
  registro falhar, a ação não roda. Ao terminar, grava o resultado apontando para a intenção;
- a tabela é só de acréscimo (gatilhos do SQLite recusam UPDATE e DELETE) e cada linha leva o hash da anterior,
  então apagar, trocar ou reordenar uma linha quebra a cadeia e aparece em `verificar`;
- `divergencia` conta resultados sem intenção prévia: o alvo é 0.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable

from .state import Store

GENESE = "0" * 64
JANELA = 1000          # o painel confere a cadeia das últimas N linhas a cada leitura; `verificar(janela=None)` confere tudo


def _hash(prev: str, tipo: str, ref, tick, ator: str, acao: str, motivo: str, regra: str, entradas: str, em: float) -> str:
    corpo = json.dumps([tipo, ref, tick, ator, acao, motivo, regra, entradas, repr(float(em))], ensure_ascii=False)
    return hashlib.sha256((prev + corpo).encode()).hexdigest()


def _gravar(store: Store, tipo: str, ator: str, acao: str, motivo: str = "", regra: str = "", entradas: Any = None,
            ref: int | None = None) -> int:
    ent = json.dumps(entradas if entradas is not None else {}, ensure_ascii=False, sort_keys=True, default=str)[:2000]
    motivo, regra = str(motivo or "")[:500], str(regra or "")[:200]
    with store.tx():                     # BEGIN IMMEDIATE: o painel (outro processo) também grava; a cadeia não bifurca
        ult = store.one("SELECT hash FROM intencoes ORDER BY seq DESC LIMIT 1")
        prev, em, tick = ult["hash"] if ult else GENESE, time.time(), store.tick
        h = _hash(prev, tipo, ref, tick, ator, acao, motivo, regra, ent, em)
        return store.x("INSERT INTO intencoes(tipo,ref,tick,ator,acao,motivo,regra,entradas,em,prev,hash) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (tipo, ref, tick, ator, acao, motivo, regra, ent, em, prev, h))


def registrar(store: Store, acao: str, motivo: str, entradas: Any = None, ator: str = "loop", regra: str = "") -> int:
    """Grava a intenção e devolve o seq. Só depois disso a ação pode rodar."""
    return _gravar(store, "intencao", ator, acao, motivo, regra, entradas)


def concluir(store: Store, seq: int, ok: bool, detalhe: str = "") -> int:
    r = store.one("SELECT ator, acao FROM intencoes WHERE seq=? AND tipo='intencao'", (seq,))
    if r is None:
        raise ValueError(f"resultado sem intenção registrada (seq {seq})")
    return _gravar(store, "resultado", r["ator"], r["acao"], "ok" if ok else "falhou", "", {"detalhe": str(detalhe)[:300]}, ref=seq)


def executar(store: Store, acao: str, fn: Callable[[], Any], motivo: str, entradas: Any = None, ator: str = "loop",
             regra: str = "") -> Any:
    seq = registrar(store, acao, motivo, entradas, ator, regra)      # se isto falhar, a ação não roda
    from . import fazendo
    fazendo.marcar(store, acao, motivo)                               # a Equipe ao vivo vê o que começou
    try:
        out = fn()
    except Exception as exc:
        concluir(store, seq, False, repr(exc))
        fazendo.terminar(store, acao, f"falhou: {type(exc).__name__}")
        raise
    concluir(store, seq, True)
    fazendo.terminar(store, acao, "ok")
    return out


def verificar(store: Store, janela: int | None = JANELA) -> dict:
    """Recalcula a cadeia. `quebra` é o primeiro seq cujo hash ou elo não confere."""
    if janela is None:
        rows = store.q("SELECT * FROM intencoes ORDER BY seq")
        prev = GENESE
    else:
        rows = store.q("SELECT * FROM (SELECT * FROM intencoes ORDER BY seq DESC LIMIT ?) ORDER BY seq", (janela + 1,))
        prev = rows[0]["prev"] if rows else GENESE
    for r in rows:
        if r["prev"] != prev or r["hash"] != _hash(r["prev"], r["tipo"], r["ref"], r["tick"], r["ator"], r["acao"],
                                                   r["motivo"], r["regra"], r["entradas"], r["em"]):
            return {"ok": False, "n": len(rows), "quebra": r["seq"]}
        prev = r["hash"]
    return {"ok": True, "n": len(rows), "quebra": None}


def divergencia(store: Store, desde: float = 0) -> int:
    """Resultados (ações executadas) sem uma intenção da mesma ação gravada antes. O alvo é 0."""
    return store.one("SELECT COUNT(*) n FROM intencoes r LEFT JOIN intencoes i ON i.seq=r.ref AND i.tipo='intencao' "
                     "AND i.acao=r.acao AND i.seq<r.seq WHERE r.tipo='resultado' AND r.em>=? AND i.seq IS NULL",
                     (desde,))["n"]


def ultima(store: Store, ator: str | None = None):
    """A última intenção gravada (com o resultado, se já houver)."""
    f, a = (" AND ator=?", (ator,)) if ator else ("", ())
    i = store.one(f"SELECT * FROM intencoes WHERE tipo='intencao'{f} ORDER BY seq DESC LIMIT 1", a)
    if i is None:
        return None
    r = store.one("SELECT motivo, entradas, em FROM intencoes WHERE tipo='resultado' AND ref=?", (i["seq"],))
    return {**dict(i), "entradas": json.loads(i["entradas"] or "{}"),
            "resultado": None if r is None else {"ok": r["motivo"] == "ok", "em": r["em"], **json.loads(r["entradas"])}}

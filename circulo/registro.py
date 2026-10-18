"""Registro estruturado das chamadas de LLM.

Cada chamada fica guardada para sempre: papel, modelo, quem escolheu (o Jev, o decisor local ou o padrão do
harness quando o Jev estava inseguro), a confiança, o contexto da escolha, custo, duração, erro e se o ciclo
que a usou foi aceito. O painel mostra isso ao vivo e o próprio Jev recebe o histórico por papel e nível
quando escolhe o próximo modelo.
"""
from __future__ import annotations

import json
import time
from typing import Any

from .state import Store


def registrar(store: Store, *, tick: int, project_id: int | None, papel: str, modelo: str, escolha: dict | None = None,
              tokens: int = 0, duracao_ms: int | None = None, ok: bool = True, erro: str | None = None,
              entrada: str = "", saida: str = "") -> int:
    e = escolha or {}
    return store.x(
        "INSERT INTO llm_calls(tick,project_id,papel,modelo,nivel,decidido_por,confianca,contexto,tokens,duracao_ms,ok,erro,entrada,saida,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (tick, project_id, papel, modelo, e.get("nivel"), e.get("decidido_por", "fixo"), e.get("confianca"),
         json.dumps(e.get("contexto") or {}, ensure_ascii=False, default=str)[:2000], int(tokens or 0), duracao_ms,
         int(bool(ok)), (erro or None) and erro[:500], (entrada or "")[:400], (saida or "")[:600], time.time()))


def marcar_resultado(store: Store, project_id: int, tick: int, aceita: bool | None) -> None:
    if aceita is None:
        return
    store.x("UPDATE llm_calls SET aceita=? WHERE project_id=? AND tick=? AND aceita IS NULL", (int(aceita), project_id, tick))


def historico(store: Store, papel: str) -> dict[str, Any]:
    """Como cada nível de modelo se saiu neste papel: entra no estado da pergunta pick_model do Jev."""
    out: dict[str, Any] = {}
    for r in store.q("SELECT nivel, COUNT(*) n, SUM(ok) ok, SUM(aceita=1) aceitas, SUM(aceita IS NOT NULL) avaliadas, "
                     "AVG(tokens) tok FROM llm_calls WHERE papel=? AND nivel IS NOT NULL GROUP BY nivel", (papel,)):
        out[r["nivel"]] = {"chamadas": r["n"], "falhas": r["n"] - (r["ok"] or 0),
                           "aceitacao": round((r["aceitas"] or 0) / r["avaliadas"], 2) if r["avaliadas"] else None,
                           "tokens_medios": int(r["tok"] or 0)}
    return out


def recentes(store: Store, projeto: int | None = None, limite: int = 30) -> list[dict]:
    pf, pa = (" WHERE project_id=?", (projeto,)) if projeto else ("", ())
    return [dict(r) for r in store.q(
        f"SELECT id, tick, project_id, papel, modelo, nivel, decidido_por, confianca, tokens, duracao_ms, ok, erro, entrada, saida, aceita, created_at "
        f"FROM llm_calls{pf} ORDER BY id DESC LIMIT ?", (*pa, limite))]


def resumo(store: Store, projeto: int | None = None) -> list[dict]:
    pf, pa = (" WHERE project_id=?", (projeto,)) if projeto else ("", ())
    return [dict(r) for r in store.q(
        f"SELECT modelo, COUNT(*) chamadas, SUM(tokens) tokens, SUM(decidido_por='jev') pelo_jev, SUM(aceita=1) aceitas, "
        f"SUM(aceita IS NOT NULL) avaliadas, SUM(ok=0) falhas, AVG(duracao_ms) ms FROM llm_calls{pf} GROUP BY modelo ORDER BY chamadas DESC", pa)]

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

from . import jobs
from .llm import LLMResult
from .state import Store


def registrar(store: Store, *, tick: int, project_id: int | None, papel: str, modelo: str, escolha: dict | None = None,
              tokens: int = 0, duracao_ms: int | None = None, ok: bool = True, erro: str | None = None,
              entrada: str = "", saida: str = "", uso: LLMResult | None = None, retry: int = 0,
              variante: str | None = None) -> int:
    """`uso` é a resposta da LLM: dela saem o custo e o uso separado em entrada, saída e cache. `retry` = 1 na repetição."""
    e = escolha or {}
    if uso is not None:
        tokens = uso.tokens
    detalhe = (uso.entrada, uso.saida, uso.cache_lido, uso.cache_escrito) if uso is not None else (None,) * 4
    return store.x(
        "INSERT INTO llm_calls(tick,project_id,papel,modelo,nivel,decidido_por,confianca,contexto,tokens,duracao_ms,ok,erro,entrada,saida,"
        "tokens_entrada,tokens_saida,cache_lido,cache_escrito,job,retry,variante,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (tick, project_id, papel, modelo, e.get("nivel"), e.get("decidido_por", "fixo"), e.get("confianca"),
         json.dumps(e.get("contexto") or {}, ensure_ascii=False, default=str)[:2000], int(tokens or 0), duracao_ms,
         int(bool(ok)), (erro or None) and erro[:500], (entrada or "")[:400], (saida or "")[:600], *detalhe,
         jobs.da_missao(store, project_id), int(retry), variante, time.time()))


def tokens_retry(store: Store, dias: int = 7) -> dict[str, int]:
    """Tokens gastos em retries por papel na janela (tokens_retry_7d): o custo de repetir, medido à parte."""
    return {r["papel"]: int(r["t"] or 0) for r in store.q(
        "SELECT papel, SUM(tokens) t FROM llm_calls WHERE retry=1 AND created_at>=? GROUP BY papel ORDER BY t DESC",
        (time.time() - dias * 86400,))}


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


# ---------------------------------------------------------------- o Claude Code em streaming: cada ferramenta vira um passo
def passo_do_evento(ev: dict) -> str | None:
    """Traduz um evento `stream-json` do Claude Code num passo legível (ou None se não é um passo)."""
    if ev.get("type") != "assistant":
        return None
    for b in (ev.get("message") or {}).get("content") or []:
        if b.get("type") != "tool_use":
            continue
        nome, inp = str(b.get("name") or ""), b.get("input") or {}
        arq = str(inp.get("file_path") or inp.get("path") or inp.get("pattern") or "")
        arq = arq.rsplit("/.circulo-wt-", 1)[-1].split("/", 1)[-1] if ".circulo-wt-" in arq else arq
        if nome in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            return f"Claude Code: {'escrevendo' if nome == 'Write' else 'editando'} {arq}"
        if nome == "Read":
            return f"Claude Code: lendo {arq}"
        if nome in ("Grep", "Glob"):
            return f"Claude Code: procurando {arq or inp.get('pattern', '')}"
        if nome == "Bash":
            cmd = str(inp.get("command") or "")
            if "pytest" in cmd:
                return "Claude Code: rodando os testes"
            if "ruff" in cmd:
                return "Claude Code: rodando o lint"
            if cmd.startswith("git "):
                return f"Claude Code: git {cmd.split()[1] if len(cmd.split()) > 1 else ''}"
            return f"Claude Code: {cmd[:60]}"
        return f"Claude Code: {nome}"
    for b in (ev.get("message") or {}).get("content") or []:
        if b.get("type") == "text" and str(b.get("text") or "").strip():
            return "Claude Code: " + str(b["text"]).strip().splitlines()[0][:100]
    return None

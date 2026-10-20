"""Conexões ao vivo: o que o loop depende de fora — Jev, Claude Code, LLM, GitHub — e se cada uma responde agora.

Cada chamada externa deixa um **pulso** (ok?, quanto demorou, o erro): o Jev e o GitHub gravam aqui direto; a LLM e o
Claude Code já ficam em `llm_calls`, e o loop tem o batimento. A tela lê os pulsos e mostra, por serviço, o estado
(ok, instável, fora, parado, ocioso), a última resposta, a latência e uma linha do tempo dos últimos pulsos. Sem
chamar ninguém: olhar a faixa nunca gasta nada.
"""
from __future__ import annotations

import os
import statistics
import time
from typing import Any

from .state import Store

ESQUEMA = """
CREATE TABLE IF NOT EXISTS conexoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  servico TEXT NOT NULL,          -- jev | github | ...
  ok INTEGER NOT NULL,
  ms INTEGER,
  erro TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS conexoes_servico ON conexoes(servico, created_at);
"""
SERVICOS = (("jev", "Jev", "decisões"), ("claude", "Claude Code", "Desenvolvedor"), ("llm", "LLM", "API da Anthropic"),
            ("github", "GitHub", "PRs e CI"), ("loop", "Loop", "batimento"))
JANELA = 3600          # 1 h de histórico por serviço
SERIE = 24             # pulsos na linha do tempo
RECENTE = 600          # falha nos últimos 10 min = instável
GUARDA_DIAS = 7


def preparar(store: Store) -> None:
    """Idempotente e sem `executescript` (que fecharia a transação em curso de quem chamou)."""
    if getattr(store, "_conexoes_pronto", False):
        return
    for sql in ESQUEMA.strip().split(";"):
        if sql.strip():
            store.x(sql)
    store._conexoes_pronto = True


def pulso(store: Store, servico: str, ok: bool, ms: float | None = None, erro: str | None = None) -> None:
    """Uma chamada externa aconteceu. Nunca grava chave: só o texto do erro, cortado."""
    preparar(store)
    store.x("INSERT INTO conexoes(servico,ok,ms,erro,created_at) VALUES(?,?,?,?,?)",
            (servico, 1 if ok else 0, int(ms) if ms is not None else None, (erro or None) and str(erro)[:200], time.time()))
    if store.db.execute("SELECT COUNT(*) FROM conexoes").fetchone()[0] % 500 == 0:
        store.x("DELETE FROM conexoes WHERE created_at<?", (time.time() - GUARDA_DIAS * 86400,))


def instalar(store: Store) -> None:
    """Liga o GitHub ao registro de pulsos (o cliente é da constituição e não importa este módulo)."""
    from .merge_gate import GitHubREST
    preparar(store)
    GitHubREST.ouvinte = staticmethod(lambda ok, ms, erro: pulso(store, "github", ok, ms, erro))


# ---------------------------------------------------------------- leitura
def _pulsos(store: Store, servico: str, desde: float) -> list[dict]:
    if servico in ("llm", "claude"):
        cond = "papel='developer'" if servico == "claude" else "papel<>'developer'"
        rows = store.q(f"SELECT ok, duracao_ms ms, erro, created_at FROM llm_calls WHERE {cond} AND created_at>? ORDER BY created_at", (desde,))
    else:
        if not store.one("SELECT 1 FROM sqlite_master WHERE name='conexoes'"):
            return []
        rows = store.q("SELECT ok, ms, erro, created_at FROM conexoes WHERE servico=? AND created_at>? ORDER BY created_at", (servico, desde))
    return [{"ok": bool(r["ok"]), "ms": r["ms"], "erro": (r["erro"] or "")[:160] or None, "em": r["created_at"]} for r in rows]


def _classificar(p: list[dict], agora: float) -> str:
    if not p:
        return "ocioso"
    ultimos = p[-3:]
    if not ultimos[-1]["ok"] and sum(1 for x in ultimos if not x["ok"]) >= 2:
        return "fora"
    if any(not x["ok"] and agora - x["em"] <= RECENTE for x in p):
        return "instavel"
    return "ok"


def _servico(store: Store, chave: str, nome: str, papel: str, agora: float) -> dict:
    p = _pulsos(store, chave, agora - JANELA)
    oks = [x for x in p if x["ok"]]
    falhas = [x for x in p if not x["ok"]]
    lat = [x["ms"] for x in oks if x["ms"] is not None]
    estado, detalhe = _classificar(p, agora), ""
    from . import llm as _llm
    if chave == "llm":
        papel = _llm.provedor() if _llm.provedor() != "anthropic" else papel
    chave_env = {"jev": "TYPESAFE_API_KEY", "llm": _llm.chave_do_provedor(), "github": "GITHUB_TOKEN"}.get(chave)
    if chave_env and not p and not os.environ.get(chave_env):      # com pulsos, o que vale é a resposta real
        estado, detalhe = "sem_chave", f"sem {chave_env}" + (": decisor local no lugar" if chave == "jev" else "")
    elif chave == "claude":
        esp = store.get("self_dev_espera") or {}
        if esp.get("precisa_de_voce") and float(esp.get("ate", 0)) > agora:
            estado, detalhe = "parado", str(esp.get("motivo", ""))[:160] + f" · tenta de novo às {esp.get('hora', '?')}"
        elif float(esp.get("ate", 0)) > agora:
            estado, detalhe = "limite", f"no limite de uso · tenta de novo às {esp.get('hora', '?')}"
    elif chave == "loop":
        b = store.get("batimento") or {}
        if not b:
            estado, detalhe = "fora", "sem batimento: o loop não está rodando"
        else:
            atraso = agora - float(b.get("proximo_giro_em", b.get("em", 0)))
            estado = "fora" if atraso > 300 else "instavel" if atraso > 60 else "ok"
            detalhe = f"giro há {int(agora - float(b.get('em', agora)))} s" if estado == "ok" else f"próximo giro atrasado {int(atraso)} s"
            p = [{"ok": estado != "fora", "ms": None, "erro": None, "em": float(b.get("em", agora))}]
            oks = p if p[0]["ok"] else []
    ultimo_erro = falhas[-1] if falhas else None
    return {"servico": chave, "nome": nome, "papel": papel, "estado": estado, "detalhe": detalhe,
            "ultima_ok": oks[-1]["em"] if oks else None, "ultimo_pulso": p[-1]["em"] if p else None,
            "ultimo_erro": {"em": ultimo_erro["em"], "texto": ultimo_erro["erro"] or "falhou"} if ultimo_erro else None,
            "latencia_ms": int(statistics.median(lat)) if lat else None,
            "chamadas_1h": len(p), "falhas_1h": len(falhas), "serie": p[-SERIE:]}


def estado(store: Store, agora: float | None = None) -> dict[str, Any]:
    agora = agora or time.time()
    itens = [_servico(store, c, n, pp, agora) for c, n, pp in SERVICOS]
    piores = [i for i in itens if i["estado"] in ("fora", "parado")]
    return {"em": agora, "servicos": itens, "resumo": "fora: " + ", ".join(i["nome"] for i in piores) if piores else
            ("instável: " + ", ".join(i["nome"] for i in itens if i["estado"] == "instavel") if any(i["estado"] == "instavel" for i in itens) else "tudo respondendo")}


__all__ = ["preparar", "pulso", "instalar", "estado", "SERVICOS"]

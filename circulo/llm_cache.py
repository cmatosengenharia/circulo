"""Cache exato das respostas da LLM, por (neurônio + modelo + prompt normalizado), com TTL curto.

Toda chamada passa por `gerar`: antes de chamar o provedor, ela procura uma chamada idêntica dos últimos `TTL_S`
segundos que deu certo e cujo ciclo foi aceito pela catraca, e anota se houve acerto potencial (modo sombra). O cache
só serve a resposta quando a taxa de acertos potenciais das últimas 24 h passa de `LIMIAR` (com pelo menos
`MIN_AMOSTRAS` chamadas). A literatura mostra que o cache exato acerta pouco em prompts variados; por isso a decisão
de servir é da taxa medida, não de um palpite. A resposta servida custa 0 tokens.

Só a resposta de chamada que deu certo é guardada, e só é servida depois que o ciclo que a usou foi aceito. O prefixo
estável (o system de cada papel) já vai marcado com cache_control para o cache de prompt do provedor (llm.py).
"""
from __future__ import annotations

import hashlib
import json
import time

from .llm import LLMResult
from .registro import registrar
from .state import Store

TTL_S = 30 * 60
JANELA_S = 24 * 3600
LIMIAR = 0.05
MIN_AMOSTRAS = 20


def chave(papel: str, model: str, system: str, prompt: str) -> str:
    norm = "\0".join(" ".join(p.split()) for p in (papel, model, system, prompt))
    return hashlib.sha256(norm.encode()).hexdigest()


def taxa(store: Store) -> dict:
    r = store.one("SELECT COUNT(*) n, COALESCE(SUM(acerto_potencial),0) a FROM llm_cache WHERE created_at>=?",
                  (time.time() - JANELA_S,))
    t = r["a"] / r["n"] if r["n"] else 0.0
    return {"chamadas": r["n"], "acertos": r["a"], "taxa": t, "servindo": r["n"] >= MIN_AMOSTRAS and t >= LIMIAR}


def _aceita(store: Store, h: str) -> dict | None:
    r = store.one("SELECT c.texto, c.citacoes FROM llm_cache c JOIN llm_calls l ON l.id=c.chamada "
                  "WHERE c.chave=? AND c.texto IS NOT NULL AND l.ok=1 AND l.aceita=1 AND c.created_at>=? "
                  "ORDER BY c.id DESC LIMIT 1", (h, time.time() - TTL_S))
    return dict(r) if r else None


def _anotar(store: Store, h: str, papel: str, chamada: int, acerto: bool, out: LLMResult | None, servido: bool = False) -> None:
    agora = time.time()
    store.x("UPDATE llm_cache SET texto=NULL, citacoes=NULL WHERE texto IS NOT NULL AND created_at<?", (agora - TTL_S,))
    store.x("INSERT INTO llm_cache(chave,papel,chamada,acerto_potencial,servido,texto,citacoes,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (h, papel, chamada, int(acerto), int(servido), out and out.text,
             out and json.dumps(out.citations, ensure_ascii=False), agora))


def gerar(store: Store, llm, *, papel: str, project_id: int | None, system: str, prompt: str, model: str,
          max_tokens: int, web_search: int = 0, escolha: dict | None = None) -> LLMResult:
    """A única forma de chamar a LLM com registro: anota a chamada em llm_calls e o acerto potencial em llm_cache."""
    h = chave(papel, model, system, prompt)
    anterior = _aceita(store, h)
    if anterior and taxa(store)["servindo"]:
        out = LLMResult(anterior["texto"], 0, model, json.loads(anterior["citacoes"] or "[]"))
        cid = registrar(store, tick=store.tick, project_id=project_id, papel=papel, modelo=model, escolha=escolha,
                        uso=out, duracao_ms=0, entrada=prompt, saida=out.text)
        _anotar(store, h, papel, cid, True, None, servido=True)
        return out
    t0 = time.time()
    try:
        out = llm.generate(system=system, prompt=prompt, model=model, max_tokens=max_tokens, web_search=web_search)
    except Exception as exc:
        cid = registrar(store, tick=store.tick, project_id=project_id, papel=papel, modelo=model, escolha=escolha,
                        duracao_ms=int((time.time() - t0) * 1000), ok=False, erro=f"{type(exc).__name__}: {exc}", entrada=prompt)
        _anotar(store, h, papel, cid, anterior is not None, None)
        raise
    cid = registrar(store, tick=store.tick, project_id=project_id, papel=papel, modelo=model, escolha=escolha,
                    uso=out, duracao_ms=int((time.time() - t0) * 1000), entrada=prompt, saida=out.text)
    _anotar(store, h, papel, cid, anterior is not None, out)
    return out

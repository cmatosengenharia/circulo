"""A mesma pergunta do conselho com evidência quase igual em 24 h não volta à LLM do Planejador.

A chave é só o texto da pergunta normalizado. A evidência não entra na chave: hash de números arredondados erra na borda
do balde (5% de diferença cai em baldes distintos). Cada número dela é comparado com o da resposta guardada por
tolerância relativa (TOLERANCIA), e os mesmos números precisam existir dos dois lados. Cada entrada tem estado:
em_andamento enquanto a LLM responde (outro giro com a mesma pergunta não chama a LLM junto) e completa com o desfecho.
"""
from __future__ import annotations

import json
import time

from .decision import norm

TTL = 86400                 # resposta guardada vale 24 h
TOLERANCIA = 0.05           # cada número da evidência a menos de 5% do guardado: a mesma pergunta, a mesma resposta
PRAZO_ANDAMENTO = 900       # entrada em andamento mais velha que isso foi abandonada (processo morto no meio da chamada)
EM_ANDAMENTO = "em_andamento"


def chave(texto: str) -> str:
    return " ".join(norm(texto).split())


def numeros(ev, caminho: str = "") -> dict[str, float]:
    if isinstance(ev, bool):
        return {}
    if isinstance(ev, (int, float)):
        return {caminho: float(ev)}
    pares = ev.items() if isinstance(ev, dict) else enumerate(ev) if isinstance(ev, list) else ()
    out: dict[str, float] = {}
    for k, v in pares:
        out.update(numeros(v, f"{caminho}/{k}"))
    return out


def quase_igual(guardada, nova) -> bool:
    a, b = numeros(guardada), numeros(nova)
    return a.keys() == b.keys() and all(b[k] == v or abs(b[k] - v) < TOLERANCIA * abs(v) for k, v in a.items())


def reservar(store, texto: str, evidencia, pergunta_id: int, now: float | None = None) -> dict | None:
    """A entrada que responde por esta pergunta: completa (24 h, evidência quase igual) ou em andamento noutro giro.
    None: nada serve, e a entrada fica em andamento por esta pergunta até concluir()."""
    now = now or time.time()
    k = chave(texto)
    with store.tx():
        r = store.one("SELECT * FROM planejador_cache WHERE chave=?", (k,))
        if r is not None and r["pergunta_id"] != pergunta_id:
            if r["estado"] == EM_ANDAMENTO and now - r["em"] < PRAZO_ANDAMENTO:
                return dict(r)
            if r["estado"] == "completa" and now - r["em"] < TTL and quase_igual(json.loads(r["evidencia"] or "{}"), evidencia):
                return dict(r)
        store.x("INSERT INTO planejador_cache(chave,estado,pergunta_id,evidencia,em) VALUES(?,'em_andamento',?,?,?) "
                "ON CONFLICT(chave) DO UPDATE SET estado='em_andamento', pergunta_id=excluded.pergunta_id, "
                "evidencia=excluded.evidencia, desfecho=NULL, motivo=NULL, item_id=NULL, em=excluded.em",
                (k, pergunta_id, json.dumps(evidencia, ensure_ascii=False, default=str), now))
    return None


def concluir(store, texto: str, pergunta_id: int, desfecho: str | None, motivo: str = "") -> None:
    """Fecha a entrada desta pergunta: completa com o desfecho da resposta da LLM, ou apagada (desfecho None: falha,
    porteiro, resposta inválida), para a próxima tentativa perguntar de novo."""
    k = chave(texto)
    if desfecho is None:
        store.x("DELETE FROM planejador_cache WHERE chave=? AND pergunta_id=? AND estado='em_andamento'", (k, pergunta_id))
        return
    store.x("UPDATE planejador_cache SET estado='completa', desfecho=?, motivo=?, em=?, "
            "item_id=(SELECT item_id FROM perguntas WHERE id=?) WHERE chave=? AND pergunta_id=?",
            (desfecho, motivo[:300], time.time(), pergunta_id, k, pergunta_id))

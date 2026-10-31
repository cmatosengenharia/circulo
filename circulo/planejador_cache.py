"""A mesma pergunta do conselho com a métrica quase igual em 7 dias não volta à LLM do Planejador.

A chave é o hash (sha256) da pergunta e do nome da métrica normalizados. Os números da evidência não entram na chave:
hash de números arredondados erra na borda do balde (a diferença pequena cai em baldes distintos). A métrica são os números do topo da evidência (o detalhamento
aninhado, como por_veredito, mexe a cada giro sem mudar a resposta: pergunta #182); sem número no topo, todos contam.
Cada um é comparado com o da resposta guardada por tolerância relativa (TOLERANCIA), e os mesmos precisam existir
dos dois lados. Cada entrada tem estado:
em_andamento enquanto a LLM responde (outro giro com a mesma pergunta não chama a LLM junto) e completa com o desfecho.
"""
from __future__ import annotations

import hashlib
import json
import time

from .decision import norm

TTL = 7 * 86400             # resposta guardada vale 7 dias (24 h deixava a pergunta #182 voltar à LLM no dia seguinte)
TOLERANCIA = 0.20           # cada número da métrica a menos de 20% do guardado: a mesma pergunta, a mesma resposta
PRAZO_ANDAMENTO = 900       # entrada em andamento mais velha que isso foi abandonada (processo morto no meio da chamada)
EM_ANDAMENTO = "em_andamento"


def chave(texto: str, evidencia) -> str:
    nome = evidencia.get("metrica") if isinstance(evidencia, dict) else None
    normal = [" ".join(norm(str(t or "")).split()) for t in (texto, nome)]
    return hashlib.sha256("\n".join(normal).encode()).hexdigest()


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


def metrica(ev) -> dict[str, float]:
    """Os números do topo da evidência; sem nenhum lá, todos os números dela."""
    topo = {k: v for k, v in numeros(ev).items() if k.count("/") == 1}
    return topo or numeros(ev)


def quase_igual(guardada, nova) -> bool:
    a, b = metrica(guardada), metrica(nova)
    return a.keys() == b.keys() and all(b[k] == v or abs(b[k] - v) < TOLERANCIA * abs(v) for k, v in a.items())


def reservar(store, texto: str, evidencia, pergunta_id: int, now: float | None = None) -> dict | None:
    """A entrada que responde por esta pergunta: completa (24 h, evidência quase igual) ou em andamento noutro giro.
    None: nada serve, e a entrada fica em andamento por esta pergunta até concluir()."""
    now = now or time.time()
    k = chave(texto, evidencia)
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


def concluir(store, texto: str, evidencia, pergunta_id: int, desfecho: str | None, motivo: str = "") -> None:
    """Fecha a entrada desta pergunta: completa com o desfecho da resposta da LLM, ou apagada (desfecho None: falha,
    porteiro, resposta inválida), para a próxima tentativa perguntar de novo."""
    k = chave(texto, evidencia)
    if desfecho is None:
        store.x("DELETE FROM planejador_cache WHERE chave=? AND pergunta_id=? AND estado='em_andamento'", (k, pergunta_id))
        return
    store.x("UPDATE planejador_cache SET estado='completa', desfecho=?, motivo=?, em=?, "
            "item_id=(SELECT item_id FROM perguntas WHERE id=?) WHERE chave=? AND pergunta_id=?",
            (desfecho, motivo[:300], time.time(), pergunta_id, k, pergunta_id))

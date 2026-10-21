"""O que cada agente está fazendo agora — não só quem está trabalhando, mas em quê, e o passo em curso.

Cada agente marca o que começou (`marcar`), o passo atual (`passo`) e quando terminou (`terminar`). Fica num só
registro (`kv fazendo`), com os últimos passos de cada um, e a Equipe ao vivo mostra ao lado do nome: "Desenvolvedor ·
item #91 · Claude Code: editando circulo/diff_size.py (passo 7)". O Developer é o caso rico: o Claude Code roda em
streaming e cada ferramenta usada (Read, Edit, Bash pytest…) vira um passo visível enquanto acontece.

Vários agentes podem estar fazendo algo ao mesmo tempo (o SRE e o Médico rodam em paralelo ao giro, o Developer é um
subprocesso): este registro é por agente, não um "ativo" só.
"""
from __future__ import annotations

import time
from typing import Any

from .registro import passo_do_evento  # o tradutor dos eventos do Claude Code mora lá (o Developer só importa de registro)
from .state import Store

KV = "fazendo"
PASSOS = 8          # últimos passos guardados por agente
VALE_S = 900        # sem atualização há 15 min: considera terminado (o processo pode ter morrido)


def _ler(store: Store) -> dict:
    return dict(store.get(KV) or {})


def marcar(store: Store, agente: str, o_que: str, item: int | None = None, passo: str | None = None, **extra: Any) -> None:
    """O agente começou algo. `o_que` é a frase curta ("item #91: Parser puro de numstat"); `passo`, o primeiro passo."""
    agora = time.time()
    f = _ler(store)
    atual = {"o_que": str(o_que)[:160], "item": item, "desde": agora, "em": agora, "passo": (passo or "")[:160],
             "passos": ([{"t": agora, "texto": passo[:160]}] if passo else []), **{k: v for k, v in extra.items() if v is not None}}
    f[agente] = atual
    store.set(KV, f)


def passo(store: Store, agente: str, texto: str, **extra: Any) -> None:
    """Um passo dentro do que o agente está fazendo (não cria o registro se ele não começou nada)."""
    f = _ler(store)
    a = f.get(agente)
    if not a:
        return
    agora = time.time()
    a["passo"], a["em"] = str(texto)[:160], agora
    a["passos"] = (a.get("passos") or [])[-(PASSOS - 1):] + [{"t": agora, "texto": str(texto)[:160]}]
    a.update({k: v for k, v in extra.items() if v is not None})
    f[agente] = a
    store.set(KV, f)


def terminar(store: Store, agente: str, resultado: str | None = None) -> None:
    f = _ler(store)
    a = f.pop(agente, None)
    if a is not None and resultado:
        ult = dict(store.get(KV + "_ultimo") or {})
        ult[agente] = {"o_que": a.get("o_que"), "resultado": str(resultado)[:160], "em": time.time(), "durou_s": int(time.time() - float(a.get("desde", time.time())))}
        store.set(KV + "_ultimo", ult)
    store.set(KV, f)


def agora(store: Store, t: float | None = None) -> dict[str, dict]:
    """O que está em curso, por agente, só o que foi atualizado há menos de VALE_S."""
    t = t or time.time()
    out = {}
    for ag, a in _ler(store).items():
        if t - float(a.get("em", 0)) <= VALE_S:
            out[ag] = {**a, "ha_s": int(t - float(a.get("desde", t))), "passo_ha_s": int(t - float(a.get("em", t)))}
    return out


def ultimo(store: Store) -> dict[str, dict]:
    return dict(store.get(KV + "_ultimo") or {})


__all__ = ["marcar", "passo", "terminar", "agora", "ultimo", "passo_do_evento"]

"""Cão de guarda do giro: um giro preso sem nenhum sinal de vida encerra o processo, e o launchd (KeepAlive) sobe um
limpo em 10 s.

24/10: o giro ficou 6 h e meia na validação do corpo (um `git`/subprocesso pendurado, sem prazo). O batimento vem de
outra thread, então tudo parecia vivo; o reinício pelo próprio loop só acontece ENTRE giros, e o giro não terminava.
Sinal de vida = qualquer passo registrado em `fazendo` (o Claude Code registra cada ferramenta) ou a troca de etapa.
Um giro legítimo e longo (o Developer trabalhando 40 min) tem passos; um processo pendurado não tem nenhum.
"""
from __future__ import annotations

import os
import threading
import time

GIRO_MIN = 60 * 60          # só olha giros que já passaram de 1 h
SEM_SINAL = 45 * 60         # e que estão sem nenhum passo novo há 45 min (validação do corpo: até 20 min sem passo)
CODIGO_SAIDA = 75


def ultimo_sinal(store, inicio: float) -> float:
    f = store.get("fazendo") or {}
    e = store.get("etapa") or {}
    marcas = [float(v.get("em", 0)) for v in f.values() if isinstance(v, dict)] + [float(e.get("em", 0) or 0), inicio]
    return max(marcas)


def preso(store, inicio: float, agora: float | None = None) -> str | None:
    """O motivo, se o giro está preso; None se está vivo."""
    agora = agora or time.time()
    if agora - inicio < GIRO_MIN:
        return None
    silencio = agora - ultimo_sinal(store, inicio)
    if silencio < SEM_SINAL:
        return None
    e = store.get("etapa") or {}
    return (f"cão de guarda: giro {e.get('tick', '?')} preso na etapa “{e.get('tarefa') or e.get('nome') or '?'}” "
            f"há {int((agora - inicio) / 60)} min, sem nenhum passo há {int(silencio / 60)} min; reiniciando o processo")


def reiniciar_se_preso(store, inicio: float, reply, sair=os._exit, agora: float | None = None) -> bool:
    motivo = preso(store, inicio, agora)
    if not motivo:
        return False
    seguro = threading.Timer(30, lambda: sair(CODIGO_SAIDA))     # se o banco estiver travado, sai mesmo assim
    seguro.daemon = True
    seguro.start()
    try:
        store.set("ultimo_reinicio", {"em": time.time(), "motivo": motivo})
        reply(motivo[0].upper() + motivo[1:] + ". O serviço sobe de novo sozinho em segundos.", "saude")
    finally:
        sair(CODIGO_SAIDA)
    return True

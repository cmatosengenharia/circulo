"""Lição #83: um dump de estatística (subagent_stats com completed/failed/killed/spawned) não é erro.

O texto que chega como motivo de uma falha às vezes é só o JSON de contadores do agente, zerados: telemetria
normal. Vira lição só se o próprio JSON tiver sinal de erro: failed/killed > 0, campo de erro/exceção preenchido
(`is_error`, `error`, `exception`…), `subtype` de erro, `terminal_reason` que não é `completed` ou exit code diferente de 0.

Lição #88: o texto guardado na lição é o dump cortado (`nd":0,"max_depth":0,"completed":0,…`), às vezes sem aspas.
Vale também, desde que seja só pares chave:valor completos (o último pode estar cortado): nada de prosa no meio.
"""
from __future__ import annotations

import json
import re

CONTADORES = {"completed", "failed", "killed", "spawned"}
CAUSA = "telemetria_sem_erro"
PAR = re.compile(r'"?(\w+)"?\s*:\s*("(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|true|false|null|[{\[])')
CAUDA_CORTADA = re.compile(r'(?:"?\w*"?\s*:?\s*)(?:\.\.\.|…)?\s*$')


def _nos(dado) -> list[dict]:
    return [dado] + [n for v in dado.values() if isinstance(v, dict) for n in _nos(v)]


def _erro(chave: str, valor) -> bool:
    k = chave.lower()
    if k == "subtype":
        return str(valor).startswith("error")
    if k == "terminal_reason":
        return valor not in (None, "", "completed")
    return bool(valor) and (k in ("failed", "killed", "returncode") or "error" in k or "exception" in k or k.startswith("exit"))


def _cortado(texto: str) -> list[dict]:
    """Cada par do JSON cortado como um nó (a mesma chave pode vir em vários níveis), se o texto é só pares chave:valor."""
    pares = PAR.findall(texto)
    resto = CAUDA_CORTADA.sub("", PAR.sub(" ", texto), count=1)
    if re.sub(r'[\s{}\[\],"]', "", resto):
        return []
    return [{k: v if v in "{[" else json.loads(v)} for k, v in pares]


def telemetria_sem_erro(texto: str) -> bool:
    """O texto inteiro é JSON (objeto, inteiro ou cortado) com contadores de estatística e nenhum sinal de erro."""
    try:
        dado = json.loads(texto or "")
    except ValueError:
        nos = _cortado(texto or "")
    else:
        nos = _nos(dado) if isinstance(dado, dict) else []
    return any(CONTADORES & n.keys() for n in nos) and not any(_erro(str(k), v) for n in nos for k, v in n.items())

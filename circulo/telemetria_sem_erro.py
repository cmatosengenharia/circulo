"""Lição #83: um dump de estatística (subagent_stats com completed/failed/killed/spawned) não é erro.

O texto que chega como motivo de uma falha às vezes é só o JSON de contadores do agente, zerados: telemetria
normal. Vira lição só se o próprio JSON tiver sinal de erro: failed/killed > 0, campo de erro/exceção preenchido
(`is_error`, `error`, `exception`…), `subtype` de erro, `terminal_reason` que não é `completed` ou exit code diferente de 0.
"""
from __future__ import annotations

import json

CONTADORES = {"completed", "failed", "killed", "spawned"}
CAUSA = "telemetria_sem_erro"


def _nos(dado) -> list[dict]:
    return [dado] + [n for v in dado.values() if isinstance(v, dict) for n in _nos(v)]


def _erro(chave: str, valor) -> bool:
    k = chave.lower()
    if k == "subtype":
        return str(valor).startswith("error")
    if k == "terminal_reason":
        return valor not in (None, "", "completed")
    return bool(valor) and (k in ("failed", "killed", "returncode") or "error" in k or "exception" in k or k.startswith("exit"))


def telemetria_sem_erro(texto: str) -> bool:
    """O texto inteiro é JSON (objeto) com contadores de estatística e nenhum sinal de erro."""
    try:
        dado = json.loads(texto or "")
    except ValueError:
        return False
    if not isinstance(dado, dict):
        return False
    nos = _nos(dado)
    return any(CONTADORES & n.keys() for n in nos) and not any(_erro(str(k), v) for n in nos for k, v in n.items())

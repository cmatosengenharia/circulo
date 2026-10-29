"""Alias causa raiz → node id: lição sem teste próprio herda a checagem determinística de outra lição da mesma causa.

A causa casa com a assinatura sem acentos e com `_` no lugar de espaços e pontuação. A lição herdada segue o ciclo
da lição de teste (licoes.py, regra 7): fecha com exit 0 em 2 execuções seguidas no main e reabre se o teste falhar,
sumir ou mudar de corpo (checagem enfraquecida).
"""
from __future__ import annotations

import re
import unicodedata

CAUSAS = {
    # lições #10/#11 (o agente edita a constituição) → teste da lição #12
    "constituicao_intacta":
        "tests/test_reparo.py::test_constituicao_editada_pelo_agente_e_revertida_em_cada_rodada_e_o_pr_sai",
    # lição #59 (o agente para no máximo de passos): o estouro não se reproduz sem LLM; o portão que reage a ele, sim
    "maximo_de_passos":
        "tests/test_developer.py::test_licao_59_parada_no_maximo_de_passos_devolve_a_tarefa_ao_fatiador",
}


def node_por_causa(assinatura: str | None) -> str | None:
    t = unicodedata.normalize("NFKD", assinatura or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "_", t)
    return next((node for causa, node in CAUSAS.items() if causa in t), None)

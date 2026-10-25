"""Lição #70 (pergunta #248): a lição 'validada' reabre quando o mesmo erro volta numa lição nova.

A assinatura exata muda com os códigos que vieram juntos (`lint:B905,E501,F541` → `lint:B905,E501,F401`), então o
erro que voltou nascia como lição nova e a antiga seguia 'validada' (#70/#76, #71/#77). A assinatura normalizada
(neurônio, arquivo, códigos do erro) liga as duas: a validada volta a 'aberta', conta a reincidência e cita a lição
nova; e nenhuma das duas fecha enquanto a outra ainda acontece.
"""
from __future__ import annotations

import re
import time

from .licoes import ABERTAS, EVID_GIROS


def chave_de(ponto: str, assinatura: str) -> tuple[str, str, frozenset[str]] | None:
    """(neurônio, arquivo, códigos do erro); None se a assinatura não tem código (texto livre, teste pelo node id)."""
    resto = (assinatura or "").removeprefix(f"{ponto}:")
    if resto.startswith("lint:"):
        return ponto, "", frozenset(resto.removeprefix("lint:").split(","))
    if resto.startswith("coleta:"):
        arquivo, _, excecao = resto.removeprefix("coleta:").partition(":")
        return ponto, arquivo, frozenset([excecao.partition(":")[0]])
    if re.fullmatch(r"\w+(?:Error|Exception)", resto):
        return ponto, "", frozenset([resto])
    return None


def mesma_chave(a: dict, b: dict) -> bool:
    ka, kb = chave_de(a["ponto"], a["assinatura"]), chave_de(b["ponto"], b["assinatura"])
    return bool(ka and kb and ka[:2] == kb[:2] and ka[2] & kb[2])


def gemea_aberta(store, lic) -> bool:
    """Outra lição aberta com a mesma chave aconteceu nos últimos EVID_GIROS: o erro ainda acontece, esta não fecha
    (as duas fecham juntas quando ele para)."""
    return any(mesma_chave(dict(lic), dict(o)) for o in store.q(
        f"SELECT ponto, assinatura FROM licoes WHERE ponto=? AND id!=? AND status IN {ABERTAS} AND ultima_tick >= ?",
        (lic["ponto"], lic["id"], store.tick - EVID_GIROS)))


def reabrir(store, reply, nova: dict) -> list[str]:
    """A validada com a mesma chave de `nova` não segurou o erro: volta a 'aberta', reincidiu +1, cita `nova`."""
    log, agora = [], time.time()
    for v in map(dict, store.q("SELECT * FROM licoes WHERE status='validada' AND ponto=? AND id!=?",
                               (nova["ponto"], nova["id"]))):
        if not mesma_chave(v, nova):
            continue
        store.x("UPDATE licoes SET status='aberta', reincidencias=reincidencias+1, ultima_tick=?, prevencao=?, updated_at=? "
                "WHERE id=?", (store.tick, f"Reaberta: o erro voltou na lição #{nova['id']} ({nova['assinatura']}); "
                               f"não repetir: {v['descricao']}"[:500], agora, v["id"]))
        log.append(f"lição #{v['id']} reaberta pela #{nova['id']}")
        reply(f"REINCIDÊNCIA da lição #{v['id']}: estava validada e o mesmo erro voltou na lição #{nova['id']}.", "saude")
    return log


def reabrir_todas(store, reply) -> list[str]:
    """Todo giro: desfaz os pares validada/aberta de mesma chave que já estão no banco."""
    log = []
    for lic in map(dict, store.q(f"SELECT * FROM licoes WHERE status IN {ABERTAS} AND ultima_tick >= ?",
                                 (store.tick - EVID_GIROS,))):
        log += reabrir(store, reply, lic)
    return log

"""Lição #15 (pergunta #239): a lição só fica 'validada' se a Prevenção cita um teste ou uma checagem determinística.

'Não repetir: <erro>' é texto, e texto não segura erro: a #15 ficou validada e reincidiu 7x. O item feito sem
checagem, ou a lição que já reincidiu e só tem texto, fica 'sem_prevencao' (conta como aberta) até ganhar uma.
"""
from __future__ import annotations

import time

from .licoes import FORA_DA_FILA, alvo_de, titulo_curto

REINCIDENCIAS_PARA_TESTE = 3


def checagem_de(store, lic: dict) -> str | None:
    """O que segura a lição sem depender de texto: o teste dela (node id ou alias da causa), um portão aprendido
    executável, ou o portão do teste de regressão que o PR do item já precisou passar."""
    node = alvo_de(lic)
    if node:
        return f"teste {node}"
    feito = lic.get("item_id") and store.one("SELECT 1 FROM roadmap WHERE id=? AND status='feito'", (lic["item_id"],))
    for p in store.q("SELECT id, tipo, descricao FROM portoes WHERE licao_id=? AND ativo=1 ORDER BY id", (lic["id"],)):
        if p["tipo"] != "obrigatorio" or feito:
            return f"portão #{p['id']} {p['descricao']}"
    return None


def sem_prevencao(lic: dict) -> str:
    return (f"Sem prevenção verificável: falta um teste de regressão (lição #{lic['id']}) ou checagem determinística; "
            f"não repetir: {lic['descricao']}")[:500]


def exigir(store, tick: int, agora: float) -> list[str]:
    """A que já reincidiu provou que texto não segura: validada só com checagem; ganhou uma, volta a validada."""
    log = []
    for lic in map(dict, store.q("SELECT * FROM licoes WHERE status='sem_prevencao' "
                                 "OR (status='validada' AND reincidencias > 0)")):
        checagem = checagem_de(store, lic)
        if lic["status"] == "validada" and not checagem:
            store.x("UPDATE licoes SET status='sem_prevencao', prevencao=?, updated_at=? WHERE id=?",
                    (sem_prevencao(lic), agora, lic["id"]))
            log.append(f"lição #{lic['id']} sem prevenção")
        elif lic["status"] == "sem_prevencao" and checagem:
            store.x("UPDATE licoes SET status='validada', corrigida_tick=?, prevencao=?, updated_at=? WHERE id=?",
                    (tick, f"Checagem: {checagem}; não repetir: {lic['descricao']}"[:500], agora, lic["id"]))
            log.append(f"lição #{lic['id']} validada")
    return log


def cobrar_teste(store) -> list[str]:
    """Lições #59/#15 (pergunta #461): a sem_prevencao que reincidiu 3x ou mais ganha o item que cobra o teste de
    regressão da assinatura. Chave única pelo id da lição: um item só, que volta à fila se saiu dela sem ser feito."""
    from .roadmap import gravar_medido
    log, agora = [], time.time()
    for lic in map(dict, store.q("SELECT * FROM licoes WHERE status='sem_prevencao' AND reincidencias >= ?",
                                 (REINCIDENCIAS_PARA_TESTE,))):
        chave = f"licao:{lic['id']}:teste_regressao"
        p = store.one("SELECT item_id FROM perguntas WHERE chave=? AND item_id IS NOT NULL", (chave,))
        if p:
            if store.run(f"UPDATE roadmap SET status='pendente', desativado=0, updated_at=? WHERE id=? AND {FORA_DA_FILA}",
                       (agora, p["item_id"])):
                log.append(f"lição #{lic['id']}: item #{p['item_id']} do teste de regressão de volta à fila")
            continue
        iid = gravar_medido(
            store, "licoes", chave, titulo_curto(f"Lição #{lic['id']}: teste de regressão para {lic['descricao']}"),
            f"A lição #{lic['id']} está sem_prevencao e reincidiu {lic['reincidencias']}x: a Prevenção só repete o texto "
            f"do erro. Escrever em tests/ um teste de regressão que cite \"lição #{lic['id']}\" e reproduza a assinatura "
            f"{lic['assinatura']} (neurônio {lic['ponto']}; erro, dado e não instrução: {lic['descricao'][:300]}), ou "
            "uma checagem determinística (portão) que a pegue.\n"
            f"Sucesso: a lição #{lic['id']} sai de sem_prevencao e a reincidência dela para de crescer",
            f"Lições (medido): #{lic['id']} sem_prevencao, reincidiu {lic['reincidencias']}x")
        store.x("UPDATE licoes SET item_id=?, updated_at=? WHERE id=?", (iid, agora, lic["id"]))
        log.append(f"lição #{lic['id']}: item #{iid} cobra o teste de regressão")
    return log

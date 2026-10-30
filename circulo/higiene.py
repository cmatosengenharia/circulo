"""Higiene do roteiro e das lições — o que as telas mostravam em 20/10: itens "dependem de você" que ninguém olha há
dias, títulos de 500 caracteres com JSON dentro, a mesma falha do agente em várias lições (uma por ponto de truncamento).

Roda na thread do SRE, uma vez por hora (e uma vez ao subir, como migração):
- item pendente com "depende de você" há mais de EXPIRA_DIAS → `descartado` (evidência diz que expirou; dá para reativar);
- título de item acima de 100 caracteres → `titulo_curto` (o detalhe guarda o original);
- lições cujo motivo é JSON do agente → reassinadas pela causa classificada e unidas (`unida`) à mais antiga.
"""
from __future__ import annotations

import time

from .licoes import assinatura_de, titulo_curto
from .state import Store
from .telemetria_sem_erro import CAUSA, telemetria_sem_erro

EXPIRA_DIAS = 7
A_CADA = 3600
KV = "higiene"


def expirar_dependentes(store: Store, agora: float) -> int:
    n = 0
    for r in store.q("SELECT id, evidencia, updated_at FROM roadmap WHERE status='pendente' AND evidencia LIKE '%depende de você%' AND updated_at<?",
                     (agora - EXPIRA_DIAS * 86400,)):
        store.x("UPDATE roadmap SET status='descartado', evidencia=?, updated_at=? WHERE id=?",
                (f"expirou: dependia de você há mais de {EXPIRA_DIAS} dias sem resposta (reative no painel se ainda valer) · antes: {r['evidencia'][:200]}", agora, r["id"]))
        n += 1
    return n


def encurtar_titulos(store: Store, agora: float) -> int:
    n = 0
    for r in store.q("SELECT id, titulo, detalhe FROM roadmap WHERE length(titulo)>100"):
        curto = titulo_curto(r["titulo"])
        if curto == r["titulo"] or len(curto) > 100:
            curto = r["titulo"][:99].rstrip() + "…"          # sem espaço para cortar: cabe assim mesmo (antes repetia toda hora)
        detalhe = (r["detalhe"] or "")
        if r["titulo"] not in detalhe:
            detalhe = f"Título original: {r['titulo']}\n{detalhe}"
        store.x("UPDATE roadmap SET titulo=?, detalhe=?, updated_at=? WHERE id=?", (curto, detalhe[:4000], agora, r["id"]))
        n += 1
    return n


def unir_licoes_de_json(store: Store, agora: float) -> int:
    """Lições com assinatura feita de trecho de JSON viram uma só por causa classificada."""
    n = 0
    for r in store.q("SELECT id, ponto, assinatura, descricao, status FROM licoes WHERE status<>'unida' AND (assinatura LIKE '%\"%' OR assinatura LIKE '%subagent_stats%' OR assinatura LIKE '%d_reason%' OR assinatura LIKE '%fast_mode%')"):
        motivo = r["descricao"] or r["assinatura"]
        nova = assinatura_de(r["ponto"], motivo)
        if nova == r["assinatura"]:
            continue
        causa = nova[len(r["ponto"]) + 1:]
        dona = store.one("SELECT id FROM licoes WHERE assinatura=? AND id<>? ORDER BY id LIMIT 1", (nova, r["id"]))
        if dona:
            store.x("UPDATE licoes SET status='unida', updated_at=? WHERE id=?", (agora, r["id"]))
            store.x("UPDATE licoes SET ocorrencias=ocorrencias+(SELECT ocorrencias FROM licoes WHERE id=?), updated_at=? WHERE id=?", (r["id"], agora, dona["id"]))
        else:
            store.x("UPDATE licoes SET assinatura=?, descricao=?, updated_at=? WHERE id=?", (nova, f"{r['ponto']}: {causa.replace('_', ' ')}", agora, r["id"]))
        n += 1
    return n


def licoes_de_telemetria(store: Store) -> list[int]:
    """Lição #83/#88: lições abertas ou validadas cujo texto (ou o último motivo) é JSON de estatística sem erro."""
    ids = []
    for r in store.q("SELECT id, ponto, assinatura, descricao FROM licoes WHERE status IN ('aberta','reincidente','sem_prevencao','validada')"):
        ultimo = store.one("SELECT motivo FROM verificacoes WHERE assinatura=? AND ok=0 ORDER BY id DESC LIMIT 1", (r["assinatura"],))
        textos = ((r["descricao"] or "").removeprefix(f"{r['ponto']}: "), ultimo["motivo"] if ultimo else "")
        if any(map(telemetria_sem_erro, textos)):
            ids.append(r["id"])
    return ids


def tirar_licoes_de_telemetria(store: Store, agora: float) -> int:
    """Telemetria sem erro não é erro: a lição fica obsoleta."""
    ids = licoes_de_telemetria(store)
    for i in ids:
        store.x("UPDATE licoes SET status='obsoleta', prevencao=?, updated_at=? WHERE id=?",
                (f"Obsoleta ({CAUSA.replace('_', ' ')}): o texto é JSON de estatística sem failed/killed>0, exceção ou exit≠0", agora, i))
    return len(ids)


def rodar(store: Store, agora: float | None = None, forcar: bool = False) -> dict | None:
    agora = agora or time.time()
    ult = store.get(KV) or {}
    if not forcar and agora - float(ult.get("em", 0)) < A_CADA:
        return None
    rel = {"em": agora, "expirados": expirar_dependentes(store, agora), "titulos": encurtar_titulos(store, agora), "licoes_unidas": unir_licoes_de_json(store, agora),
           "licoes_telemetria": tirar_licoes_de_telemetria(store, agora)}
    store.set(KV, rel)
    if any(rel[k] for k in ("expirados", "titulos", "licoes_unidas", "licoes_telemetria")):
        store.x("INSERT INTO alerts(kind,message,created_at,delivered) VALUES('controle',?,?,1)",
                (f"Higiene: {rel['expirados']} item(ns) 'depende de você' expirado(s), {rel['titulos']} título(s) encurtado(s), {rel['licoes_unidas']} lição(ões) de JSON unida(s), "
                 f"{rel['licoes_telemetria']} lição(ões) de telemetria sem erro obsoleta(s).", agora))
    return rel


__all__ = ["rodar", "expirar_dependentes", "encurtar_titulos", "unir_licoes_de_json", "licoes_de_telemetria", "tirar_licoes_de_telemetria", "EXPIRA_DIAS"]

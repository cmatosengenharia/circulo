"""Não insistir: a regra que o Cássio deu em 25/10 ("se não evoluiu, reescreva a solução"), aplicada ao que o loop
repete sem resultado. Em 31/10 a lição #47 (estagnação) tinha 9 reincidências e 5 PRs no mesmo dia tentando fechá-la;
9 sub-itens esperavam na fila desde 22/10 sem ninguém pegar (e, por serem 9, mantinham o roteiro "cheio" e o
Planejador descartando pergunta nova); 12 itens estavam 'bloqueado' pelo disjuntor de lint desde 25/10 sem sonda que
os reabrisse. Tudo aqui é regra de tempo e contagem, sem LLM, e roda na higiene do SRE (uma vez por hora).
"""
from __future__ import annotations

import time

SUB_ITEM_PARADO_DIAS = 7         # sub-item pendente que ninguém pegou nesse prazo sai da fila
BLOQUEADO_DIAS = 3               # item bloqueado pelo disjuntor há mais que isso ganha nova rodada
REABERTURAS_POR_PASSAGEM = 2     # … no máximo tantos por passagem (uma por hora): não inunda o Developer
LICAO_PRS_MAX = 3                # lição com tantos PRs mergeados que ainda reincide: esgotada, não abre mais item
KV_LICOES = "licoes_esgotadas"
DIA = 86400.0


def expirar_sub_itens(store, agora: float | None = None) -> list[int]:
    agora = agora or time.time()
    ids = [r["id"] for r in store.q("SELECT id FROM roadmap WHERE status='pendente' AND origem='sub_item' AND updated_at<? "
                                    "AND COALESCE(desativado,0)=0", (agora - SUB_ITEM_PARADO_DIAS * DIA,))]
    for iid in ids:
        store.x("UPDATE roadmap SET status='descartado', evidencia=?, updated_at=? WHERE id=?",
                (f"parado {SUB_ITEM_PARADO_DIAS} dias na fila sem ninguém pegar: descartado pela higiene (reative no painel se ainda valer)", agora, iid))
    return ids


def reabrir_bloqueados(store, agora: float | None = None) -> list[int]:
    """Item 'bloqueado' pelo disjuntor do abrir_pr há BLOQUEADO_DIAS volta à fila com o contador zerado (o teto tem a própria sonda)."""
    agora = agora or time.time()
    from .reparo import BLOQUEADO, DISJUNTOR
    ids = []
    todos = store.get(DISJUNTOR) or {}
    for r in store.q("SELECT id FROM roadmap WHERE status=? AND updated_at<? AND COALESCE(evidencia,'') NOT LIKE '%disjuntor do teto%' "
                     "ORDER BY updated_at LIMIT ?", (BLOQUEADO, agora - BLOQUEADO_DIAS * DIA, REABERTURAS_POR_PASSAGEM)):
        todos.pop(str(r["id"]), None)
        store.x("UPDATE roadmap SET status='pendente', desativado=0, evidencia=?, updated_at=? WHERE id=?",
                (f"reaberto pela higiene: {BLOQUEADO_DIAS} dias bloqueado; nova rodada com o disjuntor zerado", agora, r["id"]))
        ids.append(r["id"])
    if ids:
        store.set(DISJUNTOR, todos)
    return ids


def licao_esgotada(store, lic: dict, reply=None, agora: float | None = None) -> bool:
    """True quando a lição já teve LICAO_PRS_MAX PRs mergeados e ainda reincide: mais um item igual não resolve.
    Avisa uma vez (kv) e deixa no "Precisa de você"; quem muda o desenho é humano."""
    if not lic.get("item_id"):
        return False
    n = int(store.one("SELECT COUNT(*) n FROM prs WHERE item_id=? AND status='mergeado'", (lic["item_id"],))["n"])
    if n < LICAO_PRS_MAX:
        return False
    agora = agora or time.time()
    todas = store.get(KV_LICOES) or {}
    if str(lic["id"]) not in todas:
        todas[str(lic["id"])] = {"em": agora, "prs": n, "item": lic["item_id"]}
        store.set(KV_LICOES, todas)
        if reply:
            reply(f"Lição #{lic['id']} esgotada: {n} PRs mergeados e o erro voltou. Não abro mais item igual; a resposta está no "
                  f"desenho ({str(lic.get('descricao', ''))[:80]}).", "saude")
    return True


def rodar(store, agora: float | None = None) -> dict:
    agora = agora or time.time()
    return {"sub_itens_expirados": expirar_sub_itens(store, agora), "bloqueados_reabertos": reabrir_bloqueados(store, agora)}

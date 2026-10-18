"""Pausar e retomar missão por missão, sem parar o loop inteiro.

Como a parada do loop (parada.py), a pausa de uma missão é verificável:
- `pausar`: a missão sai na hora da escolha do motor (nenhum ciclo novo começa) e os pedidos para ela ficam
  guardados na fila, sem gasto;
- se um ciclo dela já estava rodando, ele termina, mas o resultado NÃO é aplicado: a versão fica registrada como
  descartada ("pausada no meio do ciclo") e a entrega atual não muda. Enquanto esse ciclo corre, o estado é
  "parando"; quando acaba, "pausada" (confirmada pelo próprio motor);
- `retomar`: a missão volta para a escolha do motor e os pedidos guardados são atendidos na ordem;
- cada pausa e retomada vira alerta e elo no rastro da missão (rastro.py).

O próprio loop (kit "circulo") não se pausa por aqui: para ele existe o botão "Pausar o loop".
"""
from __future__ import annotations

import json
import time

from .state import Store


def _col(store: Store) -> bool:
    return "pausada" in {r["name"] for r in store.q("PRAGMA table_info(projects)")}


def pausadas(store: Store) -> set[int]:
    if not _col(store):
        return set()
    return {r["id"] for r in store.q("SELECT id FROM projects WHERE COALESCE(pausada,0)=1")}


def pausada(store: Store, pid: int | None) -> bool:
    if pid is None or not _col(store):
        return False
    r = store.one("SELECT COALESCE(pausada,0) p FROM projects WHERE id=?", (pid,))
    return bool(r and r["p"])


def _chave(pid: int) -> str:
    return f"ciclo_em_andamento:{pid}"


def ciclo_comecou(store: Store, pid: int) -> None:
    store.set(_chave(pid), time.time())


def ciclo_terminou(store: Store, pid: int) -> None:
    store.set(_chave(pid), None)


def em_ciclo(store: Store, pid: int) -> bool:
    em = store.get(_chave(pid))
    return bool(em) and time.time() - float(em) < 3600      # ciclo órfão (processo caiu) não segura a pausa


def evento_da_missao(store: Store, kind: str, payload: dict) -> int | None:
    if kind == "novo_projeto":
        return None
    if payload.get("projeto"):
        return int(payload["projeto"])
    from .projects import kit_project_id
    return kit_project_id(store, "financas")


def evento_em_espera(store: Store, kind: str, payload_json: str, paradas: set[int]) -> bool:
    """O pedido é de uma missão pausada? Fica na fila (pendente) até você retomar."""
    if not paradas or kind == "novo_projeto":
        return False
    try:
        payload = json.loads(payload_json)
    except ValueError:
        return False
    return evento_da_missao(store, kind, payload) in paradas


def na_fila(store: Store, pid: int) -> int:
    n = 0
    for r in store.q("SELECT kind, payload FROM events WHERE status='pending'"):
        if evento_em_espera(store, r["kind"], r["payload"], {pid}):
            n += 1
    return n


def _missao(store: Store, pid: int):
    p = store.one("SELECT id, nome, kit FROM projects WHERE id=?", (pid,))
    if p is None:
        raise ValueError("missão não encontrada")
    if p["kit"] == "circulo":
        raise ValueError("o próprio loop não se pausa por missão: use o botão Pausar o loop")
    return p


def pausar(store: Store, pid: int, motivo: str = "") -> dict:
    p = _missao(store, pid)
    agora = time.time()
    if not pausada(store, pid):
        store.x("UPDATE projects SET pausada=1, pausada_em=?, updated_at=? WHERE id=?", (agora, agora, pid))
        extra = " O ciclo que estava rodando termina, mas o resultado não será aplicado." if em_ciclo(store, pid) else ""
        store.x("INSERT INTO alerts(kind,message,created_at,project_id) VALUES('controle',?,?,?)",
                (f"Você pausou a missão “{p['nome']}”. Nenhum ciclo novo começa e os pedidos para ela ficam guardados.{extra}",
                 agora, pid))
        from .rastro import elo
        elo(store, f"missao:{pid}", f"pausa:{int(agora)}", "pausada", {"motivo": motivo[:200]} if motivo else None)
    return estado(store, pid)


def retomar(store: Store, pid: int) -> dict:
    p = _missao(store, pid)
    agora = time.time()
    if pausada(store, pid):
        r = store.one("SELECT pausada_em FROM projects WHERE id=?", (pid,))
        store.x("UPDATE projects SET pausada=0, pausada_em=NULL, updated_at=? WHERE id=?", (agora, pid))
        fila = na_fila(store, pid)
        dur = int((agora - float(r["pausada_em"] or agora)) // 60)
        store.x("INSERT INTO alerts(kind,message,created_at,project_id) VALUES('controle',?,?,?)",
                (f"Você retomou a missão “{p['nome']}” depois de {dur} min pausada."
                 + (f" {fila} pedido(s) guardado(s) entram agora na fila." if fila else ""), agora, pid))
        from .rastro import elo
        elo(store, f"missao:{pid}", f"pausa:{int(agora)}", "retomada", {"minutos": dur})
    return estado(store, pid)


def estado(store: Store, pid: int) -> dict:
    p = store.one("SELECT COALESCE(pausada,0) p, pausada_em FROM projects WHERE id=?", (pid,)) if _col(store) else None
    if p is None or not p["p"]:
        return {"id": pid, "estado": "rodando", "pausada": False}
    rodando = em_ciclo(store, pid)
    return {"id": pid, "pausada": True, "estado": "parando" if rodando else "pausada", "desde": p["pausada_em"],
            "pedidos_guardados": na_fila(store, pid),
            "explicacao": "um ciclo que já tinha começado está terminando; o resultado dele não será aplicado" if rodando
            else "nenhum ciclo rodando; nada muda nesta missão até você retomar"}

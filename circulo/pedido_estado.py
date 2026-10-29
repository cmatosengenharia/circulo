"""Estado único de cada pedido do humano no painel (pergunta #472): recebido, andamento (com o PR), bloqueado (com o
motivo) ou entregue (com a evidência), e há quanto tempo está nele.

Não se grava campo de estado: ele é derivado por regra dos eventos já gravados (pedido, item, PR, CI, gate), costurados
por caminho.caminho. Uma regra só, aplicada em ordem, devolve sempre exatamente um estado.
"""
from __future__ import annotations

import time
from html import escape

from .caminho import CI_EM_CURSO, _dur, caminho
from .jobs import HUMANO, JANELA
from .state import Store

ESTADOS_PEDIDO = ("recebido", "andamento", "bloqueado", "entregue")
GLIFO_PEDIDO = {"recebido": ("neutro", "○"), "andamento": ("neutro", "◐"), "bloqueado": ("ruim", "⚠"), "entregue": ("bom", "✓")}


def estado_pedido(ev: dict, c: dict, item: dict | None, agora: float) -> dict:
    """Pura: o único estado atual de um pedido, a partir do evento e do caminho (pedido → item → estudo → PR → CI →
    merge). A primeira regra que vale decide: entregue > bloqueado > andamento (com o PR) > recebido. 'desde' é a
    última transição; 'idade_s', há quanto tempo está nele."""
    feitas = {e["etapa"]: e for e in c["etapas"] if e["feita"]}
    desde = max((e["em"] for e in feitas.values() if e["em"] is not None), default=ev["created_at"])
    esperando = c.get("esperando") or {}
    motivo = esperando.get("motivo") or ""
    pr = int(feitas["pr"]["titulo"].split("#")[1].split()[0]) if "pr" in feitas else None
    if "merge" in feitas:
        estado, detalhe = "entregue", feitas["merge"]["titulo"]
    elif item and item["status"] == "feito":
        estado, detalhe = "entregue", "item concluído sem merge registrado"
    elif ev["status"] == "done" and "item" not in feitas:
        estado, detalhe, desde = "entregue", "atendido sem virar item do roteiro", ev["processed_at"] or desde
    elif motivo and not motivo.startswith(CI_EM_CURSO):
        estado, detalhe = "bloqueado", motivo
    elif pr is not None:
        estado, detalhe = "andamento", f"PR #{pr}" + (f": {motivo}" if motivo else "")
    else:
        estado, detalhe = "recebido", f"esperando {esperando.get('o_que') or 'o loop ler o pedido'}"
    return {"estado": estado, "detalhe": detalhe, "pr": pr, "desde": desde, "idade_s": max(0, round(agora - desde))}


def pedidos(store: Store, agora: float | None = None) -> list[dict]:
    """Um estado por pedido do humano dos últimos 7 dias (o recorte de jobs.pedidos_7d), do mais recente ao mais antigo."""
    agora = time.time() if agora is None else agora
    out = []
    for ev in store.q(f"SELECT id, status, error, created_at, processed_at FROM events WHERE {HUMANO} AND created_at>? "
                      "ORDER BY created_at DESC, id DESC", (agora - JANELA,)):
        c = caminho(store, f"ev{ev['id']}", now=agora)
        it = store.one("SELECT status FROM roadmap WHERE id=?", (c["item"],)) if c["item"] is not None else None
        out.append({"evento": ev["id"], "texto": c["texto"][:160], "item": c["item"],
                    **estado_pedido(dict(ev), c, dict(it) if it else None, agora)})
    return out


def secao(ps: list[dict]) -> str:
    """O card do painel: um estado por pedido, com glifo e palavra (cor nunca sozinha) e a idade nele."""
    return ('<section class="card falhas" aria-label="Estado de cada pedido seu"><span>Seus pedidos (7 d)</span>'
            f'<b>{len(ps)}</b><small>um estado por pedido e há quanto tempo está nele</small><ol>' + "".join(
                f'<li><em class="delta {GLIFO_PEDIDO[p["estado"]][0]}">{GLIFO_PEDIDO[p["estado"]][1]} {p["estado"]}</em> '
                f'há {_dur(p["idade_s"])} · {escape(p["texto"][:80])} <small>{escape(p["detalhe"][:200])}</small></li>'
                for p in ps) + "</ol></section>")

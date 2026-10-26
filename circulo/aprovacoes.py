"""Precisa de você: tudo o que, no loop inteiro, está parado esperando uma decisão humana — num lugar só, com a ação.

O loop foi feito para não esperar ninguém; quando espera, isso tem de ficar visível na hora, não escondido numa
evidência de item ou num alerta já rolado. Fontes (cada uma com a ação que resolve):
- itens do roteiro que "dependem de você" (chaves, instalação): desativar ou resolver fora e o diagnóstico fecha;
- itens contestados pelo estudo (a evidência contradiz o pedido): reafirmar (executa mesmo assim) ou desativar;
- o loop pausado por você (botão Parar): retomar;
- orçamento esgotado no modo com limite (pausa até a meia-noite): subir o limite ou mudar para o modo sem limite;
- peças de configuração paradas (chave faltando, Claude Code ausente): o como-ligar;
- travas do SRE abertas há mais de LONGA_H horas com gravidade alta: ver e decidir;
- etapas em quarentena (incidente repetido isolou a etapa): o incidente a tratar;
- lançamentos de finanças esperando revisão: o comando `ok`;
- avisos ainda não lidos (merge, saúde, orçamento, controle): marcar como visto.
"""
from __future__ import annotations

import json
import time
from typing import Any

from .state import Store

LONGA_H = 6
AVISOS = ("merge", "saude", "orcamento", "controle", "fora_alcance")


def _item(tipo: str, titulo: str, detalhe: str, desde: float | None, acoes: list[dict], prioridade: int, ref: Any = None, link: str | None = None) -> dict:
    return {"tipo": tipo, "titulo": titulo[:160], "detalhe": (detalhe or "")[:400], "desde": desde, "acoes": acoes, "prioridade": prioridade,
            "ref": ref, "link": link}


def pendentes(store: Store, agora: float | None = None, diagnostico: bool = True) -> list[dict]:
    agora = agora or time.time()
    out: list[dict] = []
    ctl = store.get("controle") or {}
    if ctl.get("pausado"):
        p = store.get("parada") or {}
        out.append(_item("loop_pausado", "O loop está pausado por você", "Nada roda até você retomar (o botão Parar continua valendo).",
                         p.get("pedida_em"), [{"acao": "retomar", "rotulo": "Retomar o loop"}], 0))
    if store.get("loop_status") == "pausado_orcamento":
        lim = (store.get("orcamento_limite") or {}).get("limite")
        out.append(_item("orcamento", "Orçamento do dia esgotado: o loop pausou até a meia-noite",
                         f"Limite de hoje: {lim or 'padrão'} tokens. Suba o limite ou mude para o modo sem limite (medindo).", None,
                         [{"acao": "orcamento_ilimitado", "rotulo": "Mudar para sem limite"}], 0, link="/loop#seguranca"))
    for r in store.q("SELECT id, titulo, evidencia, updated_at FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 "
                     "AND evidencia LIKE '%depende de você%' ORDER BY ordem"):
        out.append(_item("item_depende", f"Item #{r['id']}: {r['titulo']}", r["evidencia"], r["updated_at"],
                         [{"acao": "desativar_item", "rotulo": "Tirar da fila"}], 2, ref=r["id"], link="/loop#evolucao"))
    for r in store.q("SELECT id, titulo, evidencia, updated_at FROM roadmap WHERE status='contestado' ORDER BY updated_at DESC"):
        out.append(_item("item_contestado", f"Item #{r['id']} contestado pelo estudo: {r['titulo']}", r["evidencia"], r["updated_at"],
                         [{"acao": "reafirmar_item", "rotulo": "Executar mesmo assim"}, {"acao": "desativar_item", "rotulo": "Deixar de lado"}], 1, ref=r["id"], link="/loop#evolucao"))
    nm = store.get("norte_marco") or {}
    if nm.get("cobrado") and not nm.get("evoluiu"):
        d = nm.get("depois") or {}
        out.append(_item("norte_sem_evolucao", "Norte: 2 dias sem evolução de produto — a solução precisa ser reescrita",
                         f"Fração de produto {nm.get('fracao_produto')} → {d.get('fracao_produto')}; {d.get('prs_produto')} PR(s) de produto na semana; "
                         f"{d.get('console')} no console. Reescrever o desenho (perspectivas, cota, pesquisa), não insistir.", nm.get("cobrado_em"), [], 0, link="/loop#evolucao"))
    par = store.get("entrega_parada") or {}
    if par:
        out.append(_item("entrega_parada", f"Entrega parada há {par.get('horas', '?')} h com {par.get('prontos', '?')} item(ns) prontos",
                         f"{par.get('frase', '')}. Nada entrou na main nesse tempo; o loop segue tentando.", par.get("desde"), [], 0, link="/loop"))
    esp = store.get("self_dev_espera") or {}
    if esp.get("precisa_de_voce") and float(esp.get("ate", 0)) > agora:
        out.append(_item("developer_parado", "Desenvolvedor parado: " + str(esp.get("motivo", "")), f"Nenhum item do roteiro anda até isso ser resolvido; o loop tenta de novo às {esp.get('hora', '?')}.",
                         None, [], 0, link="/loop"))
    for chave, e in (store.get("medico_escalados") or {}).items():
        out.append(_item("medico", f"Médico do loop escalou: {e.get('titulo', chave)}", f"Dono: {e.get('dono')}. Evidência: {json.dumps(e.get('evidencia', {}), ensure_ascii=False)[:300]}",
                         e.get("em"), [], 0, ref=chave, link="/loop"))
    q = store.get("quarentena") or {}
    for etapa, v in q.items():
        if isinstance(v, dict) and int(v.get("ate_tick", 0)) > store.tick:
            out.append(_item("quarentena", f"Etapa “{etapa}” em quarentena até o giro {v['ate_tick']}",
                             f"Incidente repetido isolou a etapa; o loop segue sem ela. {v.get('motivo', '')}", v.get("em"), [], 1, link="/loop#seguranca"))
    for r in store.q("SELECT chave, titulo, gravidade, sugestao, primeira_em FROM vigia WHERE status='aberta' AND gravidade>=0.7 AND primeira_em<=? ORDER BY gravidade DESC",
                     (agora - LONGA_H * 3600,)):
        out.append(_item("trava", f"Trava há {int((agora - r['primeira_em']) / 3600)} h: {r['titulo']}", r["sugestao"] or "", r["primeira_em"], [], 1, ref=r["chave"], link="/loop"))
    if store.one("SELECT 1 FROM sqlite_master WHERE name='ledger'"):
        for r in store.q("SELECT id, description, amount_cents, category, created_at FROM ledger WHERE status='open' AND auto_accepted=0 ORDER BY id DESC LIMIT 8"):
            out.append(_item("revisao", f"Lançamento #{r['id']}: {r['description']} → {r['category']}?", f"R$ {r['amount_cents'] / 100:.2f}. Confirme ou corrija na missão Finanças.",
                             r["created_at"], [{"acao": "ok_lancamento", "rotulo": "Está certo"}], 3, ref=r["id"], link="/"))
    for r in store.q(f"SELECT id, kind, message, created_at FROM alerts WHERE kind IN ({','.join('?' * len(AVISOS))}) AND delivered=0 ORDER BY id DESC LIMIT 12", AVISOS):
        out.append(_item("aviso", r["message"][:140], r["message"], r["created_at"], [{"acao": "visto", "rotulo": "Visto"}], 4, ref=r["id"]))
    if diagnostico:
        from .configuracao import diagnostico as diag
        for p in diag(testar_conexoes=False):
            if p.estado == "parado":
                out.append(_item("configuracao", f"{p.nome}: parado", f"{p.detalhe}. {p.como_ligar}".strip(), None, [], 2, link="/integracoes"))
    out.sort(key=lambda i: (i["prioridade"], -(i["desde"] or 0)))
    return out


def resumo(store: Store) -> dict:
    itens = pendentes(store)
    return {"total": len(itens), "urgentes": sum(1 for i in itens if i["prioridade"] <= 1), "itens": itens,
            "por_tipo": {t: sum(1 for i in itens if i["tipo"] == t) for t in {i["tipo"] for i in itens}}}


def agir(store: Store, acao: str, ref: Any, ctx=None) -> dict:
    """Executa a ação de um item; cada uma passa pelo mesmo caminho que o botão correspondente já usava."""
    agora = time.time()
    if acao == "retomar":
        from . import parada
        parada.retomar(store)
        return {"ok": True, "feito": "loop retomado"}
    if acao == "orcamento_ilimitado":
        from .budget import definir_modo
        definir_modo(store, "ilimitado")
        store.set("loop_status", "rodando")
        return {"ok": True, "feito": "orçamento sem limite (medindo)"}
    if acao == "desativar_item":
        r = store.one("SELECT titulo FROM roadmap WHERE id=?", (int(ref),))
        if not r:
            return {"ok": False, "erro": "item não existe"}
        store.x("UPDATE roadmap SET desativado=1, updated_at=? WHERE id=?", (agora, int(ref)))
        store.x("INSERT INTO alerts(kind,message,created_at,delivered) VALUES('controle',?,?,1)", (f"Você tirou da fila o item #{ref}: {r['titulo'][:100]}", agora))
        return {"ok": True, "feito": f"item #{ref} fora da fila"}
    if acao == "reafirmar_item":
        if ctx is None or getattr(ctx, "estudo", None) is None:
            store.x("UPDATE roadmap SET status='pendente', evidencia='contestado pelo estudo; você reafirmou', updated_at=? WHERE id=? AND status='contestado'", (agora, int(ref)))
            return {"ok": True, "feito": f"item #{ref} reafirmado"}
        return {"ok": bool(ctx.estudo.reafirmar(int(ref))), "feito": f"item #{ref} reafirmado"}
    if acao == "ok_lancamento":
        store.x("UPDATE ledger SET status='confirmed' WHERE id=? AND status='open'", (int(ref),))
        return {"ok": True, "feito": f"lançamento #{ref} confirmado"}
    if acao == "visto":
        store.x("UPDATE alerts SET delivered=1 WHERE id=?", (int(ref),))
        return {"ok": True, "feito": "aviso marcado como visto"}
    return {"ok": False, "erro": f"ação desconhecida: {acao}"}


__all__ = ["pendentes", "resumo", "agir"]

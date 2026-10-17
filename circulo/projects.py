"""Projetos vivos: cada pedido vira um projeto que o círculo evolui com o propósito dele.

O Intake (Jev First) classifica o tipo do pedido. Se existe um kit para aquele tipo, o projeto
entra ativo; se ainda não existe, fica registrado como `aguardando_kit` — o pedido não se perde,
e o círculo passa a atendê-lo quando o kit for criado.
"""
from __future__ import annotations

import re
import time

from .decision import DecisionLayer, Question
from .state import Store

# tipo → (rótulo, descrição para o Jev, kit que atende hoje ou None)
TIPOS: dict[str, tuple[str, str, str | None]] = {
    "financas": ("Finanças", "Controle financeiro, gastos, economia, orçamento, patrimônio", "financas"),
    "landing_page": ("Landing page", "Página para captar leads ou vender uma oferta", None),
    "produto_software": ("Produto de software", "Sistema, portal, app ou plataforma com usuários", None),
    "plano": ("Plano", "Plano de ação, cronograma, orçamento ou checklist para um objetivo", None),
    "pesquisa_decisao": ("Pesquisa e decisão", "Comparar opções e recomendar uma decisão fundamentada", None),
    "conteudo": ("Conteúdo", "Textos, posts, roteiros ou calendário editorial", None),
    "outro": ("Outro", "Nenhum dos tipos acima", None),
}

PROPOSITO = {
    "financas": "Registrar e entender os gastos da família, achar onde economizar e acompanhar o caminho até a casa.",
    "landing_page": "Captar o máximo de leads qualificados, com a página medida contra o que há de melhor no mercado.",
    "produto_software": "Entregar um produto útil para quem vai usá-lo e evoluí-lo a cada ciclo.",
    "plano": "Transformar o objetivo em passos concretos, com prazos e custos, e manter o plano atualizado.",
    "pesquisa_decisao": "Comparar as opções com evidências e recomendar a melhor decisão para o seu caso.",
    "conteudo": "Produzir conteúdo consistente e melhorar o que funciona a cada rodada.",
    "outro": "Entender melhor o pedido e encontrar a melhor forma de resolvê-lo.",
}

FINANCAS_PEDIDO = "Crie um painel web da minha vida financeira e me ajude a economizar dinheiro"

_VERBOS = re.compile(r"^\s*(por favor[,]?\s*)?(crie|criar|cria|monte|montar|faça|fazer|faz|preciso de|quero|gere|gerar|escreva|me ajude a|ajude-me a)\s+((umas|uma|uns|um|os|as|o|a)\b)?\s*", re.I)


def nome_do_pedido(pedido: str) -> str:
    """Nome curto derivado do próprio pedido (sem LLM)."""
    s = _VERBOS.sub("", pedido.strip()).strip(" .!?")
    s = s.split(" e me ")[0].split(", ")[0]
    s = s[:1].upper() + s[1:]
    return (s[:56].rsplit(" ", 1)[0] + "…") if len(s) > 56 else (s or "Pedido sem título")


def ensure_seed(store: Store) -> None:
    """O kit de finanças já existe: ele é o projeto nº 1."""
    if store.one("SELECT 1 FROM projects WHERE kit='financas'"):
        return
    now = time.time()
    store.x("INSERT INTO projects(nome,pedido,tipo,kit,status,proposito,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("Finanças da família", FINANCAS_PEDIDO, "financas", "financas", "ativo", PROPOSITO["financas"], now, now))


def kit_project_id(store: Store, kit: str) -> int | None:
    row = store.one("SELECT id FROM projects WHERE kit=? AND status!='arquivado' ORDER BY id LIMIT 1", (kit,))
    return row["id"] if row else None


def intake(store: Store, dl: DecisionLayer, pedido: str) -> dict:
    """Pedido novo → projeto. O tipo é uma decisão Jev (Choice); sem LLM."""
    d = dl.ask("project_type", Question(
        "choice", "Que tipo de solução este pedido pede?", {k: v[1] for k, v in TIPOS.items()}), {"pedido": pedido})
    tipo = d.value
    kit = TIPOS[tipo][2]
    # Pedido de finanças com o kit já ativo: é o mesmo projeto, não um novo.
    if kit and (pid := kit_project_id(store, kit)) is not None:
        store.x("UPDATE projects SET updated_at=? WHERE id=?", (time.time(), pid))
        return {"id": pid, "novo": False, "tipo": tipo, "status": "ativo", "confianca": d.confidence}
    status = "ativo" if kit else "aguardando_kit"
    now = time.time()
    pid = store.x("INSERT INTO projects(nome,pedido,tipo,kit,status,proposito,tipo_confianca,created_at,updated_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?)",
                  (nome_do_pedido(pedido), pedido, tipo, kit, status, PROPOSITO[tipo], d.confidence, now, now))
    # a decisão do Intake nasceu antes do projeto; ela passa a contar como a primeira decisão dele
    store.x("UPDATE decisions SET project_id=? WHERE id=(SELECT MAX(id) FROM decisions WHERE question='project_type' AND project_id IS NULL)", (pid,))
    return {"id": pid, "novo": True, "tipo": tipo, "status": status, "confianca": d.confidence}


def cards(store: Store) -> list[dict]:
    """Resumo de cada projeto para a tela inicial."""
    out = []
    etapa = store.get("etapa") or {}
    for p in store.q("SELECT * FROM projects WHERE status!='arquivado' ORDER BY updated_at DESC"):
        pid = p["id"]
        dec = store.one("""SELECT COUNT(*) n, SUM(source!='llm') sem_llm, MAX(created_at) ultima, COUNT(DISTINCT tick) giros
                           FROM decisions WHERE project_id=?""", (pid,))
        ev = {r["status"]: r["c"] for r in store.q("SELECT status, COUNT(*) c FROM proposals WHERE project_id=? GROUP BY status", (pid,))}
        horas = [r["h"] for r in store.q(
            "SELECT CAST((strftime('%s','now') - created_at) / 3600 AS INT) h FROM decisions WHERE project_id=? AND created_at > strftime('%s','now') - 86400",
            (pid,))]
        atividade = [0] * 24
        for h in horas:
            if 0 <= h < 24:
                atividade[23 - h] += 1
        out.append({
            "id": pid, "nome": p["nome"], "pedido": p["pedido"], "tipo": p["tipo"], "tipo_rotulo": TIPOS.get(p["tipo"], ("?",))[0],
            "kit": p["kit"], "status": p["status"], "proposito": p["proposito"],
            "decisoes": dec["n"] or 0, "sem_llm": (dec["sem_llm"] or 0) / dec["n"] if dec["n"] else None,
            "giros": dec["giros"] or 0, "ultima_atividade": dec["ultima"] or p["updated_at"],
            "evolucoes_aplicadas": ev.get("applied", 0), "evolucoes_total": sum(ev.values()),
            "atividade_24h": atividade, "agora": etapa.get("projeto") == pid,
            "criado_em": p["created_at"],
        })
    # ativos primeiro; dentro de cada grupo, o que teve atividade mais recente
    out.sort(key=lambda c: (c["status"] != "ativo", -c["ultima_atividade"]))
    return out

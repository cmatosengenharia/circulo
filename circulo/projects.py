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
    "circulo": ("O próprio círculo", "Melhorar o próprio loop: autonomia, autoevolução, guardrails, painel", "circulo"),
    "financas": ("Finanças", "Controle financeiro, gastos, economia, orçamento, patrimônio", "financas"),
    "landing_page": ("Landing page", "Página para captar leads ou vender uma oferta", None),
    "produto_software": ("Produto de software", "Sistema, portal, app ou plataforma com usuários", None),
    "plano": ("Plano", "Plano de ação, cronograma, orçamento ou checklist para um objetivo", None),
    "pesquisa_decisao": ("Pesquisa e decisão", "Comparar opções e recomendar uma decisão fundamentada", None),
    "conteudo": ("Conteúdo", "Textos, posts, roteiros ou calendário editorial", None),
    "outro": ("Outro", "Nenhum dos tipos acima", None),
}

PROPOSITO = {
    "circulo": "Chegar à autonomia total: registrar todo erro, aprender com ele, se autocorrigir e evoluir a si mesmo sem degradar.",
    "financas": "Registrar e entender os gastos da família, achar onde economizar e acompanhar o caminho até a casa.",
    "landing_page": "Captar o máximo de leads qualificados, com a página medida contra o que há de melhor no mercado.",
    "produto_software": "Entregar um produto útil para quem vai usá-lo e evoluí-lo a cada ciclo.",
    "plano": "Transformar o objetivo em passos concretos, com prazos e custos, e manter o plano atualizado.",
    "pesquisa_decisao": "Comparar as opções com evidências e recomendar a melhor decisão para o seu caso.",
    "conteudo": "Produzir conteúdo consistente e melhorar o que funciona a cada rodada.",
    "outro": "Entender melhor o pedido e encontrar a melhor forma de resolvê-lo.",
}

CIRCULO_PEDIDO = ("O próprio loop é um projeto: use todos os meus pedidos iniciais para começar a evolução dele, até ser "
                  "totalmente autônomo e se autoevoluir, registrando todos os erros, aprendendo com eles e se autocorrigindo.")

# Roteiro semente: os pedidos do Cássio que criaram o círculo, com o estado honesto de cada um.
# (titulo, detalhe, status, evidência)
ROTEIRO_SEMENTE = [
    ("Loop infinito que só pausa por orçamento", "Estado persistente, retoma de onde parou, recupera após queda.", "feito", "commit 84abb23"),
    ("Jev First antes de qualquer gasto", "worth_spending/should_evolve, perguntas em lote, decisor local com o mesmo contrato.", "feito", "commit 84abb23"),
    ("Jev em todas as etapas antes da LLM (cascata completa)", "Faltam route/pick_model/verify_output/meets_bar e a métrica de destilação.", "parcial", "Prompt Mestre §3–4"),
    ("Equipe de agentes falando com o Jev", "Núcleo de finanças pronto; Researcher, Rubric Builder e Builders genéricos pendentes.", "parcial", "commit 84abb23"),
    ("Evolução de domínio sem aprovar PR por PR", "Regras aprendidas com correções, replay e invariantes.", "feito", "commit 84abb23"),
    ("Evolução do próprio círculo em shadow", "Hoje cobre limiares; harness, perguntas e portfólio ainda não.", "parcial", "commit 84abb23"),
    ("Rollback automático quando a saúde cai", "Health Monitor reverte a última política.", "feito", "commit 84abb23"),
    ("Gate de merge no próprio círculo", "Checks verdes, limite de linhas, label aprovado-humano, SHA travado.", "feito", "commit df0b278"),
    ("Entregar qualquer solução, não só software", "Projetos e Intake prontos; kits por tipo ainda não existem.", "parcial", "commit 22e1710"),
    ("Pesquisar o melhor da internet e transformar em régua", "Researcher + Rubric Builder + evals.", "pendente", "Prompt Mestre §7"),
    ("Autogerenciar o portfólio de projetos", "next_project, retorno decrescente, parar e reabrir projetos.", "pendente", "Prompt Mestre §2"),
    ("Técnicas modernas onde fizer sentido", "Harness evoluível, skills, RAG com rerank do Jev, evals, destilação.", "pendente", "Prompt Mestre §6"),
    ("Guardrails contra deleção, degradação e estagnação", "Guard de política e quarentena prontos; catraca, held-out e snapshots pendentes.", "parcial", "Prompt Mestre §11"),
    ("Painel local ao vivo", "Feed de decisões, saúde, controles de pausa e modo seguro.", "feito", "commit 8f4895a"),
    ("Projetos em cards", "Cada pedido vira um projeto com propósito.", "feito", "commit 22e1710"),
    ("Estado do loop em tempo real", "Batimento, desligado vs rodando, contagem até o próximo giro.", "feito", "commit 9f740dd"),
    ("O próprio loop como projeto", "Registra todo erro, aprende com ele e se autocorrige.", "em_andamento", "este card"),
]

FINANCAS_PEDIDO = "Crie um painel web da minha vida financeira e me ajude a economizar dinheiro"

_VERBOS = re.compile(r"^\s*(por favor[,]?\s*)?(crie|criar|cria|monte|montar|faça|fazer|faz|preciso de|quero|gere|gerar|escreva|me ajude a|ajude-me a)\s+((umas|uma|uns|um|os|as|o|a)\b)?\s*", re.I)


def nome_do_pedido(pedido: str) -> str:
    """Nome curto derivado do próprio pedido (sem LLM)."""
    s = _VERBOS.sub("", pedido.strip()).strip(" .!?")
    s = s.split(" e me ")[0].split(", ")[0]
    s = s[:1].upper() + s[1:]
    return (s[:56].rsplit(" ", 1)[0] + "…") if len(s) > 56 else (s or "Pedido sem título")


def ensure_seed(store: Store) -> None:
    """Projetos semente: finanças (primeiro kit) e o próprio círculo (projeto zero)."""
    now = time.time()
    if not store.one("SELECT 1 FROM projects WHERE kit='financas'"):
        store.x("INSERT INTO projects(nome,pedido,tipo,kit,status,proposito,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                ("Finanças da família", FINANCAS_PEDIDO, "financas", "financas", "ativo", PROPOSITO["financas"], now, now))
    if not store.one("SELECT 1 FROM projects WHERE kit='circulo'"):
        store.x("INSERT INTO projects(nome,pedido,tipo,kit,status,proposito,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                ("O próprio círculo", CIRCULO_PEDIDO, "circulo", "circulo", "ativo", PROPOSITO["circulo"], now, now))
    if not store.one("SELECT 1 FROM roadmap WHERE origem='pedido_cassio'"):
        for i, (titulo, detalhe, status, evid) in enumerate(ROTEIRO_SEMENTE, 1):
            store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (titulo, detalhe, "pedido_cassio", status, evid, i, now, now))


def roteiro(store: Store) -> list[dict]:
    return [dict(r) for r in store.q("SELECT id, titulo, detalhe, origem, status, evidencia FROM roadmap ORDER BY "
                                     "CASE status WHEN 'em_andamento' THEN 0 WHEN 'pendente' THEN 1 WHEN 'parcial' THEN 2 ELSE 3 END, ordem")]


def incidentes(store: Store, limit: int = 20) -> list[dict]:
    return [dict(r) for r in store.q("SELECT id, stage, kind, message, count, status, resolution, last_seen, last_tick FROM incidents "
                                     "ORDER BY CASE status WHEN 'isolado' THEN 0 WHEN 'aberto' THEN 1 ELSE 2 END, last_seen DESC LIMIT ?",
                                     (limit,))]


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


def _extras_circulo(store: Store) -> dict:
    r = {x["status"]: x["n"] for x in store.q("SELECT status, COUNT(*) n FROM roadmap GROUP BY status")}
    i = {x["status"]: x["n"] for x in store.q("SELECT status, COUNT(*) n FROM incidents GROUP BY status")}
    return {"roteiro": {"feito": r.get("feito", 0), "total": sum(r.values()), "parcial": r.get("parcial", 0)},
            "erros": {"abertos": i.get("aberto", 0) + i.get("isolado", 0), "resolvidos": i.get("resolvido", 0),
                      "isolados": i.get("isolado", 0)}}


def novos_na_fila(store: Store) -> int:
    return store.one("SELECT COUNT(*) n FROM events WHERE kind='novo_projeto' AND status IN ('pending','processing')")["n"]


def cards(store: Store) -> list[dict]:
    """Resumo de cada projeto para a tela inicial."""
    out = []
    etapa = store.get("etapa") or {}
    fin = kit_project_id(store, "financas")
    fila: dict[int | None, int] = {}
    for r in store.q("SELECT kind, json_extract(payload,'$.projeto') pid FROM events WHERE status IN ('pending','processing')"):
        key = None if r["kind"] == "novo_projeto" else (r["pid"] or fin)
        fila[key] = fila.get(key, 0) + 1
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
            "criado_em": p["created_at"], "na_fila": fila.get(pid, 0),
            **(_extras_circulo(store) if p["kit"] == "circulo" else {}),
        })
    # ativos primeiro; dentro de cada grupo, o que teve atividade mais recente
    out.sort(key=lambda c: (c["kit"] != "circulo", c["status"] != "ativo", -c["ultima_atividade"]))
    return out

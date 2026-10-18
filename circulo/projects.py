"""Projetos vivos: cada pedido vira um projeto que o círculo evolui com o propósito dele.

O Intake (Jev First) classifica o tipo do pedido. Se existe um kit para aquele tipo, o projeto
entra ativo; se ainda não existe, fica registrado como `aguardando_kit` — o pedido não se perde,
e o círculo passa a atendê-lo quando o kit for criado.
"""
from __future__ import annotations

import json
import re
import time

from .decision import DecisionLayer, Question
from .state import Store

# tipo → (rótulo, descrição para o Jev, kit que atende hoje ou None)
TIPOS: dict[str, tuple[str, str, str | None]] = {
    "circulo": ("Missão zero", "Melhorar o próprio loop: autonomia, autoevolução, guardrails, painel", "circulo"),
    "financas": ("Finanças", "Controle financeiro, gastos, economia, orçamento, patrimônio", "financas"),
    "landing_page": ("Landing page", "Página para captar leads ou vender uma oferta", "geral"),
    "produto_software": ("Produto de software", "Sistema, portal, app ou plataforma com usuários", "geral"),
    "plano": ("Plano", "Plano de ação, cronograma, orçamento ou checklist para um objetivo", "geral"),
    "pesquisa_decisao": ("Pesquisa e decisão", "Comparar opções e recomendar uma decisão fundamentada", "geral"),
    "conteudo": ("Conteúdo", "Textos, posts, roteiros ou calendário editorial", "geral"),
    "outro": ("Outro", "Nenhum dos tipos acima", "geral"),
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
ROTEIRO_VERSAO = 5
ROTEIRO_SEMENTE = [
    ("Loop infinito que só pausa por orçamento", "Estado persistente, retoma de onde parou, recupera após queda.", "feito", "commit 84abb23"),
    ("Jev First antes de qualquer gasto", "worth_spending/should_evolve, perguntas em lote, decisor local com o mesmo contrato.", "feito", "commit 84abb23"),
    ("Jev em todas as etapas antes da LLM (cascata completa)", "route, pick_model, verify_output, meets_bar, relevant, remember e destilação.", "feito", "commits 401772d, c714cf4"),
    ("Equipe de agentes falando com o Jev", "Researcher, Rubric Builder, Builder, Improver, Reflector, Developer e o kit de finanças.", "feito", "commits af9deb7, b163a26"),
    ("Evolução de domínio sem aprovar PR por PR", "Regras aprendidas com correções, replay e invariantes.", "feito", "commit 84abb23"),
    ("Evolução do próprio círculo em shadow", "Limiares em shadow e prompts por A/B; perguntas do Jev e parâmetros do portfólio ainda não evoluem sozinhos.", "parcial", "commits 84abb23, c714cf4"),
    ("Rollback automático quando a saúde cai", "Health Monitor reverte a última política.", "feito", "commit 84abb23"),
    ("Gate de merge no próprio círculo", "Checks verdes, limite de linhas, label aprovado-humano, SHA travado.", "feito", "commit df0b278"),
    ("Entregar qualquer solução, não só software", "Motor genérico atende todos os tipos; produto de software ainda sai como especificação, não como código.", "parcial", "commit af9deb7"),
    ("Pesquisar o melhor da internet e transformar em régua", "Busca na web, achados filtrados pelo Jev, régua mensurável com critérios ocultos.", "feito", "commit af9deb7"),
    ("Autogerenciar o portfólio de projetos", "next_project, orçamento por projeto, retorno decrescente, manutenção e reabertura.", "feito", "commit af9deb7"),
    ("Técnicas modernas onde fizer sentido", "Harness evoluível, playbooks como skills, RAG com rerank do Jev, evals, destilação. Embeddings e fine-tuning ficaram de fora de propósito: sem gatilho ainda.", "feito", "commits 401772d, 13bc1e0, c714cf4"),
    ("Guardrails contra deleção, degradação e estagnação", "Catraca, critérios ocultos, snapshots, oscilação, orçamento de mudanças, estagnação, quarentena.", "feito", "commits af9deb7, c714cf4"),
    ("Painel local ao vivo", "Feed de decisões, saúde, controles de pausa e modo seguro.", "feito", "commit 8f4895a"),
    ("Projetos em cards", "Cada pedido vira um projeto com propósito.", "feito", "commit 22e1710"),
    ("Estado do loop em tempo real", "Batimento, desligado vs rodando, contagem até o próximo giro.", "feito", "commit 9f740dd"),
    ("O próprio loop como projeto", "Registra todo erro, aprende, se isola em execução e corrige o próprio código por PR.", "feito", "commits 17e5ea4, b163a26"),
    ("Zero espera pelo humano", "Nenhuma etapa pergunta ou aguarda: finanças se reclassificam sozinhas, a constituição é recusada na hora em vez de pedir aprovação, código de dinheiro entra com evidência reforçada no CI.", "feito", "commit c95b991"),
    ("Missões evoluindo em paralelo", "Várias missões por giro, ranqueadas pelo Jev, com orçamento reservado antes.", "feito", "commit c95b991"),
    ("Missões que se conhecem e se integram", "Grafo decidido pelo Jev; memória e contexto compartilhados; integração vira critério; lições viajam entre missões; missão ligada que muda reabre a outra.", "feito", "commit c95b991"),
    ("Evidência de acerto antes de avançar", "Medição antes/depois (visível e oculta), verificação, Jev a favor + contraprova; contradição = refazer; missão cumprida com evidência.", "feito", "commit c95b991"),
    ("Configuração única em um passo", "circulo configurar / diagnostico / instalar; o loop lê as chaves sozinho e o painel mostra o que falta.", "feito", "v1.0.0"),
    ("Ligar as chaves e o Claude Code na máquina do loop", "`circulo configurar` e preencher TYPESAFE_API_KEY, ANTHROPIC_API_KEY, GITHUB_TOKEN, CIRCULO_REPO, CIRCULO_REPO_DIR; instalar o Claude Code. O diagnóstico fecha este item sozinho.", "pendente", "depende de você"),
    ("Rodar 24/7", "`circulo instalar` (launchd no macOS, systemd no Linux). O diagnóstico fecha este item sozinho.", "pendente", "depende de você"),
    ("Produto de software vira código", "Hoje o portal sai como especificação; o próximo passo é o Builder gerar um repositório por projeto e usar o mesmo gate.", "pendente", "Prompt Mestre §6"),
    ("Perguntas do Jev e portfólio evoluindo sozinhos", "Estender o shadow para instruções das perguntas e parâmetros do portfólio.", "pendente", "Prompt Mestre §8"),
    ("Painel de confiança em tempo real, evoluindo por evidência",
     "O humano precisa sentir segurança em absolutamente tudo o que o loop faz, em tempo real. Estudar as práticas "
     "consolidadas (consciência situacional de Endsley: perceber, entender, projetar; frescor do dado; supervisão humana "
     "de agentes: trilha da decisão, parada verificável; sinais de ouro de SRE) e evoluir a Central de confiança do painel. "
     "Sucesso: neurônio painel:frescor sempre abaixo de 3 s e nenhuma ação do loop sem aparecer no painel na hora.",
     "pendente", "pedido do Cássio (18/10, 11:06)"),
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
                ("O Loop", CIRCULO_PEDIDO, "circulo", "circulo", "ativo", PROPOSITO["circulo"], now, now))
    store.x("UPDATE projects SET nome='O Loop' WHERE kit='circulo' AND nome='O próprio círculo'")
    # projetos criados antes do motor genérico passam a ser atendidos por ele
    store.x("UPDATE projects SET kit='geral', status='ativo' WHERE status='aguardando_kit'")
    if (store.get("roteiro_versao") or 0) < ROTEIRO_VERSAO:
        # roteiro semente versionado: atualiza o estado dos pedidos do humano, sem tocar nos itens que o círculo criou
        for i, (titulo, detalhe, status, evid) in enumerate(ROTEIRO_SEMENTE, 1):
            row = store.one("SELECT id FROM roadmap WHERE origem='pedido_cassio' AND titulo=?", (titulo,))
            if row:
                # o que o loop já entregou nunca volta atrás por causa da semente (ex.: item feito por PR do Developer)
                atual = store.one("SELECT status, evidencia FROM roadmap WHERE id=?", (row["id"],))
                if atual["status"] in ("feito", "observacao", "contestado") and status != "feito":
                    status, evid = atual["status"], atual["evidencia"]
                store.x("UPDATE roadmap SET detalhe=?, status=?, evidencia=?, ordem=?, updated_at=? WHERE id=?",
                        (detalhe, status, evid, i, now, row["id"]))
            else:
                store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (titulo, detalhe, "pedido_cassio", status, evid, i, now, now))
        store.set("roteiro_versao", ROTEIRO_VERSAO)


def roteiro(store: Store) -> list[dict]:
    return [dict(r) for r in store.q("SELECT id, titulo, detalhe, origem, status, evidencia, COALESCE(desativado,0) desativado, updated_at FROM roadmap ORDER BY "
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
    if kit in ("financas", "circulo") and (pid := kit_project_id(store, kit)) is not None:
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


def _modelos(store: Store, pid: int, kit: str) -> list[str]:
    """Quais IAs trabalharam nesta missão (rótulos curtos)."""
    out = []
    fontes = {r["source"] for r in store.q("SELECT DISTINCT source FROM decisions WHERE project_id=?", (pid,))}
    if "jev" in fontes:
        out.append("Jev")
    if "local" in fontes:
        out.append("Jev local")
    usados = [json.loads(r["value"]) for r in store.q("SELECT DISTINCT value FROM decisions WHERE project_id=? AND question LIKE 'llm:%'", (pid,))]
    usados += [r["modelo"] for r in store.q("SELECT DISTINCT modelo FROM llm_calls WHERE project_id=? AND modelo LIKE 'claude-%'", (pid,))]
    for valor in dict.fromkeys(usados):
        partes = valor.replace("claude-", "").split("-")
        nome = (partes[0].title() + " " + ".".join(partes[1:])).strip()
        if nome not in out:
            out.append(nome)
    if "llm" in fontes and not any(m[0].isupper() and m not in ("Jev", "Jev local") for m in out):
        out.append("LLM (fallback)")
    if kit == "circulo" and store.one("SELECT 1 FROM prs"):
        out.append("Claude Code")
    return out or ["—"]


def metricas(store: Store, p) -> dict:
    """Indicadores de uma missão. O indicador principal depende do propósito (kit)."""
    pid, kit = p["id"], p["kit"]
    dec = store.one("SELECT COUNT(*) n, SUM(source!='llm') sem_llm, COUNT(DISTINCT tick) giros FROM decisions WHERE project_id=?", (pid,))
    props = store.one("SELECT COUNT(*) n, MAX(updated_at) ult FROM proposals WHERE project_id=? AND status='applied'", (pid,))
    melhorias = store.one("SELECT COUNT(*) n, MAX(created_at) ult, COALESCE(SUM(CASE WHEN aceita=1 AND ganho>0 THEN ganho END),0) g "
                          "FROM cycles WHERE project_id=? AND aceita=1 AND fase='melhoria'", (pid,))
    tent = store.one("SELECT COUNT(*) n, SUM(aceita) ok, COALESCE(SUM(tokens),0) tok FROM cycles WHERE project_id=? AND aceita IS NOT NULL", (pid,))
    prs = {r["status"]: r["n"] for r in store.q("SELECT status, COUNT(*) n FROM prs WHERE project_id=? GROUP BY status", (pid,))}
    erros = store.one("SELECT COUNT(*) n FROM incidents WHERE project_id=? AND status!='resolvido'", (pid,))["n"]
    tokens = store.one("SELECT COALESCE(SUM(tokens),0) t FROM cycles WHERE project_id=?", (pid,))["t"]
    m = {
        "ciclos": dec["giros"] or 0,
        "decisoes": dec["n"] or 0,
        "sem_llm": (dec["sem_llm"] or 0) / dec["n"] if dec["n"] else None,
        "evolucoes": (props["n"] or 0) + (melhorias["n"] or 0),
        "ultima_evolucao": max(props["ult"] or 0, melhorias["ult"] or 0) or None,
        "prs": {"abertos": prs.get("aberto", 0), "mergeados": prs.get("mergeado", 0)},
        "modelos": _modelos(store, pid, kit),
        "erros_abertos": erros,
        "tokens": tokens,
        "aceitacao": (tent["ok"] or 0) / tent["n"] if tent["n"] else None,
        "tokens_por_ponto": round(tent["tok"] / (melhorias["g"] * 100)) if melhorias["g"] else None,
        "licoes": store.one("SELECT COUNT(*) n FROM memory WHERE kind='licao' AND status='ativa' AND tipo=?", (p["tipo"],))["n"],
        "conexoes": [dict(r) for r in store.q(
            """SELECT pr.id, pr.nome, l.relacao FROM links l JOIN projects pr ON pr.id = CASE WHEN l.a=? THEN l.b ELSE l.a END
               WHERE (l.a=? OR l.b=?) AND l.relacao!='nenhuma' AND pr.status!='arquivado' ORDER BY l.forca DESC""", (pid, pid, pid))],
        "licoes_recebidas": store.one("SELECT COUNT(*) n FROM transfers WHERE para=?", (pid,))["n"],
        "licoes_doadas": store.one("SELECT COUNT(*) n FROM transfers WHERE de=?", (pid,))["n"],
        "evidencias": store.one("SELECT COUNT(*) n FROM evidence WHERE project_id=?", (pid,))["n"],
    }
    if kit == "geral":
        hist = [r["nota"] for r in store.q("SELECT nota FROM deliverables WHERE project_id=? AND status!='descartada' ORDER BY version", (pid,))]
        cur = store.one("SELECT version FROM deliverables WHERE project_id=? AND status='atual' ORDER BY version DESC LIMIT 1", (pid,))
        m["versao"] = f"v{cur['version']}" if cur else "—"
        m["principal"] = {"rotulo": "Nota na régua", "valor": p["melhor_nota"], "formato": "pct", "historico": hist,
                          "ajuda": "Quanto a entrega atende a régua montada a partir da pesquisa."}
    elif kit == "financas":
        r = store.one("SELECT COUNT(*) n, SUM(auto_accepted=1 AND status!='corrected') ok FROM ledger WHERE kind='despesa'")
        regras = store.one("SELECT COUNT(*) n FROM proposals WHERE project_id=? AND kind='add_rule' AND status='applied'", (pid,))["n"]
        m["versao"] = f"regras v{regras + 1}"
        m["lancamentos"] = store.one("SELECT COUNT(*) n FROM ledger")["n"]
        m["principal"] = {"rotulo": "Categorizado sozinho", "valor": (r["ok"] or 0) / r["n"] if r["n"] else None, "formato": "pct",
                          "historico": [], "ajuda": "Despesas que o loop categorizou certo sem você corrigir."}
    elif kit == "circulo":
        ver = store.one("SELECT version FROM policy_versions WHERE status='active' ORDER BY version DESC LIMIT 1")["version"]
        rot = {x["status"]: x["n"] for x in store.q("SELECT status, COUNT(*) n FROM roadmap WHERE COALESCE(desativado,0)=0 GROUP BY status")}
        total = sum(rot.values()) or 1
        m["ciclos"] = store.tick                     # o loop conta todos os giros, de todas as missões
        m["versao"] = f"política v{ver}"
        m["evolucoes"] = store.one("SELECT COUNT(*) n FROM policy_versions WHERE reason!='semente'")["n"] + \
            store.one("SELECT COUNT(*) n FROM harness_experiments WHERE status='promovido'")["n"]
        m["tokens"] = store.one("SELECT COALESCE(SUM(tokens),0) t FROM budget")["t"]
        m["missoes"] = store.one("SELECT COUNT(*) n FROM projects WHERE kit!='circulo' AND status!='arquivado'")["n"]
        from .repo_stats import stats as repo_stats
        m["commits"] = repo_stats()
        m["principal"] = {"rotulo": "Roteiro concluído", "valor": rot.get("feito", 0) / total, "formato": "pct", "historico": [],
                          "ajuda": "Pedidos seus e correções que o próprio loop registrou, já entregues."}
    return m


def _pausa_estado(store: Store, pid: int) -> dict:
    from .pausa import estado
    return estado(store, pid)


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
            "paralelo": int(p["paralelo"] or 1) if "paralelo" in p.keys() else 1,
            "pausa": None if p["kit"] == "circulo" else _pausa_estado(store, pid),
            "kit": p["kit"], "status": p["status"], "proposito": p["proposito"],
            "decisoes": dec["n"] or 0, "sem_llm": (dec["sem_llm"] or 0) / dec["n"] if dec["n"] else None,
            "giros": dec["giros"] or 0, "ultima_atividade": dec["ultima"] or p["updated_at"],
            "evolucoes_aplicadas": ev.get("applied", 0), "evolucoes_total": sum(ev.values()),
            "atividade_24h": atividade, "agora": etapa.get("projeto") == pid,
            "criado_em": p["created_at"], "na_fila": fila.get(pid, 0), "metricas": metricas(store, p),
            **(_extras_circulo(store) if p["kit"] == "circulo" else {}),
            **({"nota": p["melhor_nota"], "ciclos_motor": p["ciclos"] or 0, "motor_pronto": bool(store.get("motor_pronto")),
                "versoes": store.one("SELECT COUNT(*) n FROM deliverables WHERE project_id=? AND status!='descartada'", (pid,))["n"],
                "regua": bool(store.one("SELECT 1 FROM rubrics WHERE project_id=?", (pid,)))} if p["kit"] == "geral" else {}),
        })
    # ativos primeiro; dentro de cada grupo, o que teve atividade mais recente
    out.sort(key=lambda c: (c["kit"] != "circulo", bool(c.get("pausa") and c["pausa"]["pausada"]), c["status"] != "ativo",
                            -c["ultima_atividade"]))
    return out

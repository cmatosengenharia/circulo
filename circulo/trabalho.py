"""Meu trabalho: a tela que junta o dia a dia do engenheiro — assuntos, daily, links, orçamento de IA, contexto para o
Cursor e o mapa do GAIA — e a semente de dados de exemplo que deixa o esqueleto inteiro funcionando antes do dado real.

Na madrugada de 26/10 o loop entregou as peças soltas (assuntos.py, daily.py, links.py, gasto_cursor.py,
contexto_cursor.py, pastas.py, etapas no kit), cada uma com a própria entrada (CLI, barra de busca, arquivo). Esta
tela é a cola: uma visão só (`visao`), anotar e perguntar pelo console (sem Jev, a regra local decide pelo assunto que
mais divide palavras com a frase), e o exemplo (`semear`/`apagar`) — dados fictícios de uma squad de comunicação,
marcados como exemplo em tudo que tocam, apagáveis com um clique. Nada aqui é dado da empresa: os endereços são
`*.exemplo` e os nomes, genéricos.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from pathlib import Path

from . import assuntos, contexto_cursor, daily, gasto_cursor, pastas
from .budget import TZ
from .links import Links

KV = "trabalho_exemplo"         # kv: ids do que a semente criou (assuntos, notas, links) — o que `apagar` remove
ORIGEM = "exemplo"              # gasto_cursor.origem e nome dos arquivos de nota da semente
MAX_FRASE = 1000
DIA = 86400.0

# (nome, descrição) — uma squad de comunicação fictícia, no formato do pedido: tribo, squad, cada serviço, a migração
ASSUNTOS = (
    ("Tribo Atendimento", "tribo de atendimento ao cliente: rituais, prioridades do trimestre e pessoas"),
    ("Squad Comunicação", "squad de soluções de comunicação: cerimônias, OKRs e entregas"),
    ("svc-notificacoes", "microsserviço de notificações: orquestra o envio por e-mail, SMS e push"),
    ("svc-sms", "microsserviço de envio de SMS pelos provedores"),
    ("svc-whatsapp", "microsserviço de mensagens WhatsApp: templates e janela de 24 h"),
    ("Migração Blip → Amazon Connect", "migração dos chatbots da Blip para o Amazon Connect (Lex e Contact Flows)"),
    ("GAIA", "framework da empresa que padroniza o uso de IA na esteira: etapas, portões e evidências"),
)
# (assunto, frase como seria dita, dias atrás) — o tipo sai da frase, como em assuntos.classificar
NOTAS = (
    ("svc-sms", "decidimos usar fila SQS com DLQ para o reenvio de SMS", 12),
    ("svc-sms", "nota: comando: make test roda a suíte do svc-sms", 5),
    ("svc-sms", "nota: armadilha: src/provedores/*.py não aceita número sem DDI", 4),
    ("svc-sms", "pendência: revisar o custo por provedor de SMS", 3),
    ("svc-notificacoes", "decidimos que o evento NotificacaoSolicitada v2 leva idempotency-key", 9),
    ("svc-notificacoes", "pendência: atualizar o runbook de reprocessamento", 2),
    ("svc-whatsapp", "decidimos versionar os templates aprovados no repositório", 6),
    ("svc-whatsapp", "pendência: medir a taxa de entrega fora da janela de 24 h", 1),
    ("Migração Blip → Amazon Connect", "decidimos migrar um bot por vez, começando pelo de segunda via de boleto", 7),
    ("Migração Blip → Amazon Connect", "nota: comando: aws connect list-contact-flows lista os fluxos", 3),
    ("Migração Blip → Amazon Connect", "pendência: inventariar os fluxos da Blip por bot", 2),
    ("Squad Comunicação", "decidimos fazer a daily às 9h15, 15 min, por assunto", 14),
    ("Squad Comunicação", "pendência: preparar a demo da sprint", 1),
    ("Tribo Atendimento", "nota: OKR do trimestre: reduzir o custo de comunicação em 15 %", 10),
    ("GAIA", "decidimos que toda PR gerada com IA leva o rótulo ia-assistida", 8),
    ("GAIA", "nota: etapas do GAIA: pedido, estudo, desenvolvimento, pr, merge", 8),
)
LINKS = (
    ("https://wiki.exemplo/squad-comunicacao/onboarding", "Onboarding da squad", "Squad Comunicação"),
    ("https://board.exemplo/comunicacao", "Board da squad", "Squad Comunicação"),
    ("https://wiki.exemplo/tribo-atendimento/okrs", "OKRs da tribo", "Tribo Atendimento"),
    ("https://git.exemplo/comunicacao/svc-sms", "Repositório svc-sms", "svc-sms"),
    ("https://grafana.exemplo/d/svc-sms", "Dashboard do svc-sms", "svc-sms"),
    ("https://git.exemplo/comunicacao/svc-notificacoes", "Repositório svc-notificacoes", "svc-notificacoes"),
    ("https://runbooks.exemplo/notificacoes/reprocessar", "Runbook de reprocessamento", "svc-notificacoes"),
    ("https://git.exemplo/comunicacao/svc-whatsapp", "Repositório svc-whatsapp", "svc-whatsapp"),
    ("https://docs.aws.amazon.com/connect/", "Documentação do Amazon Connect", "Migração Blip → Amazon Connect"),
    ("https://help.blip.ai/", "Ajuda da Blip", "Migração Blip → Amazon Connect"),
    ("https://wiki.exemplo/gaia", "Guia do GAIA", "GAIA"),
    ("https://wiki.exemplo/links-uteis", "Links úteis da empresa", ""),
)
# gasto do Cursor nos últimos 14 dias: (assunto, tipo, modelo, centavos) por dia, num ritmo que esgota antes do fim
GASTO_DIA = (("svc-sms", "bugfix", "claude-sonnet", 310), ("Migração Blip → Amazon Connect", "estudo", "gpt-5", 420),
             ("svc-notificacoes", "feature", "claude-sonnet", 260), ("svc-whatsapp", "refactor", "gpt-5-mini", 90))
GASTO_DIAS = 14
# o que cada etapa da esteira exige no GAIA (exemplo) e onde o loop já tem o portão (real)
GAIA = (
    ("pedido", "pedido registrado com dono, objetivo e critério de pronto", "caixa de entrada → item do roteiro com origem e evidência"),
    ("estudo", "contexto, riscos e alternativas antes de codar, com fontes", "Arquiteto estuda o item (estudo com fontes na web)"),
    ("desenvolvimento", "IA assistida com rastro dos prompts e das ferramentas", "Developer registra cada passo (fazendo, rastro)"),
    ("pr", "revisão humana, testes e rótulo ia-assistida", "portões pré-PR + resumo de impacto e risco no corpo do PR"),
    ("merge", "CI verde e evidência arquivada", "merge_gate com checks obrigatórios; rastro de ponta a ponta"),
)
DAILY_NOTAS = (
    ("svc-sms", ("- [x] troquei o provedor de fallback no ambiente de homologação", "- [ ] revisar o custo por provedor de SMS")),
    ("Migração Blip → Amazon Connect", ("- [x] exportei os fluxos do bot de segunda via", "- [ ] inventariar os fluxos da Blip por bot",
                                        "bloqueio: acesso ao console do Amazon Connect ainda não liberado")),
    ("Squad Comunicação", ("- [ ] preparar a demo da sprint",)),
)


class RegraLocal:
    """DecisionLayer mínimo para a tela: a regra de assuntos.py (sobreposição de palavras), sem Jev nem LLM."""
    source = "regra"

    def ask(self, qid, q, state):
        return assuntos.regra(self, qid, q, state)


def _data(dias_atras: int, agora: float) -> float:
    return agora - dias_atras * DIA


def semear(store, data_dir: Path, agora: float | None = None) -> dict:
    """Cria os dados de exemplo (uma vez; de novo só depois de `apagar`). Devolve o que criou."""
    agora = agora or time.time()
    if store.get(KV):
        return {"ja_semeado": True, **store.get(KV)}
    assuntos.preparar(store)
    por_nome = {a["nome"]: a["id"] for a in store.q("SELECT id, nome FROM assuntos")}
    ids = {"assuntos": [], "notas": [], "links": [], "em": agora}
    for nome, desc in ASSUNTOS:
        if nome not in por_nome:
            por_nome[nome] = assuntos.criar(store, nome, desc, agora=agora)
            ids["assuntos"].append(por_nome[nome])
    for nome, frase, dias in NOTAS:
        tipo, texto = assuntos.classificar(frase)
        ids["notas"].append(store.x("INSERT INTO assunto_notas(assunto_id, tipo, texto, origem, confianca, created_at) VALUES(?,?,?,?,?,?)",
                                    (por_nome[nome], tipo, texto, frase, 1.0, _data(dias, agora))))
    lk = Links(store)
    for url, rotulo, assunto in LINKS:
        if not store.one("SELECT 1 FROM catalogo_links WHERE url=?", (url,)):
            ids["links"].append(lk.guardar(url, rotulo, assunto)["id"])
    hoje = datetime.fromtimestamp(agora, TZ).date()
    for d in range(GASTO_DIAS):
        dia = hoje - timedelta(days=d)
        for i, (assunto, tipo, modelo, centavos) in enumerate(GASTO_DIA):
            if (d + i) % 3 == 2:                                     # nem cada assunto gasta a cada dia
                continue
            gasto_cursor.lancar(store, f"{centavos / 100:.2f}".replace(".", ","), assunto, tipo, modelo, centavos * 900,
                                dia, ORIGEM, f"{ORIGEM}:{dia.isoformat()}:{i}")
    ontem = (hoje - timedelta(days=1)).isoformat()
    for assunto, linhas in DAILY_NOTAS:
        p = Path(data_dir) / daily.PASTA / pastas.nome_da_pasta(assunto) / f"{ontem}-{ORIGEM}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"---\nassunto: {assunto}\n{ORIGEM}: 1\n---\n" + "\n".join(linhas) + "\n", encoding="utf-8")
    store.set("gaia_mapa", {"exemplo": True, "etapas": [{"etapa": e, "exige": x, "portao": p} for e, x, p in GAIA]})
    store.set(KV, ids)
    return ids


def apagar(store, data_dir: Path) -> dict:
    """Remove tudo que a semente criou (e só isso): o dado real que você já anotou fica."""
    ids = store.get(KV) or {}
    n = {"notas": 0, "links": 0, "assuntos": 0, "gastos": 0, "arquivos": 0}
    assuntos.preparar(store)
    for nid in ids.get("notas", []):
        n["notas"] += store.run("DELETE FROM assunto_notas WHERE id=?", (nid,))
    lk = Links(store)
    for lid in ids.get("links", []):
        r = store.one("SELECT * FROM catalogo_links WHERE id=?", (lid,))
        if r:
            if lk.fts:
                store.x("INSERT INTO catalogo_links_fts(catalogo_links_fts, rowid, rotulo, assunto, url) VALUES('delete', ?, ?, ?, ?)",
                        (lid, r["rotulo"], r["assunto"], r["url"]))
            n["links"] += store.run("DELETE FROM catalogo_links WHERE id=?", (lid,))
    for aid in ids.get("assuntos", []):
        if not store.one("SELECT 1 FROM assunto_notas WHERE assunto_id=?", (aid,)):     # com nota sua, o assunto fica
            n["assuntos"] += store.run("DELETE FROM assuntos WHERE id=?", (aid,))
    n["gastos"] = store.run("DELETE FROM gasto_cursor WHERE origem=?", (ORIGEM,))
    raiz = Path(data_dir) / daily.PASTA
    for p in (raiz.rglob(f"*-{ORIGEM}.md") if raiz.is_dir() else ()):
        p.unlink()
        n["arquivos"] += 1
    if (store.get("gaia_mapa") or {}).get("exemplo"):
        store.set("gaia_mapa", None)
    store.set(KV, None)
    return n


def anotar(store, frase: str, dl=None, agora: float | None = None) -> dict:
    """Anota pela tela: com o DecisionLayer do loop quando há; sem ele, a regra local escolhe o assunto."""
    return assuntos.anotar(store, dl or RegraLocal(), frase, agora=agora)


def _ultimos(store, tipo: str, n: int) -> list[dict]:
    return [assuntos._nota(r) for r in store.q(assuntos._SELECT + " WHERE n.tipo=? ORDER BY n.created_at DESC, n.id DESC LIMIT ?", (tipo, n))]


def _gasto_por(store, coluna: str, desde: date) -> list[dict]:
    return [{"nome": r["k"] or "sem etiqueta", "centavos": int(r["c"])} for r in
            store.q(f"SELECT {coluna} k, SUM(centavos) c FROM gasto_cursor WHERE dia>=? GROUP BY {coluna} ORDER BY c DESC LIMIT 8",
                    (desde.isoformat(),))]


def visao(store, data_dir: Path, agora: float | None = None) -> dict:
    """Tudo que a tela mostra, em uma chamada."""
    agora = agora or time.time()
    assuntos.preparar(store)
    lista = [dict(r) for r in store.q(
        "SELECT a.id, a.nome, a.descricao, "
        "COALESCE(SUM(n.tipo='decisao'),0) decisoes, COALESCE(SUM(n.tipo='pendencia'),0) pendencias, "
        "COALESCE(SUM(n.tipo IN ('nota','link')),0) notas, MAX(n.created_at) ultima "
        "FROM assuntos a LEFT JOIN assunto_notas n ON n.assunto_id=a.id GROUP BY a.id ORDER BY a.nome")]
    lk = Links(store)
    for a in lista:
        a["links"] = int(store.one("SELECT COUNT(*) n FROM catalogo_links WHERE assunto=?", (a["nome"],))["n"])
        a["ultima"] = assuntos._data(a["ultima"]) if a["ultima"] else None
    hoje = datetime.fromtimestamp(agora, TZ).date()
    proj = gasto_cursor.projecao(store, hoje)
    mais_notas = max(lista, key=lambda a: a["decisoes"] + a["notas"], default=None)
    contexto = {"assunto": mais_notas["nome"], "arquivos": contexto_cursor.gerar(store, mais_notas["nome"])} if mais_notas else None
    return {
        "exemplo": bool(store.get(KV)), "assuntos": lista,
        "pendencias": _ultimos(store, "pendencia", 12), "decisoes": _ultimos(store, "decisao", 8),
        "daily": daily.pauta(data_dir, agora) if (Path(data_dir) / daily.PASTA).is_dir() else [],
        "orcamento": {**proj, "texto": gasto_cursor.resumo(proj), "por_assunto": _gasto_por(store, "assunto", hoje.replace(day=1)),
                      "por_tipo": _gasto_por(store, "tipo", hoje.replace(day=1))},
        "links": {"total": int(store.one("SELECT COUNT(*) n FROM catalogo_links")["n"]), "graft": lk.graft, "fts": lk.fts,
                  "recentes": [lk._linha(r) for r in store.q("SELECT * FROM catalogo_links ORDER BY updated_at DESC LIMIT 12")]},
        "contexto": contexto, "gaia": store.get("gaia_mapa") or {"exemplo": False, "etapas": []},
        "pastas": str(pastas.raiz(data_dir)), "notas_pasta": str(Path(data_dir) / daily.PASTA),
    }


def api_get(store, data_dir: Path, caminho: str, q: dict) -> dict | None:
    """As rotas GET da tela (None = não é daqui)."""
    def um(k):
        return (q.get(k) or [""])[0]
    if caminho == "/api/trabalho":
        return visao(store, data_dir)
    if caminho == "/api/trabalho/perguntar":
        notas = assuntos.perguntar(store, um("q")[:300])
        return {"notas": notas, "texto": assuntos.responder(notas)}
    if caminho == "/api/trabalho/contexto":
        try:
            return {"assunto": um("assunto"), "arquivos": contexto_cursor.gerar(store, um("assunto") or None)}
        except ValueError as e:
            return {"erro": str(e)}
    return None


def api_post(store, data_dir: Path, caminho: str, data: dict, dl=None) -> tuple[dict, int] | None:
    """As rotas POST da tela: (resposta, status); None = não é daqui."""
    try:
        if caminho == "/api/trabalho/anotar":
            return {"ok": True, "nota": anotar(store, str(data.get("texto", ""))[:MAX_FRASE], dl)}, 200
        if caminho == "/api/trabalho/assunto":
            nome = " ".join(str(data.get("nome", "")).split())[:80]
            if len(nome) < 2:
                return {"erro": "falta o nome do assunto"}, 400
            aid = assuntos.criar(store, nome, str(data.get("descricao", ""))[:300])
            return {"ok": True, "id": aid}, 200
        if caminho == "/api/trabalho/exemplo":
            acao = data.get("acao")
            if acao == "semear":
                return {"ok": True, "semeado": semear(store, data_dir)}, 200
            if acao == "apagar":
                return {"ok": True, "apagado": apagar(store, data_dir)}, 200
            return {"erro": "ação: semear ou apagar"}, 400
    except ValueError as e:
        return {"erro": str(e)}, 400
    return None

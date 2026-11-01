"""Conselho de perguntas: a autoevolução do loop parte de PERGUNTAS, feitas por quem tem o olhar certo.

"Como usuário, qual componente devo melhorar para facilitar ver as métricas no painel?" é uma pergunta que só alguém
no papel do usuário faria. Por isso o loop tem um conselho de perspectivas (personas), cada uma com o seu objetivo e
as suas perguntas:
  usuário · economista · operador (SRE) · cientista · arquiteto · auditor · cético · financeiro (família)

Economia primeiro: gerar e priorizar perguntas NÃO gasta LLM.
1. Cada pergunta tem um sinal calculado por SQL nos dados do próprio loop (quanto aquilo dói agora) e a evidência
   que a sustenta. Pergunta sem sinal não entra.
2. Prioridade = relevância × peso aprendido da persona × diversidade (persona usada há pouco perde força)
   ÷ custo estimado. O Jev escolhe entre as 3 melhores; a regra decide quando ele está em dúvida.
3. Só a pergunta escolhida vai para a LLM (o planejador), que responde com UM item pequeno e mensurável. O item
   ainda passa pelo estudo, pelo Developer e por todos os portões.
4. As perguntas também evoluem: cada persona tem um placar (Beta) do que suas perguntas viraram. Item entregue
   (PR mergeado) soma; item contestado pelo estudo ou repetido subtrai. Quem pergunta melhor pergunta mais.
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable

from . import financeiro, jobs, jtbd, pedido_claro, pedidos_repetidos
from .curador_licoes import sem_checagem
from .custo import tokens_com_e_sem_pr, tokens_por_desfecho, tokens_por_veredito
from .decision import Question
from .higiene import licoes_de_telemetria
from .json_llm import objeto
from .licoes import item_de

DIVERSIDADE = 0.35        # a persona das últimas 3 perguntas pesa só isso (o conselho não fica preso num olhar só)
# 27/10: a mesma chave (pm:fracao_produto) foi entregue 7 vezes em 2 dias — 7 PRs de "resumo semanal" quase iguais, e a
# métrica não mexeu. Entregue não é resolvido: a chave descansa DESCANSO depois de cada entrega e, com INSISTENCIA
# entregas em JANELA_INSISTENCIA sem a dor cair, está esgotada — o conselho para de repetir e avisa uma vez.
DESCANSO = 3 * 86400
INSISTENCIA = 2
JANELA_INSISTENCIA = 14 * 86400


@dataclass
class Pergunta:
    id: str
    persona: str
    texto: str
    relevancia: float                     # 0..1: quanto aquilo dói agora, medido nos dados
    evidencia: dict = field(default_factory=dict)
    custo: float = 1.0                    # custo relativo de responder (1 = um item pequeno)
    score: float = 0.0
    eixo: str | None = None               # "produto" nas perguntas do Norte: o item que nasce delas conta como produto


PERSONAS = {
    "usuario": "Usuário (o Cássio olhando o painel): entender rápido, confiar, não precisar perguntar",
    "economista": "Economista: menos tokens e menos LLM por resultado entregue",
    "operador": "Operador (SRE): o loop não trava, não fica cego, se recupera sozinho",
    "cientista": "Cientista: toda mudança precisa provar que melhorou alguma coisa",
    "arquiteto": "Arquiteto: menos retrabalho, código mais simples onde mais quebra",
    "auditor": "Auditor: guardrail que nunca foi exercitado pode estar quebrado sem ninguém saber",
    "cetico": "Cético: que indicador diz 'tudo bem' e pode estar mentindo",
    "financeiro": "Financeiro da família: o cérebro financeiro só aprende com dados reais",
    # o Norte (norte.py): o loop é uma fábrica de software para uma equipe de engenharia — quem pede por essa equipe
    "tech_lead": "Tech lead da equipe: um pedido vira PR revisado, com testes, em horas; o console mostra em 10 s o que trava",
    "pm": "PM do produto: o que o time ganha a cada semana precisa ser visível, pedido por alguém e medido no uso",
    "mercado": "Mercado: o que as melhores fábricas de software com IA já fazem e o loop ainda não (com fontes)",
}


def _um(s, sql, args=()):
    r = s.one(sql, args)
    return (r[0] if r is not None else 0) or 0


# ------------------------------------------------------------------ sinais (SQL barato, sem LLM)

def _usuario(s, agora) -> list[Pergunta]:
    out = []
    pedidos = s.q("SELECT titulo FROM roadmap WHERE origem='pedido_cassio' AND created_at>=? "
                  "AND (titulo LIKE '%dash%' OR titulo LIKE '%painel%' OR titulo LIKE '%visualiz%')", (agora - 7 * 86400,))
    falhas_painel = _um(s, "SELECT COUNT(*) FROM verificacoes WHERE ponto LIKE 'painel:%' AND ok=0 AND created_at>=?", (agora - 86400,))
    if pedidos or falhas_painel:
        out.append(Pergunta("usuario:painel_metricas", "usuario",
                            "Como usuário, qual componente do painel devo melhorar para facilitar a visualização das métricas?",
                            min(1.0, 0.3 * len(pedidos) + 0.2 * falhas_painel),
                            {"pedidos_recentes_sobre_painel": [p["titulo"][:80] for p in pedidos][:5], "falhas_painel_24h": falhas_painel}))
    contestados = _um(s, "SELECT COUNT(*) FROM roadmap WHERE status='contestado'")
    if contestados:
        out.append(Pergunta("usuario:contestados", "usuario",
                            "Como usuário, o loop me explica bem por que contestou meus pedidos, com as fontes à vista?",
                            min(1.0, 0.25 * contestados), {"pedidos_contestados": contestados}))
    return out


def _economista(s, agora) -> list[Pergunta]:
    out = []
    papeis = s.q("SELECT papel, SUM(tokens) t, COUNT(*) n FROM llm_calls WHERE created_at>=? GROUP BY papel ORDER BY t DESC",
                 (agora - 86400,))
    total = sum(int(p["t"] or 0) for p in papeis)
    entregues = _um(s, "SELECT COUNT(DISTINCT pr) FROM merges WHERE merged=1 AND created_at>=?", (agora - 86400,))
    if papeis and total:
        maior = papeis[0]
        dev = tokens_por_desfecho(s.q("SELECT entrada, tokens FROM llm_calls WHERE papel='developer' AND created_at>=?",
                                      (agora - 7 * 86400,)), s.q("SELECT titulo, status, evidencia FROM roadmap"))
        out.append(Pergunta("economista:etapa_cara", "economista",
                            f"Qual é o jeito mais barato de obter o mesmo resultado na etapa que mais gasta ({maior['papel']})?",
                            min(1.0, int(maior["t"] or 0) / max(total, 1)),
                            {"tokens_24h_por_papel": {p["papel"]: int(p["t"] or 0) for p in papeis},
                             "prs_entregues_24h": entregues, "tokens_por_pr": int(total / max(entregues, 1)),
                             "developer_tokens_7d_por_desfecho": dev["por_desfecho"],
                             "tokens_sem_pr_pct": dev["tokens_sem_pr_pct"], "top_causas_sem_pr": dev["top_causas"]}))
    n = _um(s, "SELECT COUNT(*) FROM decisions WHERE created_at>=?", (agora - 86400,))
    regra = _um(s, "SELECT COUNT(*) FROM decisions WHERE created_at>=? AND source='local'", (agora - 86400,))
    if n and regra / n > 0.15:
        out.append(Pergunta("economista:jev_sozinho", "economista",
                            "Onde a regra ainda decide no lugar do Jev, e o que falta para o Jev decidir sozinho com confiança?",
                            min(1.0, regra / n), {"decisoes_24h": n, "pela_regra": regra}))
    return out


def _top_causa(s, ponto, desde) -> dict:
    r = s.one("SELECT causa FROM verificacoes WHERE ponto=? AND ok=0 AND created_at>=? AND causa IS NOT NULL "
              "GROUP BY causa ORDER BY COUNT(*) DESC, MAX(id) DESC LIMIT 1", (ponto, desde))
    return {"top_causa": r["causa"]} if r else {}


def _operador(s, agora) -> list[Pergunta]:
    out = []
    pontos = s.q("SELECT ponto, COUNT(*) n, SUM(ok=0) f FROM verificacoes WHERE created_at>=? GROUP BY ponto "
                 "HAVING f > 0 ORDER BY f*1.0/n DESC LIMIT 3", (agora - 86400,))
    if pontos:
        p = pontos[0]
        com_causa = [dict(x) | _top_causa(s, x["ponto"], agora - 86400) for x in pontos]
        causa = com_causa[0].get("top_causa")
        out.append(Pergunta("operador:neuronio_que_mais_barra", "operador",
                            f"Por que o neurônio {p['ponto']} é barrado tanto" + (f" (causa que mais se repete: {causa})" if causa else "") +
                            ", e o que evitaria a falha antes de ela acontecer?",
                            min(1.0, (p["f"] or 0) / max(p["n"], 1) + 0.1),
                            {"pontos_com_falha_24h": com_causa}))
    lead = s.q("SELECT r.created_at c, MIN(m.created_at) m FROM roadmap r JOIN prs p ON p.titulo=r.titulo "
               "JOIN merges m ON m.pr=p.number AND m.merged=1 WHERE r.created_at>=? GROUP BY r.id", (agora - 7 * 86400,))
    if lead:
        horas = sorted((x["m"] - x["c"]) / 3600 for x in lead if x["m"] and x["c"])
        if horas and horas[len(horas) // 2] > 1:
            out.append(Pergunta("operador:lead_time", "operador",
                                "Onde o pedido mais espera entre chegar e entrar na main, e como encurtar isso sem pular portão?",
                                min(1.0, horas[len(horas) // 2] / 12), {"mediana_horas_pedido_ate_merge": round(horas[len(horas) // 2], 1)}))
    return out


def _cientista(s, agora) -> list[Pergunta]:
    out = []
    mergeados = _um(s, "SELECT COUNT(DISTINCT pr) FROM merges WHERE merged=1 AND created_at>=?", (agora - 7 * 86400,))
    com_metrica = _um(s, "SELECT COUNT(*) FROM roadmap WHERE status='feito' AND updated_at>=? AND detalhe LIKE '%Sucesso:%'",
                      (agora - 7 * 86400,))
    if mergeados:
        out.append(Pergunta("cientista:prova_de_melhora", "cientista",
                            "Das mudanças entregues, quais têm prova medida de que melhoraram algo, e como medir as que não têm?",
                            min(1.0, 0.2 + max(0, mergeados - com_metrica) / max(mergeados, 1) * 0.8),
                            {"prs_mergeados_7d": mergeados, "itens_com_criterio_de_sucesso": com_metrica}))
    return out


def _arquiteto(s, agora) -> list[Pergunta]:
    out = []
    falhas = s.q("SELECT item_id, sujeito, tick, COUNT(*) n FROM verificacoes WHERE ponto LIKE 'developer:%' AND ok=0 "
                 "AND created_at>=? GROUP BY item_id, sujeito, tick", (agora - 7 * 86400,))
    execucoes, linhas = defaultdict(set), Counter()   # n = execuções (ticks) distintas; uma execução grava várias linhas
    for f in falhas:   # registro antigo, sem item gravado: o sujeito só resolve o item na leitura
        k = f["item_id"] if f["item_id"] is not None else item_de(s, f["sujeito"])[0]
        execucoes[k].add(f["tick"])
        linhas[k] += f["n"]
    por_item = Counter({k: len(t) for k, t in execucoes.items()})
    retrabalho = [{"item": k, "titulo": item_de(s, item_id=k)[1] or f"roteiro #{k}", "n": n, "linhas": linhas[k]}
                  if k is not None else {"item": "sem_item", "titulo": "sem_item", "n": n, "linhas": linhas[k]}
                  for k, n in por_item.most_common(3)]
    if retrabalho and retrabalho[0]["n"] >= 2:
        out.append(Pergunta("arquiteto:retrabalho", "arquiteto",
                            "Qual parte do código mais faz o Developer errar e refazer, e como simplificá-la?",
                            min(1.0, retrabalho[0]["n"] / 6), {"itens_com_mais_falhas_locais": retrabalho}))
    return out


def _auditor(s, agora) -> list[Pergunta]:
    out = []
    from .canario import com_canario, portoes_sem_prova
    nunca = portoes_sem_prova(s, agora)    # portão aprendido com canário verde já provou que recusa a própria lição
    provados = com_canario(s, agora)       # ponto com canário verde já provou, com falha injetada, que ainda barra
    sem_falha = [r["ponto"] for r in s.q("SELECT ponto FROM verificacoes GROUP BY ponto HAVING SUM(ok=0)=0 AND COUNT(*) > 50")
                 if r["ponto"] not in provados]
    if nunca or sem_falha:
        out.append(Pergunta("auditor:guardrail_nao_exercitado", "auditor",
                            "Qual guardrail nunca barrou nada, e como provar com um teste que ele ainda funciona?",
                            min(1.0, 0.15 + 0.1 * nunca + 0.05 * len(sem_falha)),
                            {"portoes_aprendidos_que_nunca_barraram": nunca, "pontos_que_nunca_falharam": sem_falha[:8]}))
    return out


def _cetico(s, agora) -> list[Pergunta]:
    out = []
    estag = _um(s, "SELECT COUNT(*) FROM verificacoes WHERE ponto='loop:progresso' AND ok=0")
    estrut = _um(s, "SELECT COUNT(*) FROM licoes WHERE classe='estrutural'")
    if estag or estrut:
        out.append(Pergunta("cetico:indicador_mentiroso", "cetico",
                            "Que indicador do painel diz 'tudo bem' e pode estar mentindo, e como cruzá-lo com outro dado?",
                            min(1.0, 0.2 + 0.2 * estag + 0.05 * estrut), {"estagnacoes": estag, "licoes_de_estrutura": estrut}))
    return out


def _financeiro(s, agora) -> list[Pergunta]:
    lanc = _um(s, "SELECT COUNT(*) FROM ledger")
    if lanc < 30:
        return [Pergunta("financeiro:dados", "financeiro",
                         "O que falta para o cérebro financeiro ter dados reais da família sem trabalho manual do Cássio?",
                         0.9 if lanc == 0 else 0.5, {"lancamentos": lanc, "politica_financeira_versao": _um(
                             s, "SELECT MAX(version) FROM policy_versions WHERE status='active'")}, custo=1.5)]
    return []


def _norte(s, agora) -> list[Pergunta]:
    """Tech lead e PM perguntam contra o Norte: cada resultado longe da meta vira uma pergunta com a medição."""
    from .norte import medir
    m = medir(s, agora)
    r = m.pop("_resumo")
    out = []
    lt = m["lead_time_h"]
    if lt["distancia"] > 0:
        out.append(Pergunta("tech_lead:lead_time", "tech_lead",
                            f"Como tech lead, o que falta para um pedido virar PR revisado e mergeado em menos de {lt['meta']:.0f} h? "
                            f"(mediana hoje: {lt['valor'] if lt['valor'] is not None else 'sem PR em 7 dias'} h; em que etapa o tempo some?)",
                            min(1.0, 0.4 + 0.6 * lt["distancia"]), {"norte": "lead_time_h", **lt, "prs_7d": r["prs_7d"]}, eixo="produto"))
    fp = m["fracao_produto"]
    if fp["distancia"] > 0:
        out.append(Pergunta("pm:fracao_produto", "pm",
                            f"Como PM, qual funcionalidade uma equipe de engenharia usaria já na próxima semana e o loop ainda não tem? "
                            f"(só {r['produto_7d']} de {r['prs_7d']} PRs em 7 dias foram produto; meta {fp['meta']:.0%})",
                            min(1.0, 0.5 + 0.5 * fp["distancia"]), {"norte": "fracao_produto", **fp}, custo=1.5, eixo="produto"))
    cs = m["console_semana"]
    recusas = _um(s, "SELECT COUNT(*) FROM revisoes WHERE created_at>=?", (agora - 86400,))
    if cs["distancia"] > 0:
        out.append(Pergunta("tech_lead:console", "tech_lead",
                            "Como tech lead, o que na Equipe ao vivo ou no painel me faria entender em 10 segundos por que um PR foi "
                            f"recusado ou um item parou, sem abrir o GitHub? (o console não mudou em 7 dias; {recusas} recusa(s) do gate em 24 h)",
                            min(1.0, 0.4 + 0.3 * cs["distancia"] + min(0.3, 0.05 * recusas)), {"norte": "console_semana", **cs, "recusas_24h": recusas}, eixo="produto"))
    ms = m["merge_sem_conserto"]
    if ms["valor"] is not None and ms["distancia"] > 0:
        out.append(Pergunta("tech_lead:primeira_tentativa", "tech_lead",
                            f"Como tech lead, por que só {ms['valor']:.0%} dos PRs entram na primeira tentativa (meta {ms['meta']:.0%}): "
                            "o que o Developer deveria conferir antes de abrir o PR que o gate confere depois?",
                            min(1.0, 0.3 + 0.7 * ms["distancia"]), {"norte": "merge_sem_conserto", **ms}, eixo="produto"))
    return out


def _mercado(s, agora) -> list[Pergunta]:
    """O que a pesquisa de mercado semanal (norte_mercado.pesquisar) deixou: perguntas com fontes, cada uma uma vez."""
    pesq = s.get("mercado_pesquisa") or {}
    out = []
    for i, p in enumerate((pesq.get("perguntas") or [])[:4]):
        if not p.get("texto"):
            continue
        out.append(Pergunta(f"mercado:{pesq.get('em', 0):.0f}:{i}", "mercado", p["texto"][:300], float(p.get("relevancia", 0.6)),
                            {"fontes": p.get("fontes", [])[:4], "pratica": p.get("pratica", "")[:200], "pesquisado_em": pesq.get("em")}, custo=1.5, eixo="produto"))
    return out


NORTE_PERSONAS = ("tech_lead", "pm", "mercado")
# 31/10: a fila nunca fica vazia. Em 280 giros o Developer trabalhou em 12: a única fonte de itens era o conselho, e o
# Jev descartava 94 % das perguntas. Os épicos são a direção de produto em pedaços (kv `norte_epicos` sobrescreve):
# cada um vira uma pergunta do PM com eixo produto sempre que não há item de produto pendente. Descanso e "esgotada"
# valem para eles como para qualquer chave; o Jev só veta.
EPICOS = (
    ("meu_trabalho_daily", "Como PM, o que falta para a pauta da daily (tela Meu trabalho) nascer das pendências e decisões anotadas no "
                           "banco, e não só dos arquivos em notas/?"),
    ("meu_trabalho_cursor", "Como PM, como o engenheiro importa o CSV real de uso do Cursor pela tela Meu trabalho e vê o gasto por "
                            "assunto sem a linha de comando?"),
    ("meu_trabalho_jev", "Como PM, como a nota ambígua (regra local não sabe o assunto) vai ao Jev e volta arquivada, em vez de ser recusada?"),
    ("meu_trabalho_graft", "Como PM, como 'o que decidimos sobre X?' usa o Graft por significado quando a palavra não bate, com a fonte?"),
    ("fabrica_segundo_repo", "Como tech lead, o que falta para `circulo init` num segundo repositório (Python ou .NET) receber um pedido e "
                             "entregar um PR com testes, sem tocar o código do loop?"),
    ("fabrica_pedido_pr", "Como tech lead, como um pedido em uma frase vira PR com critério de aceite verificável no corpo e o "
                          "resultado do critério no merge?"),
    ("fabrica_console", "Como tech lead, o que na Equipe ao vivo me diz em 10 s o que cada agente está fazendo por um pedido meu e onde parou?"),
    ("fabrica_harness", "Como tech lead, como o loop gera e mantém AGENTS.md/regras do Cursor de um repositório cliente a partir das "
                        "lições dele, por PR?"),
    ("fabrica_gaia", "Como tech lead, como as etapas de governança (GAIA) viram portões configuráveis por repositório, com evidência "
                     "guardada por etapa?"),
    ("meu_trabalho_links", "Como PM, como os links guardados aparecem agrupados por assunto na tela Meu trabalho, com busca por "
                           "significado e atalho para guardar?"),
)


def _epicos(s, agora) -> list[Pergunta]:
    """Fila nunca vazia: sem item de produto pendente, cada épico vira uma pergunta do PM com eixo produto."""
    pend = _um(s, "SELECT COUNT(*) FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 AND (origem='pedido_cassio' "
                  "OR EXISTS (SELECT 1 FROM perguntas p WHERE p.item_id=roadmap.id AND p.eixo IN ('produto','missao')))")
    if pend:
        return []
    epicos = s.get("norte_epicos") or [{"chave": c, "texto": x} for c, x in EPICOS]
    return [Pergunta(f"epico:{e['chave']}", "pm", str(e["texto"])[:400], float(e.get("relevancia", 0.7)),
                     {"epico": e["chave"], "base": "medido", "fila_de_produto": 0}, eixo="produto") for e in epicos if e.get("texto")]


SINAIS: list[Callable] = [_usuario, _economista, _operador, _cientista, _arquiteto, _auditor, _cetico, _financeiro, _norte, _mercado, _epicos]


# ------------------------------------------------------------------ o conselho

class Conselho:
    def __init__(self, ctx):
        self.ctx = ctx
        self.s = ctx.store

    def pesos(self) -> dict[str, float]:
        """Placar de cada persona: média Beta(1+entregues, 1+ruins) do que as perguntas dela viraram."""
        out = {}
        for p in personas(self.s):
            r = self.s.one("SELECT SUM(status='entregue') e, SUM(status IN ('contestada','repetida','descartada')) m "
                           "FROM perguntas WHERE persona=? AND COALESCE(cerebro,'loop')='loop'", (p,))
            e, m = int(r["e"] or 0), int(r["m"] or 0)
            out[p] = round((1 + e) / (2 + e + m) * 2, 3)        # 1.0 = neutro; >1 pergunta bem; <1 pergunta mal
        return out

    def candidatas(self) -> list[Pergunta]:
        agora = time.time()
        recentes = [r["persona"] for r in self.s.q("SELECT persona FROM perguntas WHERE COALESCE(cerebro,'loop')='loop' "
                                                   "ORDER BY id DESC LIMIT 3")]
        abertas = {r["chave"] for r in self.s.q("SELECT chave FROM perguntas WHERE status IN ('feita','virou_item') "
                                                "AND created_at>=?", (agora - 3 * 86400,))}
        abertas |= {r["chave"] for r in self.s.q("SELECT chave FROM perguntas WHERE status='entregue' AND updated_at>=?",
                                                 (agora - DESCANSO,))}                          # entregue há pouco: descansa
        pesos = self.pesos()
        out = []
        for sinal in SINAIS:
            try:
                ps = sinal(self.s, agora)
            except Exception:  # um sinal quebrado não cala o conselho
                continue
            for p in ps:
                if p.relevancia <= 0.05 or p.id in abertas or self.esgotada(p, agora):   # sem dor, em andamento ou insistindo
                    continue
                div = DIVERSIDADE if p.persona in recentes else 1.0
                p.score = round(p.relevancia * pesos.get(p.persona, 1.0) * div / max(p.custo, 0.1), 4)
                out.append(p)
        return sorted(out, key=lambda p: -p.score)

    def esgotada(self, p: Pergunta, agora: float) -> bool:
        """A chave já virou INSISTENCIA entregas em JANELA_INSISTENCIA e a dor (relevância) não caiu: repetir não resolve.
        Avisa uma vez por chave (kv `perguntas_esgotadas`) e deixa a decisão para quem muda o desenho."""
        rs = self.s.q("SELECT relevancia FROM perguntas WHERE chave=? AND status='entregue' AND updated_at>=? ORDER BY id",
                      (p.id, agora - JANELA_INSISTENCIA))
        if len(rs) < INSISTENCIA or p.relevancia < float(rs[0]["relevancia"] or 0) - 0.1:
            return False
        avisadas = self.s.get("perguntas_esgotadas") or {}
        if p.id not in avisadas:
            avisadas[p.id] = {"em": agora, "entregas": len(rs), "relevancia": p.relevancia}
            self.s.set("perguntas_esgotadas", avisadas)
            self.ctx.reply(f"Conselho: a pergunta “{p.texto[:90]}” já virou {len(rs)} entregas em 14 dias e a dor não caiu "
                           f"({p.relevancia:.2f}). Parei de repeti-la: a resposta não está em mais um item igual, está no desenho.", "saude")
        return True

    def escolher(self) -> Pergunta | None:
        """A regra estreita para as 3 melhores; o Jev escolhe entre elas (sem LLM)."""
        top = self.candidatas()[:3]
        if not top:
            return None
        if len(top) == 1:
            return top[0]
        d = self.ctx.dl.ask("pergunta_evolucao", Question(
            "choice", "Qual destas perguntas, respondida agora, mais ajuda o objetivo do loop pelo menor custo?",
            {p.id: p.texto for p in top}), {"candidatas": {p.id: {"persona": p.persona, "score": p.score,
                                                                   "relevancia": p.relevancia, "custo": p.custo}
                                                           for p in top}})
        return next((p for p in top if p.id == d.value), top[0])

    def registrar(self, p: Pergunta) -> int:
        agora = time.time()
        return self.s.x("INSERT INTO perguntas(chave,persona,texto,relevancia,score,evidencia,status,cerebro,eixo,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,'feita','loop',?,?,?)",
                        (p.id, p.persona, p.texto, p.relevancia, p.score, json.dumps(p.evidencia, ensure_ascii=False, default=str),
                         p.eixo, agora, agora))

    def marcar(self, pid: int, status: str, item_id: int | None = None) -> None:
        self.s.x("UPDATE perguntas SET status=?, item_id=COALESCE(?, item_id), updated_at=? WHERE id=?",
                 (status, item_id, time.time(), pid))

    def acompanhar(self) -> int:
        """Fecha o placar: o item da pergunta foi entregue (feito) ou contestado pelo estudo."""
        n = 0
        for r in self.s.q("SELECT p.id, r.status FROM perguntas p JOIN roadmap r ON r.id=p.item_id WHERE p.status='virou_item'"):
            novo = {"feito": "entregue", "contestado": "contestada"}.get(r["status"])
            if novo:
                self.marcar(r["id"], novo)
                n += 1
        return n

    def resumo(self, limite: int = 8) -> dict:
        return {"pesos": self.pesos(),
                "ultimas": [dict(r) for r in self.s.q("SELECT id, persona, texto, status, item_id, score, created_at FROM perguntas "
                                                      "ORDER BY id DESC LIMIT ?", (limite,))],
                "candidatas": [{"persona": p.persona, "texto": p.texto, "score": p.score} for p in self.candidatas()[:5]]}


# ------------------------------------------------------------------ perguntas que o próprio conselho inventa
# As perguntas acima são a SEMENTE. O loop gera perguntas novas (e perspectivas novas) com a LLM barata, no máximo
# 1 vez por dia, mas presas a um CATÁLOGO DE MÉTRICAS: toda pergunta gerada aponta para uma métrica medida por SQL,
# então continua sendo priorizada sem LLM, pelo tamanho da dor. Pergunta gerada que só rende item contestado,
# repetido ou sem item é desativada sozinha.

def _m_falha_neuronio(s, agora):
    from .registro import tokens_retry
    from .vigia import causas_por_classe
    r = s.one("SELECT ponto, COUNT(*) n, SUM(ok=0) f FROM verificacoes WHERE created_at>=? GROUP BY ponto HAVING f>0 "
              "ORDER BY f*1.0/n DESC LIMIT 1", (agora - 86400,))
    if not r:
        return (0.0, {})
    causas = causas_por_classe(f"{v['motivo'] or ''} {v['causa'] or ''}" for v in s.q(
        "SELECT motivo, causa FROM verificacoes WHERE ponto=? AND ok=0 AND created_at>=?", (r["ponto"], agora - 86400)))
    return (min(1.0, (r["f"] or 0) / max(r["n"], 1) + 0.1),
            {"ponto": r["ponto"], "falhas": r["f"], "total": r["n"], "causas": causas,
             "fracao_transitoria": round(causas["transitoria"] / r["f"], 2),
             "fracao_deterministica": round(causas["deterministica"] / r["f"], 2), "tokens_retry_7d": tokens_retry(s)})


def _m_tokens_por_pr(s, agora):
    t = _um(s, "SELECT SUM(tokens) FROM llm_calls WHERE created_at>=?", (agora - 86400,))
    prs = _um(s, "SELECT COUNT(DISTINCT pr) FROM merges WHERE merged=1 AND created_at>=?", (agora - 86400,))
    v = tokens_por_veredito(s.q("SELECT entrada, tokens FROM llm_calls WHERE papel='developer' AND created_at>=?",
                                (agora - 86400,)), pedido_claro.itens_com_veredito(s))
    p = tokens_com_e_sem_pr(s.q("SELECT papel, entrada, tokens, ok FROM llm_calls WHERE created_at>=?", (agora - 86400,)),
                            pedido_claro.itens_com_veredito(s))
    return (min(1.0, t / max(prs, 1) / 100_000), {"tokens_24h": t, "prs_24h": prs, **v, **p})


def _m_regra_decide(s, agora):
    n = _um(s, "SELECT COUNT(*) FROM decisions WHERE created_at>=?", (agora - 86400,))
    r = _um(s, "SELECT COUNT(*) FROM decisions WHERE created_at>=? AND source='local'", (agora - 86400,))
    return (r / n if n else 0.0, {"decisoes": n, "pela_regra": r})


def _m_recusas_gasto(s, agora):
    rec = (s.get("progresso") or {}).get("recusas") or {}
    return (min(1.0, sum(rec.values()) / 10), {"recusas": rec})


def _m_conflitos_pr(s, agora):
    n = _um(s, "SELECT COUNT(*) FROM merges WHERE reason LIKE 'conflito%' AND created_at>=?", (agora - 7 * 86400,))
    prs: dict[str, set] = {}             # arquivo → PRs que conflitaram nele (git merge-tree, gravado pelo revisor)
    for r in s.q("SELECT de, detalhe FROM elos WHERE relacao='conflito_main' AND em>=?", (agora - 7 * 86400,)):
        for a in json.loads(r["detalhe"] or "{}").get("arquivos", []):
            prs.setdefault(a, set()).add(r["de"])
    por_arquivo = {a: len(p) for a, p in sorted(prs.items(), key=lambda kv: -len(kv[1]))}
    return (min(1.0, n / 3), {"conflitos_7d": n, "arquivos_7d": por_arquivo,
                              "repetidos": [a for a, k in por_arquivo.items() if k >= 2]})


def _m_licoes_abertas(s, agora):
    n = _um(s, "SELECT COUNT(*) FROM licoes WHERE status IN ('aberta','reincidente','sem_prevencao')")
    sombra = s.get("curador_silencio") or {}           # gravado pelo curador a cada giro
    return (min(1.0, n / 6), {"licoes_abertas": n, "licoes_telemetria": len(licoes_de_telemetria(s)),
                              "licoes_elegiveis_silencio": sombra.get("licoes_elegiveis_silencio"),
                              "ultima_ocorrencia": sombra.get("elegiveis"), "sem_checagem": sem_checagem(s)})


def _m_lancamentos(s, agora):
    p = financeiro.prontidao(s)
    n = p["reais"]
    return (1.0 if n == 0 else max(0.0, 1 - n / p["minimo_lancamentos"]),
            {"lancamentos": _um(s, "SELECT COUNT(*) FROM ledger"), **p})


def _m_pedidos_humano(s, agora):
    n = _um(s, "SELECT COUNT(*) FROM roadmap WHERE origem='pedido_cassio' AND created_at>=?", (agora - 7 * 86400,))
    d, diag = jobs.medir_propostas(s, agora), jtbd.diagnostico(s, agora)
    motivo = "" if d.total else diag["motivo_sem_proposta"]
    return (min(1.0, n / 4), {"pedidos_7d": n, "repeticoes_7d": pedidos_repetidos.repeticoes_7d(s, agora),
                              "antecipacao": {"propostas": d.total, "taxa": d.taxa, **d.contagem,
                                                               "pedidos_depois": d.pedidos_depois,
                                                               "job_maior_grupo": diag["job_maior_grupo"],
                                                               "motivo_sem_proposta": motivo}})


def _m_estagnacao(s, agora):
    from .vigia import disparos_30d, resultado_30d
    sem = int((s.get("progresso") or {}).get("sem", 0))
    return (min(1.0, sem / 10), {"giros_sem_avanco": sem, "disparos_30d": disparos_30d(s, "estagnacao", agora),
                                 "resultado_30d": resultado_30d(s, "estagnacao", agora)})


METRICAS: dict[str, tuple[str, Callable]] = {
    "falha_neuronio": ("taxa de falha do neurônio que mais falha nas últimas 24 h", _m_falha_neuronio),
    "tokens_por_pr": ("tokens de LLM por PR entregue nas últimas 24 h", _m_tokens_por_pr),
    "regra_decide": ("fração das decisões tomadas pela regra no lugar do Jev", _m_regra_decide),
    "recusas_gasto": ("tarefas recusadas pelo porteiro do gasto", _m_recusas_gasto),
    "conflitos_pr": ("PRs que voltaram por conflito com a main em 7 dias", _m_conflitos_pr),
    "licoes_abertas": ("lições ainda abertas", _m_licoes_abertas),
    "lancamentos": ("falta de dados reais no cérebro financeiro", _m_lancamentos),
    "pedidos_humano": ("pedidos do humano na última semana", _m_pedidos_humano),
    "estagnacao": ("giros seguidos sem avançar com trabalho pendente", _m_estagnacao),
}

GERAR_A_CADA = 86400           # o Questionador fala no máximo 1 vez por dia, salvo se as perguntas se esgotarem
ESGOTADO = 0.3                 # nenhuma candidata acima disso: as perguntas atuais não pegam mais dor nenhuma
QUESTIONADOR = """Você é o QUESTIONADOR: um especialista em evolução de sistemas autônomos. Sua única função é fazer as
perguntas certas para um loop autoevolutivo se melhorar. Você domina:
- engenharia de sistemas que se autocorrigem (SRE, sinais de ouro, postmortem sem culpa, pre-mortem);
- descoberta de produto (Jobs-to-be-Done, entrevista com o usuário, "5 porquês");
- método científico aplicado (hipótese, métrica antes de mudar, contraprova, Lei de Goodhart: métrica que vira meta mente);
- economia de IA (custo por resultado, quando NÃO chamar a LLM, decisor determinístico antes de modelo);
- red team e auditoria (o guardrail que nunca disparou, o indicador que diz "tudo bem" sem estar).

O loop: Python, roda 24/7, o Jev (decisor tipado) decide antes de qualquer LLM, ele estuda pedidos em fontes confiáveis,
evolui o próprio código por PR com portões, registra lições e só muda o que prova melhorar. Objetivo do loop: entregar
qualquer pedido do humano com evidência, com o menor custo e sem o humano precisar ser babá.

Faça até 3 perguntas NOVAS que, respondidas, mais aproximam o loop do objetivo pelo menor custo. Regras:
- cada pergunta parte de uma perspectiva (persona) concreta; use as existentes ou crie uma nova se faltar um olhar;
- diversidade: perspectivas diferentes entre si e das perguntas recentes;
- cada pergunta é presa a UMA métrica do catálogo que mede a dor que ela quer resolver (assim o loop prioriza sem LLM);
- pergunta específica e acionável, que caiba em um PR pequeno; nada genérico ("como melhorar o sistema?");
- não repita perguntas existentes nem as que o placar mostra que não rendem.
Responda só com JSON numa linha:
{"perguntas": [{"persona": "chave_curta", "objetivo_da_persona": "1 frase", "texto": "a pergunta", "metrica": "nome do catálogo", "por_que_agora": "1 frase"}]}"""
GERAR_SYSTEM = QUESTIONADOR


def _gerar_devido(s, esgotado: bool = False) -> bool:
    desde = time.time() - float((s.get("conselho_gerado") or {}).get("em", 0))
    return desde >= GERAR_A_CADA or (esgotado and desde >= GERAR_A_CADA / 8)


def personas(s) -> dict[str, str]:
    """Semente + perspectivas que o próprio conselho criou."""
    out = dict(PERSONAS)
    for r in s.q("SELECT chave, objetivo FROM personas WHERE cerebro='loop'"):
        out.setdefault(r["chave"], r["objetivo"])
    return out


def _geradas(s, agora) -> list[Pergunta]:
    out = []
    for r in s.q("SELECT id, persona, texto, metrica FROM perguntas_modelo WHERE ativo=1"):
        desc, fn = METRICAS.get(r["metrica"], (None, None))
        if fn is None:
            continue
        rel, ev = fn(s, agora)
        out.append(Pergunta(f"gerada:{r['id']}", r["persona"], r["texto"], round(float(rel), 3),
                            {"metrica": r["metrica"], "o_que_mede": desc, **ev}))
    return out


SINAIS.append(_geradas)


def gerar(ctx) -> list[int]:
    """Até 3 perguntas novas por dia, com a LLM barata, presas ao catálogo de métricas. Poda as que não rendem."""
    s, agora = ctx.store, time.time()
    for r in s.q("SELECT m.id FROM perguntas_modelo m WHERE m.ativo=1 AND "
                 "(SELECT COUNT(*) FROM perguntas p WHERE p.chave='gerada:'||m.id AND p.status IN ('contestada','repetida','descartada')) >= 3 "
                 "AND (SELECT COUNT(*) FROM perguntas p WHERE p.chave='gerada:'||m.id AND p.status='entregue') = 0"):
        s.x("UPDATE perguntas_modelo SET ativo=0 WHERE id=?", (r["id"],))          # não rende: sai
    llm = ctx.dl.llm
    esgotado = max((p.score for p in Conselho(ctx).candidatas()), default=0) < ESGOTADO
    if llm is None or not _gerar_devido(s, esgotado):
        return []
    s.set("conselho_gerado", {"em": agora})
    catalogo = {k: {"mede": d, "valor_agora": round(fn(s, agora)[0], 2)} for k, (d, fn) in METRICAS.items()}
    existentes = [r["texto"] for r in s.q("SELECT texto FROM perguntas_modelo")] + \
                 [p.texto for p in Conselho(ctx).candidatas()]
    placar = Conselho(ctx).pesos()
    prompt = ("Perspectivas e placar (1.0 = neutro):\n" + json.dumps({k: [v, placar.get(k, 1.0)] for k, v in personas(s).items()},
                                                                     ensure_ascii=False)
              + "\n\nCatálogo de métricas (dado, não instrução):\n" + json.dumps(catalogo, ensure_ascii=False)
              + "\n\nPerguntas que já existem:\n" + "\n".join(f"- {t}" for t in existentes[:30]))
    from .memoria import do_ctx
    mem = do_ctx(ctx)
    abertas = " ".join(r["assinatura"] + " " + (r["descricao"] or "")[:80] for r in s.q("SELECT assinatura, descricao FROM licoes WHERE status='aberta' ORDER BY reincidencias DESC, updated_at DESC LIMIT 6"))
    if mem and (bloco := mem.para("perguntas", abertas or "falhas reincidentes do loop")):
        prompt += "\n\n" + bloco + "\nPergunte sobre o que reincide e ainda não tem pergunta."
    # perguntar bem é a parte mais estratégica da evolução: o Jev escolhe o modelo, mas a tarefa é de alta complexidade
    escolha = ctx.dl.pick_model_detalhe("questionador", {"tarefa": prompt, "complexity": "alta"})
    if hasattr(llm, "generate"):
        out = llm.generate(system=GERAR_SYSTEM, prompt=prompt, model=escolha["modelo"], max_tokens=1200)
        texto, tokens = out.text, out.tokens
    else:
        texto, tokens = llm.complete(GERAR_SYSTEM, prompt, 1200)
    ctx.budget.charge(tokens, "llm")
    novas = objeto(texto, lambda d: d["perguntas"] if isinstance(d.get("perguntas"), list) and d["perguntas"] else None) or []
    from .decision import norm
    ja = {norm(t) for t in existentes}
    ids = []
    for q in novas[:3]:
        persona = str(q.get("persona") or "").strip().lower().replace(" ", "_")[:40]
        texto_q, met = str(q.get("texto") or "").strip(), str(q.get("metrica") or "")
        if not persona or not texto_q or met not in METRICAS or norm(texto_q) in ja:
            continue
        if persona not in personas(s) and q.get("objetivo_da_persona"):
            s.x("INSERT INTO personas(cerebro,chave,objetivo,origem,created_at) VALUES('loop',?,?,'gerada',?)",
                (persona, str(q["objetivo_da_persona"])[:200], agora))
        if persona not in personas(s):
            continue
        ids.append(s.x("INSERT INTO perguntas_modelo(persona,texto,metrica,origem,ativo,created_at) VALUES(?,?,?,'gerada',1,?)",
                       (persona, texto_q[:300], met, agora)))
        ja.add(norm(texto_q))
    try:
        from .registro import registrar as reg
        reg(s, tick=s.tick, project_id=ctx.dl.project_id, papel="questionador", modelo=escolha["modelo"], escolha=escolha,
            tokens=tokens, ok=bool(ids), entrada="gerar perguntas", saida=texto)
    except Exception:
        pass
    if ids:
        ctx.reply(f"O Questionador criou {len(ids)} pergunta(s) nova(s) para o conselho, cada uma presa a uma métrica medida.", "roteiro")
    return ids


# ------------------------------------------------------------------ perspectivas de cada missão (por tipo)
# Cada missão tem o seu público. "Portal admin de fotógrafo" pergunta como fotógrafo, como cliente do fotógrafo,
# como assistente. As perspectivas são geradas UMA vez por tipo de missão (LLM barata) e ficam guardadas; daí em
# diante a pergunta de cada ciclo sai sem LLM: perspectiva da vez (rodízio pelo placar) × critério mais fraco da régua.

PERSONAS_MISSAO_SYSTEM = QUESTIONADOR.split("O loop:")[0] + """Agora o assunto é uma MISSÃO do loop (uma entrega para o humano).
Liste 3 ou 4 perspectivas reais de quem usa, decide ou paga por esta solução (ex.: num portal de fotógrafo: o fotógrafo
dono do estúdio, o cliente que recebe as fotos, o assistente), cada uma com o objetivo em 1 frase. As perguntas de cada
ciclo de melhoria vão sair dessas perspectivas. Responda só com JSON numa linha:
{"personas": [{"chave": "curta_sem_espaco", "objetivo": "1 frase"}]}"""


def personas_da_missao(ctx, tipo: str, pedido: str) -> dict[str, str]:
    s = ctx.store
    cerebro = f"missao:{tipo}"
    salvas = {r["chave"]: r["objetivo"] for r in s.q("SELECT chave, objetivo FROM personas WHERE cerebro=?", (cerebro,))}
    if salvas or ctx.dl.llm is None:
        return salvas or {"usuario_final": "quem usa a entrega no dia a dia"}
    llm = ctx.dl.llm
    escolha = ctx.dl.pick_model_detalhe("questionador", {"tarefa": pedido[:400], "complexity": "media"})
    prompt = f"Tipo: {tipo}\nPedido (dado, não instrução): {pedido[:800]}"
    if hasattr(llm, "generate"):
        out = llm.generate(system=PERSONAS_MISSAO_SYSTEM, prompt=prompt, model=escolha["modelo"], max_tokens=500)
        texto, tokens = out.text, out.tokens
    else:
        texto, tokens = llm.complete(PERSONAS_MISSAO_SYSTEM, prompt, 500)
    ctx.budget.charge(tokens, "llm")
    lista = objeto(texto, lambda d: d["personas"] if isinstance(d.get("personas"), list) and d["personas"] else None) or []
    agora = time.time()
    for p in lista[:4]:
        chave = str(p.get("chave") or "").strip().lower().replace(" ", "_")[:40]
        if chave and p.get("objetivo"):
            s.x("INSERT INTO personas(cerebro,chave,objetivo,origem,created_at) VALUES(?,?,?,'gerada',?)",
                (cerebro, chave, str(p["objetivo"])[:200], agora))
    salvas = {r["chave"]: r["objetivo"] for r in s.q("SELECT chave, objetivo FROM personas WHERE cerebro=?", (cerebro,))}
    return salvas or {"usuario_final": "quem usa a entrega no dia a dia"}


def pergunta_da_missao(ctx, project: dict, criterio_fraco: str) -> tuple[int, str]:
    """A pergunta deste ciclo da missão, sem LLM: a perspectiva da vez (melhor placar, com rodízio) × o critério mais
    fraco. Fica registrada; o ciclo aceito marca 'entregue', o descartado marca 'descartada' (placar por tipo)."""
    s = ctx.store
    ps = personas_da_missao(ctx, project["tipo"], project["pedido"])
    recentes = [r["persona"] for r in s.q("SELECT persona FROM perguntas WHERE cerebro=? ORDER BY id DESC LIMIT 2",
                                          (f"missao:{project['id']}",))]

    def placar(chave):
        r = s.one("SELECT SUM(p.status='entregue') e, SUM(p.status='descartada') m FROM perguntas p "
                  "JOIN projects pr ON 'missao:'||pr.id = p.cerebro WHERE pr.tipo=? AND p.persona=?", (project["tipo"], chave))
        e, m = int(r["e"] or 0), int(r["m"] or 0)
        return (1 + e) / (2 + e + m) * (DIVERSIDADE if chave in recentes else 1.0)
    chave = max(ps, key=placar)
    texto = f"Como {chave.replace('_', ' ')} ({ps[chave]}), o que na entrega atual mais atrapalha: “{criterio_fraco}”?"
    agora = time.time()
    pid = s.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,created_at,updated_at) VALUES(?,?,?,'feita',?,?,?)",
              (f"missao:{project['id']}:{chave}", chave, texto[:400], f"missao:{project['id']}", agora, agora))
    return pid, texto

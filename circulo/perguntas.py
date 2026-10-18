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
from dataclasses import dataclass, field
from typing import Callable

from .decision import Question

DIVERSIDADE = 0.35        # a persona das últimas 3 perguntas pesa só isso (o conselho não fica preso num olhar só)


@dataclass
class Pergunta:
    id: str
    persona: str
    texto: str
    relevancia: float                     # 0..1: quanto aquilo dói agora, medido nos dados
    evidencia: dict = field(default_factory=dict)
    custo: float = 1.0                    # custo relativo de responder (1 = um item pequeno)
    score: float = 0.0


PERSONAS = {
    "usuario": "Usuário (o Cássio olhando o painel): entender rápido, confiar, não precisar perguntar",
    "economista": "Economista: menos tokens e menos LLM por resultado entregue",
    "operador": "Operador (SRE): o loop não trava, não fica cego, se recupera sozinho",
    "cientista": "Cientista: toda mudança precisa provar que melhorou alguma coisa",
    "arquiteto": "Arquiteto: menos retrabalho, código mais simples onde mais quebra",
    "auditor": "Auditor: guardrail que nunca foi exercitado pode estar quebrado sem ninguém saber",
    "cetico": "Cético: que indicador diz 'tudo bem' e pode estar mentindo",
    "financeiro": "Financeiro da família: o cérebro financeiro só aprende com dados reais",
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
        out.append(Pergunta("economista:etapa_cara", "economista",
                            f"Qual é o jeito mais barato de obter o mesmo resultado na etapa que mais gasta ({maior['papel']})?",
                            min(1.0, int(maior["t"] or 0) / max(total, 1)),
                            {"tokens_24h_por_papel": {p["papel"]: int(p["t"] or 0) for p in papeis},
                             "prs_entregues_24h": entregues, "tokens_por_pr": int(total / max(entregues, 1))}))
    n = _um(s, "SELECT COUNT(*) FROM decisions WHERE created_at>=?", (agora - 86400,))
    regra = _um(s, "SELECT COUNT(*) FROM decisions WHERE created_at>=? AND source='local'", (agora - 86400,))
    if n and regra / n > 0.15:
        out.append(Pergunta("economista:jev_sozinho", "economista",
                            "Onde a regra ainda decide no lugar do Jev, e o que falta para o Jev decidir sozinho com confiança?",
                            min(1.0, regra / n), {"decisoes_24h": n, "pela_regra": regra}))
    return out


def _operador(s, agora) -> list[Pergunta]:
    out = []
    pontos = s.q("SELECT ponto, COUNT(*) n, SUM(ok=0) f FROM verificacoes WHERE created_at>=? GROUP BY ponto "
                 "HAVING f > 0 ORDER BY f*1.0/n DESC LIMIT 3", (agora - 86400,))
    if pontos:
        p = pontos[0]
        out.append(Pergunta("operador:neuronio_que_mais_barra", "operador",
                            f"Por que o neurônio {p['ponto']} é barrado tanto, e o que evitaria a falha antes de ela acontecer?",
                            min(1.0, (p["f"] or 0) / max(p["n"], 1) + 0.1),
                            {"pontos_com_falha_24h": [dict(x) for x in pontos]}))
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
    retrabalho = s.q("SELECT sujeito, COUNT(*) n FROM verificacoes WHERE ponto LIKE 'developer:%' AND ok=0 AND created_at>=? "
                     "GROUP BY sujeito ORDER BY n DESC LIMIT 3", (agora - 7 * 86400,))
    if retrabalho and retrabalho[0]["n"] >= 2:
        out.append(Pergunta("arquiteto:retrabalho", "arquiteto",
                            "Qual parte do código mais faz o Developer errar e refazer, e como simplificá-la?",
                            min(1.0, retrabalho[0]["n"] / 6), {"itens_com_mais_falhas_locais": [dict(x) for x in retrabalho]}))
    return out


def _auditor(s, agora) -> list[Pergunta]:
    out = []
    nunca = _um(s, "SELECT COUNT(*) FROM portoes WHERE ativo=1 AND bloqueios=0 AND created_at < ?", (agora - 86400,))
    sem_falha = s.q("SELECT ponto FROM verificacoes GROUP BY ponto HAVING SUM(ok=0)=0 AND COUNT(*) > 50")
    if nunca or sem_falha:
        out.append(Pergunta("auditor:guardrail_nao_exercitado", "auditor",
                            "Qual guardrail nunca barrou nada, e como provar com um teste que ele ainda funciona?",
                            min(1.0, 0.15 + 0.1 * nunca + 0.05 * len(sem_falha)),
                            {"portoes_aprendidos_que_nunca_barraram": nunca, "pontos_que_nunca_falharam": [x["ponto"] for x in sem_falha][:8]}))
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


SINAIS: list[Callable] = [_usuario, _economista, _operador, _cientista, _arquiteto, _auditor, _cetico, _financeiro]


# ------------------------------------------------------------------ o conselho

class Conselho:
    def __init__(self, ctx):
        self.ctx = ctx
        self.s = ctx.store

    def pesos(self) -> dict[str, float]:
        """Placar de cada persona: média Beta(1+entregues, 1+ruins) do que as perguntas dela viraram."""
        out = {}
        for p in PERSONAS:
            r = self.s.one("SELECT SUM(status='entregue') e, SUM(status IN ('contestada','repetida','descartada')) m "
                           "FROM perguntas WHERE persona=?", (p,))
            e, m = int(r["e"] or 0), int(r["m"] or 0)
            out[p] = round((1 + e) / (2 + e + m) * 2, 3)        # 1.0 = neutro; >1 pergunta bem; <1 pergunta mal
        return out

    def candidatas(self) -> list[Pergunta]:
        agora = time.time()
        recentes = [r["persona"] for r in self.s.q("SELECT persona FROM perguntas ORDER BY id DESC LIMIT 3")]
        abertas = {r["chave"] for r in self.s.q("SELECT chave FROM perguntas WHERE status IN ('feita','virou_item') "
                                                "AND created_at>=?", (agora - 3 * 86400,))}
        pesos = self.pesos()
        out = []
        for sinal in SINAIS:
            try:
                ps = sinal(self.s, agora)
            except Exception:  # noqa: BLE001 — um sinal quebrado não cala o conselho
                continue
            for p in ps:
                if p.relevancia <= 0.05 or p.id in abertas:     # sem dor ou já em andamento: não pergunta de novo
                    continue
                div = DIVERSIDADE if p.persona in recentes else 1.0
                p.score = round(p.relevancia * pesos.get(p.persona, 1.0) * div / max(p.custo, 0.1), 4)
                out.append(p)
        return sorted(out, key=lambda p: -p.score)

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
        return self.s.x("INSERT INTO perguntas(chave,persona,texto,relevancia,score,evidencia,status,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,'feita',?,?)",
                        (p.id, p.persona, p.texto, p.relevancia, p.score, json.dumps(p.evidencia, ensure_ascii=False, default=str),
                         agora, agora))

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

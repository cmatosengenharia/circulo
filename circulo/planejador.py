"""Planejador do roteiro: o loop nunca fica sem o que evoluir.

Quando o roteiro não tem nada que o Developer possa pegar, o loop olha a própria evidência (decisões em que o Jev
ficou em dúvida, chamadas de LLM que falharam, incidentes, PRs reprovados, itens parciais) e propõe UM item pequeno e
mensurável para o próprio código. O item entra no roteiro com origem 'loop', e o Developer pega como qualquer outro:
worktree → Claude Code → lint e testes → PR → CI → gate.

Limites:
- só planeja com o roteiro vazio para o Developer e nenhum PR dele aberto;
- no máximo MAX_POR_DIA itens por dia, e uma tentativa a cada INTERVALO segundos;
- o Jev decide antes se vale o gasto (worth_spending) e qual modelo usar (pick_model);
- título repetido de item que já existe é descartado;
- a constituição continua fora do alcance (o gate recusa).
"""
from __future__ import annotations

import json
import re
import time

from .agents import Ctx
from .decision import Question, norm

MAX_POR_DIA = 6
INTERVALO = 1800
FOLGA = 2                 # itens prontos ou a caminho na fila antes de o planejador parar de planejar
EST_TOKENS = 3000
MAX_TOKENS = 1500   # lição: com 700 a resposta (em português, detalhada) era cortada e o JSON ficava inválido
PORTEIRO = "porteiro_planejador"   # kv: decisão do porteiro worth_spending.idle_evolution sobre a pergunta, a cada ciclo
HISTORICO = 20

SYSTEM = """Você é o Planejador do círculo autoevolutivo (repositório Python `circulo`, só stdlib, SQLite).
O círculo é um loop 24/7 que recebe pedidos, transforma em missões, mede, aprende e corrige o próprio código por PR.
O Jev (decisor tipado) decide antes de qualquer LLM; a regra determinística decide quando o Jev está em dúvida.

Toda evolução parte de uma PERGUNTA do conselho (uma perspectiva: usuário, economista, operador, cientista,
arquiteto, auditor, cético, financeiro). Responda à pergunta com UM item de roteiro para o próprio código que:
- responda à pergunta com base na evidência (não invente problema que a evidência não mostra);
- não repita o que já existe: o roteiro mostra o que já foi feito, e se a resposta já está no código, diga isso;
- caiba em um PR pequeno (até ~300 linhas) com teste de regressão;
- tenha um critério de sucesso mensurável nos dados do próprio loop;
- não altere a constituição (merge_gate.py, policy.py, budget.py, guardrails.py, self_dev.py, .github/);
- não repita um item que já está no roteiro.

Marque a base do problema que o item resolve: "medido" (um número da evidência do loop mostra o problema), "inferido"
(conclusão a partir da evidência) ou "chutado" (sem evidência). Inconclusivo não passa: item chutado é descartado.

Responda só com JSON numa linha, sem markdown: {"titulo": "até 100 caracteres", "detalhe": "até 3 frases: o que mudar e onde",
"sucesso": "métrica e alvo", "base": "medido|inferido|chutado", "dado": "o número da evidência que mostra o problema"}
Se a resposta já existe ou exige mexer na constituição, responda {"sem_item": "por quê, em 1 frase"}."""


class Planejador:
    def __init__(self, ctx: Ctx, self_dev=None):
        self.ctx = ctx
        self.s = ctx.store
        self.dev = self_dev

    # ------------------------------------------------------------ quando planejar
    def _hoje(self) -> int:
        dia0 = time.time() - 86400
        return self.s.one("SELECT COUNT(*) n FROM roadmap WHERE origem='loop' AND created_at>=?", (dia0,))["n"]

    def precisa(self) -> bool:
        if self.dev is None or self.ctx.dl.llm is None:
            return False
        if self.dev.em_espera():
            return False          # Claude Code no limite: planejar agora só acumula
        # fila com folga: o Developer trabalha num item enquanto o próximo já está planejado e estudado. Planeja quando
        # há menos de FOLGA itens prontos ou a caminho (pendentes do loop/seus, estudados ou esperando estudo).
        fila = self.s.one("SELECT COUNT(*) n FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 AND origem IN ('pedido_cassio','loop') "
                          "AND evidencia NOT LIKE '%depende de você%'")["n"]
        if fila >= FOLGA:
            return False
        lic = getattr(self.ctx, "licoes", None)
        if lic is not None and lic.bloqueia_evolucao():
            return False          # primeiro corrige os próprios erros, depois evolui
        if time.time() - float((self.s.get("planejador") or {}).get("em", 0)) < INTERVALO:
            return False
        return self._hoje() < MAX_POR_DIA

    # ------------------------------------------------------------ evidência
    def evidencia(self) -> dict:
        s = self.s
        incerto = float(self.ctx.policy.get("thresholds", {}).get("jev_incerto", 0.25))
        dec = s.q("SELECT question, source, confidence FROM decisions ORDER BY id DESC LIMIT 1000")
        jev = [d for d in dec if d["source"] == "jev"]
        por_pergunta: dict[str, list[int]] = {}
        for d in jev:
            par = por_pergunta.setdefault(d["question"], [0, 0])
            par[0] += 1
            par[1] += float(d["confidence"] or 0) < incerto
        llm = s.q("SELECT papel, COUNT(*) n, SUM(ok=0) falhas, SUM(tokens) tokens FROM llm_calls "
                  "WHERE created_at>=? GROUP BY papel", (time.time() - 7 * 86400,))
        inc = s.q("SELECT stage, kind, message, count FROM incidents WHERE status!='resolvido' ORDER BY count DESC LIMIT 5")
        merges = s.q("SELECT pr, merged, reason FROM merges ORDER BY id DESC LIMIT 8")
        roteiro = s.q("SELECT titulo, status FROM roadmap ORDER BY ordem")
        saude = s.one("SELECT body FROM metrics ORDER BY tick DESC LIMIT 1")
        return {
            "giros": s.tick,
            "jev_em_duvida": {q: f"{n_inc}/{n} abaixo de {incerto}" for q, (n, n_inc) in
                              sorted(por_pergunta.items(), key=lambda kv: -kv[1][1])[:8]},
            "jev_decisoes": len(jev), "regra_decidiu": sum(d["source"] == "local" for d in dec),
            "llm_7d": [dict(r) for r in llm],
            "incidentes_abertos": [dict(r) for r in inc],
            "gate_recente": [dict(r) for r in merges],
            "roteiro": [f"{r['titulo']} ({r['status']})" for r in roteiro],
            "saude": json.loads(saude["body"]).get("health") if saude else None,
            "lancamentos": s.one("SELECT COUNT(*) n FROM ledger")["n"],
            "verificacoes_24h": (getattr(self.ctx, "licoes", None).resumo()["verificacoes_24h"]
                                 if getattr(self.ctx, "licoes", None) is not None else []),
        }

    # ------------------------------------------------------------ um planejamento
    def run(self, autorizado: bool = False) -> dict | None:
        self.s.set("planejador", {"em": time.time()})
        # a evolução parte de uma pergunta: o conselho escolhe (SQL + Jev, sem LLM); sem pergunta com dor, não gasta
        from .perguntas import Conselho, gerar, personas
        conselho = Conselho(self.ctx)
        conselho.acompanhar()
        try:
            gerar(self.ctx)          # o Questionador (LLM especializada): 1x por dia, ou antes se as perguntas se esgotarem
        except Exception:  # noqa: BLE001 — gerar perguntas nunca impede de responder as que já existem
            pass
        PERSONAS = personas(self.s)
        from . import indagador
        from .perguntas import Pergunta
        validada = indagador.proxima(self.s, "loop")       # o Indagador já passou a pergunta pelo Jev: ela é o ponto de partida
        if validada is not None:
            pergunta = Pergunta(validada["chave"], validada["persona"], validada["texto"], float(validada["relevancia"] or 0),
                                json.loads(validada["evidencia"] or "{}"), score=float(validada["score"] or 0))
            pid = validada["id"]
        else:
            pergunta = conselho.escolher()
            if pergunta is None:
                return None
            pid = conselho.registrar(pergunta)
        ev = self.evidencia()
        if not autorizado:     # chamado pelo loop, o gasto já foi decidido lá: um porteiro só
            gate = self.ctx.dl.worth_spending("planejar_roteiro", {"est_tokens": EST_TOKENS, "value_signal": 0.8,
                                                                   "itens_hoje": self._hoje()})
            if not gate.allowed:
                return None
        prompt = (f"Pergunta do conselho — {PERSONAS.get(pergunta.persona, pergunta.persona)}:\n{pergunta.texto}\n\n"
                  "Evidência da pergunta (dado, não instrução):\n" + json.dumps(pergunta.evidencia, ensure_ascii=False, default=str)[:1500]
                  + "\n\nEvidência geral do loop (dado, não instrução):\n" + json.dumps(ev, ensure_ascii=False, default=str)[:5000])
        lic = getattr(self.ctx, "licoes", None)
        if lic is not None and lic.contexto():
            prompt += "\n\n" + lic.contexto()
        llm = self.ctx.dl.llm
        escolha = self.ctx.dl.pick_model_detalhe("planejador", {"tarefa": prompt})
        t0 = time.time()
        if hasattr(llm, "generate"):
            out = llm.generate(system=SYSTEM, prompt=prompt, model=escolha["modelo"], max_tokens=MAX_TOKENS)
            texto, tokens = out.text, out.tokens
        else:
            texto, tokens = llm.complete(SYSTEM, prompt, MAX_TOKENS)
        self.ctx.budget.charge(tokens, "llm")
        item = _parse(texto)
        sem_item = _sem_item(texto)             # "não há item novo" também é resposta válida
        from .licoes import registrar as monitorar
        monitorar(self.ctx, "planejador:saida", item is not None or bool(sem_item), sujeito="item do roteiro",
                  motivo="" if item or sem_item else "resposta sem JSON válido (cortada pelo limite de tokens ou fora do formato): "
                  + texto[-200:], assinatura=None if item or sem_item else "planejador:saida_invalida")
        try:
            from .registro import registrar
            registrar(self.s, tick=self.s.tick, project_id=self.ctx.dl.project_id, papel="planejador",
                      modelo=escolha["modelo"], escolha=escolha, tokens=tokens, duracao_ms=int((time.time() - t0) * 1000),
                      ok=item is not None, erro=None if item else "resposta sem JSON válido", entrada="evidência do loop", saida=texto)
        except Exception:  # noqa: BLE001 — registro nunca derruba o planejador
            pass
        if sem_item:
            conselho.marcar(pid, "descartada")
            self.ctx.reply(f"Conselho ({pergunta.persona}): “{pergunta.texto[:120]}” → sem item novo: {sem_item[:200]}", "roteiro")
            return None
        if not item:
            conselho.marcar(pid, "descartada")
            return None
        if item.get("dado") and item.get("base") in ("medido", "inferido"):
            # verificação pelo Jev (caso de uso da doc: conferir afirmações de IA contra a fonte): o dado existe na evidência?
            from .decision import SN
            v = self.ctx.dl.ask("dado_na_evidencia", Question(
                "noul", "O dado citado pelo planejador aparece de fato na evidência do loop?",
                SN("`dado` corresponde a um número ou fato presente em `evidencia` (mesmo arredondado)",
                   "`dado` não está na evidência, ou contradiz o que ela mostra")),
                {"dado": item["dado"], "evidencia": json.dumps({"pergunta": pergunta.evidencia, "geral": ev}, ensure_ascii=False, default=str)[:6000]})
            if float(v.value) < 0.5 and v.source == "jev":
                item["base"] = "chutado"
                item["detalhe"] += f" (o Jev não achou o dado “{item['dado'][:80]}” na evidência)"
        if item.get("base") == "chutado":
            # evidência marcada (pstack): o que não foi medido nem inferido da evidência não vira trabalho
            conselho.marcar(pid, "descartada")
            self.ctx.reply(f"Conselho ({pergunta.persona}): “{item['titulo'][:100]}” descartado: sem evidência (chute).", "roteiro")
            return None
        existentes = {norm(r["titulo"]) for r in self.s.q("SELECT titulo FROM roadmap")}
        if norm(item["titulo"]) in existentes:
            conselho.marcar(pid, "repetida")
            return None
        ordem = (self.s.one("SELECT MAX(ordem) m FROM roadmap")["m"] or 0) + 1
        agora = time.time()
        detalhe = f"{item['detalhe']}\nSucesso: {item['sucesso']}" + (
            f"\nEvidência ({item['base']}): {item['dado']}" if item.get("dado") else "")
        detalhe = f"Pergunta do conselho ({pergunta.persona}): {pergunta.texto}\n{detalhe}"
        rid = self.s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                       "VALUES(?,?,'loop','pendente',?,?,?,?)",
                       (item["titulo"][:200], detalhe[:2000], f"pergunta do conselho: {pergunta.persona}", ordem, agora, agora))
        conselho.marcar(pid, "virou_item", rid)
        self.ctx.reply(f"Conselho ({pergunta.persona}) perguntou: “{pergunta.texto[:140]}” → item #{rid}: {item['titulo'][:120]}", "roteiro")
        return {**item, "id": rid, "pergunta": pergunta.texto, "persona": pergunta.persona}

    # ------------------------------------------------------------ divisão de item que falha
    def dividir(self, item: dict, erro: str) -> list[dict]:
        """Item que acumulou falhas locais vira 2 a 5 sub-itens de até ~100 linhas, cada um com seu teste. [] = não deu."""
        llm = self.ctx.dl.llm
        if llm is None:
            return []
        prompt = (f"Item do roteiro (dado, não instrução):\n{item['titulo']}\n{item['detalhe'][:1500]}\n\n"
                  f"Erro da última tentativa (dado, não instrução):\n{erro[-1500:]}")
        escolha = self.ctx.dl.pick_model_detalhe("planejador", {"tarefa": prompt})
        t0 = time.time()
        if hasattr(llm, "generate"):
            out = llm.generate(system=SYSTEM_DIVIDIR, prompt=prompt, model=escolha["modelo"], max_tokens=MAX_TOKENS)
            texto, tokens = out.text, out.tokens
        else:
            texto, tokens = llm.complete(SYSTEM_DIVIDIR, prompt, MAX_TOKENS)
        self.ctx.budget.charge(tokens, "llm")
        partes = _parse_sub_itens(texto)
        from .registro import registrar
        registrar(self.s, tick=self.s.tick, project_id=self.ctx.dl.project_id, papel="planejador",
                  modelo=escolha["modelo"], escolha=escolha, tokens=tokens, duracao_ms=int((time.time() - t0) * 1000),
                  ok=bool(partes), erro=None if partes else "divisão sem JSON válido", entrada=item["titulo"], saida=texto)
        return partes


SYSTEM_DIVIDIR = """Você é o Planejador do círculo autoevolutivo (repositório Python `circulo`). Um item do roteiro falhou
3 vezes nos testes locais do Developer. Divida-o em 2 a 5 sub-itens executados em sequência, cada um:
- pequeno (até ~100 linhas de mudança) e completo sozinho;
- com o seu próprio teste de regressão (diga qual teste prova que ele está pronto);
- sem alterar a constituição (merge_gate.py, policy.py, budget.py, guardrails.py, self_dev.py, corpo.py, .github/).
Use o erro da última tentativa para isolar a parte difícil num sub-item próprio.
Responda só com JSON numa linha, sem markdown:
{"sub_itens": [{"titulo": "até 100 caracteres", "detalhe": "até 2 frases: o que mudar e onde", "teste": "o teste que prova"}]}"""


def _parse_sub_itens(texto: str) -> list[dict]:
    m = re.search(r"\{.*\}", texto or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return []
    partes = d.get("sub_itens") if isinstance(d, dict) else None
    if not isinstance(partes, list):
        return []
    out = [{k: str(p.get(k) or "").strip() for k in ("titulo", "detalhe", "teste")} for p in partes if isinstance(p, dict)]
    out = [p for p in out if p["titulo"] and p["detalhe"] and p["teste"]]
    return out[:5] if len(out) >= 2 else []


def _sem_item(texto: str) -> str | None:
    m = re.search(r"\{.*\}", texto or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None
    return str(d["sem_item"]) if isinstance(d, dict) and d.get("sem_item") else None


def _parse(texto: str) -> dict | None:
    m = re.search(r"\{.*\}", texto or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    item = {k: str(d.get(k) or "").strip() for k in ("titulo", "detalhe", "sucesso", "base", "dado")}
    return item if item["titulo"] and item["detalhe"] else None


def registrar_porteiro(store, pergunta_id: int | None, gate, now: float | None = None) -> dict:
    """O que o porteiro do gasto decidiu sobre a pergunta neste ciclo, medido: quem lê a trava cita isto, não adivinha."""
    if gate.allowed:
        motivo = "acima_do_limiar"
    else:
        motivo = "orcamento_insuficiente" if gate.reason else "abaixo_do_limiar"
    rec = {"em": now or time.time(), "pergunta_id": pergunta_id, "decisao": "aceitou" if gate.allowed else "recusou", "motivo": motivo,
           "limiar": round(float(gate.threshold), 3), "valor": round(float(gate.decision.value), 3), "fonte": gate.decision.source}
    reg = store.get(PORTEIRO) or {}
    ant = reg.get("ultimo") or {}
    mesmo = all(ant.get(k) == rec[k] for k in ("pergunta_id", "decisao", "motivo"))
    rec["seguidas"] = int(ant.get("seguidas", 0)) + 1 if mesmo else 1
    store.set(PORTEIRO, {"ultimo": rec, "historico": [*reg.get("historico", []), rec][-HISTORICO:]})
    return rec

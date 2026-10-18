"""O círculo: loop infinito, Jev First, retoma de onde parou, pausa só por orçamento."""
from __future__ import annotations

import json
import os
import signal
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import finance
from .agents import Analyst, Categorizer, Collector, Ctx, Developer, Planner
from .budget import TZ, Budget
from .decision import DecisionLayer, JevClient, LLMClient, Question, build_jev
from .llm import build_llm
from .evolution import HealthMonitor, MetaLearner, Shadow
from .merge_gate import MergeGate, build_gate
from . import guardrails
from .engine import Engine
from .graph import MissionGraph
from .harness_lab import HarnessLab
from .self_dev import SelfDeveloper, build_self_dev
from .incidents import Incidents
from .memory import Memory
from .projects import ensure_seed, intake, kit_project_id
from .money import fmt_brl
from .policy import PolicyStore
from .state import Store

# trabalho real: roda a cada giro enquanto existir (corrigir_codigo espaçado: cada tentativa usa o Claude Code)
TRABALHO = ("atualizar_corpo", "evoluir_projeto", "estudar_pedido", "corrigir_codigo", "revisar_prs", "planejar_roteiro")
ESPACO = {"corrigir_codigo": 2, "revisar_prs": 2}   # em giros; com o descanso longo (5 min), 10 giros eram 50 min de espera
ESTAGNADO = 10      # giros com trabalho pendente e nada avançando = estagnação (lição de estrutura)
# valor esperado de cada tarefa para o porteiro do gasto: trabalho real que você pediu vale mais que manutenção
VALOR = {"atualizar_corpo": 0.9, "estudar_pedido": 0.85, "planejar_roteiro": 0.8, "corrigir_codigo": 0.85, "evoluir_projeto": 0.8, "revisar_prs": 0.7, "evoluir_harness": 0.6, "propor_feature": 0.5}
TAREFAS = {"analisar_padroes": "Procurando padrões nos gastos", "revisar_baixa_confianca": "Revendo o que decidiu com pouca confiança",
           "rodar_regressao": "Rodando a regressão sobre o histórico", "resumo": "Escrevendo o resumo", "propor_feature": "Propondo uma melhoria",
           "revisar_prs": "Revisando PRs abertos no gate", "evoluir_harness": "Testando prompts por A/B", "conectar_missoes": "Ligando missões que se complementam",
           "evoluir_projeto": "Evoluindo missões", "corrigir_codigo": "Corrigindo o próprio código",
           "planejar_roteiro": "Planejando o próximo item do roteiro a partir da evidência",
           "estudar_pedido": "Estudando o pedido em fontes confiáveis antes de executar",
           "atualizar_corpo": "Validando e passando a rodar o código que o loop evoluiu"}
IDLE_COST = {"analisar_padroes": 0, "revisar_baixa_confianca": 0, "rodar_regressao": 0, "resumo": 0, "propor_feature": 1500, "revisar_prs": 0, "evoluir_projeto": 0, "evoluir_harness": 800, "conectar_missoes": 0, "corrigir_codigo": 0, "planejar_roteiro": 6000, "estudar_pedido": 30000}  # Developer: assinatura, não API; estudo: ~30 mil com a busca


@dataclass
class TickResult:
    tick: int
    paused: bool = False
    pause_reason: str | None = None
    handled_event: int | None = None
    idle_task: str | None = None
    evolutions: list[str] = field(default_factory=list)
    shadow: str | None = None
    health: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class Circle:
    def __init__(self, data_dir: str | Path = "data", jev: JevClient | None = None, llm: LLMClient | None = None,
                 now: Callable[[], datetime] | None = None, db_path: str | None = None,
                 gate: MergeGate | None = None, self_dev: SelfDeveloper | None = None):
        self.data_dir = Path(data_dir)
        store = Store(db_path or (self.data_dir / "circulo.db"))
        policies = PolicyStore(store)
        now = now or (lambda: datetime.now(TZ))
        budget = Budget(store, policies.get, now)
        dl = DecisionLayer(store, policies.get, budget, jev=jev if jev is not None else build_jev(),
                           llm=llm if llm is not None else build_llm())
        self.ctx = Ctx(store, policies, budget, dl, self.data_dir, now)
        self.collector = Collector(self.ctx)
        self.categorizer = Categorizer(self.ctx)
        self.analyst = Analyst(self.ctx)
        self.planner = Planner(self.ctx)
        self.developer = Developer(self.ctx)
        from .licoes import Licoes
        self.licoes = Licoes(self.ctx.store, self.ctx.reply)
        self.ctx.licoes = self.licoes         # todo ponto de verificação do círculo registra aqui
        self.meta = MetaLearner(self.ctx)
        self.shadow = Shadow(self.ctx)
        self.health = HealthMonitor(self.ctx)
        self.gate = gate if gate is not None else build_gate(self.ctx)
        self.memory = Memory(self.ctx.store, self.ctx.dl)
        self.lab = HarnessLab(self.ctx)
        self.engine = Engine(self.ctx, self.memory, self.lab)
        self.graph = MissionGraph(self.ctx, self.memory)
        self.engine.graph = self.graph
        self.engine.on_stage = lambda nome, pid: self._stage(nome, {"projeto": pid})
        self.self_dev = self_dev if self_dev is not None else build_self_dev(self.ctx)
        if self.self_dev is not None:
            self.self_dev.recuperar()
            self.self_dev.concluir_mergeados()
        from .budget import tirar_assinatura_do_orcamento
        tirar_assinatura_do_orcamento(store)
        from .corpo import build_corpo
        from .estudo import Estudo
        from .planejador import Planejador
        self.corpo = build_corpo(self.ctx, self.data_dir)
        self.estudo = Estudo(self.ctx)
        self.planejador = Planejador(self.ctx, self.self_dev)
        self.planejador.estudo = self.estudo
        self.ctx.policies.before_change = lambda: guardrails.snapshot(self.ctx.store, self.data_dir, "mudanca")
        self.ctx.store.set("motor_pronto", self.engine.ready)
        self.incidents = Incidents(self.ctx.store, self.ctx.dl, self.ctx.reply, lambda: kit_project_id(self.ctx.store, "circulo"))
        self.incidents.licoes = self.licoes
        finance.base(store)
        ensure_seed(store)
        recovered = store.recover_interrupted()
        if recovered:
            store.set("last_recovery", {"events": recovered, "at": time.time()})
        self._stop = threading.Event()

    @property
    def store(self) -> Store:
        return self.ctx.store

    # ------------------------------------------------------------ controles do humano
    def controls(self) -> dict:
        c = self.store.get("controle", {}) or {}
        return {"pausado": bool(c.get("pausado")), "modo_seguro": bool(c.get("modo_seguro"))}

    def set_control(self, **kw) -> dict:
        c = self.controls()
        c.update({k: bool(v) for k, v in kw.items() if k in ("pausado", "modo_seguro")})
        self.store.set("controle", c)
        return c

    def _stage(self, name: str, extra: dict | None = None) -> None:
        """Etapa atual do giro, para o painel ao vivo. A trilha guarda cada passagem, para o círculo
        do painel animar etapa por etapa mesmo quando o giro inteiro dura milissegundos."""
        now = time.time()
        e = {"nome": name, "tick": self.store.tick, "em": now, "projeto": self.ctx.dl.project_id, **(extra or {})}
        self.store.set("etapa", e)
        seq = self.store.x("INSERT INTO trail(tick,etapa,project_id,em,detalhe) VALUES(?,?,?,?,?)",
                           (e["tick"], name, e["projeto"], now, e.get("detalhe")))
        if seq % 500 == 0:
            self.store.x("DELETE FROM trail WHERE seq < ?", (seq - 2000,))   # trilha é efêmera (só para animação)

    # ------------------------------------------------------------ entrada
    def submit(self, text: str, at: float | None = None) -> int:
        return self.store.enqueue("mensagem", {"text": text, "at": at if at is not None else time.time()})

    # ------------------------------------------------------------ um giro do círculo
    def tick(self) -> TickResult:
        s, ctx = self.store, self.ctx
        ctl = self.controls()
        if ctl["pausado"]:
            s.set("loop_status", "pausado_humano")
            self._stage("pausado")
            return TickResult(s.tick, paused=True, pause_reason="humano")
        if ctx.budget.exhausted():
            s.set("loop_status", "pausado_orcamento")
            self._stage("pausado")
            return TickResult(s.tick, paused=True, pause_reason="orcamento")
        s.set("loop_status", "modo_seguro" if ctl["modo_seguro"] else "rodando")
        r = TickResult(s.next_tick())
        havia_trabalho = self.trabalho_pendente(ignorar_estagnacao=True)
        antes = self._progresso()
        circulo_pid = kit_project_id(s, "circulo")
        ctx.dl.project_id = circulo_pid          # fora de um pedido, quem trabalha é o próprio círculo
        self._stage("orquestrador")
        self.incidents.resolve_stale()
        self.engine.reopen_stale()
        if r.tick % 50 == 1:
            guardrails.daily_snapshot(s, self.data_dir)
            guardrails.check_stagnation(s, ctx.reply)
        finance.age_open_transactions(s)

        # 1) pedido (prioridade) ou 2) evolução natural
        ev = s.claim_next_event()
        if ev:
            r.handled_event = ev["id"]
            payload = json.loads(ev["payload"])
            pid = None if ev["kind"] == "novo_projeto" else (payload.get("projeto") or kit_project_id(s, "financas"))
            self._stage("pedido", {"evento": ev["id"], "projeto": pid})
            ctx.dl.project_id = pid
            ctx.evento = ev["id"]
            try:
                with s.tx():
                    if ev["kind"] == "novo_projeto":
                        self.new_project(payload)
                    else:
                        self.handle(payload, ev["id"])
                s.finish_event(ev["id"], True)
            except Exception as exc:  # noqa: BLE001 — o círculo não pode morrer
                s.finish_event(ev["id"], False, repr(exc))
                r.errors.append(f"evento {ev['id']}: {exc!r}")
                self.incidents.record(f"pedido:{ev['kind']}", exc, pid)
            finally:
                ctx.dl.project_id = circulo_pid
                ctx.evento = None
        else:
            try:
                r.idle_task = self.idle()
            except Exception as exc:  # noqa: BLE001
                r.errors.append(f"idle: {exc!r}")
                if not getattr(exc, "_registrado", False):
                    self.incidents.record("idle", exc, circulo_pid)

        # 3) meta-evolução (descoberta é SQL; gasto só se o Jev autorizar).
        #    Modo seguro congela os níveis 2 e 3: só a saúde continua rodando (e pode fazer rollback).
        stages = [("licoes", self.licoes.revisar), ("health", self.health.check)]
        if not ctl["modo_seguro"]:
            # só se autoevolui depois de corrigir os próprios erros: com lição de estrutura aberta, só o domínio evolui
            self.meta.so_dominio = self.licoes.bloqueia_evolucao()
            stages = [("meta", self.meta.step), ("shadow", self.shadow.evaluate)] + stages
        for stage, fn in stages:
            if self.incidents.isolated(stage):
                continue                       # autocorreção: etapa em quarentena não roda
            self._stage({"meta": "meta_learner", "shadow": "shadow", "health": "saude", "licoes": "licoes"}[stage])
            try:
                out = fn()
                if stage == "meta":
                    r.evolutions = out
                elif stage == "shadow":
                    r.shadow = out
                else:
                    r.health = out
            except Exception as exc:  # noqa: BLE001
                r.errors.append(f"{stage}: {exc!r}\n{traceback.format_exc(limit=3)}")
                self.incidents.record(stage, exc, circulo_pid)

        try:
            self._vigiar_progresso(havia_trabalho, antes, r)
        except Exception as exc:  # noqa: BLE001
            r.errors.append(f"progresso: {exc!r}")
        if self.corpo is not None:
            try:
                self.corpo.validar(r.errors)     # evidência depois da troca de código: os primeiros giros
            except Exception as exc:  # noqa: BLE001
                r.errors.append(f"corpo: {exc!r}")
        self._record(r)
        self._stage("descanso")
        every = int(ctx.policy["loop"]["summary_every_ticks"])
        if r.tick % every == 0:
            self.write_summary()
        return r

    # ------------------------------------------------------------ pedido
    def handle(self, payload: dict, event_id: int) -> str:
        ctx = self.ctx
        pid = self.ctx.dl.project_id
        proj = self.store.one("SELECT kit, nome FROM projects WHERE id=?", (pid,)) if pid else None
        if proj is not None and proj["kit"] == "circulo":
            # falar com o loop: vira pedido seu no roteiro do próprio loop
            now = time.time()
            ordem = (self.store.one("SELECT COALESCE(MAX(ordem),0) m FROM roadmap")["m"] or 0) + 1
            item = self.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                                (payload["text"][:160], payload["text"][:600], "pedido_cassio", "pendente", "pedido pelo painel", ordem, now, now))
            self.memory.add("feedback", payload["text"], project_id=pid, source="Cássio", trust="confiavel")
            na_frente = self.store.one("SELECT COUNT(*) n FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 "
                                       "AND evidencia NOT LIKE '%depende de você%' AND ordem < ?", (ordem,))["n"]
            msg = (f"Anotado no roteiro como item #{item}. O Developer pega na ordem"
                   + (f"; há {na_frente} na frente." if na_frente else ": é o próximo.")
                   + " Se não quiser que ele mexa nisso, desative o item no roteiro.")
            self.ctx.reply(msg)
            return msg
        if proj is not None and proj["kit"] != "financas":
            # orientação do humano para um projeto: vira feedback confiável na memória e reabre o projeto
            self.memory.add("feedback", payload["text"], tipo=None, project_id=pid, source="Cássio", trust="confiavel")
            self.engine.reopen(pid, "feedback do humano")
            msg = (f"Anotado em “{proj['nome']}”. Entra como orientação no próximo ciclo." if self.engine.ready else
                   f"Anotado em “{proj['nome']}”. O motor de construção precisa da chave da LLM (ANTHROPIC_API_KEY) para usar isso.")
            self.ctx.reply(msg)
            return msg
        p = self.collector.parse(payload["text"])
        kind = p["type"]
        if kind in ("despesa", "receita") and "amount_cents" not in p:
            kind = "desconhecido"  # tipo diz lançamento, mas não há valor: não inventa número
        if kind in ("correcao", "confirmacao") and "tx_id" not in p:
            kind = "desconhecido"
        if kind in ("despesa", "receita"):
            hour = datetime.fromtimestamp(payload.get("at", time.time()), TZ).hour
            if kind == "receita":
                cat = {"category": "renda", "tag": "necessario", "confidence": 1.0, "auto_accept": True}
            else:
                cat = self.categorizer.categorize(p["description"], hour)
            version, _ = ctx.policies.active()
            tx_id = self.store.x(
                "INSERT INTO ledger(event_id,kind,amount_cents,description,category,tag,confidence,auto_accepted,policy_version,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (event_id, kind, p["amount_cents"], p["description"], cat["category"], cat["tag"], cat["confidence"],
                 int(cat["auto_accept"]), version, payload.get("at", time.time())))
            violations = finance.check_invariants(self.store)
            if violations:
                raise ValueError("invariante violado; lançamento desfeito: " + "; ".join(violations))
            if kind == "despesa":
                self.shadow.record(tx_id, cat, p["description"], hour)
            check = "" if cat["auto_accept"] else " (baixa confiança: o loop reclassifica sozinho quando aprender mais)"
            msg = f"#{tx_id} {fmt_brl(p['amount_cents'])} {p['description']} → {cat['category']}/{cat['tag']}{check}"
        elif kind == "correcao":
            msg = self.correct(p["tx_id"], p.get("args", []))
        elif kind == "confirmacao":
            self.store.x("UPDATE ledger SET status='confirmed' WHERE id=? AND status='open'", (p["tx_id"],))
            msg = f"#{p['tx_id']} confirmado."
        else:
            msg = "Não entendi como lançamento. Ex.: '38,90 ifood almoço', '+5000 salário', 'corrige 12 mercado'."
        ctx.reply(msg)
        return msg

    def submit_project(self, pedido: str) -> int:
        return self.store.enqueue("novo_projeto", {"pedido": pedido, "at": time.time()})

    def new_project(self, payload: dict) -> dict:
        res = intake(self.store, self.ctx.dl, payload["pedido"])
        self.ctx.dl.project_id = res["id"]
        if res["novo"]:
            self.graph.conectar(res["id"])     # a missão nova já nasce conhecendo as outras
        if not res["novo"]:
            self.ctx.reply("Esse pedido é do projeto que já existe; ele continua evoluindo por lá.")
        elif res["status"] == "aguardando_kit":
            self.ctx.reply("Projeto criado e registrado. O círculo ainda não tem o kit para construir este tipo de "
                           "solução; o pedido fica guardado e passa a ser atendido quando o kit existir.")
        else:
            self.ctx.reply("Projeto criado. O círculo começou a trabalhar nele.")
        return res

    def correct(self, tx_id: int, args: list[str]) -> str:
        policy = self.ctx.policy
        row = self.store.one("SELECT * FROM ledger WHERE id=?", (tx_id,))
        if not row:
            return f"Lançamento #{tx_id} não existe."
        cat = next((a for a in args if a in policy["categories"]), None)
        tag = next((a for a in args if a in ("necessario", "escolha", "impulso")), None)
        if not cat and not tag:
            return f"Use: corrige {tx_id} <categoria> [necessario|escolha|impulso]. Categorias: {', '.join(policy['categories'])}"
        now = time.time()
        if cat and cat != row["category"]:
            self.store.x("INSERT INTO feedback(tx_id,field,old_value,new_value,created_at) VALUES(?,?,?,?,?)", (tx_id, "category", row["category"], cat, now))
        if tag and tag != row["tag"]:
            self.store.x("INSERT INTO feedback(tx_id,field,old_value,new_value,created_at) VALUES(?,?,?,?,?)", (tx_id, "tag", row["tag"], tag, now))
        changed = (cat and cat != row["category"]) or (tag and tag != row["tag"])
        self.store.x("UPDATE ledger SET category=?, tag=?, status=? WHERE id=?",
                     (cat or row["category"], tag or row["tag"], "corrected" if changed else "confirmed", tx_id))
        return f"#{tx_id} → {cat or row['category']}/{tag or row['tag']}. Anotado para aprender."

    # ------------------------------------------------------------ evolução natural (sem input)
    def idle(self) -> str | None:
        ctx, s = self.ctx, self.store
        self._stage("idle")
        tasks = list(ctx.policy["idle"]["tasks"])
        if ctx.dl.llm is not None and "propor_feature" not in tasks:
            tasks.append("propor_feature")
        if self.engine.ready and self.engine.candidates() and "evoluir_projeto" not in tasks:
            tasks.append("evoluir_projeto")
        if self.store.one("SELECT COUNT(*) n FROM projects WHERE kit!='circulo' AND status!='arquivado'")["n"] >= 2 \
                and "conectar_missoes" not in tasks:
            tasks.append("conectar_missoes")
        if self.engine.ready and "evoluir_harness" not in tasks:
            tasks.append("evoluir_harness")
        if self.self_dev is not None and self.self_dev.tem_trabalho() and "corrigir_codigo" not in tasks:
            tasks.append("corrigir_codigo")
        if self.corpo is not None and self._corpo_precisa() and "atualizar_corpo" not in tasks:
            tasks.append("atualizar_corpo")
        if self.self_dev is not None and self.estudo.precisa() and "estudar_pedido" not in tasks:
            tasks.append("estudar_pedido")
        if self.planejador.precisa() and "planejar_roteiro" not in tasks:
            tasks.append("planejar_roteiro")
        if self.gate is not None and "revisar_prs" not in tasks:
            tasks.append("revisar_prs")
        if self.controls()["modo_seguro"]:
            # só tarefas de baixo risco: nada de evoluir regras, gerar features ou mergear
            tasks = [t for t in tasks if t in ("analisar_padroes", "rodar_regressao", "resumo", "evoluir_projeto")]
        componente = {"revisar_baixa_confianca": "meta", "evoluir_harness": "meta"}   # (corrigir_codigo tem quarentena própria)
        tasks = [t for t in tasks if not self.incidents.isolated(f"idle:{t}")
                 and not (t in componente and self.incidents.isolated(componente[t]))]
        if not tasks:
            return None
        # Cascata: regra antes do Jev. Trabalho real (missões, código, PRs) tem precedência e roda a cada giro
        # enquanto existir; manutenção gira em rodízio (a mais esquecida primeiro). O Jev decide o gasto.
        last = s.get("idle_last", {})
        staleness = {t: s.tick - int(last.get(t, -10**6)) for t in tasks}
        # recusado pelo porteiro do gasto: espera cada vez mais antes de tentar de novo (1, 2, 4… até 64 giros)
        recusas = (s.get("progresso") or {}).get("recusas") or {}
        trabalho = [t for t in TRABALHO if t in tasks and staleness[t] >= max(ESPACO.get(t, 1), min(64, 2 ** int(recusas.get(t, 0))) if recusas.get(t) else 1)
                    and self._tem_trabalho(t)]
        manut = sorted((t for t in tasks if t not in TRABALHO or t == "revisar_prs"),
                       key=lambda t: (-staleness[t], tasks.index(t)))
        manut = [t for t in manut if t not in trabalho]
        if not trabalho and len(manut) > 1:
            # a regra estreita para as 3 mais esquecidas; o Jev escolhe entre elas (o rodízio é garantido)
            top = manut[:3]
            escolha = ctx.dl.ask("idle_task", Question("choice", "Qual tarefa de manutenção tem mais valor agora?",
                                                       {x: x.replace("_", " ") for x in top}),
                                 {"staleness": {x: min(staleness[x], 10**4) for x in top}}).value
            if escolha in top:
                manut.remove(escolha)
                manut.insert(0, escolha)
        ordem = trabalho + manut
        for pick in ordem:
            est = IDLE_COST.get(pick, 0)
            if est > 0:   # só pergunta ao Jev quando há gasto
                contexto = {"est_tokens": est, "value_signal": VALOR.get(pick, 0.6), "task": pick,
                            "esquecida_ha_giros": min(staleness[pick], 10**4)}
                if pick == "corrigir_codigo" and self.self_dev is not None:
                    item = self.self_dev.alvo()
                    if item:   # o Jev vê o que seria feito: seu pedido no roteiro ou erro recorrente
                        contexto.update({"item": item["titulo"], "origem": item["origem"]})
                gate = ctx.dl.worth_spending("idle_evolution", contexto)
                if not gate.allowed:
                    last[pick] = s.tick           # recusado agora: volta para o fim da fila
                    pg = s.get("progresso") or {"sem": 0}
                    pg.setdefault("recusas", {})[pick] = int(pg["recusas"].get(pick, 0)) + 1
                    s.set("progresso", pg)
                    continue
            if pick not in ("corrigir_codigo", "evoluir_projeto"):
                self._stage("idle", {"detalhe": TAREFAS.get(pick, pick)})
            try:
                self._run_idle_task(pick)
            except Exception as exc:  # noqa: BLE001
                last[pick] = s.tick
                s.set("idle_last", last)
                self.incidents.record(f"idle:{pick}", exc, ctx.dl.project_id)
                exc._registrado = True
                raise
            last[pick] = s.tick
            s.set("idle_last", last)
            return pick
        s.set("idle_last", last)
        return None

    def _corpo_precisa(self) -> bool:
        try:
            return self.corpo.precisa()
        except Exception:  # noqa: BLE001 — rede fora: tenta de novo na próxima checagem
            return False

    def _tem_trabalho(self, t: str) -> bool:
        if t == "evoluir_projeto":
            return bool(self.engine.ready and self.engine.candidates())
        if t == "corrigir_codigo":
            return self.self_dev is not None and self.self_dev.tem_trabalho()
        if t == "planejar_roteiro":
            return self.planejador.precisa()
        if t == "atualizar_corpo":
            return self.corpo is not None and self._corpo_precisa()
        if t == "estudar_pedido":
            return self.self_dev is not None and self.estudo.precisa()
        if t == "revisar_prs":
            return self.store.one("SELECT COUNT(*) n FROM prs WHERE status='aberto'")["n"] > 0
        return False

    # ------------------------------------------------------------ neurônio de progresso
    def _progresso(self) -> tuple:
        """Fotografia do que conta como avanço: roteiro, estudos, chamadas de LLM, PRs, merges, código rodando."""
        s = self.store
        r = s.one("SELECT COUNT(*) n, MAX(updated_at) u, SUM(estudo IS NOT NULL) e FROM roadmap")
        return (r["n"], r["u"], r["e"], s.one("SELECT COUNT(*) n FROM llm_calls")["n"], s.one("SELECT COUNT(*) n FROM merges")["n"],
                s.one("SELECT COUNT(*) n FROM prs")["n"], (s.get("corpo") or {}).get("sha"),
                s.one("SELECT COUNT(*) n FROM deliverables")["n"])

    def _vigiar_progresso(self, havia_trabalho: bool, antes: tuple, r) -> None:
        """Girar sem avançar é um erro de estrutura, não "tudo bem". Havia trabalho e nada mudou por ESTAGNADO giros:
        vira lição (com a causa: as recusas de gasto), a confiança do painel cai e o ritmo vai para o descanso longo."""
        s = self.store
        st = s.get("progresso") or {"sem": 0}
        if not havia_trabalho or self._progresso() != antes:
            if st.get("sem", 0) >= ESTAGNADO:
                from .licoes import registrar as monitorar
                monitorar(self.ctx, "loop:progresso", True, sujeito=f"voltou a avançar depois de {st['sem']} giros")
            s.set("progresso", {"sem": 0, "ultimo_avanco_em": time.time(), "recusas": {}})
            return
        st["sem"] = int(st.get("sem", 0)) + 1
        st.setdefault("desde", time.time())
        if st["sem"] in (ESTAGNADO, ESTAGNADO * 5, ESTAGNADO * 25):
            rec = st.get("recusas") or {}
            causa = ", ".join(f"{t} recusado {n}x" for t, n in sorted(rec.items(), key=lambda kv: -kv[1])) or "sem recusa registrada"
            from .licoes import registrar as monitorar
            monitorar(self.ctx, "loop:progresso", False, sujeito=f"{st['sem']} giros sem avançar",
                      motivo=f"havia trabalho pendente e nada avançou em {st['sem']} giros; causa provável: {causa}",
                      assinatura="loop:estagnado", classe="estrutural")
            self.ctx.reply(f"Estagnação: há trabalho esperando e nada avançou em {st['sem']} giros ({causa}).", "saude")
        s.set("progresso", st)

    def trabalho_pendente(self, ignorar_estagnacao: bool = False) -> bool:
        """Há trabalho real esperando? Então o próximo giro vem logo, em vez do descanso longo.
        Estagnado (girando sem avançar), o ritmo rápido não ajuda: vai para o descanso longo."""
        if self.controls()["pausado"]:
            return False
        if not ignorar_estagnacao and int((self.store.get("progresso") or {}).get("sem", 0)) >= 3:
            return False
        try:
            # só conta o trabalho que pode rodar AGORA: esperar o espaçamento (ESPACO, recusas) não é estagnação
            s = self.store
            last = s.get("idle_last", {}) or {}
            rec = (s.get("progresso") or {}).get("recusas") or {}
            def pronto(t):
                espera = max(ESPACO.get(t, 1), min(64, 2 ** int(rec[t])) if rec.get(t) else 1)
                return s.tick - int(last.get(t, -10**6)) >= espera
            return any(pronto(t) and self._tem_trabalho(t) for t in TRABALHO)
        except Exception:  # noqa: BLE001
            return False

    def reclassificar_pendentes(self, limite: int = 20) -> int:
        """Autocorreção em finanças, sem perguntar: lançamentos de baixa confiança são reclassificados
        com as regras atuais (que evoluíram desde então). Só troca quando a confiança nova passa o limiar."""
        fin = kit_project_id(self.store, "financas")
        prev = self.ctx.dl.project_id
        self.ctx.dl.project_id = fin
        n = 0
        try:
            thr = self.ctx.policy["thresholds"]["auto_accept_category"]
            for r in self.store.q("SELECT id, description, created_at FROM ledger WHERE kind='despesa' AND status='open' "
                                  "AND auto_accepted=0 ORDER BY id DESC LIMIT ?", (limite,)):
                hour = datetime.fromtimestamp(r["created_at"], TZ).hour
                cat = self.categorizer.categorize(r["description"], hour)
                if cat["confidence"] >= thr and cat["category"] != "outros":
                    v, _ = self.ctx.policies.active()
                    self.store.x("UPDATE ledger SET category=?, tag=?, confidence=?, auto_accepted=1, policy_version=? WHERE id=?",
                                 (cat["category"], cat["tag"], cat["confidence"], v, r["id"]))
                    n += 1
        finally:
            self.ctx.dl.project_id = prev
        return n

    def _run_idle_task(self, pick: str) -> None:
        if pick == "analisar_padroes":
            self.analyst.scan()
        elif pick == "revisar_baixa_confianca":
            self.meta.step()
            self.reclassificar_pendentes()
        elif pick == "conectar_missoes":
            self.graph.conectar_todas()
        elif pick == "rodar_regressao":
            self.regression()
        elif pick == "resumo":
            self.write_summary()
        elif pick == "propor_feature":
            self.developer.idle()
        elif pick == "revisar_prs":
            self.gate.run()
        elif pick == "planejar_roteiro":
            self.planejador.run(autorizado=True)       # o gasto já foi decidido acima: um porteiro só
        elif pick == "estudar_pedido":
            self.estudo.run(autorizado=True)
        elif pick == "atualizar_corpo":
            from .corpo_caminho import atualizar_corpo
            atualizar_corpo(self.corpo)    # lição #1: arquivo não rastreado que a main traz não trava a troca
        elif pick == "corrigir_codigo":
            item = self.self_dev.alvo()
            self._stage("developer", {"projeto": kit_project_id(self.store, "circulo"),
                                      "detalhe": f"Claude Code trabalhando em: {item['titulo']}" if item else None})
            res = self.self_dev.run_once(autorizado=True)
            if item and res.status not in ("proposto", "consertado"):
                # tudo o que o Developer tentou fica visível na linha do tempo, inclusive o que não deu certo
                self.ctx.reply(f"Developer: “{item['titulo']}” → {res.status}: {str(res.detalhe or '')[:160]}", "saude")
        elif pick == "evoluir_harness":
            self.lab.evaluate() or self.lab.maybe_propose()
        elif pick == "evoluir_projeto":
            # várias missões ao mesmo tempo; cada uma deixa a passagem na trilha do círculo
            self.engine.run_parallel(on_stage=lambda nome, pid, detalhe=None: self._stage(nome, {"projeto": pid, "detalhe": detalhe}))

    def regression(self) -> dict:
        """Replay da política ativa sobre todo o histórico resolvido; guarda a acurácia como linha de base."""
        from .decision import LocalJev
        rules = self.ctx.policy["rules"]
        rows = self.store.q("SELECT description, category FROM ledger WHERE kind='despesa' AND status IN ('confirmed','corrected')")
        if not rows:
            return {}
        hits = sum(((LocalJev.match_rule(r["description"], rules) or {}).get("category", "outros")) == r["category"] for r in rows)
        acc = hits / len(rows)
        prev = self.store.get("regression_baseline")
        self.store.set("regression_baseline", {"accuracy": acc, "n": len(rows), "tick": self.store.tick})
        if prev and acc + 0.05 < prev["accuracy"]:
            self.ctx.reply(f"Regressão: acurácia caiu de {prev['accuracy']:.0%} para {acc:.0%}.", "saude")
        return {"accuracy": acc, "n": len(rows)}

    # ------------------------------------------------------------ métricas e resumo
    def _record(self, r: TickResult) -> None:
        body = {"handled": r.handled_event, "idle": r.idle_task, "evolutions": r.evolutions, "shadow": r.shadow,
                "health": r.health, "errors": r.errors, "budget": self.ctx.budget.snapshot()}
        self.store.x("INSERT OR REPLACE INTO metrics(tick,body,created_at) VALUES(?,?,?)",
                     (r.tick, json.dumps(body, ensure_ascii=False), time.time()))

    def status(self) -> dict:
        s = self.store
        v, _ = self.ctx.policies.active()
        sh = self.ctx.policies.shadow()
        return {
            "tick": s.tick, "loop": s.get("loop_status", "parado"), "politica_ativa": v,
            "shadow": sh[0] if sh else None, "pendentes": s.pending_count(),
            "orcamento": self.ctx.budget.snapshot(), "painel": self.planner.report(),
            "propostas": {r["status"]: r["c"] for r in s.q("SELECT status, COUNT(*) c FROM proposals GROUP BY status")},
            "jev": self.ctx.dl.jev.source,
            "licoes": self.licoes.resumo(),
        }

    def write_summary(self) -> Path:
        s = self.store
        day = self.ctx.now().astimezone(TZ).date().isoformat()
        st = self.status()
        props = s.q("SELECT status, level, description, notes FROM proposals WHERE updated_at > ? ORDER BY id",
                    (time.time() - 86400,))
        alerts = s.q("SELECT kind, message FROM alerts WHERE kind!='resposta' AND delivered=0 ORDER BY id")
        lines = [f"# Resumo do círculo — {day}", "", f"- {st['painel']}",
                 f"- Tick {st['tick']} · loop {st['loop']} · política v{st['politica_ativa']}"
                 f"{' · shadow v' + str(st['shadow']) if st['shadow'] else ''} · decisor: {st['jev']}",
                 f"- Orçamento hoje: {st['orcamento']['tokens']}/{st['orcamento']['limite']} tokens · "
                 f"{st['orcamento']['chamadas_jev']} perguntas ao Jev · {st['orcamento']['chamadas_llm']} chamadas LLM",
                 "", "## Evoluções (24h)"]
        lines += [f"- [{r['status']}] nível {r['level']}: {r['description']}" for r in props] or ["- nenhuma"]
        lines += ["", "## Alertas"] + ([f"- ({a['kind']}) {a['message']}" for a in alerts] or ["- nenhum"])
        out = self.data_dir / "resumos" / f"{day}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        s.x("UPDATE alerts SET delivered=1 WHERE kind!='resposta' AND delivered=0")
        return out

    # ------------------------------------------------------------ para sempre
    def stop(self, *_):
        self._stop.set()

    HEARTBEAT_EVERY = 5.0   # segundos; o painel considera o loop desligado sem batimento por 3x isso

    def _tick_com_pulso(self) -> "TickResult":
        """O batimento continua DURANTE o giro. Antes ele só era escrito entre giros: uma etapa longa (o Developer
        trabalhando 8 min) deixava o painel mostrando "Desligado" com o loop trabalhando."""
        parar = threading.Event()

        def pulso():
            while not parar.wait(self.HEARTBEAT_EVERY):
                try:
                    self.heartbeat()
                except Exception:  # noqa: BLE001 — o pulso nunca derruba o giro
                    pass
        t = threading.Thread(target=pulso, name="pulso", daemon=True)
        t.start()
        try:
            return self.tick()
        finally:
            parar.set()
            t.join(timeout=2)

    def heartbeat(self, proximo_giro: float | None = None) -> None:
        self.store.set("batimento", {"em": time.time(), "pid": os.getpid(), "proximo_giro_em": proximo_giro})

    def _rest(self, total: float, sleep: Callable[[float], None], wake_on_input: bool = True) -> None:
        """Descansa em pedaços curtos: mantém o batimento e acorda cedo se chegar pedido novo."""
        remaining = max(0.0, float(total))
        self.heartbeat(time.time() + remaining)
        while remaining > 0 and not self._stop.is_set():
            chunk = min(self.HEARTBEAT_EVERY, remaining)
            sleep(chunk)
            remaining -= chunk
            self.heartbeat(time.time() + remaining)
            if wake_on_input and self.store.pending_count() > 0 and not self.controls()["pausado"]:
                return
            if self._config_mudou():          # você salvou as chaves: não espera o fim do descanso
                return

    def _config_mudou(self) -> bool:
        from .configuracao import ENV_FILE
        if getattr(self, "_env_mtime", "nunca") == "nunca":
            return False
        atual = ENV_FILE.stat().st_mtime if ENV_FILE.exists() else None
        return atual != self._env_mtime and self.store.get("reiniciar_ao_mudar_config", True)

    def run_forever(self, max_ticks: int | None = None, sleep: Callable[[float], None] | None = None) -> None:
        sleep = sleep or (lambda sec: self._stop.wait(sec))
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self.stop)
            signal.signal(signal.SIGINT, self.stop)
        self.store.set("loop_iniciado_em", time.time())
        from .configuracao import ENV_FILE
        self._env_mtime = ENV_FILE.stat().st_mtime if ENV_FILE.exists() else None
        n = 0
        try:
            while not self._stop.is_set():
                # configuração mudou (você salvou as chaves): sai limpo; o serviço 24/7 sobe de novo já com elas
                if self._config_mudou():
                    self.store.set("ultimo_reinicio", {"em": time.time(), "motivo": "configuração alterada"})
                    break
                self.heartbeat()
                r = self._tick_com_pulso()
                n += 1
                if self.corpo is not None and self.corpo.reiniciar:
                    # código novo (ou rollback): sai limpo; o serviço 24/7 sobe de novo já nele
                    self.store.set("ultimo_reinicio", {"em": time.time(), "motivo": self.corpo.reiniciar})
                    break
                if max_ticks is not None and n >= max_ticks:
                    break
                loop = self.ctx.policy["loop"]
                if r.paused and r.pause_reason == "humano":
                    self._rest(2, sleep, wake_on_input=False)                    # confere o botão com frequência
                elif r.paused:
                    self._rest(min(self.ctx.budget.seconds_until_reset(), 600), sleep, wake_on_input=False)
                elif self.store.pending_count() > 0:
                    continue
                else:
                    pendente = self.trabalho_pendente()
                    self.store.set("trabalho_pendente", pendente)
                    self._rest(loop["interval_seconds"] if (r.handled_event or pendente) else loop["idle_interval_seconds"], sleep)
        finally:
            self.store.set("batimento", None)
        self.store.set("loop_status", "parado")

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
from .engine import Engine
from .incidents import Incidents
from .memory import Memory
from .projects import ensure_seed, intake, kit_project_id
from .money import fmt_brl
from .policy import PolicyStore
from .state import Store

IDLE_COST = {"analisar_padroes": 0, "revisar_baixa_confianca": 0, "rodar_regressao": 0, "resumo": 0, "propor_feature": 1500, "revisar_prs": 0, "evoluir_projeto": 9000}


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
                 gate: MergeGate | None = None):
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
        self.meta = MetaLearner(self.ctx)
        self.shadow = Shadow(self.ctx)
        self.health = HealthMonitor(self.ctx)
        self.gate = gate if gate is not None else build_gate(self.ctx)
        self.memory = Memory(self.ctx.store, self.ctx.dl)
        self.engine = Engine(self.ctx, self.memory)
        self.ctx.store.set("motor_pronto", self.engine.ready)
        self.incidents = Incidents(self.ctx.store, self.ctx.dl, self.ctx.reply, lambda: kit_project_id(self.ctx.store, "circulo"))
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
        """Etapa atual do giro, para o painel ao vivo."""
        self.store.set("etapa", {"nome": name, "tick": self.store.tick, "em": time.time(),
                                 "projeto": self.ctx.dl.project_id, **(extra or {})})

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
        circulo_pid = kit_project_id(s, "circulo")
        ctx.dl.project_id = circulo_pid          # fora de um pedido, quem trabalha é o próprio círculo
        self._stage("orquestrador")
        self.incidents.resolve_stale()
        self.engine.reopen_stale()
        finance.age_open_transactions(s)

        # 1) pedido (prioridade) ou 2) evolução natural
        ev = s.claim_next_event()
        if ev:
            r.handled_event = ev["id"]
            payload = json.loads(ev["payload"])
            pid = None if ev["kind"] == "novo_projeto" else (payload.get("projeto") or kit_project_id(s, "financas"))
            self._stage("pedido", {"evento": ev["id"], "projeto": pid})
            ctx.dl.project_id = pid
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
        else:
            try:
                r.idle_task = self.idle()
            except Exception as exc:  # noqa: BLE001
                r.errors.append(f"idle: {exc!r}")
                if not getattr(exc, "_registrado", False):
                    self.incidents.record("idle", exc, circulo_pid)

        # 3) meta-evolução (descoberta é SQL; gasto só se o Jev autorizar).
        #    Modo seguro congela os níveis 2 e 3: só a saúde continua rodando (e pode fazer rollback).
        stages = [("health", self.health.check)]
        if not ctl["modo_seguro"]:
            stages = [("meta", self.meta.step), ("shadow", self.shadow.evaluate)] + stages
        for stage, fn in stages:
            if self.incidents.isolated(stage):
                continue                       # autocorreção: etapa em quarentena não roda
            self._stage({"meta": "meta_learner", "shadow": "shadow", "health": "saude"}[stage])
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
                self.shadow.record(tx_id, cat["confidence"], cat["category"])
            check = "" if cat["auto_accept"] else f" — confere? responda 'corrige {tx_id} <categoria> [tag]' ou 'ok {tx_id}'"
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
        if self.gate is not None and "revisar_prs" not in tasks:
            tasks.append("revisar_prs")
        if self.controls()["modo_seguro"]:
            # só tarefas de baixo risco: nada de evoluir regras, gerar features ou mergear
            tasks = [t for t in tasks if t in ("analisar_padroes", "rodar_regressao", "resumo", "evoluir_projeto")]
        run = ctx.dl.ask("should_run_idle", Question("noul", "Vale rodar uma tarefa de evolução natural agora?"),
                         {"pending_events": s.pending_count(), "budget_left_ratio": round(ctx.budget.left_ratio(), 3)})
        if float(run.value) < 0.5:
            return None
        componente = {"revisar_baixa_confianca": "meta"}   # tarefa que usa uma etapa isolada também fica de fora
        tasks = [t for t in tasks if not self.incidents.isolated(f"idle:{t}")
                 and not (t in componente and self.incidents.isolated(componente[t]))]
        if not tasks:
            return None
        last = s.get("idle_last", {})
        staleness = {t: (s.tick - int(last.get(t, 0))) * (2 if t == "evoluir_projeto" else 1) for t in tasks}
        pick = ctx.dl.ask("idle_task", Question("choice", "Qual tarefa de evolução natural tem mais valor agora?",
                                                {t: t.replace("_", " ") for t in tasks}), {"staleness": staleness}).value
        gate = ctx.dl.worth_spending("idle_evolution", {"est_tokens": IDLE_COST.get(pick, 0), "value_signal": 0.6, "task": pick})
        if not gate.allowed:
            return None
        try:
            self._run_idle_task(pick)
        except Exception as exc:  # noqa: BLE001
            self.incidents.record(f"idle:{pick}", exc, ctx.dl.project_id)
            exc._registrado = True
            raise
        last[pick] = s.tick
        s.set("idle_last", last)
        return pick

    def _run_idle_task(self, pick: str) -> None:
        if pick == "analisar_padroes":
            self.analyst.scan()
        elif pick == "revisar_baixa_confianca":
            self.meta.step()
        elif pick == "rodar_regressao":
            self.regression()
        elif pick == "resumo":
            self.write_summary()
        elif pick == "propor_feature":
            self.developer.idle()
        elif pick == "revisar_prs":
            self.gate.run()
        elif pick == "evoluir_projeto":
            pid = self.engine.next_project()
            if pid is not None:
                self._stage("projeto", {"projeto": pid})
                self.engine.cycle(pid)

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

    def run_forever(self, max_ticks: int | None = None, sleep: Callable[[float], None] | None = None) -> None:
        sleep = sleep or (lambda sec: self._stop.wait(sec))
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self.stop)
            signal.signal(signal.SIGINT, self.stop)
        self.store.set("loop_iniciado_em", time.time())
        n = 0
        try:
            while not self._stop.is_set():
                self.heartbeat()
                r = self.tick()
                n += 1
                if max_ticks is not None and n >= max_ticks:
                    break
                loop = self.ctx.policy["loop"]
                if r.paused and r.pause_reason == "humano":
                    self._rest(2, sleep, wake_on_input=False)                    # confere o botão com frequência
                elif r.paused:
                    self._rest(min(self.ctx.budget.seconds_until_reset(), 600), sleep, wake_on_input=False)
                elif self.store.pending_count() > 0:
                    continue
                elif r.handled_event:
                    self._rest(loop["interval_seconds"], sleep)
                else:
                    self._rest(loop["idle_interval_seconds"], sleep)
        finally:
            self.store.set("batimento", None)
        self.store.set("loop_status", "parado")

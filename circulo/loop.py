"""O círculo: loop infinito, Jev First, retoma de onde parou, pausa só por orçamento."""
from __future__ import annotations

import json
import os
import signal
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import finance, ingestao, intencoes, jobs, jtbd, parada, revisor, telemetria
from .agents import Analyst, Categorizer, Collector, Ctx, Developer, Planner
from .budget import TZ, Budget
from .decision import SN, Decision, DecisionLayer, Gate, JevClient, LLMClient, Question, build_jev
from . import caixa, cao_de_guarda
from .llm import build_llm
from .evolution import HealthMonitor, MetaLearner, Shadow
from .merge_gate import MergeGate, build_gate
from . import guardrails
from .engine import Engine
from .estagnacao import anotar_giro, causa_provavel, pode_rodar
from .graph import MissionGraph
from .harness_lab import HarnessLab
from .reparo import build_developer
from .self_dev import SelfDeveloper
from .incidents import Incidents
from .memory import Memory
from .metrics import METRICAS, Metricas, seguro
from .projects import ensure_seed, intake, kit_project_id
from .money import fmt_brl
from .orcamento_dia import avisar_marcos, com_tokens_dia
from .policy import PolicyStore
from .state import Store

TRABALHO = ("atualizar_corpo", "evoluir_projeto", "estudar_pedido", "corrigir_codigo", "revisar_prs", "planejar_roteiro", "indagar", "pesquisar_mercado")
ESPACO = {"corrigir_codigo": 2, "revisar_prs": 2}   # em giros; com o descanso longo (5 min), 10 giros eram 50 min de espera
CONF_PARA_BARRAR = 0.5  # o Jev só barra uma tarefa que destrava a fila se disser "não" com confiança >= isto; abaixo, a regra decide
ESPERA_EM_VOO = 45     # s: há trabalho em voo (PR no CI, tarefa no espaçamento, corpo validando) — não dorme 5 min
ESTAGNADO = 10      # giros com trabalho pendente e nada avançando = estagnação (lição de estrutura)
RASTRO_A_CADA = 20          # a cada 20 giros, confere o fio de ponta a ponta das entregas recentes
VALOR = {"atualizar_corpo": 0.9, "estudar_pedido": 0.85, "planejar_roteiro": 0.8, "corrigir_codigo": 0.85, "evoluir_projeto": 0.8, "revisar_prs": 0.7, "evoluir_harness": 0.6, "propor_feature": 0.5}
TAREFAS = {"documentar": "Redator técnico: atualizando a documentação do loop em docs/", "analisar_padroes": "Procurando padrões nos gastos", "revisar_baixa_confianca": "Revendo o que decidiu com pouca confiança",
           "rodar_regressao": "Rodando a regressão sobre o histórico", "resumo": "Escrevendo o resumo", "propor_feature": "Propondo uma melhoria",
           "revisar_prs": "Revisando PRs abertos no gate", "evoluir_harness": "Testando prompts por A/B", "conectar_missoes": "Ligando missões que se complementam",
           "evoluir_projeto": "Evoluindo missões", "corrigir_codigo": "Corrigindo o próprio código",
           "planejar_roteiro": "Planejando o próximo item do roteiro a partir da evidência",
           "estudar_pedido": "Estudando o pedido em fontes confiáveis antes de executar",
           "atualizar_corpo": "Validando e passando a rodar o código que o loop evoluiu",
           "jardinagem": "Medindo padrões ruins se espalhando no próprio código",
           "checar_licoes": "Reexecutando no main os testes das lições para fechar ou reabrir",
           "indagar": "Indagador: levantando as perguntas da missão e passando cada uma pelo Jev",
           "antecipar": "Preparando antes do pedido o que você pediu 3 ou mais vezes na semana",
           "pesquisar_mercado": "Pesquisador: o que as melhores fábricas de software com IA fazem e o loop ainda não (semanal)"}
IDLE_COST = {"documentar": 0, "analisar_padroes": 0, "revisar_baixa_confianca": 0, "rodar_regressao": 0, "resumo": 0, "propor_feature": 1500, "revisar_prs": 0, "evoluir_projeto": 0, "evoluir_harness": 800, "conectar_missoes": 0, "corrigir_codigo": 0, "planejar_roteiro": 6000, "estudar_pedido": 30000, "pesquisar_mercado": 30000}  # Developer: assinatura, não API; estudo: ~30 mil com a busca


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
    inicio: float = field(default_factory=time.time)
    run_id: str | None = None


class Circle:
    def __init__(self, data_dir: str | Path = "data", jev: JevClient | None = None, llm: LLMClient | None = None,
                 now: Callable[[], datetime] | None = None, db_path: str | None = None,
                 gate: MergeGate | None = None, self_dev: SelfDeveloper | None = None, metricas: Metricas | None = None,
                 dono: bool = True):
        """`dono=False`: segundo processo sobre o mesmo banco (controle, `circulo dev`): não recupera eventos, não devolve
        itens do Developer à fila nem restaura snapshot — isso é do loop que roda (antes, reinício do controle duplicava PR)."""
        self.data_dir, self.dono = Path(data_dir), dono
        self.metricas = metricas if metricas is not None else METRICAS
        from .guardrails import restaurar_se_pedido
        restaurado = restaurar_se_pedido(self.data_dir, Path(db_path or (self.data_dir / "circulo.db"))) if dono else None   # rollback de dados pedido pelo corpo
        store = Store(db_path or (self.data_dir / "circulo.db"))
        if restaurado:
            store.x("INSERT INTO alerts(kind,message,created_at,delivered) VALUES('saude',?,?,0)", (f"Banco restaurado do snapshot {Path(restaurado['snapshot']).name} ({restaurado['motivo']}).", time.time()))
        policies = PolicyStore(store)
        now = now or (lambda: datetime.now(TZ))
        budget = Budget(store, lambda: com_tokens_dia(policies.get()), now)
        dl = DecisionLayer(store, policies.get, budget, jev=jev if jev is not None else build_jev(),
                           llm=llm if llm is not None else build_llm())
        if jev is None and not os.environ.get("JEV_MODEL") and store.get("jev_modelo") and getattr(dl.jev, "source", "") == "jev":
            dl.jev.model = store.get("jev_modelo")    # doc da TypeSafe: versão fixa para os limiares calibrados não derivarem (pin automático)
        dl.metricas = self.metricas
        self.ctx = Ctx(store, policies, budget, dl, self.data_dir, now)
        self.collector = Collector(self.ctx)
        self.categorizer = Categorizer(self.ctx)
        self.analyst = Analyst(self.ctx)
        self.planner = Planner(self.ctx)
        self.developer = Developer(self.ctx)
        from .licoes import Licoes
        self.licoes = Licoes(self.ctx.store, self.ctx.reply)
        self.ctx.licoes = self.licoes         # todo ponto de verificação do círculo registra aqui
        from .memoria import Memoria
        self.memoria = Memoria(self.ctx.store)
        self.ctx.memoria = self.memoria       # o que o time já viu, recuperado por relevância na hora de cada tarefa
        self.meta = MetaLearner(self.ctx)
        self.shadow = Shadow(self.ctx)
        self.health = HealthMonitor(self.ctx)
        self.gate = gate if gate is not None else build_gate(self.ctx)
        self.memory = Memory(self.ctx.store, self.ctx.dl)
        self.lab = HarnessLab(self.ctx)
        self.engine = Engine(self.ctx, self.memory, self.lab)
        from .vigia import Vigia
        self.vigia = Vigia(self.ctx)          # vigia as travas da autoevolução em paralelo ao giro
        self.graph = MissionGraph(self.ctx, self.memory)
        self.engine.graph = self.graph
        self.engine.on_stage = lambda nome, pid: self._stage(nome, {"projeto": pid})
        self.self_dev = self_dev if self_dev is not None else build_developer(self.ctx)
        if self.self_dev is not None and dono:
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
        self.vigia.planejador = self.planejador   # trava de pergunta validada além do prazo: o Vigia drena a mais antiga
        self.ctx.policies.before_change = lambda: guardrails.snapshot(self.ctx.store, self.data_dir, "mudanca")
        self.ctx.store.set("motor_pronto", self.engine.ready)
        self.incidents = Incidents(self.ctx.store, self.ctx.dl, self.ctx.reply, lambda: kit_project_id(self.ctx.store, "circulo"))
        self.incidents.licoes = self.licoes
        finance.base(store)
        ensure_seed(store)
        recovered = store.recover_interrupted() if dono else []
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
        seguro(self.metricas.etapa, name)      # a etapa anterior termina aqui: duração no histograma do /metrics
        now = time.time()
        e = {"nome": name, "tick": self.store.tick, "em": now, "projeto": self.ctx.dl.project_id,
             "run_id": self.store.get("run_id"), **(extra or {})}
        self.store.set("etapa", e)
        seq = self.store.x("INSERT INTO trail(tick,etapa,project_id,em,detalhe,run_id,tarefa) VALUES(?,?,?,?,?,?,?)",
                           (e["tick"], name, e["projeto"], now, e.get("detalhe"), e["run_id"], e.get("tarefa")))
        if seq % 500 == 0:
            self.store.x("DELETE FROM trail WHERE seq < ?", (seq - 2000,))   # trilha é efêmera (só para animação)

    # ------------------------------------------------------------ entrada
    def submit(self, text: str, at: float | None = None) -> int:
        return self.store.enqueue("mensagem", {"text": text, "at": at if at is not None else time.time()})

    # ------------------------------------------------------------ um giro do círculo
    def tick(self) -> TickResult:
        s, ctx = self.store, self.ctx
        if getattr(self, "dono", True):
            caixa.ler(s, self.data_dir)              # pedidos deixados como arquivo em <dados>/caixa/ viram eventos (só o dono do banco escreve)
        ctl = self.controls()
        avisar_marcos(s, ctx.budget, ctx.reply)
        if ctl["pausado"] or ctx.budget.exhausted():
            s.set("run_id", None)                # giro que não roda não é execução: nada a rastrear
        if ctl["pausado"]:
            s.set("loop_status", "pausado_humano")
            self._stage("pausado")
            parada.confirmar(s)                  # a parada só vale quando o próprio loop diz que parou
            return TickResult(s.tick, paused=True, pause_reason="humano")
        if ctx.budget.exhausted():
            s.set("loop_status", "pausado_orcamento")
            self._stage("pausado")
            return TickResult(s.tick, paused=True, pause_reason="orcamento")
        s.set("loop_status", "modo_seguro" if ctl["modo_seguro"] else "rodando")
        r = TickResult(s.next_tick())
        r.run_id = uuid.uuid4().hex[:12]
        s.set("run_id", r.run_id)
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
        seguro(ingestao.girar, self.data_dir / "extratos", s)   # extrato em <data>/extratos vira lançamento; sem ele, pedido

        ev = s.claim_next_event()   # 1) pedido (prioridade) ou 2) evolução natural
        if ev:
            r.handled_event = ev["id"]
            payload = json.loads(ev["payload"])
            pid = None if ev["kind"] == "novo_projeto" else (payload.get("projeto") or kit_project_id(s, "financas"))
            self._stage("pedido", {"evento": ev["id"], "projeto": pid})
            ctx.dl.project_id = pid
            ctx.evento = ev["id"]
            seguro(jobs.registrar, ctx, ev["id"])   # o job do pedido: regra calibrada; 'desconhecido' antes da LLM
            seq = None
            try:
                seq = intencoes.registrar(s, f"pedido:{ev['kind']}", "pedido seu na fila vem antes da evolução natural",   # write-ahead: a intenção entra na trilha antes; sem registro, o pedido não é executado
                                          {"evento": ev["id"], "texto": str(payload.get("text") or payload.get("pedido") or "")[:200]},
                                          regra="regra: a fila de pedidos tem prioridade")
                with s.tx():
                    if ev["kind"] == "novo_projeto":
                        self.new_project(payload)
                    else:
                        self.handle(payload, ev["id"])
                s.finish_event(ev["id"], True)
                intencoes.concluir(s, seq, True)
            except Exception as exc:  # o círculo não pode morrer
                if seq is not None:
                    intencoes.concluir(s, seq, False, repr(exc))
                s.finish_event(ev["id"], False, repr(exc))
                r.errors.append(f"evento {ev['id']}: {exc!r}")
                self.incidents.record(f"pedido:{ev['kind']}", exc, pid)
            finally:
                ctx.dl.project_id = circulo_pid
                ctx.evento = None
        else:
            try:
                r.idle_task = self.idle()
            except Exception as exc:
                r.errors.append(f"idle: {exc!r}")
                if not getattr(exc, "_registrado", False):
                    self.incidents.record("idle", exc, circulo_pid)
        seguro(self.planejador.no_giro)          # pergunta reagendada após 5xx/timeout volta no giro em que vence

        stages = [("licoes", self.licoes.revisar), ("health", self.health.check)]   # 3) meta-evolução (descoberta é SQL; gasto só se o Jev autorizar). Modo seguro congela os níveis 2 e 3: só a saúde roda.
        if not ctl["modo_seguro"]:
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
            except Exception as exc:
                r.errors.append(f"{stage}:{exc!r}\n{traceback.format_exc(limit=3)}")
                self.incidents.record(stage, exc, circulo_pid)

        try:
            self._vigiar_progresso(havia_trabalho, antes, r)
        except Exception as exc:
            r.errors.append(f"progresso:{exc!r}")
        if self.corpo is not None:
            try:
                self.corpo.validar(r.errors)     # evidência depois da troca de código: os primeiros giros
            except Exception as exc:
                r.errors.append(f"corpo:{exc!r}")
        self._record(r)
        telemetria.registrar_ciclo(s, self.data_dir, r.run_id, r.tick, r.inicio, erros=r.errors)
        try:
            from . import observabilidade, rastro
            observabilidade.exportar_em_segundo_plano(s.path, self.data_dir)
            if r.tick % RASTRO_A_CADA == 0:
                rastro.verificar(ctx)
                from . import jev_lab
                jev_lab.avaliar(s, ctx.reply)        # adota (ou desfaz) a forma de perguntar ao Jev que provou ganho
        except Exception as exc:  # observar nunca derruba o giro
            r.errors.append(f"rastro: {exc!r}")
        self._stage("descanso")
        seguro(self.metricas.ciclo_concluido, s)
        s.set("run_id", None)                   # erro fora do giro (ex.: teste da parada) não cai na execução que já fechou
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
            now = time.time()   # falar com o loop: vira pedido seu no roteiro do próprio loop
            ordem = (self.store.one("SELECT COALESCE(MAX(ordem),0) m FROM roadmap")["m"] or 0) + 1
            item = self.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                                (payload["text"][:160], payload["text"][:600], "pedido_cassio", "pendente", "pedido pelo painel", ordem, now, now))
            from .rastro import elo
            elo(self.store, f"pedido:{event_id}", f"item:{item}", "virou_item")
            self.memory.add("feedback", payload["text"], project_id=pid, source="Cássio", trust="confiavel")
            from . import indagador
            indagador.classificar_pedido(self.ctx, payload["text"], item)      # anota eixo e pertinência; a fila é a mesma
            na_frente = self.store.one("SELECT COUNT(*) n FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 "
                                       "AND evidencia NOT LIKE '%depende de você%' AND ordem < ?", (ordem,))["n"]
            msg = (f"Anotado no roteiro como item #{item}. O Developer pega na ordem"
                   + (f"; há {na_frente} na frente." if na_frente else ": é o próximo.")
                   + " Se não quiser que ele mexa nisso, desative o item no roteiro.")
            self.ctx.reply(msg)
            return msg
        if proj is not None and proj["kit"] != "financas":
            self.memory.add("feedback", payload["text"], tipo=None, project_id=pid, source="Cássio", trust="confiavel")   # orientação do humano para um projeto: vira feedback confiável na memória e reabre o projeto
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
    def _trabalho_pronto(self, tasks) -> list[str]:
        """Trabalho real entre `tasks` que pode rodar AGORA: esperar o espaçamento (ESPACO) ou a recusa do porteiro do gasto
        (1, 2, 4… até 64 giros) não é estagnação. Única regra do idle e do trabalho_pendente (lição #47)."""
        s = self.store
        last, recusas = s.get("idle_last", {}) or {}, (s.get("progresso") or {}).get("recusas") or {}
        return [t for t in TRABALHO if t in tasks and s.tick - int(last.get(t, -10**6)) >= max(ESPACO.get(t, 1), min(64, 2 ** int(recusas.get(t, 0))) if recusas.get(t) else 1)
                and self._tem_trabalho(t)]

    def idle(self) -> str | None:
        ctx, s = self.ctx, self.store
        self._stage("idle")
        tasks = list(ctx.policy["idle"]["tasks"])
        if ctx.dl.llm is not None and "propor_feature" not in tasks:
            tasks += ["propor_feature", "pesquisar_mercado"]
        if self.engine.ready and self.engine.candidates() and "evoluir_projeto" not in tasks:
            tasks.append("evoluir_projeto")
        if self.store.one("SELECT COUNT(*) n FROM projects WHERE kit!='circulo' AND status!='arquivado'")["n"] >= 2 \
                and "conectar_missoes" not in tasks:
            tasks.append("conectar_missoes")
        if self.engine.ready and "evoluir_harness" not in tasks:
            tasks.append("evoluir_harness")
        from . import jardineiro
        if jardineiro.precisa(self.store) and "jardinagem" not in tasks:
            tasks.append("jardinagem")
        if self.corpo is not None and self.licoes.a_checar_no_main() and "checar_licoes" not in tasks:
            tasks.append("checar_licoes")
        from . import indagador
        if indagador.precisa(self.store, self.engine) and "indagar" not in tasks:
            tasks.append("indagar")
        if jtbd.precisa(self.store) and "antecipar" not in tasks:
            tasks.append("antecipar")
        from . import documentador
        if self.gate is not None and documentador.precisa(self.store) and "documentar" not in tasks:
            tasks.append("documentar")
        if self._dev_tem_trabalho() and "corrigir_codigo" not in tasks:
            tasks.append("corrigir_codigo")
        if self.corpo is not None and self._corpo_precisa() and "atualizar_corpo" not in tasks:
            tasks.append("atualizar_corpo")
        if self.self_dev is not None and self.estudo.precisa() and "estudar_pedido" not in tasks:
            tasks.append("estudar_pedido")
        if self.planejador.precisa() and "planejar_roteiro" not in tasks:
            tasks.append("planejar_roteiro")
        if self.gate is not None and "revisar_prs" not in tasks:
            tasks.append("revisar_prs")
        seguro = self.controls()["modo_seguro"]     # modo seguro só deixa baixo risco: nada de evoluir regras, features ou merge
        tasks = [t for t in tasks if pode_rodar(s, self.incidents, t, seguro)]
        if not tasks:
            return None
        last = s.get("idle_last", {})   # Cascata: regra antes do Jev. Trabalho real tem precedência a cada giro; manutenção gira em rodízio. O Jev decide o gasto.
        staleness = {t: s.tick - int(last.get(t, -10**6)) for t in tasks}
        trabalho = self._trabalho_pronto(tasks)
        manut = sorted((t for t in tasks if t not in TRABALHO or t == "revisar_prs"),
                       key=lambda t: (-staleness[t], tasks.index(t)))
        manut = [t for t in manut if t not in trabalho]
        if not trabalho and len(manut) > 1:
            top = manut[:3]   # a regra estreita para as 3 mais esquecidas; o Jev escolhe entre elas (o rodízio é garantido)
            escolha = ctx.dl.ask("idle_task", Question("choice", "Qual tarefa de manutenção tem mais valor agora?",
                                                       {x: f"{TAREFAS.get(x, x.replace('_', ' '))} (esquecida há {min(staleness[x], 10**4)} giros)" for x in top}),
                                 {"staleness": {x: min(staleness[x], 10**4) for x in top}}).value
            if escolha in top:
                probs = getattr(d_idle, "probabilities", {}) if (d_idle := getattr(ctx.dl, "ultima_decisao", None)) else {}
                ordenadas = sorted(((float(probs.get(x, 0)), x) for x in top), reverse=True)
                if len(ordenadas) > 1 and ordenadas[0][0] - ordenadas[1][0] < 0.10 and probs:
                    escolha = max(top, key=lambda x: staleness[x])   # empate técnico no Jev: a mais esquecida (regra)
                manut.remove(escolha)
                manut.insert(0, escolha)
        ordem = trabalho + manut
        escolhida_pelo_jev = None if trabalho or len(manut) <= 1 else manut[0]
        for pick in ordem:
            est = IDLE_COST.get(pick, 0)
            contexto = {"task": pick, "esquecida_ha_giros": min(staleness[pick], 10**4)}
            regra = ("regra: trabalho real roda a cada giro enquanto existir" if pick in trabalho else
                     "Jev escolheu entre as 3 manutenções mais esquecidas" if pick == escolhida_pelo_jev else
                     "regra: rodízio de manutenção, a mais esquecida primeiro")
            if est > 0:   # só pergunta ao Jev quando há gasto
                contexto.update({"est_tokens": est, "value_signal": VALOR.get(pick, 0.6)})
                if pick == "planejar_roteiro":
                    from . import indagador
                    pv = indagador.espiar(s, "loop")
                    if pv:   # a pergunta já passou pelo Jev: o gasto é para respondê-la, e o valor vem da classificação dela
                        contexto.update({"pergunta_validada": pv["texto"][:200], "eixo": pv["eixo"],
                                         "pertinencia": pv["pertinencia"], "fila_do_developer": 0 if self.self_dev is None or
                                         self.self_dev.pick() is None else 1,
                                         "value_signal": max(VALOR.get(pick, 0.6), round(0.6 + 0.35 * float(pv["pertinencia"] or 0), 3))})
                if pick == "corrigir_codigo" and self.self_dev is not None:
                    item = self.self_dev.alvo()
                    if item:   # o Jev vê o que seria feito: seu pedido no roteiro ou erro recorrente
                        contexto.update({"item": item["titulo"], "origem": item["origem"]})
                if pick == "estudar_pedido":
                    it = self.estudo.pendente() or {}   # o Jev vê o item e o que o estudo destrava (no Mac ele recusou o estudo por 4 h com p≈0,3 e o Developer parado)
                    fila = 0 if self.self_dev is None or self.self_dev.pick() is None else 1
                    est = self.estudo.custo_estimado(it or None)          # custo medido do modo (dispensado = 0, leve, completo)
                    from .estudo import modo_do_estudo
                    contexto.update({"est_tokens": est, "modo_estudo": modo_do_estudo(it) if it else None,
                                     "item_esperando_estudo": (it.get("titulo") or "")[:160], "origem": it.get("origem"), "fila_do_developer": fila,
                                     "itens_esperando_estudo": s.one("SELECT COUNT(*) n FROM roadmap WHERE status='pendente' AND estudo IS NULL "
                                                                     "AND origem IN ('loop','pedido_cassio') AND COALESCE(desativado,0)=0")["n"],
                                     "desbloqueia_fila": fila == 0, "value_signal": max(VALOR.get(pick, 0.6), 0.95 if fila == 0 else 0.85)})
                if pick == "planejar_roteiro":
                    contexto.setdefault("desbloqueia_fila", contexto.get("fila_do_developer") == 0 and not self.estudo.precisa())
                if int(contexto.get("est_tokens") or 0) <= 0:
                    gate = None                                           # custo zero (estudo dispensado): não há gasto a decidir
                else:
                    gate = ctx.dl.worth_spending("idle_evolution", contexto)
                d0 = gate.decision if gate else None
                if gate is not None and not gate.allowed and contexto.get("desbloqueia_fila") and d0.source == "jev" \
                        and float(d0.confidence) < CONF_PARA_BARRAR and ctx.budget.can_spend(int(contexto["est_tokens"])):
                    estado = {"action": "idle_evolution", **contexto, "budget_left_ratio": round(ctx.budget.left_ratio(), 3)}   # "não" do Jev com confiança média só alerta: a regra decide e a resposta fica para o aprendiz.
                    r = ctx.dl.local.ask_many(estado, {"worth_spending": Question("noul", "vale gastar agora?", SN("sim", "não"))})[0]["worth_spending"]
                    gate = Gate(float(r.value) >= gate.threshold, r, gate.threshold)
                    regra += f"; Jev disse não com confiança média ({float(d0.confidence):.2f}) numa tarefa que destrava a fila: a regra decidiu ({float(r.value):.2f})"
                if pick == "planejar_roteiro" and gate is not None:
                    from .planejador import registrar_porteiro
                    registrar_porteiro(s, pv["id"] if pv else None, gate)
                if gate is None:
                    regra += "; sem gasto (estudo dispensado: evidência interna medida)"
                    gate = Gate(True, Decision("worth_spending", "noul", 1.0, 1.0, "local"), 0.0, "sem gasto")
                d = gate.decision
                regra += f"; gasto autorizado por {d.source} ({float(d.value):.2f} ≥ {gate.threshold:.2f})"
                if not gate.allowed:
                    last[pick] = s.tick           # recusado agora: volta para o fim da fila
                    pg = s.get("progresso") or {"sem": 0}
                    recusas = pg.setdefault("recusas", {})   # antes de ler: o lado direito da atribuição roda primeiro
                    recusas[pick] = int(recusas.get(pick, 0)) + 1
                    s.set("progresso", pg)
                    continue
            if pick not in ("corrigir_codigo", "evoluir_projeto"):
                self._stage("idle", {"detalhe": TAREFAS.get(pick, pick), "tarefa": pick})
            try:
                intencoes.executar(s, pick, lambda pick=pick: self._run_idle_task(pick), motivo=TAREFAS.get(pick, pick),   # write-ahead: intenção (motivo, regra que decidiu, entradas) gravada antes; só então a tarefa roda
                                   entradas=contexto, regra=regra)
            except Exception as exc:
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
        except Exception:  # rede fora: tenta de novo na próxima checagem
            return False

    def _dev_tem_trabalho(self) -> bool:
        """A fila do Developer, mais o sub-item liberado de um item dividido (que a fila normal não pega)."""
        dev = self.self_dev
        if dev is None:
            return False
        from . import fatiador
        return dev.tem_trabalho() or (not dev.busy() and not dev.em_espera() and fatiador.tem_trabalho(self.store))

    def _tem_trabalho(self, t: str) -> bool:
        if t == "evoluir_projeto":
            return bool(self.engine.ready and self.engine.candidates())
        if t == "corrigir_codigo":
            return self._dev_tem_trabalho()
        if t == "planejar_roteiro":
            return self.planejador.precisa()
        if t == "atualizar_corpo":
            return self.corpo is not None and self._corpo_precisa()
        if t == "estudar_pedido":
            return self.self_dev is not None and self.estudo.precisa()
        if t == "revisar_prs":
            return self.store.one("SELECT COUNT(*) n FROM prs WHERE status='aberto'")["n"] > 0
        if t == "indagar":
            from . import indagador
            return indagador.precisa(self.store, self.engine)
        if t == "pesquisar_mercado":
            from . import mercado
            return self.ctx.dl.llm is not None and mercado.devida(self.store)
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
        vira lição (com a causa medida em estagnacao), a confiança do painel cai e o ritmo vai para o descanso longo."""
        s = self.store
        st = s.get("progresso") or {"sem": 0}
        if not havia_trabalho or self._progresso() != antes:
            if st.get("sem", 0) >= ESTAGNADO:
                from .licoes import registrar as monitorar
                monitorar(self.ctx, "loop:progresso", True, sujeito=f"voltou a avançar depois de {st['sem']} giros")
            s.set("progresso", {"sem": 0, "ultimo_avanco_em": time.time(), "recusas": {}, "rodou": {}})
            return
        st["sem"] = int(st.get("sem", 0)) + 1
        st.setdefault("desde", time.time())
        anotar_giro(st, r)
        if st["sem"] in (ESTAGNADO, ESTAGNADO * 5, ESTAGNADO * 25):
            causa = causa_provavel(st)
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
            seguro = self.controls()["modo_seguro"]   # o que o idle barra não está pendente (lição #47)
            return bool(self._trabalho_pronto([t for t in TRABALHO if pode_rodar(self.store, self.incidents, t, seguro)]))
        except Exception:
            return False

    def em_voo(self) -> bool:
        """Trabalho a caminho que ainda não pode rodar neste giro: PR do Developer esperando CI/gate, tarefa com trabalho
        dentro do espaçamento ou da recusa, corpo validando código novo. Não é 'pendente' (que pede giro de 15 s), mas
        também não é ócio (5 min)."""
        if self.controls()["pausado"]:
            return False
        s = self.store
        if s.one("SELECT COUNT(*) n FROM prs WHERE status='aberto'")["n"] > 0:
            return True
        if (s.get("corpo") or {}).get("estado") == "validando":
            return True
        from .planejador import REAGENDA
        if s.get(REAGENDA):
            return True
        return any(self._tem_trabalho(t) for t in TRABALHO)

    def ritmo(self, r, pendente: bool) -> tuple[str, float]:
        """(modo, segundos) do descanso: rápido com trabalho pronto, em voo com trabalho a caminho, ocioso sem nada."""
        loop = self.ctx.policy["loop"]
        if r.handled_event or pendente:
            return "rapido", loop["interval_seconds"]
        if self.em_voo():
            return "em_voo", min(ESPERA_EM_VOO, loop["idle_interval_seconds"])
        return "ocioso", loop["idle_interval_seconds"]

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
            revisor.revisar(self.store, self.gate, repo=getattr(self.self_dev, "repo", None))   # adia com backoff; grava arquivos em conflito
        elif pick == "planejar_roteiro":
            self.planejador.run(autorizado=True)       # o gasto já foi decidido acima: um porteiro só
        elif pick == "estudar_pedido":
            self.estudo.run_paralelo(autorizado=True)          # 1 trabalhador por padrão; o Escalador pode subir
        elif pick == "antecipar":
            jtbd.antecipar(self.store)
        elif pick == "pesquisar_mercado":
            from . import mercado
            mercado.pesquisar(self.ctx)
        elif pick == "documentar":
            from . import documentador
            documentador.rodar(self.ctx, gh=getattr(self.gate, "gh", None))
        elif pick == "atualizar_corpo":
            from .corpo_caminho import atualizar_corpo
            atualizar_corpo(self.corpo)    # lição #1: arquivo não rastreado que a main traz não trava a troca
        elif pick == "corrigir_codigo":
            from . import fatiador
            livre = not (self.self_dev.busy() or self.self_dev.em_espera()) and self.self_dev._conserto() is None   # conserto de PR reprovado vem antes de tudo (o sub-item seguinte esperava o PR que ninguém consertava: 45 min parado)
            item_id = fatiador.proximo(self.ctx, self.self_dev, self.planejador) if livre else None
            if livre and item_id is None:
                return
            r = self.store.one("SELECT * FROM roadmap WHERE id=?", (item_id,)) if item_id else None
            item = dict(r) if r else self.self_dev.alvo()
            self._stage("developer", {"projeto": kit_project_id(self.store, "circulo"), "tarefa": "corrigir_codigo",
                                      "detalhe": f"Claude Code trabalhando em: {item['titulo']}" if item else None})
            res = self.self_dev.run_paralelo(item_id=item_id, autorizado=True) if livre else self.self_dev.run_once(item_id=item_id, autorizado=True)
            if item and res.status not in ("proposto", "consertado"):
                self.ctx.reply(f"Developer: “{item['titulo']}” → {res.status}: {str(res.detalhe or '')[:160]}", "saude")   # tudo o que o Developer tentou fica visível na linha do tempo, inclusive o que não deu certo
        elif pick == "evoluir_harness":
            self.lab.evaluate() or self.lab.maybe_propose()
        elif pick == "jardinagem":
            from . import jardineiro
            jardineiro.podar(self.store, self.ctx.reply)
        elif pick == "checar_licoes":
            self.licoes.checar_no_main(self.corpo.repo)
        elif pick == "indagar":
            from . import indagador
            res = indagador.rodar(self.ctx, self.engine)        # inclui uma dúvida do Jev estudada pelo Arquiteto e reclassificada
            if res and res["cerebro"] == "loop" and (res["validas"] or res.get("duvida_valida")):
                seguro(self.planejador.no_giro, validou=True)   # a pergunta validada vira item neste giro (falha fica em TENTATIVAS)
        elif pick == "evoluir_projeto":
            # várias missões ao mesmo tempo; cada uma deixa a passagem na trilha do círculo
            self.engine.run_parallel(on_stage=lambda nome, pid, detalhe=None: self._stage(nome, {"projeto": pid, "detalhe": detalhe,
                                                                                               "tarefa": "evoluir_projeto"}))

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
        body = {"run_id": r.run_id, "handled": r.handled_event, "idle": r.idle_task, "evolutions": r.evolutions, "shadow": r.shadow,
                "health": r.health, "errors": r.errors, "budget": self.ctx.budget.snapshot(),
                "duracao_ms": round(1000 * (time.time() - r.inicio))}   # sinal de ouro: latência do giro
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

    def testar_parada(self) -> bool | None:
        try:
            return parada.testar(self)
        except Exception as exc:  # o teste nunca derruba o loop; a falha vira incidente
            self.incidents.record("parada", exc, kit_project_id(self.store, "circulo"))
            return False

    # ------------------------------------------------------------ para sempre
    def stop(self, *_):
        self._stop.set()

    HEARTBEAT_EVERY = 5.0   # segundos; o painel considera o loop desligado sem batimento por 3x isso

    def _tick_com_pulso(self) -> "TickResult":
        """O batimento continua DURANTE o giro. Antes ele só era escrito entre giros: uma etapa longa (o Developer
        trabalhando 8 min) deixava o painel mostrando "Desligado" com o loop trabalhando."""
        parar, inicio = threading.Event(), time.time()

        def pulso():
            while not parar.wait(self.HEARTBEAT_EVERY):
                try:
                    self.heartbeat()
                    if getattr(self, "dono", True):
                        cao_de_guarda.reiniciar_se_preso(self.store, inicio, self.ctx.reply)   # giro preso sem sinal: o launchd sobe um limpo
                except Exception:  # o pulso nunca derruba o giro
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
        # chave cadastrada/trocada no painel (cofre do sistema): o arquivo pode nem mudar
        no_painel = float(self.store.get("config_alterada_em") or 0) > float(getattr(self, "_iniciado_em", time.time()))
        return (atual != self._env_mtime or no_painel) and self.store.get("reiniciar_ao_mudar_config", True)

    def run_forever(self, max_ticks: int | None = None, sleep: Callable[[float], None] | None = None) -> None:
        sleep = sleep or (lambda sec: self._stop.wait(sec))
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self.stop)
            signal.signal(signal.SIGINT, self.stop)
        self.store.set("loop_iniciado_em", time.time())
        from .configuracao import ENV_FILE
        self._env_mtime = ENV_FILE.stat().st_mtime if ENV_FILE.exists() else None
        self._iniciado_em = time.time()
        if getattr(self, "controle", None) is None:
            self.vigia.iniciar()                           # sem plano de controle separado: o SRE roda aqui
        n = 0
        try:
            while not self._stop.is_set():
                # configuração mudou (você salvou as chaves): sai limpo; o serviço 24/7 sobe de novo já com elas
                if self._config_mudou():
                    self.store.set("ultimo_reinicio", {"em": time.time(), "motivo": "configuração alterada"})
                    break
                self.heartbeat()
                if getattr(self, "controle", None) is not None and self.controle.cuidar() == "desistiu":
                    self.controle.assumir(self)            # o filho caiu demais: painel e SRE voltam para cá
                if parada.teste_vencido(self.store):
                    self.testar_parada()             # kill switch testado toda semana, pelo mesmo caminho do botão
                r = self._tick_com_pulso()
                n += 1
                if self.corpo is not None and self.corpo.reiniciar:
                    # código novo (ou rollback): sai limpo; o serviço 24/7 sobe de novo já nele
                    self.store.set("ultimo_reinicio", {"em": time.time(), "motivo": self.corpo.reiniciar})
                    break
                if max_ticks is not None and n >= max_ticks:
                    break
                if r.paused and r.pause_reason == "humano":
                    self._rest(2, sleep, wake_on_input=False)                    # confere o botão com frequência
                elif r.paused:
                    self._rest(min(self.ctx.budget.seconds_until_reset(), 600), sleep, wake_on_input=False)
                elif self.store.pending_count() > 0:
                    continue
                else:
                    pendente = self.trabalho_pendente()
                    self.store.set("trabalho_pendente", pendente)
                    modo, segundos = self.ritmo(r, pendente)
                    self.store.set("ritmo", {"modo": modo, "segundos": segundos, "em": time.time()})
                    self._rest(segundos, sleep)
        finally:
            self.vigia.parar()
            if getattr(self, "controle", None) is not None:
                self.controle.parar()
            self.store.set("batimento", None)
        self.store.set("loop_status", "parado")

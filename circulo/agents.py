"""Agentes de domínio. Todos decidem via DecisionLayer (Jev First)."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import finance
from .budget import Budget
from .decision import DecisionLayer, LocalJev, Question, norm, SN
from .money import find_amount, fmt_brl
from .policy import PolicyStore, fingerprint
from .state import Store

STOPWORDS = {"de", "da", "do", "das", "dos", "no", "na", "com", "para", "pra", "um", "uma", "e", "o", "a", "em", "por"}

TAG_Q = {"necessario": "Essencial para a família", "escolha": "Consciente, mas adiável", "impulso": "Não planejado / emocional"}


@dataclass
class Ctx:
    store: Store
    policies: PolicyStore
    budget: Budget
    dl: DecisionLayer
    data_dir: Path
    now: Callable[[], datetime]
    evento: int | None = None          # pedido em atendimento: a resposta fica ligada a ele (conversa no painel)

    @property
    def policy(self) -> dict:
        return self.policies.get()

    def reply(self, message: str, kind: str = "resposta") -> None:
        self.store.x("INSERT INTO alerts(kind,message,created_at,project_id,evento) VALUES(?,?,?,?,?)",
                     (kind, message, time.time(), self.dl.project_id, self.evento))


def tokens_of(description: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", norm(description))
            if len(w) >= 3 and not w.isdigit() and w not in STOPWORDS]


# ------------------------------------------------------------------ Collector

class Collector:
    """Ingere a mensagem e decide (Jev) que tipo de input é."""

    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    def parse(self, text: str) -> dict:
        found = None
        try:
            found = find_amount(text.lstrip("+"))
        except ValueError:
            found = None
        cmd = re.match(r"^\s*(corrige|corrigir|categoria|ok|confirma)\s+(\d+)\s*(.*)$", norm(text))
        state = {"text": text, "has_amount": bool(found) and not cmd}
        d = self.ctx.dl.ask("input_type", Question("choice", "Que tipo de mensagem é esta para o controle financeiro?", {
            "despesa": "Registro de gasto", "receita": "Registro de entrada de dinheiro",
            "correcao": "Correção de categoria/tag de um lançamento", "confirmacao": "Confirma que um lançamento está certo",
            "desconhecido": "Não é um registro financeiro"}), state)
        out = {"type": d.value, "confidence": d.confidence, "text": text}
        if found and d.value in ("despesa", "receita"):
            out["amount_cents"], out["description"] = found
            out["description"] = out["description"].lstrip("+").strip() or "sem descrição"
        if cmd:
            out["tx_id"] = int(cmd.group(2))
            out["args"] = cmd.group(3).split()
        return out


# ------------------------------------------------------------------ Categorizer

class Categorizer:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    def questions(self, policy: dict) -> dict[str, Question]:
        cats = {c: c.replace("_", " ") for c in policy["categories"]}
        return {
            "category": Question("choice", "Em que categoria entra este lançamento da família?", cats),
            "spend_tag": Question("choice", policy["questions"]["spend_tag_instructions"], TAG_Q),
        }

    def categorize(self, description: str, hour: int) -> dict:
        policy = self.ctx.policy
        state = {"description": description, "hour": hour, "regras": policy["rules"]}
        qs = self.questions(policy)
        res = self.ctx.dl.ask_many(state, qs)  # categoria + tag em paralelo, uma chamada
        cat = res["category"]
        if cat.confidence < policy["thresholds"]["llm_fallback_below"]:
            cat = self.ctx.dl.choose("category", qs["category"], state)
        thr = policy["thresholds"]["auto_accept_category"]
        return {
            "category": cat.value, "tag": res["spend_tag"].value, "confidence": cat.confidence,
            "auto_accept": cat.confidence >= thr and cat.value != "outros", "source": cat.source,
        }


# ------------------------------------------------------------------ Analyst

class Analyst:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    def features(self) -> dict:
        since = time.time() - 30 * 86400
        s = self.ctx.store
        tot = s.one("SELECT COALESCE(SUM(amount_cents),0) t FROM ledger WHERE kind='despesa' AND created_at>=?", (since,))["t"]
        imp = s.one("SELECT COALESCE(SUM(amount_cents),0) t FROM ledger WHERE kind='despesa' AND tag='impulso' AND created_at>=?", (since,))["t"]
        dlv = s.one("SELECT COUNT(*) c, COALESCE(SUM(amount_cents),0) t FROM ledger WHERE category='delivery' AND created_at>=?", (since,))
        top = s.q("SELECT category, SUM(amount_cents) t FROM ledger WHERE kind='despesa' AND created_at>=? GROUP BY category ORDER BY t DESC LIMIT 3", (since,))
        return {"total_30d_cents": tot, "share_impulso": round(imp / tot, 3) if tot else 0.0,
                "delivery_count_30d": dlv["c"], "delivery_30d_cents": dlv["t"],
                "top": [(r["category"], r["t"]) for r in top]}

    def scan(self) -> str | None:
        f = self.features()
        if f["total_30d_cents"] == 0:
            return None
        d = self.ctx.dl.ask("alert_pattern", Question("noul", "Este padrão de gasto merece um alerta para a família (impacta a meta da casa)?",
                                                     SN("`share_impulso` alto ou `delivery_count_30d` frequente, com valor que pesa em `total_30d_cents`: afasta a meta da casa",
                                                        "gastos dentro do padrão, impulso baixo, nada que mude o caminho até a casa")), f)
        if float(d.value) < self.ctx.policy["thresholds"]["alert_pattern"]:
            return None
        msg = (f"Últimos 30 dias: {fmt_brl(f['total_30d_cents'])} em despesas; "
               f"impulso = {round(f['share_impulso'] * 100)}%; delivery {f['delivery_count_30d']}x "
               f"({fmt_brl(f['delivery_30d_cents'])}).")
        recent = self.ctx.store.one("SELECT 1 FROM alerts WHERE kind='padrao' AND message=? AND created_at>?", (msg, time.time() - 86400))
        if not recent:
            self.ctx.reply(msg, "padrao")
        return msg


# ------------------------------------------------------------------ Planner

class Planner:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    def report(self) -> str:
        s = finance.snapshot(self.ctx.store, self.ctx.now())
        meses = "—" if s.meses_ate_meta is None else str(s.meses_ate_meta)
        return (f"Patrimônio líquido {fmt_brl(s.patrimonio_liquido_cents)} | reserva {fmt_brl(s.reserva_cents)} | "
                f"casa {s.progresso_bp / 100:.1f}% de {fmt_brl(s.meta_casa_cents)} | sobra do mês {fmt_brl(s.sobra_mes_cents)} | "
                f"meses até a meta no ritmo do mês: {meses}")


# ------------------------------------------------------------------ Developer

class Developer:
    """Propõe features. Só gasta LLM se o Jev autorizar. Código gerado vai para PR, nunca direto em produção."""

    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    def idle(self) -> str | None:
        llm = self.ctx.dl.llm
        if llm is None or not self.ctx.policy["agents"].get("developer_enabled", True):
            return None
        gate = self.ctx.dl.worth_spending("developer_feature", {"est_tokens": 1500, "value_signal": 0.55})
        if not gate.allowed:
            return None
        feats = Analyst(self.ctx).features()
        backlog = [r["description"] for r in self.ctx.store.q("SELECT description FROM proposals WHERE kind='feature' ORDER BY id DESC LIMIT 10")]
        text, used = llm.complete(
            "Você é o Developer do círculo financeiro da família. Proponha UMA feature pequena e testável, em uma frase.",
            f"Métricas: {json.dumps(feats, ensure_ascii=False)}\nJá no backlog: {backlog}", max_tokens=200)
        self.ctx.budget.charge(used, "llm")
        idea = text.strip()[:400]
        if idea:
            now = time.time()
            self.ctx.store.x("INSERT INTO proposals(level,kind,fingerprint,description,patch,evidence,status,created_at,updated_at) "
                             "VALUES(1,'feature',?,?,'[]','{}','backlog',?,?)", (fingerprint(idea), idea, now, now))
        return idea


# ------------------------------------------------------------------ Reviewers

class ReviewerFinance:
    """Valida propostas por replay determinístico + invariantes; decisão final tipada via Jev."""

    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    def replay(self, old: dict, new: dict) -> dict:
        rows = self.ctx.store.q("SELECT description, category FROM ledger WHERE status IN ('confirmed','corrected')")
        breaks = fixes = 0
        for r in rows:
            o = LocalJev.match_rule(r["description"], old["rules"])
            n = LocalJev.match_rule(r["description"], new["rules"])
            ok_old = (o["category"] if o else "outros") == r["category"]
            ok_new = (n["category"] if n else "outros") == r["category"]
            breaks += ok_old and not ok_new
            fixes += ok_new and not ok_old
        return {"resolved": len(rows), "replay_breaks": breaks, "replay_fixes": fixes}

    def review(self, level: int, old: dict, new: dict) -> tuple[str, dict]:
        rep = self.replay(old, new)
        violations = finance.check_invariants(self.ctx.store)
        state = {"level": level, "invariants_ok": not violations, **rep}
        d = self.ctx.dl.ask("review_finance", Question("choice", "Esta mudança de política é segura para as finanças da família?", {
            "approve": "Aplicar", "shadow": "Rodar em paralelo antes", "reject": "Descartar"}), state)
        verdict = d.value
        # Regras críticas não negociáveis, independentes do Jev:
        if violations or rep["replay_breaks"] > 0:
            verdict = "reject"
        if level >= 2 and verdict == "approve":
            verdict = "shadow"
        return verdict, {**state, "jev": d.value, "jev_conf": d.confidence}


class ReviewerCode:
    """Gate para PRs do Developer (usado pelo fluxo de GitHub/CI)."""

    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    def review(self, tests_ok: bool, lines_changed: int, touches_money_code: bool) -> str:
        d = self.ctx.dl.ask("review_code", Question("choice", "Este PR pode ser mergeado automaticamente?", {
            "approve": "Merge automático", "changes": "Precisa de ajustes", "reject": "Descartar"}),
            {"tests_ok": tests_ok, "lines_changed": lines_changed, "touches_money_code": touches_money_code})
        if not tests_ok:
            return "reject"
        if touches_money_code and d.value == "approve":
            return "changes"  # código de dinheiro nunca entra sem revisão humana no resumo
        # roteamento por confiança (doc do Jev): aprovação automática só com o Jev seguro; em dúvida, pede ajustes
        if d.value == "approve" and d.source == "jev" and d.confidence < self.ctx.policy["thresholds"].get("review_code_confianca", 0.5):
            return "changes"
        return d.value

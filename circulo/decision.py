"""DecisionLayer — Jev First.

Todo ponto do círculo que vai gastar recurso pergunta primeiro aqui.
- JevHttpClient: API real da TypeSafe (POST https://api.typesafe.ai/v1/systemone).
- LocalJev: decisor determinístico com o MESMO contrato, usado quando não há chave ou a API falha.
Ambos recebem o mesmo `state` + `questions`, então trocar um pelo outro não muda os agentes.
"""
from __future__ import annotations

import json
import math
import os
import re
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Protocol

from .budget import Budget
from .state import Store

Kind = Literal["choice", "score", "noul"]


# ---------------------------------------------------------------- contrato

@dataclass(frozen=True)
class Question:
    kind: Kind
    instructions: str
    criteria: Mapping[str, str] | tuple[str, ...] | None = None  # choice: {opção: descrição}; score: (nível0, nível1, ...)

    def options(self) -> tuple[str, ...]:
        if self.kind == "choice":
            return tuple(self.criteria or {})
        return ()


@dataclass(frozen=True)
class Decision:
    name: str
    kind: Kind
    value: Any                      # choice: str | score: float | noul: float 0..1
    confidence: float               # noul: |2p-1|
    source: str                     # jev | local | llm
    probabilities: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Gate:
    allowed: bool
    decision: Decision
    threshold: float
    reason: str = ""


class JevClient(Protocol):
    source: str

    def ask_many(self, state: Mapping[str, Any], questions: Mapping[str, Question]) -> tuple[dict[str, Decision], int]:
        """Retorna (decisões, tokens_de_entrada)."""


class LLMClient(Protocol):
    def complete(self, system: str, prompt: str, max_tokens: int) -> tuple[str, int]:
        """Retorna (texto, tokens_totais)."""


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


# ---------------------------------------------------------------- Jev real

class JevHttpClient:
    source = "jev"
    URL = "https://api.typesafe.ai/v1/systemone"

    def __init__(self, api_key: str, model: str = "jev-latest", timeout: float = 5.0):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def ask_many(self, state, questions):
        body = {"state": state, "model": self.model, "questions": {}}
        for qid, q in questions.items():
            item: dict[str, Any] = {"type": q.kind, "instructions": q.instructions}
            if q.kind == "choice":
                item["criteria"] = dict(q.criteria or {})
            elif q.kind == "score":
                item["criteria"] = list(q.criteria or ())
            body["questions"][qid] = item
        req = urllib.request.Request(
            self.URL,
            data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        out: dict[str, Decision] = {}
        for qid, a in data["answers"].items():
            t = a["type"]
            if t == "choice":
                out[qid] = Decision(qid, "choice", a["choice"], float(a["confidence"]), "jev", a.get("probabilities", {}))
            elif t == "score":
                out[qid] = Decision(qid, "score", float(a["score"]), float(a["confidence"]), "jev", a.get("probabilities", {}))
            else:
                p = float(a["noul"])
                out[qid] = Decision(qid, "noul", p, abs(2 * p - 1), "jev")
        return out, int(data.get("usage", {}).get("input_tokens", 0))


# ---------------------------------------------------------------- Jev local (stand-in)

class LocalJev:
    """Heurísticas determinísticas por pergunta. Mesmo contrato do Jev; serve de fallback e para testes."""
    source = "local"

    def ask_many(self, state, questions):
        out = {}
        for qid, q in questions.items():
            fn = getattr(self, f"_q_{qid}", None)
            if fn is None:
                out[qid] = self._unknown(qid, q)
            else:
                out[qid] = fn(q, state)
        return out, 0

    # --- genéricos
    def _unknown(self, qid, q):
        if q.kind == "choice":
            opts = q.options()
            return Decision(qid, "choice", opts[-1], 0.0, self.source)
        if q.kind == "score":
            return Decision(qid, "score", 0.0, 0.0, self.source)
        return Decision(qid, "noul", 0.5, 0.0, self.source)

    def _noul(self, qid, p):
        p = min(1.0, max(0.0, p))
        return Decision(qid, "noul", p, abs(2 * p - 1), self.source)

    # --- porteiros
    def _q_worth_spending(self, q, s):
        value = float(s.get("value_signal", 0.5))
        left = float(s.get("budget_left_ratio", 1.0))
        tokens = int(s.get("est_tokens", 0))
        size = 1.0 / (1.0 + tokens / 50_000)
        return self._noul("worth_spending", value * (0.4 + 0.6 * left) * size + 0.1 * value)

    def _q_should_evolve(self, q, s):
        n = int(s.get("occurrences", 0))
        consistency = float(s.get("consistency", 0.0))
        p = consistency * (1 - math.exp(-n / 3))
        if s.get("previously_rolled_back"):
            p *= 0.3
        return self._noul("should_evolve", p)

    def _q_should_run_idle(self, q, s):
        if s.get("pending_events", 0) > 0:
            return self._noul("should_run_idle", 0.05)
        return self._noul("should_run_idle", 0.3 + 0.6 * float(s.get("budget_left_ratio", 1.0)))

    # --- domínio
    def _q_input_type(self, q, s):
        t = norm(s.get("text", ""))
        if re.match(r"^(corrige|corrigir|categoria)\s+\d+", t):
            return Decision("input_type", "choice", "correcao", 0.98, self.source)
        if re.match(r"^(ok|confirma)\s+\d+", t):
            return Decision("input_type", "choice", "confirmacao", 0.98, self.source)
        if not s.get("has_amount"):
            return Decision("input_type", "choice", "desconhecido", 0.6, self.source)
        if t.startswith("+") or re.search(r"\b(recebi|salario|reembolso|freela)\b", t):
            return Decision("input_type", "choice", "receita", 0.9, self.source)
        return Decision("input_type", "choice", "despesa", 0.85, self.source)

    @staticmethod
    def match_rule(description: str, rules: list[dict]) -> dict | None:
        d = f" {norm(description)} "
        for r in rules:
            for kw in r["keywords"]:
                if re.search(rf"(?<!\w){re.escape(norm(kw))}(?!\w)", d):
                    return r
        return None

    def _q_category(self, q, s):
        r = self.match_rule(s.get("description", ""), s.get("regras", []))
        if r and r["category"] in q.options():
            conf = 0.92 if r.get("learned") is None else 0.88
            return Decision("category", "choice", r["category"], conf, self.source)
        return Decision("category", "choice", "outros", 0.3, self.source)

    def _q_spend_tag(self, q, s):
        r = self.match_rule(s.get("description", ""), s.get("regras", []))
        hour = int(s.get("hour", 12))
        late = hour >= 22 or hour < 5
        if r:
            tag = r["tag"]
            if late and r["category"] in ("delivery", "lazer", "alimentacao"):
                return Decision("spend_tag", "choice", "impulso", 0.7, self.source)
            return Decision("spend_tag", "choice", tag, 0.8, self.source)
        return Decision("spend_tag", "choice", "escolha", 0.35, self.source)

    def _q_alert_pattern(self, q, s):
        share = float(s.get("share_impulso", 0))
        deliveries = int(s.get("delivery_count_30d", 0))
        return self._noul("alert_pattern", max(min(1.0, share * 2.2), 0.85 if deliveries >= 8 else 0.0))

    def _q_review_finance(self, q, s):
        if not s.get("invariants_ok", False) or int(s.get("replay_breaks", 0)) > 0:
            return Decision("review_finance", "choice", "reject", 0.95, self.source)
        if int(s.get("level", 1)) >= 2:
            return Decision("review_finance", "choice", "shadow", 0.9, self.source)
        return Decision("review_finance", "choice", "approve", 0.85, self.source)

    def _q_review_code(self, q, s):
        if not s.get("tests_ok", False):
            return Decision("review_code", "choice", "reject", 0.95, self.source)
        if int(s.get("lines_changed", 0)) > 400 or s.get("touches_money_code"):
            return Decision("review_code", "choice", "changes", 0.7, self.source)
        return Decision("review_code", "choice", "approve", 0.75, self.source)

    def _q_health_rollback(self, q, s):
        if int(s.get("invariant_violations", 0)) > 0:
            return self._noul("health_rollback", 1.0)
        rate, limit = float(s.get("correction_rate", 0)), float(s.get("max_correction_rate", 0.35))
        before = float(s.get("correction_rate_before", 0))
        if rate > limit and rate > before:
            return self._noul("health_rollback", 0.6 + min(0.4, rate - limit))
        return self._noul("health_rollback", 0.1)

    _TIPO_HINTS = {
        "financas": r"\b(financ\w*|dinheiro|gasto\w*|econom\w*|orcamento|despesa\w*|investimento\w*)\b",
        "landing_page": r"\b(landing|pagina de captura|captar leads?|leads?|pagina de vendas)\b",
        "produto_software": r"\b(portal|sistema|aplicativo|app|plataforma|admin|saas|painel)\b",
        "plano": r"\b(plano|planejamento|cronograma|roteiro de|checklist|construcao|obra)\b",
        "pesquisa_decisao": r"\b(compar\w*|escolher|decid\w*|melhor opcao|vale a pena|pesquis\w*)\b",
        "conteudo": r"\b(conteudo|post\w*|instagram|roteiro|texto|artigo|newsletter|video)\b",
    }

    def _q_project_type(self, q, s):
        t = norm(s.get("pedido", ""))
        hits = [k for k, rx in self._TIPO_HINTS.items() if k in q.options() and re.search(rx, t)]
        if len(hits) == 1:
            return Decision("project_type", "choice", hits[0], 0.8, self.source)
        if hits:  # vários sinais: o primeiro na ordem de especificidade, com confiança menor
            order = ["financas", "landing_page", "produto_software", "plano", "pesquisa_decisao", "conteudo"]
            return Decision("project_type", "choice", min(hits, key=order.index), 0.55, self.source)
        return Decision("project_type", "choice", "outro", 0.3, self.source)

    def _q_isolate_stage(self, q, s):
        n = int(s.get("falhas_recentes", 0))
        return self._noul("isolate_stage", 0.0 if n < 3 else min(1.0, 0.55 + 0.1 * n))

    def _q_idle_task(self, q, s):
        stale = s.get("staleness", {})
        opts = q.options()
        best = max(opts, key=lambda o: (stale.get(o, 10**9), -opts.index(o)))
        return Decision("idle_task", "choice", best, 0.7, self.source)


# ---------------------------------------------------------------- DecisionLayer

class DecisionLayer:
    def __init__(self, store: Store, policy: Callable[[], dict], budget: Budget,
                 jev: JevClient | None = None, llm: LLMClient | None = None):
        self.s = store
        self.policy = policy
        self.budget = budget
        self.jev = jev or LocalJev()
        self.local = LocalJev()
        self.llm = llm
        self.project_id: int | None = None   # projeto em atendimento (None = o próprio círculo)

    # --- chamada base (várias perguntas, um request, avaliadas em paralelo pelo Jev)
    def ask_many(self, state: Mapping[str, Any], questions: Mapping[str, Question]) -> dict[str, Decision]:
        try:
            out, tokens = self.jev.ask_many(state, questions)
            self.budget.charge_jev(max(1, tokens // 1000))  # Jev ~1000x mais barato que LLM
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OSError) as exc:
            out, _ = self.local.ask_many(state, questions)
            self.s.set("jev_last_error", str(exc)[:300])
        for qid, q in questions.items():
            d = out.get(qid)
            if d is None or not self._valid(q, d):
                out[qid] = self.local.ask_many(state, {qid: q})[0][qid]
            self._log(out[qid])
        return out

    def ask(self, name: str, q: Question, state: Mapping[str, Any]) -> Decision:
        return self.ask_many(state, {name: q})[name]

    @staticmethod
    def _valid(q: Question, d: Decision) -> bool:
        if d.kind != q.kind or not 0.0 <= d.confidence <= 1.0:
            return False
        if q.kind == "choice":
            return d.value in q.options()
        if q.kind == "noul":
            return 0.0 <= float(d.value) <= 1.0
        return 0.0 <= float(d.value) <= max(0, len(q.criteria or ()) - 1)

    def _log(self, d: Decision) -> None:
        self.s.x("INSERT INTO decisions(tick,question,value,confidence,source,created_at,project_id) "
                 "VALUES(?,?,?,?,?,strftime('%s','now'),?)",
                 (self.s.tick, d.name, json.dumps(d.value), d.confidence, d.source, self.project_id))

    def _thr(self, path: str, default: float = 0.5) -> float:
        cur: Any = self.policy()["thresholds"]
        for p in path.split("."):
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
        return float(cur)

    # --- porteiro econômico universal
    def worth_spending(self, action: str, context: Mapping[str, Any]) -> Gate:
        est = int(context.get("est_tokens", 0))
        thr = self._thr(f"worth_spending.{action}", self._thr("worth_spending.default"))
        state = {"action": action, "est_tokens": est, "budget_left_ratio": round(self.budget.left_ratio(), 3),
                 "value_signal": float(context.get("value_signal", 0.5)),
                 **{k: v for k, v in context.items() if k not in ("est_tokens", "value_signal")}}
        d = self.ask("worth_spending", Question(
            "noul", f"Vale a pena gastar ~{est} tokens agora na ação '{action}', dado o valor esperado e o orçamento restante?"), state)
        if est > 0 and not self.budget.can_spend(est):
            return Gate(False, d, thr, "orçamento insuficiente (hard limit)")
        return Gate(float(d.value) >= thr, d, thr)

    # --- pré-filtro de evolução
    def should_evolve(self, evolution_type: Literal["domain", "circle"], evidence: Mapping[str, Any]) -> Gate:
        thr = self._thr(f"should_evolve.{evolution_type}", 0.8)
        d = self.ask("should_evolve", Question(
            "noul", f"A evidência justifica aplicar esta evolução de nível '{evolution_type}' agora?"),
            {"evolution_type": evolution_type, **evidence})
        return Gate(float(d.value) >= thr, d, thr)

    # --- escolha com fallback para LLM só quando o Jev estiver inseguro
    def choose(self, name: str, q: Question, state: Mapping[str, Any], llm_tokens: int = 400) -> Decision:
        d = self.ask(name, q, state)
        if d.confidence >= self._thr("llm_fallback_below") or self.llm is None:
            return d
        gate = self.worth_spending("llm_fallback", {"est_tokens": llm_tokens, "value_signal": 0.6, "question": name})
        if not gate.allowed:
            return d
        opts = ", ".join(q.options())
        text, used = self.llm.complete(
            "Responda apenas com uma das opções, sem explicação.",
            f"{q.instructions}\nOpções: {opts}\nDados: {json.dumps(state, ensure_ascii=False)[:1500]}",
            max_tokens=10,
        )
        self.budget.charge(used, "llm")
        pick = norm(text).strip().split()[0] if text.strip() else ""
        if pick in q.options():
            d = Decision(name, "choice", pick, 0.7, "llm")
            self._log(d)
        return d


def build_jev() -> JevClient:
    key = os.environ.get("TYPESAFE_API_KEY") or os.environ.get("JEV_API_KEY")
    if key:
        return JevHttpClient(key, model=os.environ.get("JEV_MODEL", "jev-latest"))
    return LocalJev()


class AnthropicLLM:
    """Opcional (pip install circulo[llm]). Só é chamado depois que o Jev autoriza o gasto."""

    def __init__(self, model: str | None = None):
        import anthropic  # noqa: import tardio
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("CIRCULO_LLM_MODEL", "claude-haiku-5-5")

    def complete(self, system, prompt, max_tokens):
        msg = self.client.messages.create(model=self.model, max_tokens=max_tokens, system=system,
                                          messages=[{"role": "user", "content": prompt}])
        text = "".join(getattr(b, "text", "") for b in msg.content)
        return text, msg.usage.input_tokens + msg.usage.output_tokens


def build_llm() -> LLMClient | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        return AnthropicLLM()
    except ImportError:
        return None

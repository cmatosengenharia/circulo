"""Meta-Learner (evolução nível 1 e 2), Shadow mode e Health Monitor (rollback automático)."""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import finance
from .agents import Ctx, ReviewerFinance, tokens_of
from .decision import LocalJev, Question
from .policy import PolicyStore, PolicyViolation, fingerprint, level_of_change

RESOLVED = "('confirmed','corrected')"


@dataclass
class Candidate:
    kind: str
    description: str
    patch: list[dict]
    evidence: dict = field(default_factory=dict)


def utility(accepted: bool, wrong: bool) -> float:
    """Valor de uma decisão de auto-accept: errar aceitando custa caro; revisar algo certo custa atenção."""
    if accepted:
        return -3.0 if wrong else 1.0
    return 0.5 if wrong else -0.2


class MetaLearner:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.reviewer = ReviewerFinance(ctx)

    # ---------------------------------------------------- descoberta (SQL local, custo zero)
    def domain_candidates(self) -> list[Candidate]:
        s = self.ctx.store
        policy = self.ctx.policy
        corrected = s.q("SELECT description, category, tag FROM ledger WHERE status='corrected'")
        # Abertos auto-aceitos também contam (silêncio = evidência fraca de acerto);
        # abertos aguardando revisão não contam (ninguém olhou ainda).
        resolved = s.q(f"SELECT description, category FROM ledger WHERE kind='despesa' AND (status IN {RESOLVED} OR auto_accepted=1)")
        per_token: dict[str, Counter] = defaultdict(Counter)
        tags: dict[tuple[str, str], Counter] = defaultdict(Counter)
        for r in corrected:
            for tok in set(tokens_of(r["description"])):
                per_token[tok][r["category"]] += 1
                tags[(tok, r["category"])][r["tag"]] += 1
        out = []
        for tok, cats in per_token.items():
            cat, n = cats.most_common(1)[0]
            if n < 2 or cat not in policy["categories"]:
                continue
            with_tok = [r for r in resolved if tok in tokens_of(r["description"])]
            consistency = sum(r["category"] == cat for r in with_tok) / len(with_tok)
            already = all((LocalJev.match_rule(r["description"], policy["rules"]) or {}).get("category") == cat for r in with_tok)
            if already or consistency < 0.75:
                continue
            tag = tags[(tok, cat)].most_common(1)[0][0]
            out.append(Candidate(
                "add_rule", f"Aprender: '{tok}' → {cat}/{tag}",
                [{"op": "add_rule", "rule": {"keywords": [tok], "category": cat, "tag": tag, "learned": True}}],
                {"occurrences": n, "consistency": round(consistency, 3), "seen": len(with_tok)},
            ))
        # Mais específico primeiro (aparece em menos lançamentos; empate → palavra mais longa).
        # Candidatos redundantes depois disso são barrados por replay_fixes == 0.
        out.sort(key=lambda c: (-c.evidence["consistency"], c.evidence["seen"], -len(c.patch[0]["rule"]["keywords"][0])))
        return out

    def distillation_candidates(self) -> list[Candidate]:
        """Destilação: se a LLM só confirma o que o Jev já tinha respondido, o fallback é desperdício → subir na cascata."""
        rows = self.ctx.store.q("""SELECT j.value jv, l.value lv FROM decisions l JOIN decisions j
            ON j.tick=l.tick AND j.question=l.question AND j.source!='llm' AND j.id < l.id
            WHERE l.source='llm' AND l.question NOT LIKE 'llm:%' ORDER BY l.id DESC LIMIT 200""")
        if len(rows) < 20:
            return []
        agree = sum(r["jv"] == r["lv"] for r in rows) / len(rows)
        thr = float(self.ctx.policy["thresholds"]["llm_fallback_below"])
        if agree >= 0.9 and thr > 0.2:
            new = round(max(0.2, thr - 0.05), 2)
            return [Candidate("distillation", f"Destilar: LLM concordou com o Jev em {agree:.0%}; fallback só abaixo de {new}",
                              [{"op": "set", "path": "thresholds.llm_fallback_below", "value": new}],
                              {"occurrences": len(rows), "consistency": round(agree, 3)})]
        return []

    def circle_candidates(self) -> list[Candidate]:
        s, policy = self.ctx.store, self.ctx.policy
        thr = float(policy["thresholds"]["auto_accept_category"])
        window = int(policy["rollback"]["health_window"]) * 2
        rows = s.q(f"SELECT auto_accepted, confidence, status FROM ledger WHERE kind='despesa' AND status IN {RESOLVED} ORDER BY id DESC LIMIT ?", (window,))
        acc = [r for r in rows if r["auto_accepted"]]
        if len(acc) < 10:
            return []
        wrong = sum(r["status"] == "corrected" for r in acc) / len(acc)
        if wrong >= 0.2 and thr < 0.95:
            new = round(min(0.95, thr + 0.05), 2)
            return [Candidate("threshold", f"Subir auto-accept {thr}→{new} (erro aceito {wrong:.0%})",
                              [{"op": "set", "path": "thresholds.auto_accept_category", "value": new}],
                              {"occurrences": len(acc), "consistency": round(min(1.0, wrong * 3), 3)})]
        if wrong == 0 and thr > 0.6:
            near = [r for r in rows if not r["auto_accepted"] and thr - 0.05 <= r["confidence"] < thr]
            if len(near) >= 5 and all(r["status"] == "confirmed" for r in near):
                new = round(max(0.6, thr - 0.05), 2)
                return [Candidate("threshold", f"Baixar auto-accept {thr}→{new} ({len(near)} revisões desnecessárias)",
                                  [{"op": "set", "path": "thresholds.auto_accept_category", "value": new}],
                                  {"occurrences": len(near), "consistency": 1.0})]
        return []

    # ---------------------------------------------------- decisão + apply
    def step(self) -> list[str]:
        log = []
        for c in self.domain_candidates() + self.circle_candidates() + self.distillation_candidates():
            r = self.process(c)
            if r:
                log.append(r)
        return log

    def _upsert(self, c: Candidate, level: int, fp: str, status: str, notes: str = "") -> int:
        s, now = self.ctx.store, time.time()
        row = s.one("SELECT id FROM proposals WHERE fingerprint=?", (fp,))
        if row:
            s.x("UPDATE proposals SET status=?, evidence=?, notes=?, updated_at=? WHERE id=?",
                (status, json.dumps(c.evidence), notes, now, row["id"]))
            return row["id"]
        # regra de domínio pertence ao projeto do kit; mudança do círculo não pertence a projeto nenhum
        from .projects import kit_project_id
        pid = kit_project_id(s, "financas" if level == 1 else "circulo")
        return s.x("INSERT INTO proposals(level,kind,fingerprint,description,patch,evidence,status,notes,created_at,updated_at,project_id) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (level, c.kind, fp, c.description, json.dumps(c.patch, ensure_ascii=False), json.dumps(c.evidence), status, notes, now, now, pid))

    def process(self, c: Candidate) -> str | None:
        s = self.ctx.store
        fp = fingerprint(c.patch)
        prev = s.one("SELECT status, evidence, COALESCE(rollbacks,0) rb FROM proposals WHERE fingerprint=?", (fp,))
        if prev and prev["status"] in ("applied", "shadow", "rejected", "bloqueada"):
            return None
        from .guardrails import MAX_ROLLBACKS, can_change_level2
        if prev and prev["rb"] >= MAX_ROLLBACKS:
            # oscilação: revertida 2x → bloqueada; só o humano reabre
            s.x("UPDATE proposals SET status='bloqueada', notes='revertida 2 vezes: oscilação' WHERE fingerprint=?", (fp,))
            return f"bloqueada por oscilação: {c.description}"
        if prev and prev["status"] == "rolled_back":
            old_n = json.loads(prev["evidence"]).get("occurrences", 0)
            if c.evidence.get("occurrences", 0) < 2 * old_n:
                return None
            c.evidence["previously_rolled_back"] = True

        old = self.ctx.policy
        try:
            new = PolicyStore.patched(old, c.patch)
            from .policy import guard
            guard(new)
        except (PolicyViolation, KeyError, ValueError) as exc:
            self._upsert(c, 2, fp, "rejected", f"guard: {exc}")
            return f"rejeitada pelo guard: {c.description}"
        level = level_of_change(old, new)
        if level == 2 and not can_change_level2(s):
            self._upsert(c, level, fp, "deferred", "orçamento de mudanças de nível 2 do dia esgotado")
            return None
        if level == 2 and self.ctx.policies.shadow():
            self._upsert(c, level, fp, "deferred", "já existe um shadow em avaliação")
            return None

        gate = self.ctx.dl.should_evolve("circle" if level == 2 else "domain", {**c.evidence, "kind": c.kind, "description": c.description})
        if not gate.allowed:
            self._upsert(c, level, fp, "deferred", f"jev should_evolve={gate.decision.value:.2f} < {gate.threshold}")
            return None

        verdict, review = self.reviewer.review(level, old, new)
        if verdict == "reject":
            self._upsert(c, level, fp, "rejected", json.dumps(review))
            return f"rejeitada pelo Reviewer Finance: {c.description}"
        if c.kind == "add_rule" and review.get("replay_fixes", 0) == 0:
            self._upsert(c, level, fp, "deferred", "redundante: não corrige nenhum lançamento além das regras atuais")
            return None

        apply_gate = self.ctx.dl.worth_spending("apply_proposal", {"value_signal": c.evidence.get("consistency", 0.5), "level": level})
        if not apply_gate.allowed:
            self._upsert(c, level, fp, "deferred", "jev worth_spending(apply) negou")
            return None

        pid = self._upsert(c, level, fp, "shadow" if verdict == "shadow" else "applied", json.dumps(review))
        self.ctx.policies.add_version(new, "shadow" if verdict == "shadow" else "active", c.description, pid)
        if verdict != "shadow":
            self.ctx.policies.rebase_shadow(c.patch)  # shadow não pode perder o que o ativo aprendeu
        return f"{'shadow' if verdict == 'shadow' else 'aplicada'} (nível {level}): {c.description}"


class Shadow:
    """Avalia a versão shadow com as mesmas decisões reais, sem afetar o usuário."""

    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    def record(self, tx_id: int, confidence: float, category: str) -> None:
        sh = self.ctx.policies.shadow()
        if not sh:
            return
        version, body, _ = sh
        would = confidence >= body["thresholds"]["auto_accept_category"] and category != "outros"
        self.ctx.store.x("INSERT OR IGNORE INTO shadow_obs(version,tx_id,would_accept) VALUES(?,?,?)", (version, tx_id, int(would)))

    def evaluate(self) -> str | None:
        sh = self.ctx.policies.shadow()
        if not sh:
            return None
        version, body, started = sh
        cfg = self.ctx.policy["shadow"]
        age = self.ctx.store.tick - (started or 0)
        rows = self.ctx.store.q(f"""SELECT o.would_accept, l.auto_accepted, l.status FROM shadow_obs o
            JOIN ledger l ON l.id=o.tx_id WHERE o.version=? AND l.status IN {RESOLVED}""", (version,))
        if age < cfg["min_ticks"] or len(rows) < cfg["min_observations"]:
            if age > 50 * cfg["min_ticks"]:
                self._close(version, False, "sem observações suficientes")
                return "shadow expirado"
            return None
        u_shadow = sum(utility(bool(r["would_accept"]), r["status"] == "corrected") for r in rows) / len(rows)
        u_active = sum(utility(bool(r["auto_accepted"]), r["status"] == "corrected") for r in rows) / len(rows)
        win = u_shadow > u_active + cfg["min_gain"]
        self._close(version, win, f"utilidade shadow={u_shadow:.3f} ativa={u_active:.3f} n={len(rows)}")
        return f"shadow v{version} {'promovido' if win else 'descartado'} ({u_shadow:.2f} vs {u_active:.2f})"

    def _close(self, version: int, promote: bool, note: str) -> None:
        row = self.ctx.store.one("SELECT proposal_id FROM policy_versions WHERE version=?", (version,))
        if promote:
            self.ctx.policies.promote_shadow(version)
        else:
            self.ctx.policies.reject_shadow(version)
        if row and row["proposal_id"]:
            self.ctx.store.x("UPDATE proposals SET status=?, notes=?, updated_at=? WHERE id=?",
                             ("applied" if promote else "rejected", note, time.time(), row["proposal_id"]))


class HealthMonitor:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx

    def _rate(self, version: int | None) -> tuple[float, int]:
        if version is None:
            return 0.0, 0
        rows = self.ctx.store.q(f"SELECT status FROM ledger WHERE policy_version=? AND auto_accepted=1 AND status IN {RESOLVED}", (version,))
        if not rows:
            return 0.0, 0
        return sum(r["status"] == "corrected" for r in rows) / len(rows), len(rows)

    def check(self) -> dict:
        s, policy = self.ctx.store, self.ctx.policy
        violations = finance.check_invariants(s)
        version, _ = self.ctx.policies.active()
        parent = s.one("SELECT parent FROM policy_versions WHERE version=?", (version,))["parent"]
        since = s.tick - self.ctx.policies.activated_tick()
        rate, n = self._rate(version)
        rate_before, _ = self._rate(parent)
        m = {"invariant_violations": len(violations), "correction_rate": round(rate, 3), "samples": n,
             "correction_rate_before": round(rate_before, 3), "policy_version": version, "ticks_since_change": since,
             "rolled_back": None}
        if violations:
            self.ctx.reply("Invariante financeiro violado: " + "; ".join(violations), "saude")
        recent_change = parent is not None and since <= policy["rollback"]["watch_ticks"]
        if recent_change and (violations or n >= 5):
            d = self.ctx.dl.ask("health_rollback", Question("noul", "A última mudança de política piorou a saúde do sistema e deve ser desfeita?"),
                                {**m, "max_correction_rate": policy["rollback"]["max_correction_rate"]})
            if violations or float(d.value) >= policy["thresholds"]["rollback"]:
                restored = self.ctx.policies.rollback(f"saúde: viol={len(violations)} correção={rate:.0%} antes={rate_before:.0%}")
                m["rolled_back"] = restored
                self.ctx.reply(f"Rollback automático da política v{version} → v{restored}.", "saude")
        return m

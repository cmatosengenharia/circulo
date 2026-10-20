"""Evolução do harness: A/B online de prompts de papel (estilo otimização de prompts), sempre com gates.

1. Quando um papel (builder/improver) acumulou ciclos suficientes, a LLM pequena propõe UMA variante
   do prompt de sistema (o Jev autoriza o gasto antes).
2. A variante passa pelo guard (não pode perder a regra anti-injeção, nem limites).
3. Os próximos ciclos alternam base e variante; o resultado de cada braço é o ganho na régua
   (inclusive a nota oculta, via catraca do motor).
4. Com amostras suficientes, o Jev decide (should_evolve nível círculo) e a variante vira uma nova
   versão da política — que ainda passa pela saúde/rollback. Senão, é descartada.
"""
from __future__ import annotations

import json
import time

from .agents import Ctx
from .policy import PolicyStore, PolicyViolation, guard

ROLES = ("builder", "improver")
MIN_CYCLES_BEFORE = 6
MIN_TRIALS_PER_ARM = 3
MARGIN = 0.02


class HarnessLab:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.s = ctx.store

    def active(self, role: str) -> dict | None:
        r = self.s.one("SELECT * FROM harness_experiments WHERE role=? AND status='rodando' ORDER BY id DESC LIMIT 1", (role,))
        return dict(r) if r else None

    def system_for(self, role: str) -> tuple[str, str | None, int | None]:
        """(prompt, braço, experimento) — alterna base/variante enquanto há experimento rodando."""
        base = self.ctx.policy["harness"]["roles"][role]["system"]
        exp = self.active(role)
        if not exp:
            return base, None, None
        trials = json.loads(exp["trials"])
        arm = "variante" if len(trials["variante"]) <= len(trials["base"]) else "base"
        return (exp["variante"] if arm == "variante" else base), arm, exp["id"]

    def record(self, exp_id: int | None, arm: str | None, gain: float, aceita: bool) -> None:
        if not exp_id or not arm:
            return
        exp = dict(self.s.one("SELECT * FROM harness_experiments WHERE id=?", (exp_id,)))
        trials = json.loads(exp["trials"])
        trials[arm].append(round(gain if aceita else min(gain, 0.0), 4))
        self.s.x("UPDATE harness_experiments SET trials=? WHERE id=?", (json.dumps(trials), exp_id))

    def maybe_propose(self) -> str | None:
        llm = self.ctx.dl.llm
        if llm is None or not hasattr(llm, "generate"):
            return None
        for role in ROLES:
            if self.active(role):
                continue
            n = self.s.one("SELECT COUNT(*) n FROM cycles WHERE fase IN ('construcao','melhoria') AND created_at > COALESCE("
                           "(SELECT MAX(created_at) FROM harness_experiments WHERE role=?),0)", (role,))["n"]
            if n < MIN_CYCLES_BEFORE:
                continue
            gate = self.ctx.dl.worth_spending("harness_variant", {"est_tokens": 800, "value_signal": 0.55, "role": role})
            if not gate.allowed:
                continue
            base = self.ctx.policy["harness"]["roles"][role]["system"]
            ruins = [r["resultado"] for r in self.s.q("SELECT resultado FROM cycles WHERE aceita=0 ORDER BY id DESC LIMIT 5")]
            model = self.ctx.policy["harness"]["models"]["pequena"]
            from .memoria import do_ctx
            mem = do_ctx(self.ctx)
            bloco = mem.para("evoluir_harness", f"{role} " + " ".join(str(x)[:80] for x in ruins)) if mem else ""
            out = llm.generate(system="Você otimiza prompts de sistema. Devolva SOMENTE o novo prompt, completo.",
                               prompt=f"Papel: {role}\nPrompt atual:\n{base}\n\nFalhas recentes:\n" + "\n".join(f"- {x}" for x in ruins) +
                                      (("\n\n" + bloco) if bloco else "") +
                                      "\n\nProponha uma variante que corrija essas falhas mantendo todas as regras do prompt atual.",
                               model=model, max_tokens=600)
            self.ctx.budget.charge(out.tokens, "llm")
            variante = out.text.strip()
            try:
                guard(PolicyStore.patched(self.ctx.policy, [{"op": "set", "path": f"harness.roles.{role}.system", "value": variante}]))
            except PolicyViolation as exc:
                self.s.x("INSERT INTO harness_experiments(role,variante,trials,status,notes,created_at) VALUES(?,?,?,?,?,?)",
                         (role, variante, json.dumps({"base": [], "variante": []}), "rejeitado", f"guard: {exc}", time.time()))
                return f"variante de {role} rejeitada pelo guard"
            self.s.x("INSERT INTO harness_experiments(role,variante,trials,status,notes,created_at) VALUES(?,?,?,?,?,?)",
                     (role, variante, json.dumps({"base": [], "variante": []}), "rodando", "", time.time()))
            return f"experimento de prompt iniciado para {role}"
        return None

    def evaluate(self) -> str | None:
        for role in ROLES:
            exp = self.active(role)
            if not exp:
                continue
            t = json.loads(exp["trials"])
            if min(len(t["base"]), len(t["variante"])) < MIN_TRIALS_PER_ARM:
                continue
            mb, mv = sum(t["base"]) / len(t["base"]), sum(t["variante"]) / len(t["variante"])
            evid = {"occurrences": len(t["base"]) + len(t["variante"]), "consistency": min(1.0, max(0.0, (mv - mb) * 10)),
                    "ganho_base": mb, "ganho_variante": mv}
            gate = self.ctx.dl.should_evolve("circle", evid)
            from .guardrails import can_change_level2
            if mv >= mb + MARGIN and gate.allowed and can_change_level2(self.s):
                new = PolicyStore.patched(self.ctx.policy, [{"op": "set", "path": f"harness.roles.{role}.system", "value": exp["variante"]}])
                now = time.time()
                from .projects import kit_project_id
                pid = self.s.x("INSERT INTO proposals(level,kind,fingerprint,description,patch,evidence,status,notes,created_at,updated_at,project_id) "
                               "VALUES(3,'harness',?,?,?,?,?,?,?,?,?)",
                               (f"harness-{exp['id']}", f"Prompt do {role} evoluído por A/B ({mb:+.3f} → {mv:+.3f})",
                                json.dumps([{"op": "set", "path": f"harness.roles.{role}.system"}]), json.dumps(evid), "applied", "", now, now,
                                kit_project_id(self.s, "circulo")))
                self.ctx.policies.add_version(new, "active", f"harness {role} por A/B", pid)
                self.s.x("UPDATE harness_experiments SET status='promovido', notes=? WHERE id=?", (json.dumps(evid), exp["id"]))
                return f"prompt do {role} promovido"
            self.s.x("UPDATE harness_experiments SET status='descartado', notes=? WHERE id=?", (json.dumps(evid), exp["id"]))
            return f"variante do {role} descartada"
        return None

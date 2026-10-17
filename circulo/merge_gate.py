"""Gate de merge do círculo.

O GitHub Free não aplica proteção de branch em repositório privado, então a regra mora aqui.
Ordem: regras duras (código, não evoluem) → Reviewer Code (Jev) → merge com SHA travado.
O Jev só pode deixar o gate MAIS rígido: ele nunca libera o que uma regra dura barrou.

Este arquivo é protegido: o CI exige o label `aprovado-humano` para alterá-lo.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from .agents import Ctx, ReviewerCode

# ------------------------------------------------------------------ regras duras (não evoluem)
REQUIRED_CHECKS = ("Testes (Python 3.11)", "Testes (Python 3.12)", "Testes (Python 3.13)", "Arquivos protegidos")
PROTECTED_PATHS = (
    "circulo/finance.py", "circulo/money.py", "circulo/policy.py", "circulo/budget.py",
    "circulo/merge_gate.py", ".github/",
)
HUMAN_LABEL = "aprovado-humano"
AGENT_BRANCH_PREFIX = "circulo/"     # o gate só mergeia PRs abertos pelos agentes
MAX_LINES = 800                       # PR maior que isso nunca entra sozinho


class GitHub(Protocol):
    def open_prs(self) -> list[dict]: ...
    def pr_files(self, number: int) -> list[dict]: ...
    def check_runs(self, sha: str) -> list[dict]: ...
    def label_events(self, number: int) -> list[dict]: ...
    def merge(self, number: int, sha: str, title: str) -> tuple[bool, str]: ...


@dataclass
class Verdict:
    number: int
    sha: str
    merge: bool
    reason: str
    details: dict = field(default_factory=dict)


def touches_protected(files: list[str]) -> list[str]:
    return [f for f in files if any(f == p or (p.endswith("/") and f.startswith(p)) for p in PROTECTED_PATHS)]


def checks_ok(runs: list[dict]) -> tuple[bool, str]:
    """Todos os checks obrigatórios concluídos com sucesso, e nenhum outro check falhando."""
    latest: dict[str, dict] = {}
    for r in runs:
        prev = latest.get(r["name"])
        if prev is None or (r.get("id", 0) > prev.get("id", 0)):
            latest[r["name"]] = r
    missing = [n for n in REQUIRED_CHECKS if n not in latest]
    if missing:
        return False, f"checks ausentes: {', '.join(missing)}"
    pending = [n for n, r in latest.items() if r.get("status") != "completed"]
    if pending:
        return False, f"checks em andamento: {', '.join(pending)}"
    bad = [n for n, r in latest.items() if r.get("conclusion") not in ("success", "skipped", "neutral")]
    if bad:
        return False, f"checks falhando: {', '.join(bad)}"
    if any(latest[n].get("conclusion") != "success" for n in REQUIRED_CHECKS):
        return False, "check obrigatório não passou com sucesso"
    return True, "ok"


def human_approved(events: list[dict], human: str) -> bool:
    """O label precisa ter sido colocado (e não removido depois) pelo humano — não por um bot/agente."""
    state = False
    for e in events:
        if e.get("label") != HUMAN_LABEL:
            continue
        if e.get("event") == "labeled":
            state = e.get("actor", "").lower() == human.lower()
        elif e.get("event") == "unlabeled":
            state = False
    return state


class MergeGate:
    def __init__(self, ctx: Ctx, gh: GitHub, human: str):
        self.ctx = ctx
        self.gh = gh
        self.human = human
        self.reviewer = ReviewerCode(ctx)

    def evaluate(self, pr: dict) -> Verdict:
        n, sha = pr["number"], pr["head_sha"]
        if pr.get("draft"):
            return Verdict(n, sha, False, "rascunho")
        if not pr.get("head_ref", "").startswith(AGENT_BRANCH_PREFIX):
            return Verdict(n, sha, False, "não é PR de agente (merge é seu)")

        ok, why = checks_ok(self.gh.check_runs(sha))
        if not ok:
            return Verdict(n, sha, False, why)

        files = self.gh.pr_files(n)
        names = [f["filename"] for f in files]
        lines = sum(f.get("additions", 0) + f.get("deletions", 0) for f in files)
        protected = touches_protected(names)
        if lines > MAX_LINES:
            return Verdict(n, sha, False, f"PR grande demais ({lines} linhas > {MAX_LINES})", {"lines": lines})
        if protected and not human_approved(self.gh.label_events(n), self.human):
            return Verdict(n, sha, False, f"altera arquivo protegido sem '{HUMAN_LABEL}' seu: {', '.join(protected)}",
                           {"protected": protected})

        # Se tocou em dinheiro, quem revisou o dinheiro foi você (label); o Jev avalia o resto do PR.
        decision = self.reviewer.review(tests_ok=True, lines_changed=lines, touches_money_code=False)
        details = {"lines": lines, "files": len(names), "protected": protected, "review": decision}
        if decision != "approve":
            return Verdict(n, sha, False, f"Reviewer Code: {decision}", details)
        return Verdict(n, sha, True, "todos os gates passaram", details)

    def run(self) -> list[Verdict]:
        out = []
        for pr in self.gh.open_prs():
            v = self.evaluate(pr)
            if v.merge:
                merged, msg = self.gh.merge(v.number, v.sha, pr.get("title", f"PR #{v.number}"))
                if not merged:
                    v = Verdict(v.number, v.sha, False, f"GitHub recusou o merge: {msg}", v.details)
            self._log(v)
            out.append(v)
        return out

    def _log(self, v: Verdict) -> None:
        s = self.ctx.store
        last = s.one("SELECT reason FROM merges WHERE pr=? AND sha=? ORDER BY id DESC LIMIT 1", (v.number, v.sha))
        if last and last["reason"] == v.reason:
            return  # não repete a mesma avaliação a cada giro
        s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,?,?,?,?,?)",
            (v.number, v.sha, int(v.merge), v.reason, json.dumps(v.details, ensure_ascii=False), time.time()))
        if v.merge:
            self.ctx.reply(f"Merge automático do PR #{v.number} ({v.details.get('lines', 0)} linhas).", "merge")
        elif "protegido" in v.reason or "grande" in v.reason:
            self.ctx.reply(f"PR #{v.number} aguarda você: {v.reason}.", "merge")


# ------------------------------------------------------------------ cliente REST real

class GitHubREST:
    API = "https://api.github.com"

    def __init__(self, repo: str, token: str, timeout: float = 15.0):
        self.repo = repo
        self.token = token
        self.timeout = timeout

    def _req(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            f"{self.API}/repos/{self.repo}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "circulo"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read() or b"null")

    def open_prs(self):
        return [{"number": p["number"], "head_sha": p["head"]["sha"], "head_ref": p["head"]["ref"],
                 "draft": p.get("draft", False), "title": p["title"]}
                for p in self._req("GET", "/pulls?state=open&per_page=50")]

    def pr_files(self, number):
        return self._req("GET", f"/pulls/{number}/files?per_page=100")

    def check_runs(self, sha):
        return self._req("GET", f"/commits/{sha}/check-runs?per_page=100")["check_runs"]

    def label_events(self, number):
        return [{"event": e["event"], "label": (e.get("label") or {}).get("name"), "actor": (e.get("actor") or {}).get("login", "")}
                for e in self._req("GET", f"/issues/{number}/events?per_page=100") if e["event"] in ("labeled", "unlabeled")]

    def merge(self, number, sha, title):
        try:
            # `sha` trava o merge: se alguém empurrar commit novo depois da avaliação, o GitHub recusa.
            r = self._req("PUT", f"/pulls/{number}/merge", {"sha": sha, "merge_method": "squash", "commit_title": f"{title} (#{number})"})
            return bool(r.get("merged")), r.get("message", "")
        except urllib.error.HTTPError as e:
            return False, f"HTTP {e.code}"


def build_gate(ctx: Ctx) -> MergeGate | None:
    repo, token = os.environ.get("CIRCULO_REPO"), os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        return None
    human = os.environ.get("CIRCULO_HUMANO", repo.split("/")[0])
    return MergeGate(ctx, GitHubREST(repo, token), human)

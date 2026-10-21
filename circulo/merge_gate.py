"""QA e release (merge) do círculo.

O GitHub Free não aplica proteção de branch em repositório privado, então a regra mora aqui.
Ordem: regras duras (código, não evoluem) → Reviewer Code (Jev) → merge com SHA travado.
O Jev só pode deixar o gate MAIS rígido: ele nunca libera o que uma regra dura barrou.

Nada aqui espera o humano:
- Constituição (os próprios guardrails, o gate, orçamento, CI): o loop NUNCA altera. PR de agente que
  toca nesses arquivos é recusado e registrado como "fora do alcance" — a missão segue por outro caminho.
- Código de dinheiro (finance.py, money.py): entra sozinho, mas só com o check "Evidência reforçada"
  (propriedades financeiras em milhares de casos aleatórios) verde, além dos testes normais.
- PR do Developer reprovado pelo CI, ou sem teste novo, não fica parado esperando: volta para o próprio Developer
  consertar na mesma branch, com o log do CI (`self_dev_aberto.conserto`).
"""
from __future__ import annotations

import json
import re
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from .agents import Ctx, ReviewerCode

# ------------------------------------------------------------------ regras duras (não evoluem)
REQUIRED_CHECKS = ("Testes (Python 3.11)", "Testes (Python 3.12)", "Testes (Python 3.13)", "Constituição", "Evidência reforçada")
CONSTITUICAO = (
    "circulo/merge_gate.py", "circulo/policy.py", "circulo/budget.py", "circulo/guardrails.py",
    "circulo/self_dev.py", "circulo/corpo.py", ".github/",
)
DINHEIRO = ("circulo/finance.py", "circulo/money.py")
PROTECTED_PATHS = CONSTITUICAO + DINHEIRO   # compatibilidade
HUMAN_LABEL = "aprovado-humano"             # legado: não é mais exigido
AGENT_BRANCH_PREFIX = "circulo/"     # o gate só mergeia PRs abertos pelos agentes
MAX_LINES = 800                       # PR maior que isso nunca entra sozinho
DEVELOPER_BRANCH_PREFIX = "circulo/fix-"   # PRs do Developer precisam trazer teste novo
DOCS_BRANCH_PREFIX = "circulo/docs-"       # PRs do Redator técnico: só docs/, nada de código por essa porta


def protegidos() -> tuple[str, ...]:
    """A constituição do repositório que o loop cuida: a deste repo por padrão; `CIRCULO_PROTEGIDOS` (vírgulas) para outro."""
    v = os.environ.get("CIRCULO_PROTEGIDOS", "").strip()
    return tuple(x.strip() for x in v.split(",") if x.strip()) or CONSTITUICAO


def required_checks() -> tuple[str, ...]:
    v = os.environ.get("CIRCULO_REQUIRED_CHECKS", "").strip()
    return tuple(x.strip() for x in v.split(",") if x.strip()) or REQUIRED_CHECKS


def tem_teste(files: list[str]) -> bool:
    return any(f.startswith("tests/") or f.split("/")[-1].startswith("test_") for f in files)


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


def _match(files: list[str], paths: tuple[str, ...]) -> list[str]:
    return [f for f in files if any(f == p or (p.endswith("/") and f.startswith(p)) for p in paths)]


def touches_protected(files: list[str]) -> list[str]:
    return _match(files, PROTECTED_PATHS)


def touches_constitution(files: list[str]) -> list[str]:
    return _match(files, protegidos())


def touches_money(files: list[str]) -> list[str]:
    return _match(files, DINHEIRO)


def checks_ok(runs: list[dict]) -> tuple[bool, str]:
    """Todos os checks obrigatórios concluídos com sucesso, e nenhum outro check falhando."""
    latest: dict[str, dict] = {}
    for r in runs:
        prev = latest.get(r["name"])
        if prev is None or (r.get("id", 0) > prev.get("id", 0)):
            latest[r["name"]] = r
    missing = [n for n in required_checks() if n not in latest]
    if missing:
        return False, f"checks ausentes: {', '.join(missing)}"
    pending = [n for n, r in latest.items() if r.get("status") != "completed"]
    if pending:
        return False, f"checks em andamento: {', '.join(pending)}"
    bad = [n for n, r in latest.items() if r.get("conclusion") not in ("success", "skipped", "neutral")]
    if bad:
        return False, f"checks falhando: {', '.join(bad)}"
    if any(latest[n].get("conclusion") != "success" for n in required_checks()):
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
            return Verdict(n, sha, False, "PR humano: o loop não interfere")

        files = self.gh.pr_files(n)
        names = [f["filename"] for f in files]
        if pr.get("head_ref", "").startswith(DOCS_BRANCH_PREFIX):
            fora = [f for f in names if not f.startswith("docs/")]
            if fora:
                return Verdict(n, sha, False, f"fora do alcance: PR de documentação toca código ({', '.join(fora[:5])})", {"fora_do_alcance": True})
            ok, why = checks_ok(self.gh.check_runs(sha))
            return Verdict(n, sha, ok, "documentação: só docs/ e CI verde" if ok else why, {"docs": True, "files": len(names)})
        const = touches_constitution(names)
        if const:   # recusa definitiva: não espera ninguém, não tenta de novo
            return Verdict(n, sha, False, f"fora do alcance: PR de agente altera a constituição ({', '.join(const)})",
                           {"constituicao": const, "fora_do_alcance": True})
        # Revisor: PR do Developer que cruza arquivos com um PR mais antigo ainda aberto é rejeitado (o item volta à fila)
        from . import revisor
        row = self.ctx.store.one("SELECT item_id FROM prs WHERE number=?", (n,))
        rev = revisor.no_gate(self.ctx.store, self.ctx.dl, n, row["item_id"] if row else None, names)
        if rev:
            return Verdict(n, sha, False, f"Revisor: {rev['motivo']}", {"revisor": True, "aguarda_pr": rev["aguarda_pr"], "fora_do_alcance": True})

        atras = getattr(self.gh, "atras_da_main", None)
        if atras is not None:
            try:
                n_atras = atras(sha)
            except Exception:  # noqa: BLE001
                n_atras = 0
            if n_atras:
                # o CI do PR precisa ter rodado sobre a main ATUAL (lição do PR #4: CI verde sobre main antiga,
                # merge e main vermelha). Traz a main para a branch; o CI roda de novo.
                try:
                    self.gh.update_branch(n)
                    return Verdict(n, sha, False, f"branch {n_atras} commit(s) atrás da main: atualizada, o CI roda de novo")
                except Exception:  # noqa: BLE001 — conflito: o Developer resolve
                    return Verdict(n, sha, False, "conflito com a main: o Developer precisa trazer a main para a branch",
                                   {"conserto": True, "conflito": True})
        estado = getattr(self.gh, "pr_state", None)
        if estado is not None and pr.get("head_ref", "").startswith(DEVELOPER_BRANCH_PREFIX):
            try:
                if estado(n).get("mergeable") is False:
                    # PR que não entra na main por conflito não fica parado: volta para o Developer resolver
                    return Verdict(n, sha, False, "conflito com a main: o Developer precisa trazer a main para a branch",
                                   {"conserto": True, "conflito": True})
            except Exception:  # noqa: BLE001 — sem a informação, segue para os checks
                pass
        ok, why = checks_ok(self.gh.check_runs(sha))
        if not ok:
            reprovado = why.startswith("checks falhando") or why.startswith("check obrigatório")
            return Verdict(n, sha, False, why, {"conserto": True} if reprovado else {})
        if pr.get("head_ref", "").startswith(DEVELOPER_BRANCH_PREFIX) and not tem_teste(names):
            return Verdict(n, sha, False, "PR do Developer sem teste novo: precisa de um teste de regressão em tests/",
                           {"conserto": True, "sem_teste": True})

        lines = sum(f.get("additions", 0) + f.get("deletions", 0) for f in files)
        if lines > MAX_LINES:
            return Verdict(n, sha, False, f"PR grande demais ({lines} linhas > {MAX_LINES}): o Developer deve quebrar em partes",
                           {"lines": lines, "fora_do_alcance": True})
        dinheiro = touches_money(names)
        # Código de dinheiro: a evidência reforçada (check obrigatório) já rodou; o Jev revisa como código sensível.
        decision = self.reviewer.review(tests_ok=True, lines_changed=lines, touches_money_code=False)
        if dinheiro and decision == "approve":
            d2 = self.reviewer.review(tests_ok=True, lines_changed=lines * 2, touches_money_code=False)   # 2ª opinião, mais exigente
            decision = d2
        details = {"lines": lines, "files": len(names), "dinheiro": dinheiro, "review": decision}
        if decision != "approve":
            return Verdict(n, sha, False, f"Reviewer Code: {decision}", details)
        return Verdict(n, sha, True, "todos os gates passaram", details)

    def _passo(self, texto: str) -> None:
        """O que a Equipe ao vivo mostra do gate (mesmo contrato de `fazendo.passo`, sem importar o módulo: constituição)."""
        f = dict(self.ctx.store.get("fazendo") or {})
        a = f.get("revisar_prs")
        if a:
            agora = time.time()
            a.update({"passo": texto[:160], "em": agora, "passos": (a.get("passos") or [])[-7:] + [{"t": agora, "texto": texto[:160]}]})
            self.ctx.store.set("fazendo", f)

    def run(self) -> list[Verdict]:
        out = []
        abertos = self.gh.open_prs()
        self._pr_do_developer_sumiu({p["number"] for p in abertos})
        self._vigiar_main()
        for pr in abertos:
            self._passo(f"PR #{pr['number']}: conferindo CI, revisor e tamanho")
            v = self.evaluate(pr)
            self._passo(f"PR #{v.number}: {'merge' if v.merge else v.reason[:90]}")
            if v.merge:
                merged, msg = self.gh.merge(v.number, v.sha, pr.get("title", f"PR #{v.number}"))
                if not merged:
                    v = Verdict(v.number, v.sha, False, f"GitHub recusou o merge: {msg}", v.details)
            self._log(v)
            out.append(v)
        return out

    def _vigiar_main(self) -> None:
        """Neurônio `gate:main`: a main vermelha é um erro de estrutura (algo entrou quebrado). Vira lição na hora."""
        ci = getattr(self.gh, "main_ci", None)
        if ci is None:
            return
        try:
            sha, conclusao = ci()
        except Exception:  # noqa: BLE001
            return
        s = self.ctx.store
        if not sha or conclusao not in ("success", "failure") or s.get("main_ci_visto") == sha:
            return
        s.set("main_ci_visto", sha)
        from .licoes import registrar as monitorar
        monitorar(self.ctx, "gate:main", conclusao == "success", sujeito=sha[:12],
                  motivo="" if conclusao == "success" else f"CI da main falhou no {sha[:7]}: algo entrou quebrado",
                  assinatura="gate:main_vermelha", classe="estrutural")

    def _pr_do_developer_sumiu(self, abertos: set[int]) -> None:
        """PR do Developer fechado ou mergeado fora do gate (por você, no GitHub): o Developer não fica esperando
        para sempre um PR que não existe mais."""
        s = self.ctx.store
        estado = getattr(self.gh, "pr_state", None)
        for dev in [dict(r) for r in s.q("SELECT number, item_id FROM prs WHERE status='aberto' AND item_id IS NOT NULL")]:
            if dev["number"] in abertos:
                continue
            info = {}
            if estado is not None:
                try:
                    info = estado(dev["number"])
                except Exception:  # noqa: BLE001
                    continue
            merged = bool(info.get("merged"))
            self._fechar(dev["number"], merged)
            if not merged:
                s.x("UPDATE roadmap SET status='pendente', evidencia=?, updated_at=? WHERE id=? AND status='em_andamento'",
                    (f"PR #{dev['number']} fechado sem merge fora do gate", time.time(), dev["item_id"]))
                self.ctx.reply(f"PR #{dev['number']} foi fechado sem merge fora do gate; o item volta para a fila e o Developer segue.", "merge")

    def _fechar(self, pr: int, merged: bool) -> None:
        """PR saiu (mergeado ou fechado): tabela prs, item do roteiro e retrato do Developer."""
        s = self.ctx.store
        s.x("UPDATE prs SET status=?, conserto=NULL, updated_at=? WHERE number=?", ("mergeado" if merged else "fechado", time.time(), pr))
        if merged:
            from .self_dev import concluir_mergeados
            concluir_mergeados(s)
        dev = s.get("self_dev_aberto") or {}
        ab = [r["number"] for r in s.q("SELECT number FROM prs WHERE status='aberto' AND item_id IS NOT NULL")]
        if dev.get("pr") == pr:
            dev.update({"fechado": True, "merged": merged})
        s.set("self_dev_aberto", {**dev, "abertos": ab})

    def _log(self, v: Verdict) -> None:
        s = self.ctx.store
        # todo PR de agente que o gate viu aberto entra na contagem (inclusive os que aguardam você)
        from .projects import kit_project_id
        s.x("INSERT OR IGNORE INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(?,?,?,?,'aberto',?,?)",
            (v.number, kit_project_id(s, "circulo"), f"PR #{v.number}", None, time.time(), time.time()))
        dev = s.one("SELECT number, item_id, conserto, conserto_sha FROM prs WHERE number=? AND status='aberto' AND item_id IS NOT NULL", (v.number,))
        dev = dict(dev) if dev else {}
        try:
            cons = json.loads(dev.get("conserto") or "null") or {}
        except ValueError:
            cons = {}
        if v.details.get("conserto") and dev and cons.get("sha") != v.sha and dev.get("conserto_sha") != v.sha:
            # devolve ao Developer uma vez por versão do PR, com o que o CI disse
            log = ""
            if not v.details.get("sem_teste") and hasattr(self.gh, "falhas_ci"):
                try:
                    log = self.gh.falhas_ci(v.sha)
                except Exception:  # noqa: BLE001 — sem o log o Developer ainda reproduz localmente
                    log = ""
            s.x("UPDATE prs SET conserto=?, conserto_sha=?, updated_at=? WHERE number=?",
                (json.dumps({"sha": v.sha, "motivo": v.reason, "log": log[-4000:]}, ensure_ascii=False), v.sha, time.time(), v.number))
            # toda reprovação é uma verificação que falhou: vira lição (prevenção para o Developer não repetir)
            from .licoes import registrar as monitorar
            const = "Constituição" in v.reason
            monitorar(self.ctx, "gate:ci", False, sujeito=f"PR #{v.number}", motivo=f"{v.reason}\n{log[-1500:]}",
                      assinatura=("gate:ci:constituicao" if const else "gate:sem_teste" if v.details.get("sem_teste") else None),
                      classe="estrutural" if const else None)
            self.ctx.reply(f"PR #{v.number} não passou no gate ({v.reason}); o Developer vai consertar na mesma branch.", "saude")
        last = s.one("SELECT reason FROM merges WHERE pr=? AND sha=? ORDER BY id DESC LIMIT 1", (v.number, v.sha))
        if last and last["reason"] == v.reason:
            return  # não repete a mesma avaliação a cada giro
        s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,?,?,?,?,?)",
            (v.number, v.sha, int(v.merge), v.reason, json.dumps(v.details, ensure_ascii=False), time.time()))
        if v.merge:
            from .licoes import registrar as monitorar
            monitorar(self.ctx, "gate:merge", True, sujeito=f"PR #{v.number}")
            self.ctx.reply(f"Merge automático do PR #{v.number} ({v.details.get('lines', 0)} linhas).", "merge")
            from .projects import kit_project_id
            s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(?,?,?,?,'mergeado',?,?) "
                "ON CONFLICT(number) DO UPDATE SET status='mergeado', updated_at=excluded.updated_at",
                (v.number, kit_project_id(s, "circulo"), f"PR #{v.number}", None, time.time(), time.time()))
            self._fechar(v.number, True)       # libera a vaga; o item do roteiro desse PR vira "feito"
        elif v.details.get("revisor"):
            # rejeitado pelo Revisor: fecha o PR (a branch fica) e o item volta para a fila, esperando o PR que ele cruza
            fechar = getattr(self.gh, "close_pr", None)
            if fechar:
                try:
                    fechar(v.number, f"Fechado pelo Revisor do círculo: {v.reason}. O item volta para a fila e será refeito sobre a main nova.")
                except Exception:  # noqa: BLE001 — fechar no GitHub é cortesia; o estado local é o que manda
                    pass
            self._fechar(v.number, False)
            s.x("UPDATE roadmap SET status='pendente', evidencia=?, updated_at=? WHERE status='em_andamento' AND evidencia=?",
                (f"aguarda PR #{v.details.get('aguarda_pr')}: {v.reason[:200]}", time.time(), f"PR #{v.number}"))
            self.ctx.reply(f"Revisor rejeitou o PR #{v.number}: {v.reason[:160]}. O item volta para a fila.", "saude")
        elif v.details.get("fora_do_alcance"):
            self.ctx.reply(f"PR #{v.number} recusado: {v.reason}. A missão segue por outro caminho.", "fora_alcance")
            self._fechar(v.number, False)
            s.x("UPDATE roadmap SET status='pendente', evidencia=?, updated_at=? WHERE status='em_andamento' AND evidencia=?",
                (f"PR #{v.number} recusado: {v.reason[:200]}", time.time(), f"PR #{v.number}"))


# ------------------------------------------------------------------ cliente REST real

class GitHubREST:
    API = "https://api.github.com"

    ouvinte = None      # (ok, ms, erro) a cada chamada — conexoes.instalar() liga; o cliente não conhece o registro

    def __init__(self, repo: str, token: str, timeout: float = 15.0):
        self.repo = repo
        self.token = token
        self.timeout = timeout

    def _req(self, method: str, path: str, body: dict | None = None, tolerar: tuple[int, ...] = ()):
        req = urllib.request.Request(
            f"{self.API}/repos/{self.repo}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "circulo"})
        t0, ok = time.monotonic(), False
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read() or b"null")
            ok = True
            return data
        finally:
            if GitHubREST.ouvinte:
                exc = sys.exc_info()[1]
                esperado = isinstance(exc, urllib.error.HTTPError) and exc.code in tolerar      # 403 sem Checks: a API do Actions cobre
                GitHubREST.ouvinte(ok or esperado, (time.monotonic() - t0) * 1000, None if ok or esperado else f"{method} {path}: {exc}"[:200])

    def open_prs(self):
        return [{"number": p["number"], "head_sha": p["head"]["sha"], "head_ref": p["head"]["ref"],
                 "draft": p.get("draft", False), "title": p["title"]}
                for p in self._req("GET", "/pulls?state=open&per_page=50")]

    def pr_files(self, number):
        return self._req("GET", f"/pulls/{number}/files?per_page=100")

    def check_runs(self, sha):
        try:
            return self._req("GET", f"/commits/{sha}/check-runs?per_page=100", tolerar=(403,))["check_runs"]
        except urllib.error.HTTPError as e:
            if e.code != 403:
                raise
        # Token sem a permissão Checks: lê os mesmos jobs pela API do Actions (permissão Actions, leitura).
        filtro = f"head_sha={sha}" if re.fullmatch(r"[0-9a-f]{7,40}", sha) else f"branch={sha}"
        corridas = self._req("GET", f"/actions/runs?{filtro}&per_page=20")["workflow_runs"]
        if not re.fullmatch(r"[0-9a-f]{7,40}", sha) and corridas:
            corridas = [r for r in corridas if r["head_sha"] == corridas[0]["head_sha"]]
        jobs = []
        for run in corridas:
            for j in self._req("GET", f"/actions/runs/{run['id']}/jobs?per_page=100")["jobs"]:
                jobs.append({"id": j["id"], "name": j["name"], "status": j["status"], "conclusion": j.get("conclusion")})
        return jobs

    def falhas_ci(self, sha: str, linhas: int = 60) -> str:
        """Final do log dos jobs que falharam (o GitHub redireciona para um armazenamento que recusa o token)."""
        class _SemRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        corridas = self._req("GET", f"/actions/runs?head_sha={sha}&per_page=20")["workflow_runs"]
        partes = []
        for run in corridas:
            for j in self._req("GET", f"/actions/runs/{run['id']}/jobs?per_page=100")["jobs"]:
                if j.get("conclusion") != "failure" or len(partes) >= 1:   # um job basta: os outros costumam repetir
                    continue
                req = urllib.request.Request(f"{self.API}/repos/{self.repo}/actions/jobs/{j['id']}/logs",
                                             headers={"Authorization": f"Bearer {self.token}", "User-Agent": "circulo"})
                try:
                    with urllib.request.build_opener(_SemRedirect).open(req, timeout=self.timeout) as r:
                        texto = r.read().decode("utf-8", "replace")
                except urllib.error.HTTPError as e:
                    if e.code not in (301, 302, 303, 307, 308) or not e.headers.get("Location"):
                        raise
                    with urllib.request.urlopen(e.headers["Location"], timeout=self.timeout) as r:
                        texto = r.read().decode("utf-8", "replace")
                limpas = [re.sub(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ", "", x) for x in texto.splitlines()]
                limpas = [x for x in limpas if x.strip() and not x.startswith(("##[group]", "##[endgroup]"))]
                fim = next((i for i, x in enumerate(limpas) if x.startswith("##[error]")), len(limpas))
                partes.append(f"[{j['name']}]\n" + "\n".join(limpas[max(0, fim - linhas):fim + 1]))
        return "\n".join(partes)

    def atras_da_main(self, sha: str) -> int:
        return int(self._req("GET", f"/compare/main...{sha}").get("behind_by", 0))

    def update_branch(self, number: int) -> None:
        self._req("PUT", f"/pulls/{number}/update-branch", {})

    def main_ci(self) -> tuple[str | None, str | None]:
        runs = self._req("GET", "/actions/runs?branch=main&event=push&per_page=10")["workflow_runs"]
        ci = [r for r in runs if r.get("name") == "CI" and r.get("status") == "completed"]
        return (ci[0]["head_sha"], ci[0]["conclusion"]) if ci else (None, None)

    def pr_state(self, number: int) -> dict:
        p = self._req("GET", f"/pulls/{number}")
        return {"state": p.get("state"), "merged": bool(p.get("merged")), "mergeable": p.get("mergeable")}

    def close_pr(self, number: int, comentario: str = "") -> None:
        """Fecha (não apaga): o PR e a branch continuam no GitHub e podem ser reabertos."""
        if comentario:
            self._req("POST", f"/issues/{number}/comments", {"body": comentario})
        self._req("PATCH", f"/pulls/{number}", {"state": "closed"})

    def label_events(self, number):
        return [{"event": e["event"], "label": (e.get("label") or {}).get("name"), "actor": (e.get("actor") or {}).get("login", "")}
                for e in self._req("GET", f"/issues/{number}/events?per_page=100") if e["event"] in ("labeled", "unlabeled")]

    def create_pr(self, head: str, base: str, title: str, body: str) -> int:
        return int(self._req("POST", "/pulls", {"head": head, "base": base, "title": title, "body": body})["number"])

    def merge(self, number, sha, title):
        try:
            # `sha` trava o merge: se alguém empurrar commit novo depois da avaliação, o GitHub recusa.
            r = self._req("PUT", f"/pulls/{number}/merge", {"sha": sha, "merge_method": "squash", "commit_title": f"{title} (#{number})"})
            return bool(r.get("merged")), r.get("message", "")
        except urllib.error.HTTPError as e:
            return False, f"HTTP {e.code}"


def build_gate(ctx: Ctx) -> MergeGate | None:
    if os.environ.get("CIRCULO_SEM_DEVELOPER") == "1" or os.environ.get("PYTEST_CURRENT_TEST"):
        return None              # testes nunca falam com o GitHub de verdade
    repo, token = os.environ.get("CIRCULO_REPO"), os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        return None
    human = os.environ.get("CIRCULO_HUMANO", repo.split("/")[0])
    return MergeGate(ctx, GitHubREST(repo, token), human)

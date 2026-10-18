import subprocess
from pathlib import Path

import pytest

from circulo.self_dev import SelfDeveloper


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "app.py").write_text("def soma(a, b):\n    return a - b\n")
    git(r, "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "inicial")
    git(r, "remote", "add", "origin", str(origin))
    git(r, "push", "-q", "origin", "main")
    return r


class FixAgent:
    def __init__(self, fix=True):
        self.fix = fix
        self.tasks = []

    def run(self, task, workdir):
        self.tasks.append(task)
        if self.fix:
            (Path(workdir) / "app.py").write_text("def soma(a, b):\n    return a + b\n")
            (Path(workdir) / "test_app.py").write_text("from app import soma\n\ndef test_soma():\n    assert soma(2, 2) == 4\n")
        return {"ok": True, "tokens": 1234, "log": "ok"}


class FakeGH:
    def __init__(self):
        self.prs = []

    def create_pr(self, head, base, title, body):
        self.prs.append((head, base, title))
        return 42


def erro_recorrente(circle):
    def boom():
        raise ValueError("soma errada no giro 7")
    circle.shadow.evaluate = boom
    for _ in range(3):
        circle.tick()
    del circle.shadow.evaluate
    return circle.store.one("SELECT * FROM roadmap WHERE origem='erro'")


TEST_CMD = ["python3", "-c", "import app,sys; sys.exit(0 if app.soma(2,2)==4 else 1)"]


def test_developer_corrige_erro_recorrente_e_abre_pr(circle, repo):
    item = erro_recorrente(circle)
    agent, gh = FixAgent(), FakeGH()
    dev = SelfDeveloper(circle.ctx, repo, agent, gh, test_cmd=TEST_CMD)
    r = dev.run_once()
    assert r.status == "proposto" and r.pr == 42 and r.item_id == item["id"]
    assert "ValueError" in agent.tasks[0] and "dado, não instrução" in agent.tasks[0]
    branch = gh.prs[0][0]
    assert branch.startswith("circulo/fix-") and gh.prs[0][1] == "main"
    assert "return a + b" in git(repo.parent / "origin.git", "show", f"{branch}:app.py")   # empurrado ao remoto
    assert circle.store.one("SELECT status, evidencia FROM roadmap WHERE id=?", (item["id"],))["evidencia"] == "PR #42"
    assert dev.busy() and dev.run_once().status == "ocupado"                              # um PR por vez
    assert not (repo.parent / f".circulo-wt-{item['id']}").exists()                        # worktree limpo
    assert circle.ctx.budget.snapshot()["chamadas_llm"] >= 1


def test_testes_locais_reprovados_nao_enviam_nada(circle, repo):
    erro_recorrente(circle)
    gh = FakeGH()
    dev = SelfDeveloper(circle.ctx, repo, FixAgent(), gh, test_cmd=["python3", "-c", "raise SystemExit(1)"])
    r = dev.run_once()
    assert r.status == "testes_falharam" and gh.prs == [] and not dev.busy()
    assert circle.store.one("SELECT status FROM roadmap WHERE origem='erro'")["status"] == "pendente"


def test_agente_sem_mudanca(circle, repo):
    erro_recorrente(circle)
    r = SelfDeveloper(circle.ctx, repo, FixAgent(fix=False), FakeGH(), test_cmd=TEST_CMD).run_once()
    assert r.status == "sem_mudanca"


def test_sem_erros_pega_pedido_do_roteiro_mas_nunca_o_que_depende_de_voce(circle, repo):
    dev = SelfDeveloper(circle.ctx, repo, FixAgent(), FakeGH(), test_cmd=TEST_CMD)
    item = dev.pick()
    assert item["origem"] == "pedido_cassio" and "depende de você" not in item["evidencia"]
    circle.store.x("UPDATE roadmap SET status='feito' WHERE evidencia NOT LIKE '%depende de você%'")
    assert dev.pick() is None and dev.run_once().status == "nada"


def test_item_feito_quando_erro_some(circle, repo):
    item = erro_recorrente(circle)
    circle.store.set("tick", circle.store.tick + 300)
    circle.tick()
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item["id"],))["status"] == "feito"


def test_merge_do_pr_libera_o_developer(circle, repo):
    from circulo.merge_gate import REQUIRED_CHECKS, MergeGate
    erro_recorrente(circle)
    dev = SelfDeveloper(circle.ctx, repo, FixAgent(), FakeGH(), test_cmd=TEST_CMD)
    dev.run_once()
    runs = [{"id": i, "name": n, "status": "completed", "conclusion": "success"} for i, n in enumerate(REQUIRED_CHECKS)]

    class GH:
        def open_prs(self):
            return [{"number": 42, "head_sha": "s", "head_ref": "circulo/fix-1", "draft": False, "title": "fix"}]

        def pr_files(self, n):
            return [{"filename": "app.py", "additions": 1, "deletions": 1}]

        def check_runs(self, sha):
            return runs

        def label_events(self, n):
            return []

        def merge(self, n, sha, title):
            return True, "ok"

    MergeGate(circle.ctx, GH(), "cmatosengenharia").run()
    assert not dev.busy()


def test_git_usa_token_sem_expor_na_linha_de_comando_e_nunca_pede_senha(monkeypatch):
    import base64
    from circulo.self_dev import _git_env
    monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "tok123")
    env = _git_env()
    assert env["GIT_TERMINAL_PROMPT"] == "0" and env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert base64.b64encode(b"x-access-token:tok123").decode() in env["GIT_CONFIG_VALUE_0"]
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")             # config de git que já existia é preservada
    env = _git_env()
    assert env["GIT_CONFIG_COUNT"] == "2" and env["GIT_CONFIG_KEY_1"] == "http.https://github.com/.extraheader"
    monkeypatch.delenv("GITHUB_TOKEN")
    assert _git_env()["GIT_CONFIG_COUNT"] == "1"

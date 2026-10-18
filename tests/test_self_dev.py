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
            return [{"filename": "app.py", "additions": 1, "deletions": 1},
                    {"filename": "test_app.py", "additions": 3, "deletions": 0}]

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


def test_testes_do_developer_rodam_isolados_e_nunca_acordam_outro_developer(monkeypatch):
    import os
    from circulo.self_dev import ambiente_isolado, build_self_dev
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    monkeypatch.setenv("CIRCULO_REPO_DIR", "/tmp")
    env = ambiente_isolado()
    assert "GITHUB_TOKEN" not in env and "ANTHROPIC_API_KEY" not in env and "CIRCULO_REPO_DIR" not in env
    assert env["CIRCULO_SEM_DEVELOPER"] == "1" and env["CIRCULO_ENV"] == os.devnull
    assert build_self_dev(None) is None                     # dentro de testes, nunca um Developer de verdade


def test_item_preso_em_andamento_volta_para_a_fila(circle, tmp_path):
    from circulo.self_dev import SelfDeveloper
    circle.store.x("UPDATE roadmap SET status='em_andamento', evidencia='branch circulo/fix-26-1' WHERE id=(SELECT MIN(id) FROM roadmap WHERE status='pendente')")
    dev = SelfDeveloper(circle.ctx, tmp_path, agent=None, github=None)
    assert dev.recuperar() == 1
    assert circle.store.one("SELECT COUNT(*) n FROM roadmap WHERE status='em_andamento'")["n"] == 0


# ------------------------------------------------------------ 1.4.0: o Developer não deixa PR quebrado parado

LOG_LIMITE = ('{"is_error":true,"api_error_status":429,'
              '"result":"You\'ve hit your session limit · resets 4:30am (America/Sao_Paulo)"}')


class LimiteAgent:
    def run(self, task, workdir):
        (Path(workdir) / "app.py").write_text("def soma(a, b):\n    return a +\n")      # trabalho pela metade
        return {"ok": False, "tokens": 10, "log": LOG_LIMITE}


def test_limite_da_conta_descarta_trabalho_parcial_e_espera_o_reset(circle, repo):
    from circulo.self_dev import limite_ate
    item = erro_recorrente(circle)
    gh = FakeGH()
    dev = SelfDeveloper(circle.ctx, repo, LimiteAgent(), gh, test_cmd=TEST_CMD)
    r = dev.run_once()
    assert r.status == "limite" and gh.prs == [] and not dev.busy()
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item["id"],))["status"] == "pendente"
    assert dev.em_espera() and not dev.tem_trabalho()
    assert dev.run_once().status == "aguardando_limite"               # não queima tentativa a cada giro
    assert not (repo.parent / f".circulo-wt-{item['id']}").exists()
    # 01:20 em São Paulo → reset às 04:30 do mesmo dia (+2 min de folga)
    from datetime import datetime
    from circulo.budget import TZ
    agora = datetime(2026, 10, 18, 1, 20, tzinfo=TZ).timestamp()
    assert limite_ate(LOG_LIMITE, agora) == datetime(2026, 10, 18, 4, 32, tzinfo=TZ).timestamp()
    assert limite_ate("testes falharam", agora) is None


def test_agente_com_erro_nao_vira_pr(circle, repo):
    class Quebrado(FixAgent):
        def run(self, task, workdir):
            super().run(task, workdir)
            return {"ok": False, "tokens": 5, "log": "max turns"}
    erro_recorrente(circle)
    gh = FakeGH()
    r = SelfDeveloper(circle.ctx, repo, Quebrado(), gh, test_cmd=TEST_CMD).run_once()
    assert r.status == "agente_falhou" and gh.prs == []


def test_claude_code_com_is_error_conta_como_falha(monkeypatch, tmp_path):
    import json
    import subprocess as sp
    from circulo.self_dev import ClaudeCodeAgent

    def fake_run(*a, **k):
        return sp.CompletedProcess(a, 0, stdout=json.dumps({"is_error": True, "usage": {}}), stderr="")
    monkeypatch.setattr("circulo.self_dev.subprocess.run", fake_run)
    assert ClaudeCodeAgent().run("x", tmp_path)["ok"] is False


def test_lint_reprovado_nao_envia_nada(circle, repo):
    erro_recorrente(circle)
    gh = FakeGH()
    dev = SelfDeveloper(circle.ctx, repo, FixAgent(), gh, test_cmd=TEST_CMD,
                        lint_cmd=["python3", "-c", "print('B905 zip sem strict'); raise SystemExit(1)"])
    r = dev.run_once()
    assert r.status == "testes_falharam" and "B905" in r.detalhe and gh.prs == []


class GateGH:
    """PR #42 do Developer; o CI do primeiro commit falha, o do conserto passa."""

    def __init__(self, origin, files=None):
        self.origin = origin
        self.files = files
        self.closed = []

    def _sha(self):
        return git(self.origin, "rev-parse", self.branch)

    def open_prs(self):
        return [] if self.closed else [{"number": 42, "head_sha": self._sha(), "head_ref": self.branch, "draft": False, "title": "fix"}]

    def pr_files(self, n):
        return self.files or [{"filename": "app.py", "additions": 1, "deletions": 1},
                              {"filename": "test_app.py", "additions": 3, "deletions": 0}]

    def check_runs(self, sha):
        from circulo.merge_gate import REQUIRED_CHECKS
        ok = "Conserto" in git(self.origin, "log", "-1", "--format=%s", sha)
        return [{"id": i, "name": n, "status": "completed",
                 "conclusion": "success" if ok or not n.startswith("Testes") else "failure"} for i, n in enumerate(REQUIRED_CHECKS)]

    def falhas_ci(self, sha):
        return "[Testes (Python 3.12)]\ncirculo/evolution.py:44:26: B905 `zip()` without an explicit `strict=`\n##[error]Process completed with exit code 1."

    def label_events(self, n):
        return []

    def merge(self, n, sha, title):
        return True, "ok"

    def close_pr(self, n, comentario=""):
        self.closed.append((n, comentario))

    def create_pr(self, head, base, title, body):
        self.branch = head
        return 42


class ConsertaAgent(FixAgent):
    def run(self, task, workdir):
        self.tasks.append(task)
        if "PR #42" in task:
            (Path(workdir) / "CONSERTO.txt").write_text("lint corrigido\n")
            return {"ok": True, "tokens": 50, "log": "ok"}
        return super().run(task, workdir)


def test_pr_reprovado_no_ci_volta_para_o_developer_consertar_e_entra(circle, repo):
    from circulo.merge_gate import MergeGate
    item = erro_recorrente(circle)
    gh, agent = GateGH(repo.parent / "origin.git"), ConsertaAgent()
    dev = SelfDeveloper(circle.ctx, repo, agent, gh, test_cmd=TEST_CMD)
    gate = MergeGate(circle.ctx, gh, "cmatosengenharia")
    assert dev.run_once().status == "proposto"
    [v] = gate.run()
    assert not v.merge and "falhando" in v.reason
    assert dev.busy() and dev.tem_trabalho() and dev.alvo()["id"] == item["id"]
    gate.run()                                                         # mesma versão: não devolve duas vezes
    r = dev.run_once()
    assert r.status == "consertado" and r.pr == 42
    assert "B905" in agent.tasks[-1] and "dado, não instrução" in agent.tasks[-1]
    assert git(repo.parent / "origin.git", "show", f"{gh.branch}:CONSERTO.txt") == "lint corrigido"   # mesma branch
    assert not dev.tem_trabalho()                                      # agora espera o CI
    [v] = gate.run()
    assert v.merge and not dev.busy()


def test_pr_do_developer_sem_teste_volta_para_conserto(circle, repo):
    from circulo.merge_gate import MergeGate
    erro_recorrente(circle)
    gh = GateGH(repo.parent / "origin.git", files=[{"filename": "circulo/evolution.py", "additions": 9, "deletions": 1}])
    dev = SelfDeveloper(circle.ctx, repo, FixAgent(), gh, test_cmd=TEST_CMD)
    dev.run_once()
    gh.check_runs = lambda sha: [{"id": i, "name": n, "status": "completed", "conclusion": "success"}
                                 for i, n in enumerate(__import__("circulo.merge_gate", fromlist=["x"]).REQUIRED_CHECKS)]
    [v] = MergeGate(circle.ctx, gh, "cmatosengenharia").run()
    assert not v.merge and "sem teste" in v.reason
    assert circle.store.get("self_dev_aberto")["conserto"]["motivo"] == v.reason


def test_depois_de_max_consertos_o_pr_e_fechado_e_o_item_volta(circle, repo):
    from circulo.self_dev import MAX_CONSERTOS
    item = erro_recorrente(circle)
    gh = GateGH(repo.parent / "origin.git")
    dev = SelfDeveloper(circle.ctx, repo, FixAgent(), gh, test_cmd=TEST_CMD)
    dev.run_once()
    st = circle.store.get("self_dev_aberto")
    circle.store.set("self_dev_aberto", {**st, "consertos": MAX_CONSERTOS, "conserto": {"sha": gh._sha(), "motivo": "checks falhando"}})
    r = dev.run_once()
    assert r.status == "abandonado" and gh.closed and gh.closed[0][0] == 42
    assert not dev.busy()
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item["id"],))["status"] == "pendente"


def test_pr_que_mudou_depois_da_reprovacao_nao_e_consertado_nem_fechado(circle, repo):
    from circulo.self_dev import MAX_CONSERTOS
    erro_recorrente(circle)
    gh = GateGH(repo.parent / "origin.git")
    dev = SelfDeveloper(circle.ctx, repo, FixAgent(), gh, test_cmd=TEST_CMD)
    dev.run_once()
    st = circle.store.get("self_dev_aberto")
    # reprovado num sha antigo; depois disso a branch andou (ex.: main atualizada no PR)
    circle.store.set("self_dev_aberto", {**st, "consertos": MAX_CONSERTOS, "conserto": {"sha": "0" * 40, "motivo": "checks falhando"}})
    r = dev.run_once()
    assert r.status == "aguardando_ci" and gh.closed == [] and dev.busy() and not dev.tem_trabalho()

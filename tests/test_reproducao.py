"""Reprodução primeiro: o teste novo precisa falhar no código antigo e passar no novo."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from circulo.reproducao import main, reproduz
from circulo.reproducao import testes_novos as novos_de


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    (r / "tests").mkdir(parents=True)
    git(r, "init", "-q", "-b", "main")
    (r / "app.py").write_text("def soma(a, b):\n    return a - b\n\ndef dobro(x):\n    return 2 * x\n")
    (r / "tests" / "test_app.py").write_text("from app import dobro\n\ndef test_dobro():\n    assert dobro(2) == 4\n")
    git(r, "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    return r


def _commit(r, msg):
    git(r, "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


def test_teste_que_reproduz_o_erro_passa_no_portao(repo):
    git(repo, "checkout", "-q", "-b", "fix")
    (repo / "app.py").write_text("def soma(a, b):\n    return a + b\n\ndef dobro(x):\n    return 2 * x\n")
    (repo / "tests" / "test_app.py").write_text((repo / "tests" / "test_app.py").read_text()
                                                + "\nfrom app import soma\n\ndef test_soma():\n    assert soma(2, 2) == 4\n")
    _commit(repo, "fix")
    assert novos_de(repo, "main", "HEAD") == ["tests/test_app.py::test_soma"]   # o teste antigo não conta
    ok, det, _ = reproduz(repo, "main", "HEAD")
    assert ok and "reproduzido" in det
    assert main(["--repo", str(repo), "--base", "main"]) == 0


def test_teste_que_ja_passa_no_codigo_antigo_e_barrado(repo):
    git(repo, "checkout", "-q", "-b", "falso")
    (repo / "app.py").write_text("def soma(a, b):\n    return a + b\n\ndef dobro(x):\n    return 2 * x\n")
    (repo / "tests" / "test_extra.py").write_text("from app import dobro\n\ndef test_dobro_zero():\n    assert dobro(0) == 0\n")
    _commit(repo, "teste que não prova nada")
    ok, det, novos = reproduz(repo, "main", "HEAD")
    assert not ok and "já passam no código antigo" in det and novos == ["tests/test_extra.py::test_dobro_zero"]
    assert main(["--repo", str(repo), "--base", "main"]) == 1


def test_arvore_de_trabalho_sem_commit_e_codigo_que_ainda_nao_existe(repo):
    (repo / "novo.py").write_text("def triplo(x):\n    return 3 * x\n")
    (repo / "tests" / "test_novo.py").write_text("from novo import triplo\n\ndef test_triplo():\n    assert triplo(2) == 6\n")
    ok, det, novos = reproduz(repo, "HEAD", None)          # como o Developer antes do commit
    assert ok and novos == ["tests/test_novo.py::test_triplo"]   # no código antigo nem importa: reproduz


def test_sem_teste_novo_nao_trava(repo):
    (repo / "app.py").write_text("def soma(a, b):\n    return a + b\n\ndef dobro(x):\n    return 2 * x\n")
    ok, det, novos = reproduz(repo, "HEAD", None)
    assert ok and novos == []


def test_developer_nao_abre_pr_com_teste_que_nao_reproduz(circle, tmp_path):
    """Integração com o portão do Developer: o agente "corrige", mas o teste dele já passava antes."""
    from pathlib import Path

    from circulo.self_dev import SelfDeveloper
    from test_self_dev import TEST_CMD, FakeGH, erro_recorrente

    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    r = tmp_path / "dev"
    (r / "tests").mkdir(parents=True)
    git(r, "init", "-q", "-b", "main")
    (r / "app.py").write_text("def soma(a, b):\n    return a - b\n")
    _commit(r, "inicial")
    git(r, "remote", "add", "origin", str(origin))
    git(r, "push", "-q", "origin", "main")

    class AgenteSemReproducao:
        def run(self, task, workdir):
            (Path(workdir) / "app.py").write_text("def soma(a, b):\n    return a + b\n")
            (Path(workdir) / "tests").mkdir(exist_ok=True)
            (Path(workdir) / "tests" / "test_app.py").write_text("import app\n\ndef test_existe():\n    assert app.soma\n")
            return {"ok": True, "tokens": 1, "log": "ok"}
    erro_recorrente(circle)
    gh = FakeGH()
    res = SelfDeveloper(circle.ctx, r, AgenteSemReproducao(), gh, test_cmd=TEST_CMD).run_once()
    assert res.status == "testes_falharam" and "reprodução primeiro" in res.detalhe and not gh.prs


_FINDER_EDITAVEL = '''import sys
from importlib.machinery import PathFinder

MAPPING = {"pkg": %r}


class _EditableFinder:  # como o __editable___*_finder.py que o setuptools instala no `pip install -e`
    @classmethod
    def find_spec(cls, fullname, path=None, target=None):
        parent, _, _ = fullname.rpartition(".")
        if parent in MAPPING:
            return PathFinder.find_spec(fullname, path=[MAPPING[parent]])


def install():
    sys.meta_path.append(_EditableFinder)
'''


def test_instalacao_editavel_do_checkout_novo_nao_vaza_modulo_novo_para_o_codigo_antigo(tmp_path):
    """No CI, o `pip install -e .` resolvia `pkg.modulo_novo` pelo checkout do PR mesmo com o código antigo no
    PYTHONPATH: o teste novo passava no código antigo e o portão reprovava um PR que reproduzia (PR #39)."""
    r = tmp_path / "r"
    (r / "pkg").mkdir(parents=True)
    git(r, "init", "-q", "-b", "main")
    (r / "pkg" / "__init__.py").write_text("")
    _commit(r, "base")
    (r / "pkg" / "novo.py").write_text("def um():\n    return 1\n")
    (r / "tests").mkdir()
    (r / "tests" / "test_novo.py").write_text("from pkg.novo import um\n\ndef test_um():\n    assert um() == 1\n")
    _commit(r, "módulo novo")

    env = {**os.environ, "PYTHONUSERBASE": str(tmp_path / "userbase")}
    ativo, usersite = subprocess.run(
        [sys.executable, "-c", "import site; print(site.ENABLE_USER_SITE); print(site.getusersitepackages())"],
        env=env, capture_output=True, text=True, check=True).stdout.split("\n")[:2]
    if ativo != "True":
        pytest.skip("interpretador sem site de usuário (venv): não dá para simular a instalação editável")
    usersite = Path(usersite)
    usersite.mkdir(parents=True)
    (usersite / "__editable___pkg_finder.py").write_text(_FINDER_EDITAVEL % str(r / "pkg"))
    (usersite / "__editable__.pkg.pth").write_text("import __editable___pkg_finder; __editable___pkg_finder.install()\n")

    ok, det, novos = reproduz(r, "HEAD~1", "HEAD", env=env)
    assert novos == ["tests/test_novo.py::test_um"]
    assert ok and "reproduzido" in det

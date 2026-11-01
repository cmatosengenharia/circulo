"""Autofix determinístico do lint antes do commit do Developer (item #190, pergunta #234).

As lições de lint #36, #70, #71, #76 e #77 reincidiram sempre em tests/. O que tem correção mecânica (F401, F541 e
B905) sai sem LLM; só o que sobra (F811, por exemplo) volta ao agente. O `ruff check --fix` não corrige o B905 (fix
inseguro), então o B905 é corrigido antes por AST, com `strict=False`, que mantém o comportamento do `zip`."""
import re
import sys
from pathlib import Path

from test_self_dev import FakeGH, erro_recorrente, git, repo  # noqa: F401 — fixture do repositório

from circulo import lint_fix, reparo

COM_ERROS = '''import os


def soma(a, b):
    return [x + y for x, y in zip(a, b)]


def soma(a, b):
    return f"soma"
'''
PY311 = '[project]\nname = "x"\nrequires-python = ">=3.11"\n'


def projeto(raiz: Path, pyproject: str = PY311) -> Path:
    raiz.mkdir(exist_ok=True)
    (raiz / "pyproject.toml").write_text(pyproject)
    for nome in ("tests/test_alvo.py", "circulo/x.py"):
        (raiz / nome).parent.mkdir(exist_ok=True)
        (raiz / nome).write_text(COM_ERROS)
    return raiz


def test_autofix_zera_f401_f541_b905_e_devolve_so_o_f811(tmp_path):
    projeto(tmp_path)
    pendentes = lint_fix.corrigir(["tests/test_alvo.py"], cwd=tmp_path)
    assert [d.split(": ", 1)[1].split()[0] for d in pendentes] == ["F811"], pendentes
    texto = (tmp_path / "tests/test_alvo.py").read_text()
    assert "import os" not in texto and 'return "soma"' in texto and "zip(a, b, strict=False)" in texto


def test_autofix_so_toca_tests_e_so_poe_strict_com_python_alvo_que_o_tem(tmp_path):
    projeto(tmp_path)
    assert lint_fix.corrigir(["circulo/x.py"], cwd=tmp_path) == []
    assert (tmp_path / "circulo/x.py").read_text() == COM_ERROS
    antigo = projeto(tmp_path / "py39", '[project]\nname = "x"\nrequires-python = ">=3.9"\n')
    lint_fix.corrigir(["tests/test_alvo.py"], cwd=antigo)
    assert "strict=" not in (antigo / "tests/test_alvo.py").read_text()     # no 3.9 o strict= quebraria o zip
    assert lint_fix.alvo_python(tmp_path) == (3, 11) and lint_fix.alvo_python(tmp_path / "nada") is None


def test_b905_por_ast_respeita_virgula_final_aninhado_e_strict_existente():
    fonte = ("pares = zip(\n    a,\n    zip(b, c),\n)\n"
             "ok = zip(a, b, strict=True)\n"
             "vazio = zip()\n")
    assert lint_fix.corrigir_b905(fonte) == ("pares = zip(\n    a,\n    zip(b, c, strict=False), strict=False,\n)\n"
                                             "ok = zip(a, b, strict=True)\n"
                                             "vazio = zip()\n")
    assert lint_fix.corrigir_b905("x = (\n") == "x = (\n"          # sem parse: não toca


class AgenteDeTesteSujo:
    """Corrige o app e escreve o teste em tests/ com F401, F541 e B905: o lint do CI reprova antes do autofix."""

    def __init__(self):
        self.tasks = []

    def run(self, task, workdir):
        self.tasks.append(task)
        m = re.search(r"lição #(\d+)", task)         # o teste de regressão cita a lição que ele prova
        marca = f"    # lição #{m.group(1)}\n" if m else ""
        wt = Path(workdir)
        (wt / "app.py").write_text("def soma(a, b):\n    return a + b\n")
        (wt / "pyproject.toml").write_text(PY311)
        (wt / "tests").mkdir(exist_ok=True)
        (wt / "tests/test_app.py").write_text(
            "import os\n\nfrom app import soma\n\n\ndef test_soma():\n" + marca +
            "    assert [soma(a, b) for a, b in zip([2], [2])] == [4], f\"soma\"\n")
        return {"ok": True, "tokens": 1000, "log": "ok"}


def test_developer_abre_pr_com_o_lint_fix_sem_gastar_rodada_do_agente(circle, repo):  # noqa: F811
    erro_recorrente(circle)
    agent, gh = AgenteDeTesteSujo(), FakeGH()
    lint = [sys.executable, "-m", "ruff", "check", "tests", *lint_fix.SELECAO_CI, "--output-format", "concise"]
    teste = [sys.executable, "-c", "import app,sys; sys.exit(0 if app.soma(2,2)==4 else 1)"]
    dev = reparo.DeveloperComReparo(circle.ctx, repo, agent, gh, test_cmd=teste, lint_cmd=lint, fix_cmds=reparo.RUFF_FIX)
    r = dev.run_once()
    assert r.status == "proposto" and gh.prs, r.detalhe
    assert len(agent.tasks) == 1                                    # nenhuma rodada de reparo da LLM pelo lint
    autofix = circle.store.one("SELECT ok, motivo FROM verificacoes WHERE ponto='developer:autofix'")
    assert autofix["ok"] == 1 and "0 depois" in autofix["motivo"], autofix["motivo"]

"""Lição #78: um portão de lint aprendido (`ruff --select B905,E501,...`) nunca é mais estrito que o CI.

O CI roda `--ignore E501`; o portão herdava o E501 da lição e barrava qualquer PR por linhas longas que já estavam no
main (tests/test_vigia_drena.py:93). O loop julga o PR com o código do main, então a política do CI também mora no
pyproject.toml, que o ruff lê do worktree do PR."""
import subprocess
import tomllib
from pathlib import Path

from circulo import self_dev
from circulo.neuronios import ABRIR_PR, avaliar_aprendidos, criar_portao

IGNORADOS_NO_CI = self_dev.LINT_CMD[self_dev.LINT_CMD.index("--ignore") + 1].split(",")


def test_pyproject_ignora_em_qualquer_arquivo_o_que_o_ci_ignora():  # lição #78
    cfg = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())
    por_arquivo = cfg.get("tool", {}).get("ruff", {}).get("lint", {}).get("per-file-ignores", {})
    assert set(IGNORADOS_NO_CI) <= set(por_arquivo.get("*.py", []))


def test_portao_de_lint_aprendido_ignora_o_que_o_ci_ignora(circle, tmp_path, monkeypatch):  # lição #78
    criar_portao(circle.store, ABRIR_PR, "comando",
                 {"argv": ["-m", "ruff", "check", "circulo", "tests", "--select", "B905,E501,F401"]}, "lint", 78)
    rodados = []
    monkeypatch.setattr(self_dev, "garantir_ruff", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: rodados.append(argv) or
                        subprocess.CompletedProcess(argv, 0, "", ""))
    [r] = avaliar_aprendidos(circle.store, ABRIR_PR, tmp_path, {}, {})
    assert r.ok and rodados[0][rodados[0].index("--ignore") + 1].split(",") == IGNORADOS_NO_CI

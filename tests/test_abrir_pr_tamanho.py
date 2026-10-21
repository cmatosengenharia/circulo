"""Pré-checagem de tamanho em developer:abrir_pr: excedeu → causa dominante na trilha e na lição, item ao fatiador,
sem push, sem CI e sem PR."""
from unittest import mock

from test_reparo import ZipAgent, dev_de
from test_self_dev import erro_recorrente, repo  # noqa: F401 — fixture do repositório

from circulo import fatiador, self_dev

GRANDE = "10\t0\tapp.py\n" + "".join(f"300\t0\ttests/test_{i}.py\n" for i in range(3))
PEQUENO = "4\t1\tapp.py\n6\t0\ttests/test_app.py\n"


def _simulado(circle, repo, tmp_path, numstat):  # noqa: F811
    item = erro_recorrente(circle)
    dev, gh = dev_de(circle, repo, tmp_path, ZipAgent(conserta_na=1))
    dev._numstat = lambda wt, base: numstat
    dev.verificar = mock.Mock(return_value=(True, ""))
    gh.create_pr = mock.Mock(return_value=42)
    git_real = self_dev._git
    pushes = mock.Mock()

    def git(args, cwd, check=True):
        if args and args[0] == "push":
            pushes(args)
            return ""
        return git_real(args, cwd, check)
    return item, dev, gh, pushes, git


def test_excedeu_devolve_ao_fatiador(circle, repo, tmp_path):  # noqa: F811
    item, dev, gh, pushes, git = _simulado(circle, repo, tmp_path, GRANDE)
    with mock.patch.object(self_dev, "_git", git), mock.patch("circulo.reparo._git", git):
        r = dev.run_once()
    assert r.status == "tamanho" and "domina teste" in r.detalhe
    pushes.assert_not_called()
    dev.verificar.assert_not_called()
    gh.create_pr.assert_not_called()
    trilha = circle.store.one("SELECT motivo, causa FROM verificacoes WHERE ponto='developer:abrir_pr' AND ok=0")
    assert trilha["causa"] == "tamanho:teste" and "tests/test_0.py" in trilha["motivo"]
    licao = circle.store.one("SELECT assinatura FROM licoes WHERE assinatura='developer:abrir_pr:tamanho:teste'")
    assert licao is not None
    assert "910 linhas" in fatiador.motivo_de_dividir(circle.store, item["id"])
    assert "fatiador" in circle.store.one("SELECT evidencia FROM roadmap WHERE id=?", (item["id"],))["evidencia"]


def test_dentro_do_limite_segue(circle, repo, tmp_path):  # noqa: F811
    item, dev, gh, pushes, git = _simulado(circle, repo, tmp_path, PEQUENO)
    with mock.patch.object(self_dev, "_git", git), mock.patch("circulo.reparo._git", git):
        r = dev.run_once()
    assert r.status == "proposto" and r.pr == 42
    pushes.assert_called_once()
    dev.verificar.assert_called()
    gh.create_pr.assert_called_once()
    assert fatiador.motivo_de_dividir(circle.store, item["id"]) == ""

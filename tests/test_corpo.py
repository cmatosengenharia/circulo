"""Corpo: o loop passa a rodar o código que evoluiu, com validação antes e evidência depois (com rollback)."""
import subprocess
import sys

import pytest

from circulo.corpo import MAX_ERROS_NA_VALIDACAO, VALIDAR_GIROS, Corpo


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repos(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    vivo = tmp_path / "vivo"
    vivo.mkdir()
    git(vivo, "init", "-q", "-b", "main")
    (vivo / "app.py").write_text("V = 1\n")
    git(vivo, "add", "-A")
    git(vivo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "v1")
    git(vivo, "remote", "add", "origin", str(origin))
    git(vivo, "push", "-q", "origin", "main")
    dev = tmp_path / "dev"                      # outro clone: onde o "merge" acontece
    git(tmp_path, "clone", "-q", str(origin), str(dev))
    return origin, vivo, dev


def evoluir(dev, conteudo="V = 2\n"):
    (dev / "app.py").write_text(conteudo)
    git(dev, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "evolução")
    git(dev, "push", "-q", "origin", "main")
    return git(dev, "rev-parse", "HEAD")


OK = [[sys.executable, "-c", "import app; assert app.V >= 1"]]


def test_codigo_novo_validado_vira_o_corpo_e_reinicia(circle, repos, tmp_path):
    _, vivo, dev = repos
    c = Corpo(circle.ctx, vivo, tmp_path, validacao=OK)
    assert not c.precisa()
    novo = evoluir(dev)
    circle.store.set("corpo", {"checado_tick": -10**6})
    assert c.precisa()
    (vivo / "anotacao_local.txt").write_text("não pode sumir\n")      # mudança local fica guardada
    r = c.run()
    assert r["status"] == "atualizado" and git(vivo, "rev-parse", "HEAD") == novo
    assert (vivo / "app.py").read_text() == "V = 2\n" and c.reiniciar
    assert (vivo / "anotacao_local.txt").exists()                      # nunca apaga arquivo não rastreado
    assert "anotacao_local.txt" in open(r["patch"]).read()
    assert circle.store.get("corpo")["estado"] == "validando"
    for _ in range(VALIDAR_GIROS):
        c.validar([])
    assert circle.store.get("corpo")["estado"] == "ok"
    assert circle.store.one("SELECT ok FROM verificacoes WHERE ponto='corpo:evidencia'")["ok"] == 1


def test_codigo_que_nao_passa_na_validacao_nao_vira_corpo(circle, repos, tmp_path):
    _, vivo, dev = repos
    antes = git(vivo, "rev-parse", "HEAD")
    novo = evoluir(dev, "V = (\n")                                     # quebrado
    c = Corpo(circle.ctx, vivo, tmp_path, validacao=OK)
    r = c.run()
    assert r["status"] == "reprovado" and git(vivo, "rev-parse", "HEAD") == antes and not c.reiniciar
    circle.store.set("corpo", {**circle.store.get("corpo"), "checado_tick": -10**6})
    assert not c.precisa()                                             # não tenta de novo o mesmo código reprovado
    assert novo in circle.store.get("corpo")["reprovados"]
    assert circle.store.one("SELECT classe FROM licoes WHERE assinatura='corpo:validacao_falhou'")["classe"] == "estrutural"


def test_erros_nos_primeiros_giros_voltam_para_o_codigo_anterior(circle, repos, tmp_path):
    _, vivo, dev = repos
    antes = git(vivo, "rev-parse", "HEAD")
    evoluir(dev)
    c = Corpo(circle.ctx, vivo, tmp_path, validacao=OK)
    c.run()
    c.reiniciar = None
    for _ in range(MAX_ERROS_NA_VALIDACAO):
        out = c.validar(["idle: RuntimeError('x')"])
    assert out == "revertido" and git(vivo, "rev-parse", "HEAD") == antes and c.reiniciar == "rollback do código"
    assert circle.store.one("SELECT 1 FROM licoes WHERE assinatura='corpo:regressao_pos_atualizacao'")


def test_em_testes_nunca_ha_corpo_de_verdade(circle):
    from circulo.corpo import build_corpo
    assert build_corpo(circle.ctx, circle.data_dir) is None and circle.corpo is None

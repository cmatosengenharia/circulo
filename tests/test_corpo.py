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


def test_licao_1_arquivo_nao_rastreado_que_a_main_traz_nao_trava_a_troca(circle, repos, tmp_path):
    """Lição #1: `git checkout -B main <alvo>` abortava com "untracked working tree files would be overwritten
    by checkout" quando o arquivo copiado à mão para o corpo vivo chegava à main por merge."""
    from circulo.corpo_caminho import atualizar_corpo
    _, vivo, dev = repos
    (dev / "igual.py").write_text("X = 1\n")
    (dev / "diferente.py").write_text("Y = 2\n")
    git(dev, "add", "-A")
    novo = evoluir(dev)
    (vivo / "igual.py").write_text("X = 1\n")                         # cópia manual, idêntica à main
    (vivo / "diferente.py").write_text("Y = 'local'\n")               # cópia manual que divergiu
    # duas correções da mesma lição convivem: o corpo troca direto (checkout -f depois de guardar o patch, 1.9.1)
    # e, se a troca ainda esbarrar, o caminho livre do Developer (PR #4) libera e tenta de novo
    r = atualizar_corpo(Corpo(circle.ctx, vivo, tmp_path, validacao=OK))
    assert r["status"] == "atualizado" and git(vivo, "rev-parse", "HEAD") == novo
    assert (vivo / "diferente.py").read_text() == "Y = 2\n" and (vivo / "igual.py").read_text() == "X = 1\n"
    assert "Y = 'local'" in open(r["patch"]).read()                    # nada diferente se perde


def test_licao_1_sem_colisao_o_erro_continua_visivel(circle, repos, tmp_path, monkeypatch):
    """Lição #1: só a colisão com não rastreados é tratada; outra falha do git não é engolida."""
    from circulo.corpo_caminho import atualizar_corpo
    _, vivo, dev = repos
    evoluir(dev)
    c = Corpo(circle.ctx, vivo, tmp_path, validacao=OK)

    def falha():
        raise RuntimeError("git fetch: rede fora")
    monkeypatch.setattr(c, "run", falha)
    with pytest.raises(RuntimeError, match="rede fora"):
        atualizar_corpo(c)


def test_licao_2_troca_direta_nao_esbarra_e_main_consertada_vira_corpo(circle, repos, tmp_path):
    """Lição #2 (corpo:validacao_falhou): o teste do PR #4 exigia que `Corpo.run()` abortasse na colisão com não
    rastreados, mas a 1.9.1 já trocava direto (-f); a main ficou vermelha e o corpo reprovou o código novo.
    O contrato: a troca direta não esbarra, e a main reprovada não trava o corpo quando o conserto chega."""
    from circulo.corpo_caminho import atualizar_corpo
    _, vivo, dev = repos
    (dev / "novo.py").write_text("X = 1\n")
    git(dev, "add", "novo.py")
    vermelha = evoluir(dev, "V = (\n")                                 # main vermelha: não passa na validação
    (vivo / "novo.py").write_text("X = 0  # cópia manual\n")
    c = Corpo(circle.ctx, vivo, tmp_path, validacao=OK)
    assert c.run()["status"] == "reprovado" and vermelha in circle.store.get("corpo")["reprovados"]
    consertada = evoluir(dev)                                          # o conserto chega à main
    circle.store.set("corpo", {**circle.store.get("corpo"), "checado_tick": -10**6})
    assert c.precisa()                                                 # o sha reprovado não bloqueia o novo
    r = atualizar_corpo(c)
    assert r["status"] == "atualizado" and "liberado" not in r         # trocou direto, sem o caminho livre
    assert git(vivo, "rev-parse", "HEAD") == consertada and (vivo / "novo.py").read_text() == "X = 1\n"
    assert "cópia manual" in open(r["patch"]).read()


def test_em_testes_nunca_ha_corpo_de_verdade(circle):
    from circulo.corpo import build_corpo
    assert build_corpo(circle.ctx, circle.data_dir) is None and circle.corpo is None


def test_arquivo_nao_rastreado_no_caminho_nao_trava_a_troca(circle, repos, tmp_path):
    """lição #1 (máquina do loop): o código novo trazia um arquivo que já existia lá sem rastreio (cópia manual)
    e o checkout recusava; a troca de corpo nunca acontecia."""
    _, vivo, dev = repos
    (dev / "novo.py").write_text("X = 1\n")
    git(dev, "add", "novo.py")
    novo = evoluir(dev)
    (vivo / "novo.py").write_text("X = 0  # cópia manual\n")
    r = Corpo(circle.ctx, vivo, tmp_path, validacao=OK).run()
    assert r["status"] == "atualizado" and git(vivo, "rev-parse", "HEAD") == novo
    assert (vivo / "novo.py").read_text() == "X = 1\n" and "cópia manual" in open(r["patch"]).read()

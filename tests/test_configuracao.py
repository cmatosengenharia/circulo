import os
import platform
import stat

import pytest

from circulo import configuracao as cfg


@pytest.fixture
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cfg.Path, "home", classmethod(lambda c: tmp_path))
    env = tmp_path / ".config" / "circulo" / "env"
    monkeypatch.setattr(cfg, "ENV_FILE", env)
    for k, _ in cfg.CHAVES:
        monkeypatch.delenv(k, raising=False)
    return tmp_path, env


def test_configurar_cria_arquivo_privado_e_preserva_chaves(casa):
    _, env = casa
    cfg.configurar(env)
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    env.write_text(env.read_text().replace("TYPESAFE_API_KEY=", "TYPESAFE_API_KEY=abc123"))
    cfg.configurar(env)                                     # rodar de novo não apaga o que você preencheu
    assert "TYPESAFE_API_KEY=abc123" in env.read_text()


def test_carregar_env_nao_sobrescreve_ambiente(casa, monkeypatch):
    _, env = casa
    env.parent.mkdir(parents=True)
    env.write_text("TYPESAFE_API_KEY=do_arquivo\nANTHROPIC_API_KEY='sk-x'\n# comentario\nCIRCULO_REPO=\n")
    monkeypatch.setenv("TYPESAFE_API_KEY", "do_ambiente")
    lidas = cfg.carregar_env(env)
    assert lidas == ["ANTHROPIC_API_KEY"]                    # devolve nomes, nunca valores
    assert os.environ["TYPESAFE_API_KEY"] == "do_ambiente" and os.environ["ANTHROPIC_API_KEY"] == "sk-x"
    monkeypatch.delenv("ANTHROPIC_API_KEY")


def test_diagnostico_sem_nada_nao_gasta_e_explica(casa):
    pecas = {p.nome: p for p in cfg.diagnostico()}
    assert pecas["Motor das missões (LLM)"].estado == "parado" and "ANTHROPIC_API_KEY" in pecas["Motor das missões (LLM)"].como_ligar
    assert pecas["Jev (decisões)"].estado == "aviso"           # funciona com o decisor local
    assert pecas["Rodando 24/7"].estado == "aviso"


def test_instalar_escreve_servico_com_caminhos_reais(casa):
    home, _ = casa
    dest, feitos = cfg.instalar(home / "dados", 8765, aplicar=False)
    txt = dest.read_text()
    assert feitos == [] and cfg._comando()[0] in txt and str((home / "dados").resolve()) in txt and "--painel" in txt
    if platform.system() == "Darwin":
        assert "<key>KeepAlive</key><true/>" in txt
    else:
        assert "Restart=always" in txt
    assert cfg.servico_instalado()
    guardado = cfg.desinstalar(aplicar=False)
    assert guardado.exists() and not cfg.servico_instalado()  # desligar não apaga


def test_registrar_fecha_itens_de_configuracao_do_roteiro(circle):
    P = cfg.Peca
    pecas = [P("Jev (decisões)", "ligado", ""), P("Motor das missões (LLM)", "ligado", ""), P("Gate de merge", "ligado", ""),
             P("Developer (corrige o próprio código)", "ligado", ""), P("Rodando 24/7", "ligado", "")]
    cfg.registrar(circle.store, pecas)
    st = {r["titulo"]: r["status"] for r in circle.store.q("SELECT titulo, status FROM roadmap")}
    assert st["Ligar as chaves e o Claude Code na máquina do loop"] == "feito" and st["Rodar 24/7"] == "feito"
    assert circle.store.get("configuracao")["pecas"][0]["nome"] == "Jev (decisões)"


def test_loop_reinicia_sozinho_quando_a_configuracao_muda(circle, casa, monkeypatch):
    _, env = casa
    cfg.configurar(env)
    monkeypatch.setattr(cfg, "ENV_FILE", env)
    import time as _t
    passos = []

    def sleep(sec):
        passos.append(sec)
        if len(passos) == 2:
            _t.sleep(0.01)
            env.write_text(env.read_text().replace("TYPESAFE_API_KEY=", "TYPESAFE_API_KEY=nova"))
            os.utime(env, (env.stat().st_atime, env.stat().st_mtime + 5))

    circle.run_forever(max_ticks=50, sleep=sleep)
    assert circle.store.tick < 50 and circle.store.get("ultimo_reinicio")["motivo"] == "configuração alterada"


def test_servico_roda_na_pasta_de_dados_e_nao_e_escondido_pelo_clone(tmp_path):
    """Regressão: com WorkingDirectory=~/Projects e `python -m`, a pasta ~/Projects/circulo (o clone)
    escondia o pacote instalado e o loop caía ao subir."""
    from circulo import configuracao as cfg
    dados = tmp_path / "circulo-dados"
    p = cfg.plist(dados, 8765)
    assert f"<key>WorkingDirectory</key><string>{dados.resolve()}</string>" in p
    u = cfg.unit(dados, 8765)
    assert f"WorkingDirectory={dados.resolve()}" in u
    cmd = cfg._comando()
    assert cmd[0].endswith("circulo") or cmd[1:3] == ["-m", "circulo"]

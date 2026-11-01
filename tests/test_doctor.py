"""`circulo doctor` (item #356): confere Python, git, Claude Code, Jev e GitHub num ambiente SIMULADO (PATH, variáveis
e saída de comando injetadas) e diz exatamente o que falta, com o comando que corrige."""
import tomllib
from pathlib import Path

from circulo import doctor

RAIZ = Path(__file__).resolve().parent.parent


def _amb(env=None, bins=("git", "claude"), versao=(3, 12, 1), saidas=None):
    saidas = {"git": "git version 2.44.0", "claude": "2.1.0 (Claude Code)", **(saidas or {})}
    return doctor.Ambiente(env=dict(env or {}), which=lambda b: f"/usr/bin/{b}" if b in bins else None,
                           rodar=lambda cmd: saidas.get(cmd[0], ""), versao=versao)


COMPLETO = {"TYPESAFE_API_KEY": "ts_x", "GITHUB_TOKEN": "ghp_x", "CIRCULO_REPO": "dono/circulo"}


def test_ambiente_completo_tudo_ok_e_sai_zero():
    vs = doctor.verificar(_amb(COMPLETO))
    assert [v.nome for v in vs] == ["Python", "git", "Claude Code", "Jev", "GitHub"]
    assert all(v.ok for v in vs) and doctor.codigo_saida(vs) == 0
    assert "2.44.0" in vs[1].detalhe and "Claude Code" in vs[2].detalhe
    assert "falta" not in doctor.texto(vs)


def test_ambiente_vazio_diz_exatamente_o_que_falta_e_como_corrigir():
    vs = {v.nome: v for v in doctor.verificar(_amb({}, bins=(), versao=(3, 9, 7)))}
    assert not any(v.ok for v in vs.values())
    assert "3.9.7" in vs["Python"].detalhe and "3.11" in vs["Python"].correcao
    assert "git" in vs["git"].correcao
    assert "npm install -g @anthropic-ai/claude-code" in vs["Claude Code"].correcao
    assert "TYPESAFE_API_KEY" in vs["Jev"].correcao and "circulo configurar" in vs["Jev"].correcao
    assert "GITHUB_TOKEN" in vs["GitHub"].correcao and "CIRCULO_REPO" in vs["GitHub"].correcao
    t = doctor.texto(list(vs.values()))
    assert t.count("→ ") == 5 and "faltam 5" in t
    assert doctor.codigo_saida(list(vs.values())) == 1


def test_github_so_com_metade_cita_so_a_metade_que_falta():
    vs = {v.nome: v for v in doctor.verificar(_amb({"TYPESAFE_API_KEY": "x", "GITHUB_TOKEN": "g"}))}
    assert not vs["GitHub"].ok and "CIRCULO_REPO" in vs["GitHub"].correcao and "GITHUB_TOKEN" not in vs["GitHub"].correcao
    assert vs["Jev"].ok


def test_comando_que_nao_responde_conta_como_quebrado():
    vs = {v.nome: v for v in doctor.verificar(_amb(COMPLETO, saidas={"claude": ""}))}
    assert not vs["Claude Code"].ok and "não respondeu" in vs["Claude Code"].detalhe


def test_agente_de_codigo_configuravel():
    amb = _amb({**COMPLETO, "CIRCULO_CODE_AGENT": "meu-claude"}, bins=("git", "meu-claude"), saidas={"meu-claude": "2.0"})
    assert {v.nome: v for v in doctor.verificar(amb)}["Claude Code"].ok


def test_cli_doctor_imprime_e_sai_com_o_codigo(capsys, monkeypatch):
    from circulo import cli
    vazio = _amb({}, bins=())
    monkeypatch.setattr(doctor, "Ambiente", lambda **_: vazio)
    try:
        cli.main(["doctor"])
        code = 0
    except SystemExit as exc:
        code = exc.code
    assert code == 1 and "→ " in capsys.readouterr().out


def test_pyproject_instala_o_comando_com_versao():
    p = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    assert p["project"]["scripts"]["circulo"] == "circulo.cli:main" and p["project"]["version"]
    assert p["build-system"]["build-backend"]


def test_redator_gera_o_guia_de_instalacao_em_5_minutos():
    from circulo import documentador
    guia = documentador._doc_instalacao("9.9.9")
    for passo in ("pip install", "circulo doctor", "circulo init", "circulo configurar", "circulo painel", "circulo pedir"):
        assert passo in guia, passo
    for v in doctor.verificar(_amb({}, bins=(), versao=(3, 9, 0))):
        assert v.correcao in guia                 # o guia é gerado das mesmas correções que o doctor sugere
    assert "9.9.9" in guia

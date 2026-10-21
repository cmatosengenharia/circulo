"""Assinatura (CIRCULO_CONTA=max): LLM e Developer pelo `claude` com o login da conta, sem a chave da API,
e o guardião da sessão que percebe a queda, abre o login e libera tudo quando volta."""
import json
import os
import stat
import time

import pytest

from circulo import conta, llm, self_dev


@pytest.fixture
def max_ligado(monkeypatch):
    monkeypatch.setenv("CIRCULO_CONTA", "max")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-teste-nao-pode-chegar-no-claude")


def falso_claude(tmp_path, monkeypatch, saida: dict, codigo: int = 0):
    """Um `claude` de mentira no PATH que grava argumentos, stdin e ambiente e responde `saida`."""
    pasta = tmp_path / "bin"
    pasta.mkdir()
    log = tmp_path / "chamada.json"
    roteiro = pasta / "claude"
    roteiro.write_text(f"""#!/usr/bin/env python3
import json, os, sys
json.dump({{"args": sys.argv[1:], "stdin": sys.stdin.read(), "tem_chave": "ANTHROPIC_API_KEY" in os.environ,
           "max_tokens": os.environ.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS")}}, open({str(log)!r}, "w"))
print({json.dumps(json.dumps(saida))})
sys.exit({codigo})
""")
    roteiro.chmod(roteiro.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{pasta}{os.pathsep}{os.environ['PATH']}")
    return log


def test_conta_max_troca_o_provedor_e_tira_a_chave_do_ambiente(max_ligado, monkeypatch):
    monkeypatch.setenv("CIRCULO_LLM_PROVEDOR", "anthropic")
    assert conta.assinatura() and llm.provedor() == "assinatura"
    assert "ANTHROPIC_API_KEY" not in conta.ambiente()
    monkeypatch.delenv("CIRCULO_CONTA")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")         # o token de 1 ano sozinho já liga a assinatura
    assert conta.assinatura()


def test_llm_pela_assinatura_usa_o_claude_sem_a_chave(max_ligado, tmp_path, monkeypatch):
    log = falso_claude(tmp_path, monkeypatch, {"type": "result", "result": "ok, veja https://exemplo.org/a.", "is_error": False,
                                               "usage": {"input_tokens": 10, "output_tokens": 3, "cache_read_input_tokens": 20}})
    g = llm.build_llm()
    assert isinstance(g, llm.AssinaturaLLM)
    r = g.generate(system="papel", prompt="pergunta longa " * 50, model="claude-haiku-5-5", max_tokens=99, web_search=2)
    chamada = json.load(open(log))
    assert r.text.startswith("ok") and r.tokens == 10 + 3 + 2 and r.citations[0]["url"] == "https://exemplo.org/a."[:-1]
    assert not chamada["tem_chave"] and chamada["stdin"].startswith("pergunta longa")      # prompt pelo stdin
    assert "--system-prompt" in chamada["args"] and "WebSearch,WebFetch" in chamada["args"] and chamada["max_tokens"] == "99"
    g.generate(system="s", prompt="p", model="claude-haiku-5-5", max_tokens=5)
    assert "--max-turns" in (a := json.load(open(log))["args"]) and a[a.index("--max-turns") + 1] == "1"


def test_llm_pela_assinatura_acusa_sessao_caida(max_ligado, tmp_path, monkeypatch):
    falso_claude(tmp_path, monkeypatch, {"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}, codigo=1)
    with pytest.raises(llm.ContaDeslogada):
        llm.build_llm().generate(system="s", prompt="p", model="claude-haiku-5-5", max_tokens=5)


def test_developer_na_assinatura_nao_recebe_a_chave(max_ligado, tmp_path, monkeypatch):
    log = falso_claude(tmp_path, monkeypatch, {"type": "result", "result": "feito", "is_error": False, "usage": {}})
    ag = self_dev.ClaudeCodeAgent() if hasattr(self_dev, "ClaudeCodeAgent") else None
    if ag is None:
        pytest.skip("agente do Claude Code com outro nome")
    ag.run("tarefa", tmp_path)
    assert not json.load(open(log))["tem_chave"]


class Respostas:
    def __init__(self, *estados):
        self.estados, self.n = list(estados), 0

    def __call__(self):
        self.n += 1
        return self.estados.pop(0) if len(self.estados) > 1 else self.estados[0]


def test_guardiao_reabre_o_login_e_libera_quando_volta(circle, max_ligado):
    s, avisos, abertos = circle.store, [], []
    caiu = {"logado": False, "metodo": "none", "erro": "Not logged in"}
    ok = {"logado": True, "metodo": "claude.ai"}
    consultar = Respostas(ok, caiu, caiu, caiu, ok)

    def abrir(token_venceu):
        abertos.append(token_venceu)
        return "claude auth login"

    def passo(t):
        return conta.vigiar(s, lambda m, k: avisos.append(m), t, consultar=consultar, abrir=abrir)

    t0 = 1_000_000.0
    assert passo(t0)["logado"]
    assert passo(t0 + 10)["checado_em"] == t0                     # dentro do intervalo: não consulta de novo
    st = passo(t0 + conta.CHECAR)                                   # 1ª queda: pode ser a renovação em curso
    assert st["caiu_em"] and not abertos and not s.get("self_dev_espera")
    passo(t0 + conta.CHECAR + conta.RECHECAR)                       # continua caído: abre o login e pede você
    assert abertos == [False] and s.get("self_dev_espera")["precisa_de_voce"]
    assert s.get("self_dev_espera")["motivo"].startswith(conta.DESLOGADO)
    passo(t0 + conta.CHECAR + 2 * conta.RECHECAR)                   # não reabre o Terminal a cada minuto
    assert abertos == [False]
    st = passo(t0 + conta.CHECAR + 3 * conta.RECHECAR)              # você autorizou: volta sozinho
    assert st["logado"] and not st["caiu_em"] and s.get("self_dev_espera") is None
    assert any("de volta" in a for a in avisos)


def test_guardiao_confere_na_hora_quando_o_developer_acusa(circle, max_ligado):
    s = circle.store
    s.set(conta.CHAVE, {"checado_em": time.time()})
    s.set("self_dev_espera", {"ate": time.time() + 1800, "motivo": conta.DESLOGADO + " no Mac: abra o Terminal"})
    consultar = Respostas({"logado": True, "metodo": "claude.ai"})
    conta.vigiar(s, lambda *a: None, consultar=consultar, abrir=lambda v: None)
    assert consultar.n == 1 and s.get("self_dev_espera") is None    # falso alarme: o Developer segue


def test_token_de_um_ano_avisa_antes_de_vencer_sem_guardar_o_valor(circle, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-segredo-1234")
    s, avisos = circle.store, []
    t0 = 2_000_000.0
    conta.vigiar(s, lambda m, k: avisos.append(m), t0, consultar=lambda: {"logado": True, "metodo": "oauth_token"})
    st = s.get(conta.CHAVE)
    assert "segredo" not in json.dumps(st) and st["token"]["impressao"] == conta.impressao("sk-ant-oat-segredo-1234")
    conta.vigiar(s, lambda m, k: avisos.append(m), t0 + conta.VALIDADE_TOKEN - 10 * 86400,
                 consultar=lambda: {"logado": True, "metodo": "oauth_token"})
    assert any("vence em 10 dia" in a for a in avisos)


def test_sem_assinatura_o_guardiao_nao_faz_nada(circle):
    assert conta.vigiar(circle.store, lambda *a: None, consultar=lambda: 1 / 0) is None

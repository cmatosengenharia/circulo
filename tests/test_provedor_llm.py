"""Qualquer API de IA (circulo/llm.py): o provedor vem do ambiente, o contrato OpenAI vale para todos os outros, o porte
pedido pelo harness vira o modelo do provedor — e o Desenvolvedor passa a gastar pela API, não pelo login."""
import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from circulo import llm as mod


@pytest.fixture
def servidor_compat():
    """Um provedor falso no contrato OpenAI: devolve o modelo e o system que recebeu, com uso detalhado."""
    visto = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            visto.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
            if body["model"] == "quebrado":
                self.send_response(503)
                self.end_headers()
                return
            resp = {"model": body["model"], "choices": [{"message": {"role": "assistant", "content": f"ok:{body['model']}:{body['messages'][0]['content'][:6]}"}}],
                    "usage": {"prompt_tokens": 120, "completion_tokens": 7, "prompt_tokens_details": {"cached_tokens": 100}}}
            out = json.dumps(resp).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1", visto
    srv.shutdown()


def test_provedor_compativel_traduz_o_porte_e_mede_o_uso(servidor_compat, monkeypatch):
    base, visto = servidor_compat
    monkeypatch.setenv("CIRCULO_LLM_PROVEDOR", "compat")
    monkeypatch.setenv("CIRCULO_LLM_BASE_URL", base)
    monkeypatch.setenv("CIRCULO_LLM_API_KEY", "segredo-de-teste")
    monkeypatch.setenv("CIRCULO_LLM_MODELO_PEQUENA", "mini-x")
    monkeypatch.setenv("CIRCULO_LLM_MODELO_GRANDE", "max-x")
    llm = mod.build_llm()
    assert isinstance(llm, mod.CompatLLM) and llm.nome == "compat"
    r = llm.generate(system="Sistema", prompt="oi", model="claude-sonnet-5-5", max_tokens=50, web_search=3)   # o harness pede no nome da Anthropic
    assert r.text == "ok:max-x:Sistem" and r.model == "max-x" and r.citations == []
    assert r.entrada == 20 and r.cache_lido == 100 and r.saida == 7 and r.tokens == 20 + 7 + 10
    assert visto[-1]["path"] == "/v1/chat/completions" and visto[-1]["auth"] == "Bearer segredo-de-teste" and "tools" not in visto[-1]["body"]
    texto, tokens = llm.complete("s", "p", 10)
    assert texto.startswith("ok:mini-x") and tokens == 37                       # complete usa o porte pequeno
    assert "segredo" not in mod.descricao() and "compat" in mod.descricao() and "sem busca na web" in mod.descricao()


def test_provedores_conhecidos_tem_endereco_e_chave_proprios(monkeypatch):
    for nome, (base, var, peq, gra) in mod.PROVEDORES.items():
        if nome in ("anthropic", "compat"):
            continue
        monkeypatch.setenv("CIRCULO_LLM_PROVEDOR", nome)
        monkeypatch.delenv("CIRCULO_LLM_BASE_URL", raising=False)
        c = mod.CompatLLM()
        assert c.base_url == base.rstrip("/") and c.modelos == {"pequena": peq, "grande": gra} and c.traduzir("claude-haiku-5-5") == peq
        assert mod.chave_do_provedor(nome) == (var or None)
    monkeypatch.setenv("CIRCULO_LLM_PROVEDOR", "compat")
    monkeypatch.delenv("CIRCULO_LLM_BASE_URL", raising=False)
    assert mod.build_llm() is None                                               # compat sem endereço: sem LLM, sem quebrar
    monkeypatch.setenv("CIRCULO_LLM_PROVEDOR", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert mod.build_llm() is None and mod.provedor() == "anthropic"


def test_erro_do_provedor_repete_e_depois_sobe(servidor_compat, monkeypatch):
    base, visto = servidor_compat
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    llm = mod.CompatLLM("compat", base_url=base, api_key="k")
    with pytest.raises(urllib.error.HTTPError):
        llm.generate(system="s", prompt="p", model="quebrado", max_tokens=5)
    assert sum(1 for v in visto if v["body"]["model"] == "quebrado") == 3


def test_desenvolvedor_gasta_pela_api_por_padrao(monkeypatch, tmp_path):
    from circulo.self_dev import ClaudeCodeAgent
    ambientes = []

    def falso_run(cmd, **kw):
        ambientes.append(kw["env"])

        class P:
            returncode, stdout, stderr = 0, '{"usage":{"input_tokens":1,"output_tokens":1}}', ""
        return P()
    monkeypatch.setattr("subprocess.run", falso_run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k-de-teste")
    monkeypatch.delenv("CIRCULO_CODE_AGENT_USA_API", raising=False)
    ClaudeCodeAgent().run("tarefa", tmp_path)
    assert ambientes[-1].get("ANTHROPIC_API_KEY") == "k-de-teste"              # padrão novo: API
    monkeypatch.setenv("CIRCULO_CODE_AGENT_USA_API", "0")
    ClaudeCodeAgent().run("tarefa", tmp_path)
    assert "ANTHROPIC_API_KEY" not in ambientes[-1]                              # =0 volta ao login da assinatura


def test_diagnostico_e_faixa_de_conexoes_mostram_o_provedor(monkeypatch, circle):
    from circulo import conexoes, configuracao
    monkeypatch.setenv("CIRCULO_LLM_PROVEDOR", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("CIRCULO_LLM_API_KEY", raising=False)
    peca = next(p for p in configuracao.diagnostico() if p.nome.startswith("Motor"))
    assert peca.estado == "parado" and "GROQ_API_KEY" in peca.como_ligar and "groq" in peca.detalhe
    monkeypatch.setenv("GROQ_API_KEY", "g")
    assert next(p for p in configuracao.diagnostico() if p.nome.startswith("Motor")).estado == "ligado"
    sv = next(x for x in conexoes.estado(circle.store)["servicos"] if x["servico"] == "llm")
    assert sv["papel"] == "groq"

"""Lição #56: o Claude Code ERRA ("exceeded the N output token maximum") em vez de cortar a resposta no teto;
idle:propor_feature caía com max_tokens=200. A resposta tem de sair, cortada aqui, mesmo acima do primeiro teto."""
import json
import os
import stat

import pytest

from circulo import llm

PRECISA = 20_000                 # tokens que a resposta de mentira gasta: acima do primeiro teto pedido


def claude_que_estoura_o_teto(tmp_path, monkeypatch):
    """Um `claude` de mentira que falha como o Claude Code real quando o teto de saída é menor que a resposta."""
    pasta = tmp_path / "bin"
    pasta.mkdir()
    tetos = tmp_path / "tetos.txt"
    roteiro = pasta / "claude"
    erro = {"type": "result", "is_error": True, "result": "API Error: Claude's response exceeded the {teto} output token maximum. "
            "To configure this behavior, set the CLAUDE_CODE_MAX_OUTPUT_TOKENS environment variable."}
    ok = {"type": "result", "is_error": False, "result": "x" * (4 * PRECISA), "usage": {"output_tokens": PRECISA}}
    roteiro.write_text(f"""#!/usr/bin/env python3
import os, sys
sys.stdin.read()
teto = int(os.environ.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS") or 32000)
open({str(tetos)!r}, "a").write(f"{{teto}}\\n")
if teto < {PRECISA}:
    print({json.dumps(json.dumps(erro))}.replace("{{teto}}", str(teto)))
    sys.exit(1)
print({json.dumps(json.dumps(ok))})
""")
    roteiro.chmod(roteiro.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{pasta}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CIRCULO_CONTA", "max")
    return tetos


@pytest.mark.parametrize("max_tokens", [5, 200, 6000])
def test_licao_56_resposta_acima_do_teto_sobe_o_teto_e_corta_aqui(tmp_path, monkeypatch, max_tokens):
    tetos = claude_que_estoura_o_teto(tmp_path, monkeypatch)
    r = llm.build_llm().generate(system="s", prompt="p", model="claude-haiku-5-5", max_tokens=max_tokens)
    assert r.text == "x" * (6 * max_tokens)
    pedidos = [int(t) for t in tetos.read_text().split()]
    assert pedidos == sorted(pedidos) and pedidos[-1] <= llm.TETO_SAIDA


def test_licao_56_no_teto_maximo_o_erro_sobe_sem_repetir_a_chamada(tmp_path, monkeypatch):
    tetos = claude_que_estoura_o_teto(tmp_path, monkeypatch)
    monkeypatch.setattr(llm, "TETO_SAIDA", llm.PISO_SAIDA)       # sem folga para subir: o erro do incidente aparece
    with pytest.raises(RuntimeError, match="output token maximum"):
        llm.build_llm().generate(system="s", prompt="p", model="claude-haiku-5-5", max_tokens=200)
    assert len(tetos.read_text().split()) == 1

"""Corpo do PR do Developer: template fixo de impacto e risco. Módulos e testes vêm do diff e do gate (determinísticos);
só impacto e risco vêm da LLM, em JSON curto, com "não informado" quando a saída é inválida."""
from circulo.corpo_pr import NAO_INFORMADO, SECOES, impacto_risco, modulos, montar, pedir_impacto_risco

ARQUIVOS = ["circulo/loop.py", "tests/test_loop.py", "circulo/painel.html", "circulo/loop.py", "README.md"]
COMANDOS = ["python -m ruff check circulo tests --select E,F,W,B --ignore E501", "python -m pytest -q"]


def test_modulos_agrupam_os_arquivos_do_diff_por_pasta():
    assert modulos(ARQUIVOS) == {"(raiz)": ["README.md"], "circulo": ["loop.py", "painel.html"], "tests": ["test_loop.py"]}


def test_corpo_tem_as_4_secoes_preenchidas_e_a_lista_de_arquivos_recolhida_no_fim():
    corpo = montar(ARQUIVOS, COMANDOS, True, {"impacto": "O giro fica mais rápido.", "risco": "Fila pode travar."},
                   evidencia="test_x falha no código antigo")
    posicoes = [corpo.index(f"## {s}") for s in SECOES]
    assert posicoes == sorted(posicoes) and len(SECOES) == 4
    assert "O giro fica mais rápido." in corpo and "Fila pode travar." in corpo
    assert "- `circulo`: loop.py, painel.html" in corpo and "- `tests`: test_loop.py" in corpo
    for c in COMANDOS:
        assert f"`{c}`" in corpo
    assert "todos ok" in corpo and "test_x falha no código antigo" in corpo
    detalhes = corpo.index("<details>")
    assert detalhes > posicoes[-1] and corpo.rstrip().endswith("</details>")
    assert corpo.count("circulo/loop.py") == 1          # arquivo repetido no diff aparece uma vez


def test_gate_reprovado_aparece_como_reprovado():
    corpo = montar(["a.py"], COMANDOS, False, {})
    assert "reprovado" in corpo and "todos ok" not in corpo


def test_saida_invalida_da_llm_vira_nao_informado():
    assert impacto_risco("nada de json aqui") == {"impacto": NAO_INFORMADO, "risco": NAO_INFORMADO}
    assert impacto_risco('{"impacto": "", "risco": "quebra o painel"}') == {"impacto": NAO_INFORMADO, "risco": NAO_INFORMADO}
    assert impacto_risco('{"impacto": 3, "risco": "x"}') == {"impacto": NAO_INFORMADO, "risco": NAO_INFORMADO}
    assert impacto_risco('ok: {"impacto": "Painel novo.", "risco": "Nenhum.", "extra": 1}') == \
        {"impacto": "Painel novo.", "risco": "Nenhum."}
    assert len(impacto_risco('{"impacto": "%s", "risco": "r"}' % ("a" * 2000))["impacto"]) <= 400


def test_llm_que_falha_nao_impede_o_corpo():
    def explode(prompt: str) -> str:
        raise TimeoutError("sem rede")
    ir = pedir_impacto_risco(explode, "Título", ARQUIVOS)
    assert ir == {"impacto": NAO_INFORMADO, "risco": NAO_INFORMADO}
    vistos = []
    ir = pedir_impacto_risco(lambda p: vistos.append(p) or '{"impacto": "i", "risco": "r"}', "Título", ARQUIVOS)
    assert ir == {"impacto": "i", "risco": "r"} and "circulo/loop.py" in vistos[0] and "Título" in vistos[0]
    corpo = montar(ARQUIVOS, COMANDOS, True, {"impacto": NAO_INFORMADO, "risco": NAO_INFORMADO})
    assert corpo.count(NAO_INFORMADO) == 2

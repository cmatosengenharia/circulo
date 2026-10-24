"""lição #19 (developer:testes:timeout): o pytest imprime o código do teste que falhou, e um `timeout=10` nesse código
virava a assinatura `:timeout` e a classe "ambiente". Testes diferentes caíam numa lição só, sem o nome do teste,
e o erro de código passava por rede lenta. O teste que falhou é a causa, não uma palavra do código dele."""
from circulo.licoes import assinatura_de, classificar

# a saída real da lição #19, cortada antes do resumo `FAILED …` (sobrou só o cabeçalho do teste)
CORTADA = """\
........................................................................ [  8%]
.......................................F
=================================== FAILURES ===================================
_________ test_sse_reempurra_confianca_parada_dentro_do_slo_de_frescor _________

circle = <circulo.loop.Circle object at 0x10bf3db80>
painel = 'http://127.0.0.1:61906'

    def test_sse_reempurra_confianca_parada_dentro_do_slo_de_frescor(circle, painel):  # noqa: F811
        with urllib.request.urlopen(painel + "/api/eventos?desde=0", timeout=10) as r:
>       assert len(chegadas) >= 3
E       assert 2 >= 3
"""


def test_licao_19_timeout_no_codigo_do_teste_nao_e_timeout():
    sig = assinatura_de("developer:testes", CORTADA)
    assert sig == "developer:testes:teste:test_sse_reempurra_confianca_parada_dentro_do_slo_de_frescor"
    assert classificar("developer:testes", CORTADA) == "trabalho"


def test_licao_19_resumo_do_pytest_vence_o_timeout_do_codigo():
    saida = CORTADA + "FAILED tests/test_confianca.py::test_sse_reempurra_confianca_parada_dentro_do_slo_de_frescor - assert 2 >= 3\n"
    assert assinatura_de("developer:testes", saida) == \
        "developer:testes:teste:tests/test_confianca.py::test_sse_reempurra_confianca_parada_dentro_do_slo_de_frescor"


def test_licao_19_timeout_de_verdade_continua_ambiente():
    motivo = "urllib.error.URLError: <urlopen error timed out>"
    assert assinatura_de("developer:testes", motivo) == "developer:testes:timeout"
    assert classificar("developer:testes", motivo) == "ambiente"

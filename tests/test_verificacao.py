"""Verificação de ponta a ponta do painel pelo mapa de funcionalidades: roda no CI e na validação do corpo."""
from circulo.verificacao import ids_quebrados, verificar, verificar_html


def test_mapa_de_funcionalidades_do_painel_inteiro():
    r = verificar()
    assert r["ok"], "\n".join(r["erros"])
    assert r["conferidos"] >= 12


def test_pega_id_que_o_script_procura_e_nao_existe():
    html = '<div id="a"></div><script>$("#a"); document.getElementById("b"); x.innerHTML = `<i id="c"></i>`; $("#c")</script>'
    assert ids_quebrados(html) == ["b"]


def test_toda_tela_tem_a_regra_unica_do_hidden():
    erros = verificar_html("x.html", "<style>.faixa{display:flex}</style><div class='faixa' hidden></div>")
    assert any("[hidden]" in e for e in erros)

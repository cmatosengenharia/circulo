"""Pergunta #399 (entrevistador_jtbd): pedidos do humano que reformulam um anterior (mesmo alvo, texto parecido, em até
7 dias) mostram que a entrega do original não resolveu; a evidência de pedidos_humano passa a contá-los."""
import time

from circulo import perguntas
from circulo.pedidos_repetidos import pares

DIA = 86400.0


def _p(titulo, dias, modulo=None, detalhe=""):
    return {"titulo": titulo, "detalhe": detalhe, "modulo": modulo, "created_at": 1_000_000.0 + dias * DIA}


def test_reformulacao_do_mesmo_alvo_vira_par_original_repeticao():
    original = _p("Mostrar no painel quantos PRs o developer abriu", 0, "circulo/painel.py")
    repeticao = _p("Mostrar no painel quantos PRs o developer já abriu!", 2, "circulo/painel.py")
    assert pares([repeticao, original]) == [(original, repeticao)]


def test_alvo_tirado_do_texto_quando_nao_ha_modulo():
    a = _p("Corrigir a cor do botão em circulo/painel.html", 0)
    b = _p("Corrigir a cor do botao em circulo/painel.html de novo", 1)
    assert pares([a, b]) == [(a, b)]


def test_pedidos_distintos_nao_sao_repeticao():
    base = _p("Mostrar no painel quantos PRs o developer abriu", 0, "circulo/painel.py")
    outro_alvo = _p("Mostrar no painel quantos PRs o developer abriu", 1, "circulo/loop.py")
    outro_texto = _p("Trocar a cor do cabeçalho do relatório semanal", 1, "circulo/painel.py")
    fora_da_janela = _p("Mostrar no painel quantos PRs o developer abriu", 8, "circulo/painel.py")
    assert pares([base, outro_alvo, outro_texto, fora_da_janela]) == []


def test_cadeia_marca_cada_entrega_que_nao_resolveu():
    a, b, c = (_p("Separar no painel os PRs do developer por dia", d, "circulo/painel.py") for d in (0, 1, 2))
    assert pares([a, b, c]) == [(a, b), (b, c)]


def test_evidencia_de_pedidos_humano_traz_repeticoes_7d(circle):
    s = circle.store
    agora = time.time()
    s.x("DELETE FROM roadmap WHERE origem='pedido_cassio'")
    textos = [("Mostrar no painel quantos PRs o developer abriu", "circulo/painel.py"),
              ("Mostrar no painel quantos PRs o developer abriu hoje", "circulo/painel.py"),
              ("Trocar a cor do cabeçalho", None), ("Responder mais rápido", None), ("Mudar o nome do botão", None),
              ("Corrigir o bug do botão de enviar", None), ("Explicar por que o loop parou", None),
              ("Resumo dos gastos da semana", None), ("Comparar planos de celular", None),
              ("Corrigir o bug do botão de enviar agora", None)]
    for i, (t, mod) in enumerate(textos):
        s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,modulo) "
            "VALUES(?,?,'pedido_cassio','pendente','pedido pelo painel',?,?,?,?)",
            (t, t, i, agora - (len(textos) - i) * 3600, agora, mod))
    ev = perguntas._m_pedidos_humano(s, agora)[1]
    assert ev["pedidos_7d"] == 10
    assert ev["repeticoes_7d"] == 2

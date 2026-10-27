"""Pergunta #363: cada barra em missao:verificacao_saida grava a causa normalizada, e o operador vê a que mais se repete."""
import time

from circulo.perguntas import _operador

from test_engine import motor  # noqa: F401


def _barrar(c, gen, pid, monkeypatch, saida, checks):
    gen.builds = [saida] * 2
    monkeypatch.setattr(c.engine.ctx.dl, "verify_output", lambda content, pedido, fmt: (False, dict(checks)))
    assert c.engine.cycle(pid).aceita is False


def test_tres_barras_distintas_gravam_tres_causas_normalizadas(motor, monkeypatch):  # noqa: F811
    c, gen, pid = motor
    c.engine.cycle(pid)
    ok = {"verify_formato": 1.0, "verify_injecao": 1.0, "verify_dados": 1.0, "verify_pedido": 1.0}
    _barrar(c, gen, pid, monkeypatch, "", ok | {"verify_formato": 0.0, "verify_pedido": 0.0})
    _barrar(c, gen, pid, monkeypatch, "<html><body>{{ PREENCHER", ok | {"verify_formato": 0.1})
    _barrar(c, gen, pid, monkeypatch, "<html><body>Receita de bolo</body></html>", ok | {"verify_pedido": 0.2})
    barras = c.store.q("SELECT causa FROM verificacoes WHERE ponto='missao:verificacao_saida' AND ok=0 ORDER BY id")
    causas = [b["causa"] for b in barras]
    assert list(dict.fromkeys(causas)) == ["saida_vazia", "formato_invalido", "criterio_nao_atendido"]


def test_ponto_com_falha_traz_a_causa_que_mais_se_repete(circle):
    s, agora = circle.store, time.time()
    for causa in ("formato_invalido", "criterio_nao_atendido", "formato_invalido"):
        s.x("INSERT INTO verificacoes(tick,ponto,sujeito,ok,motivo,created_at,causa) "
            "VALUES(1,'missao:verificacao_saida','m',0,'x',?,?)", (agora, causa))
    p = [x for x in _operador(s, agora) if x.id == "operador:neuronio_que_mais_barra"][0]
    ponto = p.evidencia["pontos_com_falha_24h"][0]
    assert ponto == {"ponto": "missao:verificacao_saida", "n": 3, "f": 3, "top_causa": "formato_invalido"}
    assert "formato_invalido" in p.texto

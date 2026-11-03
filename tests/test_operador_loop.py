"""Operador do loop (ECC `loop-operator`, ADR 0001): o mesmo traceback 2x seguidas troca a estratégia em vez de
repetir; na 3ª o item é fatiado pelo fatiador."""
from circulo import fatiador, operador_loop

from test_fatiador import falhar, preparar, subs
from test_self_dev import repo  # noqa: F401 — fixture do repositório

TB = ('Traceback (most recent call last):\n  File "circulo/a.py", line {n}, in soma\n    b.c(0x{h})\n'
      '  File "circulo/b.py", line {m}, in c\n    return d.e()\n  File "circulo/d.py", line 9, in e\n'
      'AssertionError: soma(2, 2) == 0 at 0x{h}')


def tb(n=10, m=20, h="7f3a9c"):
    return TB.format(n=n, m=m, h=h)


def test_impressao_ignora_numeros_e_enderecos_e_olha_as_ultimas_linhas():
    assert operador_loop.impressao(tb()) == operador_loop.impressao(tb(n=11, m=99, h="10ffe2"))
    assert operador_loop.impressao(tb()) != operador_loop.impressao(tb().replace("AssertionError", "KeyError"))
    assert operador_loop.impressao("x\n" + tb()) == operador_loop.impressao(tb())


def test_mesmo_traceback_2x_troca_a_estrategia_e_marca_o_item(circle, repo):  # noqa: F811
    item, dev, agent, _ = preparar(circle, repo)
    falhar(circle, item, motivo=tb())
    assert fatiador.proximo(circle.ctx, dev, circle.planejador) == item
    assert not operador_loop.estrategia_trocada(circle.store, item)          # 1x: tenta de novo igual
    falhar(circle, item, motivo=tb(n=12, h="aa01"))
    assert fatiador.proximo(circle.ctx, dev, circle.planejador) == item      # cita 3 módulos, mas não é pré-dividido
    assert fatiador.proximo(circle.ctx, dev, circle.planejador) == item
    detalhe = circle.store.one("SELECT detalhe FROM roadmap WHERE id=?", (item,))["detalhe"]
    assert detalhe.count(operador_loop.MARCA) == 1 and "AssertionError: soma(2, 2)" in detalhe
    assert operador_loop.estrategia_trocada(circle.store, item)
    circle._run_idle_task("corrigir_codigo")
    assert "mude de abordagem" in agent.tasks[0] and 'File "circulo/b.py"' in agent.tasks[0]


def test_tracebacks_diferentes_nao_trocam_a_estrategia(circle, repo):  # noqa: F811
    item, dev, _, _ = preparar(circle, repo)
    falhar(circle, item, motivo=tb())
    falhar(circle, item, motivo=tb().replace("AssertionError", "KeyError"))
    assert fatiador.proximo(circle.ctx, dev, circle.planejador) == item
    assert not operador_loop.estrategia_trocada(circle.store, item)
    assert operador_loop.MARCA not in circle.store.one("SELECT detalhe FROM roadmap WHERE id=?", (item,))["detalhe"]


def test_mesmo_traceback_3x_fatia_o_item_em_vez_de_tentar_de_novo(circle, repo):  # noqa: F811
    item, dev, _, _ = preparar(circle, repo)
    falhar(circle, item, motivo=tb(), n=2)
    assert fatiador.proximo(circle.ctx, dev, circle.planejador) == item
    falhar(circle, item, motivo=tb(n=77))
    alvo = fatiador.proximo(circle.ctx, dev, circle.planejador)
    a, _ = subs(circle, item)
    assert alvo == a["id"]
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "dividido"

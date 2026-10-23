"""Lição #63: com dois trabalhadores, o Developer pegava duas lições que mexem no mesmo arquivo. A que terminava depois
era recusada pelo Revisor (arquivo compartilhado com o PR da outra, "mais antigo") e o trabalho ia fora; qual das duas
dependia de quem chegava primeiro (test_desenvolvedor_pega_itens_distintos_em_paralelo falhava às vezes no CI).
O item da lição grava o módulo citado, e o `picks` nunca põe dois itens do mesmo módulo em paralelo."""
from circulo.self_dev import SelfDeveloper

from test_self_dev import TEST_CMD, FakeGH, FixAgent, repo  # noqa: F401


def _licao(circle, teste):
    return circle.licoes.verificar("developer:testes", False, motivo=f"FAILED {teste} - AssertionError", classe="estrutural")


def test_licoes_no_mesmo_arquivo_nao_rodam_em_paralelo(circle, repo):  # noqa: F811
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    a = _licao(circle, "tests/test_capacidade.py::test_a")
    b = _licao(circle, "tests/test_capacidade.py::test_b")
    c = _licao(circle, "tests/test_loop.py::test_c")
    modulos = {r["id"]: r["modulo"] for r in s.q("SELECT id, modulo FROM roadmap WHERE origem='erro'")}
    assert modulos[a["item_id"]] == modulos[b["item_id"]] == "tests/test_capacidade.py"
    assert modulos[c["item_id"]] == "tests/test_loop.py"
    dev = SelfDeveloper(circle.ctx, repo, FixAgent(), FakeGH(), test_cmd=TEST_CMD)
    assert [i["id"] for i in dev.picks(3)] == [a["item_id"], c["item_id"]]     # a lição b espera a a, no mesmo arquivo

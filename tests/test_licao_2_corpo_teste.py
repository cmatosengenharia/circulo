"""Lição #2 (corpo:validacao_falhou): a assinatura fixa do corpo juntava toda main reprovada numa lição só, sem node
id. Cada teste diferente que falhava "reincidia" a #2, que nunca fechava pela reexecução no main e travava a evolução.
Quando a saída cita o teste que falhou, a lição é desse teste."""
from circulo.licoes import LICAO_DE_COLETA, alvo_de

SAIDA = "...\nFAILED tests/test_capacidade.py::test_arquiteto_estuda_varios_itens - assert 0.61 < 0.55\n1 failed, 900 passed"
OUTRA = "...\nFAILED tests/test_painel.py::test_frescor - AssertionError\n1 failed, 900 passed"


def reprovar(circle, motivo):
    return circle.licoes.verificar("corpo:atualizar", False, sujeito="abc123", motivo=motivo, classe="estrutural",
                                   assinatura="corpo:validacao_falhou")


def test_licao_2_main_reprovada_por_um_teste_vira_licao_desse_teste(circle):
    lic = reprovar(circle, SAIDA)
    assert lic["node_id"] == "tests/test_capacidade.py::test_arquiteto_estuda_varios_itens"
    assert lic["assinatura"].startswith("corpo:validacao_falhou")
    assert alvo_de(lic) and lic["classe"] == "estrutural"          # fecha pela reexecução no main (regra 7)


def test_licao_2_outro_teste_nao_reincide_a_licao_do_primeiro(circle):
    a = reprovar(circle, SAIDA)
    circle.store.x("UPDATE licoes SET status='obsoleta' WHERE id=?", (a["id"],))
    b = reprovar(circle, OUTRA)
    assert b["id"] != a["id"] and b["reincidencias"] == 0
    assert circle.store.one("SELECT status FROM licoes WHERE id=?", (a["id"],))["status"] == "obsoleta"


def test_licao_2_sem_teste_citado_a_assinatura_do_corpo_fica(circle):
    lic = reprovar(circle, "SyntaxError: '(' was never closed")
    assert lic["assinatura"] == "corpo:validacao_falhou" and not lic["node_id"]
    assert not LICAO_DE_COLETA.search(lic["assinatura"])

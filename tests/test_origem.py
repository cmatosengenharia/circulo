import pytest

from circulo.roadmap import Origem


@pytest.mark.parametrize("invalido", [None, 0, -1, "x", "", "34", True, 3.0])
def test_origem_sem_pergunta_inteira_positiva_e_recusada(invalido):
    with pytest.raises(ValueError):
        Origem(invalido)


def test_origem_com_pergunta_valida_e_aceita_e_imutavel():
    origem = Origem(34)
    assert origem.pergunta_id == 34
    with pytest.raises(AttributeError):
        origem.pergunta_id = 35

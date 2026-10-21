"""Lição #54: "Credit balance is too low" é a conta da API sem saldo, não erro do Developer. Lida como 'trabalho',
repetia 5 vezes, subia para a camada CI e virava item pedindo um teste para um erro que nenhum código previne."""
from circulo.licoes import REPETICOES_PARA_SUBIR, classificar

CREDITO = ('{"is_error": true, "num_turns": 1, "subtype": "success", "api_error_status": 400, '
           '"result": "Credit balance is too low", "type": "result"}')


def test_licao_54_credito_da_api_acabou_e_ambiente_e_nao_sobe_de_camada(circle):
    assert classificar("developer:agente", CREDITO) == "ambiente"
    L = circle.licoes
    for _ in range(REPETICOES_PARA_SUBIR):
        L.verificar("developer:agente", False, sujeito="wt", motivo=CREDITO)
    lic = circle.store.one("SELECT classe, camada FROM licoes")
    assert lic["classe"] == "ambiente" and lic["camada"] != "ci"
    assert not circle.store.one("SELECT 1 FROM roadmap WHERE detalhe LIKE '%Subir de camada%'")


def test_licao_54_aberta_como_trabalho_e_reclassificada(circle):
    L = circle.licoes
    licao = L.verificar("developer:agente", False, motivo=CREDITO, assinatura="developer:agente:credit_balance_is_too_low")
    circle.store.x("UPDATE licoes SET classe='trabalho', descricao=? WHERE id=?",
                   ("developer:agente: credit balance is too low — Credit balance is too low", licao["id"]))
    assert L.reclassificar_ambiente() == [licao["id"]]

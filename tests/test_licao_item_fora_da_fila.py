"""Item #171 (Vigia: 1 lição de estrutura aberta há 79 h bloqueando a evolução).

A lição seguia aberta e o erro continuava a acontecer, mas o item dela tinha saído da fila (descartado pelo fatiador,
bloqueado pelo reparo). Só a reincidência de uma lição já fechada reabria o item, então nada andava: o TTL não expira
(a assinatura volta) e `revisar` não valida (o erro não para). A lição de estrutura que trava a evolução e ainda
acontece precisa ter o item na fila.
"""
from circulo.licoes import Licoes

SIG = "developer:agente:maximo_de_passos"


def _erro(L):
    return L.verificar("developer:agente", False, motivo="maximo de passos", assinatura=SIG, classe="estrutural")


def test_licao_aberta_que_volta_a_acontecer_com_o_item_fora_da_fila_reabre_o_item(circle):
    s, L = circle.store, Licoes(circle.store)
    lic = _erro(L)
    item = s.one("SELECT item_id FROM licoes WHERE id=?", (lic["id"],))["item_id"]
    s.x("UPDATE roadmap SET status='descartado', evidencia='descartado: sub-item falhou; depende de você' WHERE id=?", (item,))

    _erro(L)
    r = s.one("SELECT status, evidencia FROM roadmap WHERE id=?", (item,))
    assert r["status"] == "pendente" and "depende de você" not in r["evidencia"]
    assert s.one("SELECT item_id FROM licoes WHERE id=?", (lic["id"],))["item_id"] == item


def test_item_na_fila_ou_feito_nao_e_mexido(circle):
    s, L = circle.store, Licoes(circle.store)
    lic = _erro(L)
    item = s.one("SELECT item_id FROM licoes WHERE id=?", (lic["id"],))["item_id"]
    s.x("UPDATE roadmap SET status='em_andamento', evidencia='rodando' WHERE id=?", (item,))
    _erro(L)
    assert s.one("SELECT status, evidencia FROM roadmap WHERE id=?", (item,))["evidencia"] == "rodando"

    s.x("UPDATE roadmap SET status='feito', evidencia='PR #1' WHERE id=?", (item,))
    _erro(L)
    assert s.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "feito"

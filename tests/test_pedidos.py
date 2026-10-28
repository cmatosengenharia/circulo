"""Canal de origem de cada pedido (pergunta do conselho #441): gravado na criação e contado em 7 dias na evidência geral."""
import json
import time

import pytest

from circulo import pedidos
from circulo.planejador import Planejador


def _canal(s, eid: int) -> str:
    return json.loads(s.one("SELECT payload FROM events WHERE id=?", (eid,))["payload"])["canal"]


@pytest.mark.parametrize("canal", ["painel", "issue", "comentario_pr", "slack"])
def test_cada_canal_conhecido_fica_gravado_no_pedido(circle, canal):
    eid = circle.store.enqueue("mensagem", {"text": "abre um PR", "at": time.time(), "origem": canal})
    assert _canal(circle.store, eid) == canal


@pytest.mark.parametrize("payload", [{}, {"origem": "caixa"}, {"origem": "telegram"}, {"origem": None}])
def test_pedido_sem_canal_conhecido_fica_desconhecido(circle, payload):
    eid = circle.store.enqueue("novo_projeto", {"pedido": "um projeto", "at": time.time(), **payload})
    assert _canal(circle.store, eid) == "desconhecido"


def test_pedidos_de_todas_as_portas_saem_com_canal(circle):
    ids = [circle.submit("pelo cli"), circle.submit_project("missão pelo cli")]
    assert {_canal(circle.store, e) for e in ids} == {"desconhecido"}


def test_evidencia_geral_conta_os_pedidos_de_7_dias_por_canal(circle):
    s = circle.store
    for origem in ("painel", "painel", "issue", "slack", "caixa", "demo"):
        s.enqueue("mensagem", {"text": "x", "origem": origem})
    velho = s.enqueue("mensagem", {"text": "x", "origem": "comentario_pr"})
    s.x("UPDATE events SET created_at=? WHERE id=?", (time.time() - 8 * 86400, velho))
    esperado = {"painel": 2, "issue": 1, "comentario_pr": 0, "slack": 1, "desconhecido": 1}
    assert pedidos.por_canal_7d(s) == esperado
    assert Planejador(circle.ctx).evidencia()["pedidos_7d_por_canal"] == esperado

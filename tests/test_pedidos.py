"""Canal de origem de cada pedido (pergunta do conselho #441): gravado na criação e contado em 7 dias na evidência geral."""
import json
import time
from datetime import datetime, timedelta

import pytest

from circulo import pedidos
from circulo.budget import TZ
from circulo.planejador import Planejador
from circulo.projects import kit_project_id


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


def _resposta(s) -> str:
    return s.one("SELECT message FROM alerts WHERE kind='resposta' ORDER BY id DESC LIMIT 1")["message"]


def _n(s, tabela: str) -> int:
    return s.one(f"SELECT COUNT(*) n FROM {tabela}")["n"]


@pytest.mark.parametrize("porta", ["missao", "falar_com_o_loop"])
def test_pedido_em_formato_de_lancamento_grava_no_ledger_e_nao_vira_missao(circle, porta):
    """Pergunta do conselho #557: o parser de uma linha (PR #230) só existia na CLI e os lançamentos seguiam em 0."""
    s = circle.store
    if porta == "missao":
        circle.submit_project("gastei 42,90 mercado ontem")
    else:
        s.enqueue("mensagem", {"text": "gastei 42,90 mercado ontem", "origem": "painel", "projeto": kit_project_id(s, "circulo")})
    missoes, itens = _n(s, "projects"), _n(s, "roadmap")
    circle.tick()
    linha = s.one("SELECT amount_cents, description, category, created_at FROM ledger")
    assert (linha["amount_cents"], linha["description"], linha["category"]) == (4290, "mercado", "mercado")
    assert datetime.fromtimestamp(linha["created_at"], TZ).date() == circle.ctx.now().astimezone(TZ).date() - timedelta(days=1)
    assert _resposta(s).startswith("Registrado")
    assert (_n(s, "projects"), _n(s, "roadmap")) == (missoes, itens)


def test_linha_sem_verbo_com_categoria_conhecida_tambem_vira_lancamento(circle):
    s = circle.store
    missoes = _n(s, "projects")
    circle.submit_project("mercado 45,90 ontem")
    circle.tick()
    assert tuple(s.one("SELECT amount_cents, category FROM ledger")) == (4590, "mercado")
    assert _resposta(s) == "Registrado: mercado 45,90 ontem." and _n(s, "projects") == missoes


def test_lancamento_sem_valor_pede_so_o_valor_e_nao_vira_missao(circle):
    s = circle.store
    missoes = _n(s, "projects")
    circle.submit_project("gastei mercado ontem")
    circle.tick()
    assert _n(s, "ledger") == 0 and _n(s, "projects") == missoes
    assert _resposta(s) == "Qual foi o valor de 'mercado'?"


@pytest.mark.parametrize("pedido", ["crie 3 posts para o instagram da padaria",
                                    "monte um plano de viagem até R$ 2.000,00",
                                    "Preciso de 3,5 litros de tinta",         # vírgula decimal não é dinheiro
                                    "Preciso de 3,50 de gasolina"])           # sem verbo de gasto, descrição longa é pedido
def test_pedido_comum_nao_grava_lancamento(circle, pedido):
    s = circle.store
    circle.submit_project(pedido)
    circle.tick()
    assert _n(s, "ledger") == 0
    assert not _resposta(s).startswith("Registrado")


@pytest.mark.parametrize("pedido", ["crie 3 posts para o instagram da padaria",
                                    "monte um plano de viagem até R$ 2.000,00"])
def test_pedido_comum_segue_o_fluxo_de_missao(circle, pedido):
    s = circle.store
    missoes = _n(s, "projects")
    circle.submit_project(pedido)
    circle.tick()
    assert _n(s, "ledger") == 0 and _n(s, "projects") == missoes + 1

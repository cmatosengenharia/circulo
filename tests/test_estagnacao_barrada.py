"""Lição #47 (loop:estagnado, "causa provável: sem recusa registrada"): o loop contava como trabalho pendente uma tarefa
que o idle nunca deixa rodar (pausada pelo Médico, em quarentena, fora do modo seguro, revisor adiado). Ela não roda nem
é recusada, então cada giro "parado" virava estagnação sem causa. Pendente e executável têm de ser a mesma regra."""
import pytest

from circulo.loop import ESTAGNADO


def _pausar(circle, t):
    circle.store.set("medico_pausas", {t: {"ate": 4e9}})


def _isolar(circle, t):
    circle.store.set("quarentena", {f"idle:{t}": {"ate_tick": circle.store.tick + 10**6}})


def _modo_seguro(circle, t):
    circle.set_control(modo_seguro=True)


def _revisor_adiado(circle, t):
    circle.store.set("revisar_prs_adiado", {"tentativas": 1, "causa": "rede", "ate_tick": circle.store.tick + 10**6})


BARREIRAS = [(_pausar, "corrigir_codigo"), (_isolar, "corrigir_codigo"), (_modo_seguro, "corrigir_codigo"),
             (_revisor_adiado, "revisar_prs")]


@pytest.mark.parametrize("barrar,tarefa", BARREIRAS, ids=[b.__name__ for b, _ in BARREIRAS])
def test_licao_47_tarefa_que_o_idle_barra_nao_e_trabalho_pendente(circle, barrar, tarefa):
    circle._tem_trabalho = lambda t: t == tarefa
    assert circle.trabalho_pendente(ignorar_estagnacao=True)
    barrar(circle, tarefa)
    assert not circle.trabalho_pendente(ignorar_estagnacao=True)


def test_licao_47_tarefa_pausada_nao_vira_estagnacao_sem_causa(circle):
    circle._tem_trabalho = lambda t: t == "corrigir_codigo"
    _pausar(circle, "corrigir_codigo")
    for _ in range(ESTAGNADO):
        circle.tick()
    assert not circle.store.one("SELECT 1 FROM licoes WHERE assinatura='loop:estagnado'")

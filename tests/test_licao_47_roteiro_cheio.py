"""Lição #47 (loop:estagnado): "havia trabalho pendente e nada avançou em 10 giros; causa provável: planejar_roteiro
rodou sem avançar 8x, indagar rodou sem avançar 2x". O roteiro cheio (mais de ROTEIRO_CHEIO pendentes de qualquer
origem) só era visto dentro de `_tentar`: `precisa()` contava apenas os pendentes do loop e do Cássio, dizia que havia
trabalho, e cada giro rodava o Planejador só para descartar por regra a pergunta que o Indagador acabara de validar.
Uma só regra (`roteiro_cheio`) decide em `motivo()`: roteiro cheio não é trabalho pendente."""
from circulo.planejador import ROTEIRO_CHEIO, roteiro_cheio

from test_planejador import PlanLLM, preparar
from test_self_dev import repo  # noqa: F401 — fixture do repositório


def _pendentes_de_erro(s, n):
    for i in range(n):
        s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
            "VALUES(?,'d','erro','pendente','x',?,strftime('%s','now'),strftime('%s','now'))", (f"correção {i}", 900 + i))


def test_licao_47_roteiro_cheio_de_outras_origens_nao_e_trabalho_do_planejador(circle, repo):  # noqa: F811
    _, plan = preparar(circle, repo, PlanLLM())
    assert plan.precisa()
    _pendentes_de_erro(circle.store, ROTEIRO_CHEIO + 1)
    assert not plan.precisa()
    assert plan.motivo().startswith("roteiro cheio") and plan.motivo(no_giro=True) == roteiro_cheio(circle.store)
    circle.planejador = plan
    assert not circle._tem_trabalho("planejar_roteiro")

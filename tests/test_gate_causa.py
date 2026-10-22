"""Pergunta do conselho #76: os PRs #48, #49, #50 e #80 a #84 fecharam com os mesmos 7 checks falhando juntos. A falha
uniforme é do CI, não do PR; o baseline (fração de PRs fechados assim e os tokens do developer neles) é o que o portão
pré-PR do item #125 precisa para provar economia."""
import time

from circulo.gate_causa import ESPECIFICA, UNIFORME, baseline, checks_falhando, classificar

TODOS = ("checks falhando: Evidência reforçada, Container, Testes (Python 3.13), Testes (Python 3.11), "
         "Testes (Python 3.12), Reprodução primeiro, Constituição")


def test_os_7_checks_juntos_sao_falha_uniforme_em_qualquer_ordem():
    assert classificar(TODOS) == UNIFORME
    assert classificar("checks falhando: Container, Reprodução primeiro, Constituição, Testes (Python 3.11), "
                       "Testes (Python 3.13), Evidência reforçada, Testes (Python 3.12)\ndetalhe") == UNIFORME


def test_falha_parcial_e_especifica_e_motivo_sem_checks_fica_de_fora():
    assert classificar("checks falhando: Testes (Python 3.12)") == ESPECIFICA
    # 6 dos 7 (sem Container): ainda é o PR, não o CI inteiro
    assert classificar(TODOS.replace("Container, ", "")) == ESPECIFICA
    assert classificar("conflito com a main") is None
    assert checks_falhando("checks em andamento: Testes (Python 3.11)") is None
    assert checks_falhando("checks falhando: Lint, Testes\nsaída") == {"Lint", "Testes"}


def _pr(s, numero, titulo, motivo, tokens, agora):
    s.x("INSERT INTO prs(number,titulo,status,created_at,updated_at) VALUES(?,?,'fechado',?,?)", (numero, titulo, agora, agora))
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,'s',0,?,'{}',?)", (numero, motivo, agora))
    for entrada in (titulo, f"conserto do PR #{numero}: {titulo}"):
        s.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,ok,entrada,created_at) "
            "VALUES(1,'developer','m','fixo',?,1,?,?)", (tokens, entrada, agora))


def test_baseline_da_a_fracao_uniforme_e_os_tokens_do_developer_nesses_prs(circle):
    s, agora = circle.store, time.time()
    _pr(s, 48, "Integrar a pré-checagem", "checks falhando: Testes (Python 3.12)", 50, agora)
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(48,'s',0,?,'{}',?)", (TODOS, agora + 1))
    _pr(s, 80, "Outro item", TODOS, 300, agora)
    _pr(s, 81, "Item específico", "checks falhando: Testes (Python 3.11)", 7000, agora)
    _pr(s, 82, "Fechado por conflito", "conflito com a main", 9000, agora)

    b = baseline(s)
    # o último motivo do gate em cada PR é o que o fechou; o conflito não entra na conta de checks
    assert b["prs"] == 3 and b["uniformes"] == [48, 80]
    assert b["fracao"] == round(2 / 3, 3)
    assert b["tokens_uniformes"] == 2 * 50 + 2 * 300

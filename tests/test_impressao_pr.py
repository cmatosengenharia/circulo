"""Impressão digital de PR (título + checks falhos): a 3ª abertura idêntica é bloqueada (pergunta #265).

Caso real: 'Integrar a pré-checagem em developer:abrir_pr antes do push' foi aberto e fechado em #48, #49 e #50
com os mesmos checks falhando; com 2 fechamentos iguais no histórico, a 3ª abertura não acontece."""
from circulo.impressao_pr import impressao, veredito_abertura

TITULO = "Integrar a pré-checagem em developer:abrir_pr antes do push"
CHECKS = ["test", "lint", "constituicao"]


def _fechado(titulo=TITULO, checks=CHECKS, estado="fechado"):
    return {"titulo": titulo, "checks_falhos": checks, "estado": estado}


def test_terceira_abertura_igual_a_48_e_49_fechados_e_bloqueada():
    historico = [_fechado(), _fechado(checks=["lint", "constituicao", "test"])]  # #48, #49
    assert veredito_abertura(TITULO, CHECKS, historico) == "bloquear"  # seria o #50


def test_titulo_normalizado_e_checks_sem_ordem_dao_a_mesma_impressao():
    assert impressao("  Integrar a PRÉ-checagem em developer:abrir_pr   antes do push. ", ["lint", "test", "lint"]) \
        == impressao("integrar a pre-checagem em developer:abrir_pr antes do push", ["test", "lint"])


def test_uma_abertura_fechada_ainda_deixa_abrir():
    assert veredito_abertura(TITULO, CHECKS, [_fechado()]) == "abrir"


def test_mudar_os_checks_falhos_ou_o_titulo_libera_a_abertura():
    historico = [_fechado(), _fechado()]
    assert veredito_abertura(TITULO, ["test"], historico) == "abrir"
    assert veredito_abertura("Pré-checagem só do lint em developer:abrir_pr", CHECKS, historico) == "abrir"


def test_so_aberturas_fechadas_contam():
    historico = [_fechado(estado="mergeado"), _fechado(estado="aberto"), _fechado()]
    assert veredito_abertura(TITULO, CHECKS, historico) == "abrir"

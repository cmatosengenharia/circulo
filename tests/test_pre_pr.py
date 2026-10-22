"""Portão pré-PR (pergunta do conselho #74, lição #50 gate:main_vermelha): com a main vermelha ou o CI sem iniciar,
o developer:abrir_pr adia com a causa normalizada em vez de abrir um PR que falharia por motivo externo."""
from test_reparo import ZipAgent, dev_de
from test_self_dev import erro_recorrente, repo  # noqa: F401 — fixture do repositório

from circulo.merge_gate import REQUIRED_CHECKS
from circulo.pre_pr import ABRIR, ADIAR, ADIAR_PONTO, CI_NAO_INICIOU, MAIN_VERMELHA, decidir

COBRANCA = "The job was not started because your spending limit needs to be increased"


def _runs(nao_iniciado: bool):
    return [{"id": i, "name": n, "status": "completed", "conclusion": "failure",
             **({"nao_iniciado": COBRANCA} if nao_iniciado else {})} for i, n in enumerate(REQUIRED_CHECKS)]


def test_main_verde_abre_main_vermelha_e_ci_sem_iniciar_adiam_com_causas_separadas():
    assert decidir("success", True).acao == ABRIR
    assert decidir(None, True).acao == ABRIR                       # sem status da main: não inventa causa
    assert (decidir("failure", True).acao, decidir("failure", True).causa) == (ADIAR, MAIN_VERMELHA)
    assert (decidir("failure", False).acao, decidir("failure", False).causa) == (ADIAR, CI_NAO_INICIOU)


def test_o_item_que_conserta_a_main_vermelha_abre_mas_nao_com_o_ci_sem_iniciar():
    assert decidir("failure", True, conserta_main=True).acao == ABRIR
    assert decidir("failure", False, conserta_main=True).causa == CI_NAO_INICIOU


def _dev_com_main(circle, repo, tmp_path, conclusao, nao_iniciado=False):  # noqa: F811
    dev, gh = dev_de(circle, repo, tmp_path, ZipAgent(conserta_na=1))
    gh.main_ci = lambda: ("abc1234def", conclusao)
    gh.check_runs = lambda sha: _runs(nao_iniciado)
    return dev, gh


def _adiados(circle):
    return [dict(r) for r in circle.store.q("SELECT causa FROM verificacoes WHERE ponto=? ORDER BY id", (ADIAR_PONTO,))]


def test_licao_50_main_vermelha_adia_o_pr_e_registra_a_causa(circle, repo, tmp_path):  # noqa: F811
    """Regressão (lição #50, gate:main_vermelha): PR aberto com a main vermelha falhava nos 7 checks juntos."""
    erro_recorrente(circle)
    dev, gh = _dev_com_main(circle, repo, tmp_path, "failure")
    r = dev.run_once()
    assert r.status == "testes_falharam" and not gh.prs and MAIN_VERMELHA in r.detalhe
    assert _adiados(circle) == [{"causa": MAIN_VERMELHA}]


def test_ci_da_main_sem_iniciar_adia_com_causa_propria(circle, repo, tmp_path):  # noqa: F811
    erro_recorrente(circle)
    dev, gh = _dev_com_main(circle, repo, tmp_path, "failure", nao_iniciado=True)
    assert dev.run_once().status == "testes_falharam" and not gh.prs
    assert _adiados(circle) == [{"causa": CI_NAO_INICIOU}]


def test_main_verde_abre_o_pr(circle, repo, tmp_path):  # noqa: F811
    erro_recorrente(circle)
    dev, gh = _dev_com_main(circle, repo, tmp_path, "success")
    assert dev.run_once().status == "proposto" and gh.prs
    assert _adiados(circle) == []


def test_item_da_licao_main_vermelha_passa_pelo_portao(circle, repo, tmp_path):  # noqa: F811
    item = erro_recorrente(circle)
    circle.store.x("INSERT INTO licoes(assinatura, ponto, classe, descricao, status, ocorrencias, reincidencias, item_id, "
                   "created_at, updated_at) VALUES('gate:main_vermelha','gate:main','estrutural','main vermelha',"
                   "'aberta',1,0,?,0,0)", (item["id"],))
    dev, gh = _dev_com_main(circle, repo, tmp_path, "failure")
    assert dev.run_once().status == "proposto" and gh.prs

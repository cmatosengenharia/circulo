"""Portão pré-PR (pergunta do conselho #74, lição #50 gate:main_vermelha): com a main vermelha ou o CI sem iniciar,
o developer:abrir_pr adia com a causa normalizada em vez de abrir um PR que falharia por motivo externo."""
import time

from test_reparo import ZipAgent, dev_de
from test_self_dev import erro_recorrente, git, repo  # noqa: F401 — fixture do repositório

from circulo.merge_gate import REQUIRED_CHECKS
from circulo.pre_pr import ABRIR, ADIAR, ADIAR_PONTO, CI_NAO_INICIOU, MAIN_VERMELHA, SISTEMICO, checks_dos_prs, decidir
from circulo.reparo import BLOQUEADO, DISJUNTOR, LIMITE_ADIAR, adiado_do_item

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


# pergunta do conselho #75: os mesmos 7 checks falhando juntos em PRs seguidos (49, 80-84) é causa sistêmica
SETE = ["Container", "Constituição", "Reprodução primeiro", "Evidência reforçada",
        "Testes (Python 3.11)", "Testes (Python 3.12)", "Testes (Python 3.13)"]
# a ordem dos nomes muda de PR para PR no motivo do gate; o conjunto é o mesmo
PRS = {49: SETE[::-1], 80: SETE, 81: SETE[2:] + SETE[:2], 82: SETE, 83: SETE[::-1], 84: SETE[3:] + SETE[:3]}


def _gate_ci(circle, pr, checks, quando):
    circle.store.x("INSERT INTO verificacoes(tick,ponto,sujeito,ok,assinatura,motivo,created_at) VALUES(0,'gate:ci',?,0,'x',?,?)",
                   (f"PR #{pr}", f"checks falhando: {', '.join(checks)}\nlog do CI", quando))


def _gate_main(circle, ok, quando):
    circle.store.x("INSERT INTO verificacoes(tick,ponto,sujeito,ok,assinatura,motivo,created_at) VALUES(0,'gate:main','abc',?,NULL,'',?)",
                   (int(ok), quando))


def test_prs_49_e_80_a_84_com_os_mesmos_7_checks_adiam_como_sistemico():
    historico = [set(PRS[n]) for n in (84, 83, 82, 81, 80, 49)]
    d = decidir("success", True, historico=historico)
    assert (d.acao, d.causa) == (ADIAR, SISTEMICO)
    assert decidir(None, True, historico=historico).causa == SISTEMICO
    assert decidir("failure", True, historico=historico).causa == MAIN_VERMELHA    # a main vermelha é a causa mais exata
    assert decidir("success", True, conserta_main=True, historico=historico).acao == ABRIR


def test_falhas_diferentes_ou_poucas_nao_adiam():
    assert decidir("success", True, historico=[set(SETE)] * 2).acao == ABRIR           # 2 PRs ainda não são padrão
    assert decidir("success", True, historico=[set(SETE), {"Container"}, set(SETE)]).acao == ABRIR
    assert decidir("success", True, historico=[{"Testes (Python 3.11)"}] * 3).acao == ABRIR   # falha do item, não de todos


def test_historico_vale_desde_a_ultima_main_verde(circle):
    agora = time.time()
    _gate_main(circle, True, agora - 3600)
    for i, n in enumerate((49, 80, 81, 82, 83, 84)):
        _gate_ci(circle, n, PRS[n], agora - 600 + i)
    historico = checks_dos_prs(circle.store, agora)
    assert historico[0] == set(SETE) and len(historico) == 6
    _gate_main(circle, True, agora - 10)                     # a main ficou verde depois: o padrão antigo não vale mais
    assert checks_dos_prs(circle.store, agora) == []


def test_abrir_pr_adiado_registra_adiado_sistemico_e_nao_gasta_portoes(circle, repo, tmp_path):  # noqa: F811
    agora = time.time()
    for i, n in enumerate((49, 80, 81, 82, 83, 84)):
        _gate_ci(circle, n, PRS[n], agora - 600 + i)
    erro_recorrente(circle)
    dev, gh = _dev_com_main(circle, repo, tmp_path, "success")   # sem o portão sistêmico, este item vira PR
    r = dev.run_once()
    assert r.status == "testes_falharam" and not gh.prs and SISTEMICO in r.detalhe
    assert circle.store.q("SELECT 1 FROM verificacoes WHERE ponto='developer:testes'") == []
    assert _adiados(circle) == [{"causa": SISTEMICO}]


# pergunta do conselho #296: developer:abrir_pr:adiar falhou 13 de 13; a mesma causa 3x seguidas tira o item da fila
def _giro(dev, repo):  # noqa: F811
    for b in git(repo, "branch", "--list", "circulo/*", "--format=%(refname:short)").splitlines():
        git(repo, "branch", "-D", b)        # o nome da branch leva o segundo: dois giros no mesmo segundo colidem
    return dev.run_once()


def test_tres_adiamentos_com_a_mesma_causa_bloqueiam_o_item_para_triagem(circle, repo, tmp_path):  # noqa: F811
    item = erro_recorrente(circle)
    dev, gh = _dev_com_main(circle, repo, tmp_path, "failure")
    assert [_giro(dev, repo).status for _ in range(LIMITE_ADIAR)] == ["testes_falharam"] * LIMITE_ADIAR
    st = circle.store.one("SELECT status, evidencia FROM roadmap WHERE id=?", (item["id"],))
    assert st["status"] == BLOQUEADO and MAIN_VERMELHA in st["evidencia"] and "triagem" in st["evidencia"]
    assert _giro(dev, repo).status == "nada" and not gh.prs                   # bloqueado não adia de novo
    assert _adiados(circle) == [{"causa": MAIN_VERMELHA}] * LIMITE_ADIAR       # toda falha com a causa registrada


def test_item_em_quarentena_por_adiamento_nao_volta_pela_barra_antiga_do_abrir_pr(circle, repo, tmp_path):  # noqa: F811
    """Pergunta do conselho #300: a barra antiga do item no disjuntor do abrir_pr reabria a quarentena do adiar assim que
    a main mudava, e o item adiava de novo pela mesma causa."""
    item = erro_recorrente(circle)
    circle.store.set(DISJUNTOR, {str(item["id"]): {"sig": "x", "n": 1, "chave": "main antiga", "texto": ""}})
    dev, gh = _dev_com_main(circle, repo, tmp_path, "failure")
    for _ in range(LIMITE_ADIAR):
        _giro(dev, repo)
    assert _giro(dev, repo).status == "nada" and not gh.prs
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item["id"],))["status"] == BLOQUEADO
    assert len(_adiados(circle)) == LIMITE_ADIAR


def test_causa_diferente_de_adiamento_zera_a_contagem(circle):
    s = circle.store
    assert [adiado_do_item(s, 7, MAIN_VERMELHA) for _ in range(2)] == [1, 2]
    assert adiado_do_item(s, 7, CI_NAO_INICIOU) == 1                          # outra causa: recomeça
    assert [adiado_do_item(s, 7, CI_NAO_INICIOU) for _ in range(2)] == [2, 3]
    assert adiado_do_item(s, 8, CI_NAO_INICIOU) == 1                          # por item
    adiado_do_item(s, 7, None)                                                # abriu: os adiamentos deixam de ser seguidos
    assert adiado_do_item(s, 7, CI_NAO_INICIOU) == 1

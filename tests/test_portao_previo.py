"""Portão de reincidência (pergunta do conselho #85): os PRs #82, #83 e #84, do mesmo item, fecharam sem merge com os
mesmos 7 checks falhando. Depois de 2 fechamentos seguidos com o mesmo conjunto, o item não vira PR de novo: é vetado
antes do Developer gastar e volta para diagnóstico (circuit breaker por título e conjunto de checks)."""
import time

from test_reparo import ZipAgent, dev_de
from test_self_dev import erro_recorrente, repo  # noqa: F401 — fixture do repositório

from circulo.portao_previo import LIMIAR, REINCIDENCIA, VETAR, VETO_PONTO, decidir, fechados_sem_merge
from circulo.pre_pr import ABRIR

TITULO = "Teste de arquitetura: detectar padrão sdk_opt_in_required em saídas do SDK"
SETE = ["Container", "Constituição", "Reprodução primeiro", "Evidência reforçada",
        "Testes (Python 3.11)", "Testes (Python 3.12)", "Testes (Python 3.13)"]
# a ordem dos nomes muda de PR para PR no motivo do gate; o conjunto é o mesmo
PRS = {82: SETE, 83: SETE[::-1], 84: SETE[3:] + SETE[:3]}


def test_prs_82_e_83_com_os_mesmos_checks_vetam_o_84():
    assert LIMIAR == 2
    assert decidir(TITULO, [(TITULO, PRS[82])]).acao == ABRIR                     # 1 fechamento ainda é sonda
    d = decidir(TITULO, [(TITULO, PRS[83]), (TITULO, PRS[82])])
    assert (d.acao, d.causa) == (VETAR, REINCIDENCIA)
    assert decidir(TITULO, [(TITULO, PRS[n]) for n in (84, 83, 82)]).acao == VETAR


def test_titulo_normalizado_e_outros_itens_nao_contam():
    assert decidir(f"  {TITULO.upper()} ", [(TITULO, PRS[83]), (f"{TITULO}  ", PRS[82])]).acao == VETAR
    assert decidir("Outro item", [(TITULO, PRS[83]), (TITULO, PRS[82])]).acao == ABRIR
    assert decidir(TITULO, [(TITULO, PRS[83]), ("Outro item", PRS[82])]).acao == ABRIR


def test_conjunto_que_mudou_no_ultimo_fechamento_desarma():
    assert decidir(TITULO, [(TITULO, ["Testes (Python 3.11)"]), (TITULO, PRS[83]), (TITULO, PRS[82])]).acao == ABRIR
    assert decidir(TITULO, [(TITULO, PRS[83]), (TITULO, SETE[:3])]).acao == ABRIR


def _pr(s, numero, titulo, motivo, merged=0, quando=0.0):
    s.x("INSERT INTO prs(number,titulo,status,created_at,updated_at) VALUES(?,?,?,?,?)",
        (numero, titulo, "mergeado" if merged else "fechado", quando, quando))
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,'s',?,?,'{}',?)", (numero, merged, motivo, quando))


def _fechados_82_a_85(s, titulo):
    agora = time.time()
    for i, n in enumerate((82, 83, 84)):
        _pr(s, n, titulo, f"checks falhando: {', '.join(PRS[n])}\nlog do CI", quando=agora - 100 + i)
    _pr(s, 85, titulo, "conflito com a main: o Developer precisa trazer a main para a branch", quando=agora - 50)


def test_fechados_sem_merge_le_do_mais_recente_e_ignora_motivo_sem_checks(circle):
    s = circle.store
    _fechados_82_a_85(s, TITULO)
    _pr(s, 90, "Item mergeado", "ok", merged=1)
    fechados = fechados_sem_merge(s)
    assert fechados == [(TITULO, set(PRS[n])) for n in (84, 83, 82)]
    assert decidir(TITULO, fechados).acao == VETAR


def test_item_reincidente_e_vetado_sem_chamar_o_developer_e_volta_para_diagnostico(circle, repo, tmp_path):  # noqa: F811
    item = erro_recorrente(circle)
    _fechados_82_a_85(circle.store, item["titulo"])
    agent = ZipAgent(conserta_na=1)
    dev, gh = dev_de(circle, repo, tmp_path, agent)
    r = dev.run_once()
    assert r.status == VETAR and not gh.prs and agent.tasks == []
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item["id"],))["status"] == "bloqueado"
    assert [x["causa"] for x in circle.store.q("SELECT causa FROM verificacoes WHERE ponto=?", (VETO_PONTO,))] == [REINCIDENCIA]
    dev.run_once()                                                         # o próximo giro não gasta de novo
    assert agent.tasks == [] and not gh.prs


def test_item_sem_reincidencia_abre_o_pr(circle, repo, tmp_path):  # noqa: F811
    item = erro_recorrente(circle)
    _pr(circle.store, 82, item["titulo"], f"checks falhando: {', '.join(SETE)}")
    dev, gh = dev_de(circle, repo, tmp_path, ZipAgent(conserta_na=1))
    assert dev.run_once().status == "proposto" and gh.prs

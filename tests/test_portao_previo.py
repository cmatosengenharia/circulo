"""Portão de reincidência (pergunta do conselho #85, itens #128 e #129 fundidos): os PRs #80 a #84, do mesmo item,
fecharam sem merge com os mesmos 7 checks falhando. Depois de 2 fechamentos seguidos com o mesmo conjunto, o item não
vira PR de novo: vai para 'descartado' com a causa antes do Developer gastar (DLQ por título e conjunto de checks), e só
o redrive manual o reabre."""
import time

from test_reparo import ZipAgent, dev_de
from test_self_dev import erro_recorrente, repo  # noqa: F401 — fixture do repositório

from circulo.portao_previo import (DESCARTADO, LIMIAR, REINCIDENCIA, VETAR, VETO_PONTO, decidir, fechados_sem_merge,
                                   redrive)
from circulo.pre_pr import ABRIR

TITULO = "Teste de arquitetura: detectar padrão sdk_opt_in_required em saídas do SDK"
SETE = ["Container", "Constituição", "Reprodução primeiro", "Evidência reforçada",
        "Testes (Python 3.11)", "Testes (Python 3.12)", "Testes (Python 3.13)"]
# a ordem dos nomes muda de PR para PR no motivo do gate; o conjunto é o mesmo
PRS = {80: SETE[::-1], 81: SETE[2:] + SETE[:2], 82: SETE, 83: SETE[::-1], 84: SETE[3:] + SETE[:3]}


def test_prs_82_e_83_com_os_mesmos_checks_vetam_o_84():
    assert LIMIAR == 2
    assert decidir(TITULO, [(TITULO, PRS[82])]).acao == ABRIR                     # 1 fechamento ainda é sonda
    d = decidir(TITULO, [(TITULO, PRS[83]), (TITULO, PRS[82])])
    assert (d.acao, d.causa) == (VETAR, REINCIDENCIA)
    assert decidir(TITULO, [(TITULO, PRS[n]) for n in (84, 83, 82)]).acao == VETAR


def test_historico_dos_prs_80_a_83_bloqueia_o_84_e_1_fechamento_deixa_passar():
    assert decidir(TITULO, [(TITULO, PRS[n]) for n in (83, 82, 81, 80)]).acao == VETAR
    assert decidir(TITULO, [(TITULO, PRS[80])]).acao == ABRIR


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


def test_item_reincidente_vai_para_descartado_sem_chamar_o_developer(circle, repo, tmp_path):  # noqa: F811
    item = erro_recorrente(circle)
    _fechados_82_a_85(circle.store, item["titulo"])
    agent = ZipAgent(conserta_na=1)
    dev, gh = dev_de(circle, repo, tmp_path, agent)
    r = dev.run_once()
    assert r.status == VETAR and not gh.prs and agent.tasks == []
    linha = circle.store.one("SELECT status, evidencia FROM roadmap WHERE id=?", (item["id"],))
    assert linha["status"] == DESCARTADO and REINCIDENCIA in linha["evidencia"] and "Container" in linha["evidencia"]
    assert [x["causa"] for x in circle.store.q("SELECT causa FROM verificacoes WHERE ponto=?", (VETO_PONTO,))] == [REINCIDENCIA]
    dev.run_once()                                                         # o próximo giro não gasta de novo
    dev._reabrir()                                                         # nem a sonda do disjuntor o devolve à fila
    assert agent.tasks == [] and not gh.prs and dev.pick() is None


def test_redrive_reabre_o_descartado_e_os_fechamentos_antigos_nao_contam(circle, repo, tmp_path):  # noqa: F811
    item = erro_recorrente(circle)
    _fechados_82_a_85(circle.store, item["titulo"])
    dev, gh = dev_de(circle, repo, tmp_path, ZipAgent(conserta_na=1))
    assert dev.run_once().status == VETAR
    assert "não está descartado" in redrive(circle.store, item["id"] + 999)
    assert "#85" in redrive(circle.store, item["id"])
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item["id"],))["status"] == "pendente"
    assert fechados_sem_merge(circle.store) == []
    assert dev.run_once().status == "proposto" and gh.prs


def test_item_sem_reincidencia_abre_o_pr(circle, repo, tmp_path):  # noqa: F811
    item = erro_recorrente(circle)
    _pr(circle.store, 82, item["titulo"], f"checks falhando: {', '.join(SETE)}")
    dev, gh = dev_de(circle, repo, tmp_path, ZipAgent(conserta_na=1))
    assert dev.run_once().status == "proposto" and gh.prs

"""Causa da falha de CI pelos sinais da API de checks (conclusion, status, anotação), não pela contagem de checks.

Os 7 checks caindo juntos não separam infra de código: nos PRs #80 a #84 todos rodaram e deram 'failure' porque a main
estava vermelha (test_auditoria com `from tests.`), código de verdade; no #86 nenhum job iniciou (limite de gasto).
Só startup_failure, job que não iniciou ou anotação de cobrança/runner são infra; a falha total sem esses sinais
dispara o reexecute local (main vs branch). Infra suspeita não gasta conserto do Developer nem reabre o item."""
import json
import time

import pytest

from circulo import revisor
from circulo.ci_causa import (CODIGO, CODIGO_OU_INDETERMINADO, INFRA, PELA_REGRA, apos_reexecucao, classificar, do_run,
                              raiz)
from circulo.merge_gate import Verdict

SETE = ("Container", "Constituição", "Reprodução primeiro", "Evidência reforçada",
        "Testes (Python 3.11)", "Testes (Python 3.12)", "Testes (Python 3.13)")
COBRANCA = ("The job was not started because recent account payments have failed or your spending limit "
            "needs to be increased. Please check the 'Billing & plans' section in your settings")
SAIDA_1 = "Process completed with exit code 1."


def _checks(conclusion="failure", status="completed", anotacao=SAIDA_1, nomes=SETE):
    return [{"name": n, "status": status, "conclusion": conclusion, "anotacao": anotacao} for n in nomes]


# PRs #80 a #84: os 7 rodaram e falharam com exit code 1 (main vermelha: código). #86: nenhum job iniciou (cobrança).
FIXTURES = {80: _checks(), 81: _checks(), 82: _checks(), 83: _checks(), 84: _checks(),
            86: _checks(anotacao=COBRANCA)}


@pytest.mark.parametrize("pr", [80, 81, 82, 83, 84])
def test_falha_total_por_codigo_dos_prs_80_a_84_nao_vira_infra(pr):
    assert classificar(FIXTURES[pr]) == CODIGO_OU_INDETERMINADO
    assert apos_reexecucao(main_ok=False, branch_ok=False) == CODIGO      # o reexecute local reproduz: é código


def test_pr_86_com_anotacao_de_cobranca_e_infra():
    assert classificar(FIXTURES[86]) == INFRA


def test_startup_failure_job_nao_iniciado_e_runner_sao_infra():
    assert classificar(_checks(conclusion="startup_failure", anotacao="")) == INFRA
    assert classificar(_checks(status="queued", anotacao="")) == INFRA
    assert classificar(_checks(anotacao="The runner has received a shutdown signal.")) == INFRA


def test_falha_parcial_e_codigo_e_mistura_com_falha_real_nunca_e_infra():
    assert classificar(_checks(nomes=SETE[4:5]) + [{"name": "Lint", "status": "completed", "conclusion": "success"}]) == CODIGO
    assert classificar(_checks(nomes=SETE[:3], anotacao=COBRANCA) + _checks(nomes=SETE[3:])) == CODIGO_OU_INDETERMINADO
    assert classificar(_checks(conclusion="success", anotacao="")) is None


def test_reexecute_local_main_vs_branch_decide_o_indeterminado():
    assert apos_reexecucao(main_ok=True, branch_ok=False) == CODIGO
    assert apos_reexecucao(main_ok=True, branch_ok=True) == INFRA
    assert apos_reexecucao(main_ok=False, branch_ok=True) == CODIGO_OU_INDETERMINADO


def test_run_do_github_vira_sinal_nao_iniciado_e_sem_passos():
    assert do_run({"conclusion": "failure", "status": "completed", "nao_iniciado": COBRANCA})["anotacao"] == COBRANCA
    assert classificar([do_run({"conclusion": "failure", "status": "completed", "sem_passos": True})]) == INFRA


class GH:
    def __init__(self, runs):
        self.runs, self.lidos = runs, 0

    def check_runs(self, sha):
        self.lidos += 1
        return self.runs


class Gate:
    def __init__(self, runs, pr=86):
        self.gh, self.pr = GH(runs), pr

    def run(self):
        return [Verdict(self.pr, "sha86", False, f"checks falhando: {', '.join(SETE)}", {"conserto": True})]


def _pr_em_conserto(s, pr):
    agora = time.time()
    item = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,created_at,updated_at) "
               "VALUES('item','d','loop','em_andamento','e',1,'ok',?,?)", (agora, agora))
    s.x("INSERT INTO prs(number,item_id,titulo,branch,status,conserto,conserto_sha,created_at,updated_at) "
        "VALUES(?,?,?,?,'aberto',?,'sha86',?,?)", (pr, item, "item", "circulo/fix-1", json.dumps({"sha": "sha86", "motivo": "x"}), agora, agora))
    return item


def test_revisor_nao_gasta_conserto_nem_reabre_item_com_assinatura_de_infra(circle):
    s = circle.store
    item = _pr_em_conserto(s, 86)
    gate = Gate([{"id": i, "name": n, "status": "completed", "conclusion": "failure", "nao_iniciado": COBRANCA}
                 for i, n in enumerate(SETE)])
    revisor.revisar(s, gate)
    pr = s.one("SELECT conserto, conserto_sha, status FROM prs WHERE number=86")
    assert (pr["conserto"], pr["conserto_sha"], pr["status"]) == (None, "sha86", "aberto")
    assert s.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "em_andamento"
    rev = s.one("SELECT momento, veredito FROM revisoes WHERE pr=86 ORDER BY id DESC LIMIT 1")
    assert (rev["momento"], rev["veredito"]) == ("ci_causa", INFRA)
    revisor.revisar(s, gate)
    assert gate.gh.lidos == 1                       # uma classificação por versão do PR


def test_revisor_mantem_o_conserto_e_rotula_a_causa_quando_e_codigo(circle):
    s = circle.store
    _pr_em_conserto(s, 82)
    gate = Gate([{"id": i, "name": n, "status": "completed", "conclusion": "failure"} for i, n in enumerate(SETE)], pr=82)
    revisor.revisar(s, gate)
    assert s.one("SELECT conserto FROM prs WHERE number=82")["conserto"] is not None
    assert s.one("SELECT veredito FROM revisoes WHERE pr=82 AND momento='ci_causa'")["veredito"] == CODIGO_OU_INDETERMINADO


# lição #53: os 7 checks vermelhos juntos têm uma raiz pela ordem fixa; os demais são derivados e não viram ação.
def test_licao_53_sete_checks_vermelhos_viram_uma_acao_sobre_a_constituicao():
    r = raiz(list(SETE))
    assert (r["check"], r["acao"], r["decisao"]) == ("Constituição", "rodar_local", PELA_REGRA)
    assert "circulo/merge_gate.py" in r["comando"]
    assert sorted(r["derivados"]) == sorted(set(SETE) - {"Constituição"})


def test_raiz_segue_a_ordem_fixa_e_so_decide_com_tres_ou_mais_checks_conhecidos():
    assert raiz(list(SETE[2:]))["check"] == "Reprodução primeiro"
    assert raiz(["Container", "Testes (Python 3.13)", "Testes (Python 3.11)"])["check"] == "Testes (Python 3.11)"
    assert raiz(["Container", "Testes (Python 3.13)", "Evidência reforçada"])["check"] == "Testes (Python 3.13)"
    assert raiz(["Container", "Evidência reforçada"]) is None
    assert raiz(["Container", "Evidência reforçada", "Lint externo"]) is None    # check fora da ordem fica para o Jev


def test_licao_53_revisor_grava_uma_decisao_pela_regra_por_versao_do_pr(circle):
    s = circle.store
    _pr_em_conserto(s, 82)
    gate = Gate([{"id": i, "name": n, "status": "completed", "conclusion": "failure"} for i, n in enumerate(SETE)], pr=82)
    revisor.revisar(s, gate)
    revisor.revisar(s, gate)
    # source='local' é o que a métrica regra_decide conta como pela_regra; a trilha leva o rótulo explícito
    ds = s.q("SELECT value, source FROM decisions WHERE question='ci_causa'")
    assert [(d["value"], d["source"]) for d in ds] == [("Constituição", "local")]
    revs = s.q("SELECT veredito, evidencia FROM revisoes WHERE pr=82 AND momento='ci_raiz'")
    assert [r["veredito"] for r in revs] == [PELA_REGRA]
    ev = json.loads(revs[0]["evidencia"])
    assert (ev["check"], ev["acao"]) == ("Constituição", "rodar_local")
    assert len(ev["derivados"]) == 6

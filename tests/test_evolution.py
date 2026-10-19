import pathlib
import subprocess
import sys

import pytest

from circulo.agents import ReviewerCode
from circulo.evolution import CUSTO_CICLO, valor_portfolio
from circulo.policy import DEFAULT_POLICY, PolicyStore, PolicyViolation, guard
from conftest import say


@pytest.mark.parametrize("patch", [
    [{"op": "set", "path": "invariants_enabled", "value": False}],
    [{"op": "set", "path": "rollback.enabled", "value": False}],
    [{"op": "set", "path": "budget.daily_token_limit", "value": 10**12}],
    [{"op": "set", "path": "thresholds.should_evolve.circle", "value": 0.3}],
    [{"op": "set", "path": "thresholds.auto_accept_category", "value": 1.5}],
    [{"op": "set", "path": "loop.interval_seconds", "value": 0}],
])
def test_guard_impede_remover_protecoes(patch):
    with pytest.raises(PolicyViolation):
        guard(PolicyStore.patched(DEFAULT_POLICY, patch))


def test_evolucao_de_dominio_aprende_regra(circle):
    for i in range(3):
        say(circle, f"{50 + i} sacolão do bairro")
        tx = circle.store.one("SELECT MAX(id) id FROM ledger")["id"]
        assert circle.store.one("SELECT category FROM ledger WHERE id=?", (tx,))["category"] == "outros"
        say(circle, f"corrige {tx} mercado necessario")
    assert circle.ctx.policies.active()[0] == 2
    rule = circle.ctx.policy["rules"][0]
    assert rule["keywords"] == ["sacolao"] and rule["category"] == "mercado"
    assert sum(1 for r in circle.ctx.policy["rules"] if r.get("learned")) == 1   # 'bairro' é redundante
    assert circle.store.one("SELECT status FROM proposals WHERE description LIKE '%bairro%'")["status"] == "deferred"
    msg, _ = say(circle, "33 sacolão do bairro")
    assert "mercado/necessario" in msg and "corrige" not in msg


def test_duas_correcoes_ainda_nao_bastam(circle):
    for i in range(2):
        say(circle, f"{50 + i} sacolão")
        say(circle, f"corrige {i + 1} mercado")
    assert circle.ctx.policies.active()[0] == 1
    assert circle.store.one("SELECT status FROM proposals")["status"] == "deferred"


def test_reviewer_finance_rejeita_regra_que_quebra_historico(circle):
    say(circle, "40 ifood")
    say(circle, "ok 1")
    old = circle.ctx.policy
    new = PolicyStore.patched(old, [{"op": "add_rule", "rule": {"keywords": ["ifood"], "category": "lazer", "tag": "escolha"}}])
    verdict, review = circle.meta.reviewer.review(1, old, new)
    assert verdict == "reject" and review["replay_breaks"] == 1


def test_evolucao_do_circulo_vai_para_shadow(circle):
    circle.store.set("indagador", {"loop": __import__("time").time()})   # o Indagador não toma o giro deste teste
    # 10 aceitos automaticamente, 3 errados => propõe subir o limiar (nível 2)
    for i in range(10):
        say(circle, f"{10 + i} uber")
    for tx in (1, 2, 3):
        say(circle, f"corrige {tx} lazer")
    for tx in range(4, 11):
        say(circle, f"ok {tx}")
    sh = circle.ctx.policies.shadow()
    assert sh is not None and sh[1]["thresholds"]["auto_accept_category"] == 0.8
    assert circle.ctx.policies.active()[0] == 1          # o ativo não mudou
    assert circle.store.one("SELECT level, status FROM proposals WHERE kind='threshold'")["status"] == "shadow"


def test_shadow_promovido_quando_melhor(circle):
    pol = circle.ctx.policies
    pol.add_version(PolicyStore.patched(pol.get(), [
        {"op": "set", "path": "shadow.min_ticks", "value": 1},
        {"op": "set", "path": "shadow.min_observations", "value": 4}]), "active", "teste")
    pol.add_version(PolicyStore.patched(pol.get(), [
        {"op": "set", "path": "thresholds.auto_accept_category", "value": 0.95}]), "shadow", "limiar alto")
    for i in range(4):
        say(circle, f"{10 + i} uber")                    # ativo aceita (0.92); shadow mandaria revisar
        say(circle, f"corrige {i + 1} lazer")            # e o ativo errou
    assert pol.shadow() is None
    assert pol.get()["thresholds"]["auto_accept_category"] == 0.95
    assert pol.get()["rules"][0]["keywords"] == ["uber"]  # regra aprendida no meio do shadow sobreviveu


def test_rollback_automatico_quando_saude_cai(circle):
    for i in range(3):
        say(circle, f"{50 + i} sacolão")
        say(circle, f"corrige {i + 1} mercado")
    assert circle.ctx.policies.active()[0] == 2
    for i in range(5):                                   # regra nova erra sempre
        say(circle, f"{60 + i} sacolão")
        tx = circle.store.one("SELECT MAX(id) id FROM ledger")["id"]
        say(circle, f"corrige {tx} lazer")
    assert circle.ctx.policies.active()[0] == 1
    assert circle.store.one("SELECT status FROM proposals WHERE kind='add_rule'")["status"] == "rolled_back"
    assert circle.store.one("SELECT 1 FROM alerts WHERE kind='saude' AND message LIKE 'Rollback%'")


def test_reviewer_code_nunca_auto_aprova_codigo_de_dinheiro(circle):
    rc = ReviewerCode(circle.ctx)
    assert rc.review(tests_ok=False, lines_changed=10, touches_money_code=False) == "reject"
    assert rc.review(tests_ok=True, lines_changed=10, touches_money_code=True) == "changes"
    assert rc.review(tests_ok=True, lines_changed=10, touches_money_code=False) == "approve"


def _ciclo(pid, tick, ganho, aceita=1, fase="melhoria", tokens=9000):
    return {"project_id": pid, "tick": tick, "fase": fase, "ganho": ganho, "aceita": aceita, "tokens": tokens}


def test_valor_portfolio_um_valor_por_par_de_ciclos_por_projeto():
    cycles = [_ciclo(1, 1, 0.5), _ciclo(2, 2, 0.5), _ciclo(1, 3, 0.1), _ciclo(1, 4, 0.2), _ciclo(2, 5, 0.3)]
    pf = {"min_gain": 0.0, "plateau_cycles": 3}
    # projeto 1 tem 3 ciclos (2 pares), projeto 2 tem 2 (1 par); ciclo único não gera valor
    assert valor_portfolio(cycles, pf, 9000) == pytest.approx([0.1 - CUSTO_CICLO, 0.2 - CUSTO_CICLO, 0.3 - CUSTO_CICLO])
    assert valor_portfolio([_ciclo(1, 1, 0.5)], pf, 9000) == []


def test_valor_portfolio_para_no_plateau_e_mantem_tamanho_entre_politicas():
    cycles = [_ciclo(1, t, 0.0) for t in range(1, 7)]
    atual = valor_portfolio(cycles, {"min_gain": 0.01, "plateau_cycles": 3}, 9000)
    menor = valor_portfolio(cycles, {"min_gain": 0.01, "plateau_cycles": 2}, 9000)
    assert len(atual) == len(menor) == 5        # portfolio_candidates compara posição a posição (zip strict)
    assert sum(menor) > sum(atual)              # parar antes queima menos ciclos sem ganho


def test_codigo_passa_no_lint_do_ci():
    """Mesmo comando do CI: zip sem strict (B905) derrubou o PR antes."""
    pytest.importorskip("ruff")
    raiz = pathlib.Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, "-m", "ruff", "check", "circulo", "tests", "--select", "E,F,W,B", "--ignore", "E501"],
                       cwd=raiz, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

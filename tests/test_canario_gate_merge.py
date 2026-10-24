"""Canário de falha para gate:merge: o portão do merge tem de recusar PR com check vermelho, pendente ou atrás da main.

Pergunta do conselho #137 (auditor): "Qual guardrail nunca barrou nada, e como provar com um teste que ele ainda
funciona?" PRs simulados passam pela interface pública do portão (`MergeGate.run`): cada PR ruim fica com merged=0 e a
razão certa em `merges`, e o PR com todos os gates verdes entra. Se o portão for neutralizado, o canário acusa.
"""
import time

import pytest

from circulo import canario
from circulo.merge_gate import REQUIRED_CHECKS, MergeGate
from circulo.perguntas import _auditor

VERDES = [{"id": i, "name": n, "status": "completed", "conclusion": "success"} for i, n in enumerate(REQUIRED_CHECKS)]
VERMELHO = [{**r, "conclusion": "failure"} if r["name"] == "Constituição" else r for r in VERDES]
PENDENTE = [{**r, "status": "in_progress", "conclusion": None} if r["name"] == "Evidência reforçada" else r for r in VERDES]


class GitHubSimulado:
    def __init__(self, runs, atras=0):
        self.runs, self.atras, self.merged, self.atualizados = runs, atras, [], []

    def open_prs(self):
        return [{"number": 7, "head_sha": "abc", "head_ref": "circulo/feature-x", "draft": False, "title": "PR 7"}]

    def pr_files(self, n):
        return [{"filename": "circulo/agents.py", "additions": 10, "deletions": 2},
                {"filename": "tests/test_agents.py", "additions": 5, "deletions": 0}]

    def check_runs(self, sha):
        return self.runs

    def label_events(self, n):
        return []

    def atras_da_main(self, sha):
        return self.atras

    def update_branch(self, n):
        self.atualizados.append(n)

    def merge(self, n, sha, title):
        self.merged.append(n)
        return True, "merged"


def _rodar(circle, gh):
    [v] = MergeGate(circle.ctx, gh, human="h").run()
    return v, dict(circle.store.one("SELECT merged, reason FROM merges WHERE pr=7 ORDER BY id DESC LIMIT 1"))


@pytest.mark.parametrize("runs,atras,razao", [
    (VERMELHO, 0, "checks falhando: Constituição"),
    (PENDENTE, 0, "checks em andamento: Evidência reforçada"),
    (VERDES, 3, "branch 3 commit(s) atrás da main: atualizada, o CI roda de novo"),
])
def test_portao_recusa_merge_com_a_razao_certa(circle, runs, atras, razao):
    gh = GitHubSimulado(runs, atras)
    v, linha = _rodar(circle, gh)
    assert not v.merge and gh.merged == []
    assert linha == {"merged": 0, "reason": razao}
    assert gh.atualizados == ([7] if atras else [])


def test_portao_mergeia_quando_todos_os_gates_passam(circle):
    gh = GitHubSimulado(VERDES)
    v, linha = _rodar(circle, gh)
    assert v.merge and gh.merged == [7]
    assert linha == {"merged": 1, "reason": "todos os gates passaram"}


def test_canario_do_gate_merge_barra_a_falha_injetada_e_deixa_passar_o_controle():
    assert canario.injetar("gate:merge") == {"ponto": "gate:merge", "velho_falhou": True, "fresco_passou": True, "ok": True}


def test_canario_acusa_portao_neutralizado(monkeypatch):
    from circulo import merge_gate
    monkeypatch.setattr(merge_gate.MergeGate, "evaluate",
                        lambda self, pr: merge_gate.Verdict(pr["number"], pr["head_sha"], True, "todos os gates passaram"))
    r = canario.injetar("gate:merge")
    assert not r["velho_falhou"] and not r["ok"]


def test_canario_acusa_portao_que_barra_tudo(monkeypatch):
    from circulo import merge_gate
    monkeypatch.setattr(merge_gate, "checks_ok", lambda runs: (False, "checks falhando: tudo"))
    r = canario.injetar("gate:merge")
    assert not r["fresco_passou"] and not r["ok"]


def test_auditor_deixa_de_contar_gate_merge_depois_do_canario(circle):
    s = circle.store
    agora = time.time()
    for _ in range(51):
        s.x("INSERT INTO verificacoes(tick,ponto,sujeito,ok,created_at) VALUES(0,'gate:merge','PR #1',1,?)", (agora,))
    assert _auditor(s, agora)[0].evidencia["pontos_que_nunca_falharam"] == ["gate:merge"]

    canario.rodar(s, now=agora)
    assert {(r["ponto"], r["ok"]) for r in s.q("SELECT ponto, ok FROM canarios")} == {("gate:merge", 1)}
    assert _auditor(s, agora) == []      # sem ponto nunca exercitado, o auditor nem faz a pergunta

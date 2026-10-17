import pytest

from circulo.merge_gate import REQUIRED_CHECKS, MergeGate, checks_ok, human_approved, touches_protected

OK_RUNS = [{"id": i, "name": n, "status": "completed", "conclusion": "success"} for i, n in enumerate(REQUIRED_CHECKS)]


class FakeGH:
    def __init__(self, prs, files=None, runs=None, events=None, merge_ok=True):
        self.prs = prs
        self.files = files or {}
        self.runs = runs if runs is not None else {p["head_sha"]: OK_RUNS for p in prs}
        self.events = events or {}
        self.merge_ok = merge_ok
        self.merged = []

    def open_prs(self):
        return self.prs

    def pr_files(self, n):
        return self.files.get(n, [{"filename": "circulo/agents.py", "additions": 20, "deletions": 5}])

    def check_runs(self, sha):
        return self.runs.get(sha, [])

    def label_events(self, n):
        return self.events.get(n, [])

    def merge(self, n, sha, title):
        if self.merge_ok:
            self.merged.append((n, sha))
            self.prs = [p for p in self.prs if p["number"] != n]   # PR mergeado sai da lista de abertos
            return True, "merged"
        return False, "Head branch was modified"


def pr(n=1, ref="circulo/feature-x", sha="abc", draft=False):
    return {"number": n, "head_sha": sha, "head_ref": ref, "draft": draft, "title": f"PR {n}"}


def gate(circle, gh):
    return MergeGate(circle.ctx, gh, human="cmatosengenharia")


def test_merge_quando_tudo_verde(circle):
    gh = FakeGH([pr()])
    [v] = gate(circle, gh).run()
    assert v.merge and gh.merged == [(1, "abc")]
    assert circle.store.one("SELECT merged FROM merges")["merged"] == 1


@pytest.mark.parametrize("runs,why", [
    ([], "ausentes"),
    ([{**r, "status": "in_progress", "conclusion": None} if i == 0 else r for i, r in enumerate(OK_RUNS)], "andamento"),
    ([{**r, "conclusion": "failure"} if i == 1 else r for i, r in enumerate(OK_RUNS)], "falhando"),
    (OK_RUNS + [{"id": 99, "name": "outro", "status": "completed", "conclusion": "failure"}], "falhando"),
])
def test_bloqueia_checks_nao_verdes(circle, runs, why):
    gh = FakeGH([pr()], runs={"abc": runs})
    [v] = gate(circle, gh).run()
    assert not v.merge and why in v.reason and gh.merged == []


def test_usa_execucao_mais_recente_do_check():
    rerun = OK_RUNS + [{"id": -1, "name": REQUIRED_CHECKS[0], "status": "completed", "conclusion": "failure"}]
    assert checks_ok(rerun)[0]          # a falha antiga (id menor) foi superada pela execução nova


def test_nao_mergeia_pr_humano_nem_rascunho(circle):
    gh = FakeGH([pr(1, ref="feature/minha"), pr(2, sha="d", draft=True)])
    vs = gate(circle, gh).run()
    assert [v.merge for v in vs] == [False, False] and gh.merged == []


def test_arquivo_protegido_exige_label_do_humano(circle):
    files = {1: [{"filename": "circulo/finance.py", "additions": 3, "deletions": 1}]}
    gh = FakeGH([pr()], files=files)
    [v] = gate(circle, gh).run()
    assert not v.merge and "protegido" in v.reason
    assert circle.store.one("SELECT 1 FROM alerts WHERE kind='merge' AND message LIKE '%aguarda você%'")

    # label colocado por um bot/agente não vale
    gh.events = {1: [{"event": "labeled", "label": "aprovado-humano", "actor": "circulo-bot"}]}
    assert not gate(circle, gh).run()[0].merge

    # colocado por você vale
    gh.events = {1: [{"event": "labeled", "label": "aprovado-humano", "actor": "cmatosengenharia"}]}
    assert gate(circle, gh).run()[0].merge


def test_label_removido_depois_nao_vale():
    ev = [{"event": "labeled", "label": "aprovado-humano", "actor": "cmatosengenharia"},
          {"event": "unlabeled", "label": "aprovado-humano", "actor": "circulo-bot"}]
    assert not human_approved(ev, "cmatosengenharia")


def test_workflow_e_proprio_gate_sao_protegidos():
    assert touches_protected([".github/workflows/ci.yml", "circulo/merge_gate.py", "circulo/agents.py"]) == [
        ".github/workflows/ci.yml", "circulo/merge_gate.py"]


def test_pr_grande_nao_entra_sozinho(circle):
    gh = FakeGH([pr()], files={1: [{"filename": "circulo/agents.py", "additions": 900, "deletions": 0}]})
    [v] = gate(circle, gh).run()
    assert not v.merge and "grande" in v.reason


def test_sha_travado_github_recusa(circle):
    gh = FakeGH([pr()], merge_ok=False)
    [v] = gate(circle, gh).run()
    assert not v.merge and "recusou" in v.reason


def test_jev_pode_endurecer_mas_nao_liberar(circle):
    class Strict:
        source = "jev"

        def ask_many(self, state, questions):
            from circulo.decision import Decision
            return {k: Decision(k, "choice", "reject", 0.9, "jev") for k in questions}, 1

    circle.ctx.dl.jev = Strict()
    gh = FakeGH([pr()])
    assert not gate(circle, gh).run()[0].merge          # Jev endureceu

    class Lax(Strict):
        def ask_many(self, state, questions):
            from circulo.decision import Decision
            return {k: Decision(k, "choice", "approve", 0.99, "jev") for k in questions}, 1

    circle.ctx.dl.jev = Lax()
    gh = FakeGH([pr()], runs={"abc": []})
    assert not gate(circle, gh).run()[0].merge          # Jev não libera sem checks


def test_avaliacao_repetida_nao_polui_log(circle):
    gh = FakeGH([pr()], runs={"abc": []})
    g = gate(circle, gh)
    for _ in range(5):
        g.run()
    assert circle.store.one("SELECT COUNT(*) c FROM merges")["c"] == 1


def test_loop_inclui_revisao_de_prs_no_idle(tmp_path, clock):
    from circulo.decision import LocalJev
    from circulo.loop import Circle
    c = Circle(tmp_path, jev=LocalJev(), now=clock)
    c.gate = gate(c, FakeGH([pr()]))
    tasks = {c.tick().idle_task for _ in range(10)}
    assert "revisar_prs" in tasks and c.gate.gh.merged == [(1, "abc")]

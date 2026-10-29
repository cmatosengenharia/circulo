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


def test_constituicao_e_recusada_na_hora_sem_esperar_ninguem(circle):
    files = {1: [{"filename": "circulo/merge_gate.py", "additions": 3, "deletions": 1}]}
    gh = FakeGH([pr()], files=files)
    [v] = gate(circle, gh).run()
    assert not v.merge and "constituição" in v.reason and gh.merged == []
    assert circle.store.one("SELECT 1 FROM alerts WHERE kind='fora_alcance'")
    assert not circle.store.one("SELECT 1 FROM alerts WHERE message LIKE '%aguarda você%'")
    # nem um label "humano" libera: a constituição é imutável para o loop
    gh.events = {1: [{"event": "labeled", "label": "aprovado-humano", "actor": "cmatosengenharia"}]}
    assert not gate(circle, gh).run()[0].merge


def test_codigo_de_dinheiro_entra_sozinho_com_evidencia_reforcada(circle):
    files = {1: [{"filename": "circulo/finance.py", "additions": 10, "deletions": 2}]}
    gh = FakeGH([pr()], files=files)
    [v] = gate(circle, gh).run()
    assert v.merge and v.details["dinheiro"] == ["circulo/finance.py"]
    sem = [r for r in OK_RUNS if r["name"] != "Evidência reforçada"]
    gh2 = FakeGH([pr(2, sha="z")], files={2: files[1]}, runs={"z": sem})
    assert not gate(circle, gh2).run()[0].merge          # sem a evidência reforçada, não entra


def test_label_removido_depois_nao_vale():
    ev = [{"event": "labeled", "label": "aprovado-humano", "actor": "cmatosengenharia"},
          {"event": "unlabeled", "label": "aprovado-humano", "actor": "circulo-bot"}]
    assert not human_approved(ev, "cmatosengenharia")


def test_workflow_e_proprio_gate_sao_constituicao():
    from circulo.merge_gate import touches_constitution
    assert touches_constitution([".github/workflows/ci.yml", "circulo/merge_gate.py", "circulo/agents.py", "circulo/finance.py"]) == [
        ".github/workflows/ci.yml", "circulo/merge_gate.py"]
    assert touches_protected(["circulo/finance.py"]) == ["circulo/finance.py"]


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


def test_sem_permissao_checks_le_os_jobs_pelo_actions(monkeypatch):
    import io
    import urllib.error
    from circulo.merge_gate import GitHubREST
    gh = GitHubREST("dono/repo", "t")

    def req(method, path, body=None, **_):
        if "/check-runs" in path:
            raise urllib.error.HTTPError(path, 403, "Forbidden", {}, io.BytesIO(b"{}"))
        if path.startswith("/actions/runs?"):
            assert "head_sha=abc1234" in path
            return {"workflow_runs": [{"id": 9, "head_sha": "abc1234"}]}
        if path.startswith("/actions/runs/9/jobs"):
            return {"jobs": [{"id": 1, "name": "Testes (Python 3.12)", "status": "completed", "conclusion": "success"}]}
        raise AssertionError(path)

    monkeypatch.setattr(gh, "_req", req)
    assert gh.check_runs("abc1234") == [{"id": 1, "name": "Testes (Python 3.12)", "status": "completed", "conclusion": "success"}]


def test_pr_atras_da_main_e_atualizado_antes_do_merge(circle):
    gh = FakeGH([pr()])
    atualizados = []
    gh.atras_da_main = lambda sha: 2
    gh.update_branch = lambda n: atualizados.append(n)
    [v] = gate(circle, gh).run()
    assert not v.merge and "atrás da main" in v.reason and atualizados == [1] and gh.merged == []


def test_main_vermelha_vira_licao_de_estrutura(circle):
    gh = FakeGH([])
    gh.main_ci = lambda: ("abc1234def", "failure")
    gate(circle, gh).run()
    gate(circle, gh).run()                                     # o mesmo sha não registra duas vezes
    lic = circle.store.one("SELECT classe, ocorrencias, item_id FROM licoes WHERE assinatura='gate:main_vermelha'")
    assert lic["classe"] == "estrutural" and lic["ocorrencias"] == 1 and lic["item_id"]


def test_pr_de_docs_fechado_fora_do_gate_sai_de_aberto_na_tabela(circle):
    """PR #44 (Redator técnico, sem item): fechado no GitHub em 28/10, ficou 'aberto' na tabela `prs` porque a
    sincronização só olhava PR com item; o Redator ficou parado ("um PR de docs por vez") e o Vigia alertou por 8 dias."""
    import time
    s = circle.store
    agora = time.time()
    s.x("INSERT INTO prs(number,titulo,branch,status,created_at,updated_at,item_id) VALUES(44,'docs','circulo/docs-1',"
        "'aberto',?,?,NULL)", (agora, agora))
    gh = FakeGH([])                                   # não está mais entre os abertos do GitHub
    gh.pr_state = lambda n: {"state": "closed", "merged": False, "mergeable": None}
    gate(circle, gh).run()
    assert s.one("SELECT status FROM prs WHERE number=44")["status"] == "fechado"
    assert s.one("SELECT 1 FROM alerts WHERE kind='merge' AND message LIKE 'PR #44 (sem item)%'")

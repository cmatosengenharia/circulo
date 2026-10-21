"""Lições de 20/10: CI que nem começa (cobrança do GitHub Actions) não vira conserto, e um erro que já existia antes
da troca de código (worktree órfão) não reprova a versão nova; o worktree órfão é movido, nunca apagado."""
import subprocess
import time
import urllib.error

from circulo import self_dev
from circulo.corpo import MAX_ERROS_NA_VALIDACAO, Corpo
from circulo.merge_gate import CI_NAO_INICIOU, REQUIRED_CHECKS, GitHubREST, MergeGate, checks_ok

COBRANCA = ("The job was not started because recent account payments have failed or your spending limit "
            "needs to be increased. Please check the 'Billing & plans' section in your settings")


def _nao_iniciados():
    return [{"id": i, "name": n, "status": "completed", "conclusion": "failure", "nao_iniciado": COBRANCA}
            for i, n in enumerate(REQUIRED_CHECKS)]


class GH:
    def __init__(self, runs):
        self.runs, self.refeitos = runs, []

    def open_prs(self):
        return [{"number": 7, "head_sha": "abc", "head_ref": "circulo/fix-1-1", "draft": False, "title": "x"}]

    def pr_files(self, n):
        return [{"filename": "circulo/agents.py", "additions": 3, "deletions": 1}, {"filename": "tests/test_x.py", "additions": 3}]

    def check_runs(self, sha):
        return self.runs

    def label_events(self, n):
        return []

    def refazer_falhos(self, sha):
        self.refeitos.append(sha)

    def merge(self, *a):
        raise AssertionError("não pode mergear")


def test_checks_que_nem_comecaram_nao_sao_falha_do_pr():
    ok, why = checks_ok(_nao_iniciados())
    assert not ok and why.startswith(CI_NAO_INICIOU)
    misto = _nao_iniciados()
    misto[0].pop("nao_iniciado")                     # um job falhou de verdade: é falha comum, vai para conserto
    assert checks_ok(misto)[1].startswith("checks falhando")


def test_gate_pausa_o_developer_e_nao_pede_conserto(circle):
    gh = GH(_nao_iniciados())
    [v] = MergeGate(circle.ctx, gh, human="h").run()
    assert not v.merge and v.details.get("ci_indisponivel") and not v.details.get("conserto")
    espera = circle.store.get("self_dev_espera")
    assert espera["precisa_de_voce"] and espera["motivo"].startswith(CI_NAO_INICIOU) and espera["ate"] > time.time()
    assert gh.refeitos == ["abc"]
    MergeGate(circle.ctx, gh, human="h").run()
    assert gh.refeitos == ["abc"]                    # no máximo uma nova tentativa por hora


def test_gate_nao_atropela_espera_mais_importante(circle):
    circle.store.set("self_dev_espera", {"ate": time.time() + 600, "motivo": "limite de uso", "hora": "23:00"})
    MergeGate(circle.ctx, GH(_nao_iniciados()), human="h").run()
    assert circle.store.get("self_dev_espera")["motivo"] == "limite de uso"


def test_cliente_marca_jobs_sem_passos_pela_anotacao(monkeypatch):
    gh = GitHubREST("o/r", "t")
    jobs = [{"id": 1, "name": "Testes", "status": "completed", "conclusion": "failure", "steps": []},
            {"id": 2, "name": "Lint", "status": "completed", "conclusion": "success", "steps": [{"n": 1}]}]
    monkeypatch.setattr(gh, "_check_runs", lambda sha: [dict(j) for j in jobs])
    monkeypatch.setattr(gh, "_req", lambda m, p, *a, **k: [{"message": COBRANCA}] if "annotations" in p else {})
    runs = gh.check_runs("abc")
    assert runs[0]["nao_iniciado"].startswith("The job was not started") and "nao_iniciado" not in runs[1]
    jobs[0]["steps"] = [{"name": "Set up job"}, {"name": "pytest"}]       # falha de verdade: tem passos
    monkeypatch.setattr(gh, "_req", lambda m, p, *a, **k: [{"message": "Process completed with exit code 1."}])
    assert "nao_iniciado" not in gh.check_runs("abc")[0]


def test_erro_que_ja_existia_antes_da_troca_nao_reprova_o_codigo_novo(circle, tmp_path):
    s = circle.store
    msg = ("git worktree add -b circulo/fix-95-1792548845 /Users/x/Projects/.circulo-wt-95 origin/main: "
           "Preparing worktree (new branch 'circulo/fix-95-1792548845')\nfatal: already exists")
    s.x("INSERT INTO run_errors(run_id, tick, stage, kind, message, em) VALUES ('r', 90, 'idle:corrigir_codigo', "
        "'RuntimeError', ?, 0)", (msg,))
    s.set("corpo", {"estado": "validando", "sha": "novo", "anterior": "velho", "desde_tick": 100, "giros_ok": 0, "erros": 0})
    c = Corpo(circle.ctx, None, tmp_path)
    mesmo = 'idle: RuntimeError("git worktree add -b circulo/fix-95-1792549999 /Users/x/Projects/.circulo-wt-95 origin/main")'
    for _ in range(MAX_ERROS_NA_VALIDACAO + 1):
        c.validar([mesmo])
    assert s.get("corpo")["erros"] == 0 and s.get("corpo")["estado"] == "validando"
    c.validar(["meta: KeyError('chave nova que nunca apareceu antes da troca')"])
    assert s.get("corpo")["erros"] == 1              # erro novo continua contando contra o código novo


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_worktree_orfao_e_movido_e_o_caminho_fica_livre(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "a.py").write_text("x = 1\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i")
    wt = tmp_path / ".circulo-wt-95"
    wt.mkdir()
    (wt / "sobra.txt").write_text("trabalho antigo\n")       # diretório que o git não conhece mais
    self_dev._liberar_worktree(repo, wt)
    assert not wt.exists()
    orfaos = list((tmp_path / ".circulo-wt-orfaos").iterdir())
    assert len(orfaos) == 1 and (orfaos[0] / "sobra.txt").read_text() == "trabalho antigo\n"   # movido, não apagado
    git(repo, "worktree", "add", "-q", "-b", "circulo/fix-95-1", str(wt), "HEAD")
    assert (wt / "a.py").exists()


def test_job_sem_nenhum_passo_conta_como_ci_nao_iniciado_mesmo_sem_a_anotacao(monkeypatch):
    """Noite de 20→21/10: o token sem a permissão Checks não lê a anotação; 31 PRs em círculo. Sem passos = não iniciou."""
    gh = GitHubREST("o/r", "t")
    jobs = [{"id": 1, "name": "Testes", "status": "completed", "conclusion": "failure", "sem_passos": True},
            {"id": 2, "name": "Lint", "status": "completed", "conclusion": "failure", "started_at": "2026-10-21T01:00:00Z", "completed_at": "2026-10-21T01:00:04Z"}]
    monkeypatch.setattr(gh, "_check_runs", lambda sha: [dict(j) for j in jobs])

    def req(m, p, *a, **k):
        if "annotations" in p:
            raise urllib.error.HTTPError(p, 403, "sem Checks", {}, None)
        if p.startswith("/actions/jobs/2"):
            return {"id": 2, "steps": []}
        return {}
    monkeypatch.setattr(gh, "_req", req)
    runs = gh.check_runs("abc")
    assert all(r.get("nao_iniciado") for r in runs)
    ok, why = checks_ok([{**r, "name": n} for r, n in zip(runs * 4, REQUIRED_CHECKS, strict=False)])
    assert not ok and why.startswith(CI_NAO_INICIOU)


def test_disjuntor_pausa_o_developer_depois_de_tres_abandonos_iguais(circle):
    from circulo.revisor import DISJUNTOR_PRS, disjuntor_abandonos
    avisos = []
    motivo = "checks falhando: Container, Testes (Python 3.12), Constituição"
    for _ in range(DISJUNTOR_PRS - 1):
        assert not disjuntor_abandonos(circle.store, lambda m, k: avisos.append(m), motivo)
    assert disjuntor_abandonos(circle.store, lambda m, k: avisos.append(m), "checks falhando: Constituição, Container")
    e = circle.store.get("self_dev_espera")
    assert e["precisa_de_voce"] and e["motivo"].startswith("Disjuntor") and e["ate"] > time.time() + 3600 and avisos
    assert circle.store.get("self_dev_abandonos") == []                   # recomeça a contar depois de desarmar
    assert not disjuntor_abandonos(circle.store, lambda m, k: None, "conflito com a main")   # causa diferente não soma


def test_espera_de_ci_nao_iniciado_cai_assim_que_os_jobs_rodam(circle):
    """21/10: o repo virou público e o CI voltou, mas a espera velha segurou o Developer por mais 1 h."""
    gh = GH(_nao_iniciados())
    MergeGate(circle.ctx, gh, human="h").run()
    assert circle.store.get("self_dev_espera")["motivo"].startswith(CI_NAO_INICIOU)
    gh.runs = [{"id": 10 + i, "name": n, "status": "completed", "conclusion": "failure" if i == 0 else "success"}
               for i, n in enumerate(REQUIRED_CHECKS)]                       # rodou de verdade (e um teste falhou)
    MergeGate(circle.ctx, gh, human="h").run()
    assert circle.store.get("self_dev_espera") is None


def test_espera_mais_importante_nao_e_tirada_quando_o_ci_volta(circle):
    circle.store.set("self_dev_espera", {"ate": time.time() + 600, "motivo": "limite de uso", "hora": "23:00"})
    gh = GH([{"id": i, "name": n, "status": "completed", "conclusion": "failure" if i == 0 else "success"}
             for i, n in enumerate(REQUIRED_CHECKS)])                         # CI rodou de verdade (um teste falhou)
    MergeGate(circle.ctx, gh, human="h").run()
    assert circle.store.get("self_dev_espera")["motivo"] == "limite de uso"

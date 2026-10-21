"""Revisor: vários PRs do Developer em paralelo, cada um validado dentro do ecossistema; rejeitado, o item volta à fila."""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from circulo import revisor
from circulo.merge_gate import REQUIRED_CHECKS, MergeGate
from circulo.self_dev import SelfDeveloper

from test_self_dev import FixAgent, git, repo  # noqa: F401 — fixture do repositório
from test_painel import painel  # noqa: F401 — fixture do servidor do painel


OK_CMD = ["python3", "-c", "import sys; sys.exit(0)"]    # cada item traz o seu teste; aqui só importa o fluxo dos PRs


class AgenteDeArquivo(FixAgent):
    """Cada item mexe num arquivo próprio (ou no mesmo, quando pedido), com teste novo."""

    def __init__(self, arquivo="mod_a.py"):
        super().__init__()
        self.arquivo = arquivo

    def run(self, task, workdir):
        self.tasks.append(task)
        (Path(workdir) / self.arquivo).write_text("def f():\n    return 1\n")
        (Path(workdir) / "tests").mkdir(exist_ok=True)
        (Path(workdir) / "tests" / f"test_{self.arquivo}").write_text(f"from {self.arquivo[:-3]} import f\n\ndef test_f():\n    assert f() == 1\n")
        return {"ok": True, "tokens": 10, "log": "ok"}


class GHVarios:
    """GitHub falso que numera PRs e sabe listá-los, fechá-los e mergeá-los."""

    def __init__(self, origin):
        self.origin, self.n, self.prs, self.closed, self.merged = origin, 100, {}, [], []
        self.pendentes = set()          # PRs cujo CI ainda está rodando

    def create_pr(self, head, base, title, body):
        self.n += 1
        self.prs[self.n] = head
        return self.n

    def open_prs(self):
        return [{"number": n, "head_sha": git(self.origin, "rev-parse", b), "head_ref": b, "draft": False, "title": "fix"}
                for n, b in self.prs.items() if n not in [c[0] for c in self.closed] and n not in self.merged]

    def pr_files(self, n):
        b = self.prs[n]
        return [{"filename": f, "additions": 1, "deletions": 0} for f in git(self.origin, "diff", "--name-only", f"main...{b}").splitlines()]

    def check_runs(self, sha):
        rodando = any(git(self.origin, "rev-parse", b) == sha for n, b in self.prs.items() if n in self.pendentes)
        return [{"id": i, "name": nm, "status": "in_progress" if rodando else "completed", "conclusion": None if rodando else "success"}
                for i, nm in enumerate(REQUIRED_CHECKS)]

    def label_events(self, n):
        return []

    def merge(self, n, sha, title):
        self.merged.append(n)
        return True, "ok"

    def close_pr(self, n, comentario=""):
        self.closed.append((n, comentario))

    def pr_state(self, n):
        return {"state": "open", "merged": n in self.merged, "mergeable": True}


def _itens(circle, n, titulo="item"):
    s, agora, ids = circle.store, time.time(), []
    s.x("UPDATE roadmap SET status='feito'")
    for i in range(n):
        ids.append(s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,created_at,updated_at) "
                       "VALUES(?,?,'loop','pendente','e',?, 'ok',?,?)", (f"{titulo} {i}", "d", 900 + i, agora, agora)))
    return ids


def test_dois_prs_em_paralelo_e_a_terceira_vaga_respeita_o_maximo(circle, repo):  # noqa: F811
    ids = _itens(circle, revisor.MAX_PRS_ABERTOS + 1)
    gh = GHVarios(repo.parent / "origin.git")
    abertos = []
    for i in range(revisor.MAX_PRS_ABERTOS):
        dev = SelfDeveloper(circle.ctx, repo, AgenteDeArquivo(f"mod_{i}.py"), gh, test_cmd=OK_CMD)
        r = dev.run_once()
        assert r.status == "proposto", r.detalhe
        abertos.append(r.pr)
    dev = SelfDeveloper(circle.ctx, repo, AgenteDeArquivo("mod_x.py"), gh, test_cmd=OK_CMD)
    assert dev.busy() and dev.run_once().status == "ocupado"                       # sem vaga: espera
    assert [a["number"] for a in dev.abertos()] == abertos
    assert all(json.loads(circle.store.one("SELECT arquivos FROM prs WHERE number=?", (n,))["arquivos"]) for n in abertos)
    st = circle.store.get("self_dev_aberto")
    assert st["abertos"] == abertos and st["max"] == revisor.MAX_PRS_ABERTOS   # retrato para painel, Vigia e fluxo
    assert circle.store.one("SELECT COUNT(*) n FROM revisoes WHERE veredito='aprovado' AND momento='antes_do_pr'")["n"] == revisor.MAX_PRS_ABERTOS
    assert {r["question"] for r in circle.store.q("SELECT question FROM decisions WHERE question='revisor_seguro'")}   # Jev First
    # o gate mesclou um: a vaga abre e o quarto item entra
    gate = MergeGate(circle.ctx, gh, "cmatosengenharia")
    vs = gate.run()
    assert all(v.merge for v in vs) and dev.abertos() == []
    assert circle.store.one("SELECT COUNT(*) n FROM roadmap WHERE status='feito' AND evidencia LIKE 'PR #% mergeado'")["n"] == revisor.MAX_PRS_ABERTOS
    assert dev.run_once().status == "proposto" and dev.pick() is None and ids[-1] in [a["item_id"] for a in dev.abertos()]


def test_arquivo_compartilhado_com_pr_aberto_e_rejeitado_e_o_item_espera_aquele_pr(circle, repo):  # noqa: F811
    ids = _itens(circle, 2)
    gh = GHVarios(repo.parent / "origin.git")
    dev1 = SelfDeveloper(circle.ctx, repo, AgenteDeArquivo("mesmo.py"), gh, test_cmd=OK_CMD)
    assert dev1.run_once().status == "proposto"
    pr1 = dev1.abertos()[0]["number"]
    dev2 = SelfDeveloper(circle.ctx, repo, AgenteDeArquivo("mesmo.py"), gh, test_cmd=OK_CMD)
    r = dev2.run_once()
    assert r.status == "revisor_rejeitou" and f"PR #{pr1}" in r.detalhe and len(gh.prs) == 1   # nada empurrado
    item = circle.store.one("SELECT status, evidencia FROM roadmap WHERE id=?", (ids[1],))
    assert item["status"] == "pendente" and item["evidencia"].startswith(f"aguarda PR #{pr1}:")
    assert dev2.pick() is None                                                     # espera o PR que cruza fechar
    rv = circle.store.one("SELECT veredito, momento, evidencia FROM revisoes ORDER BY id DESC LIMIT 1")
    assert rv["veredito"] == "rejeitado" and json.loads(rv["evidencia"])["compartilhados"][0]["pr"] == pr1
    MergeGate(circle.ctx, gh, "cmatosengenharia").run()                            # o primeiro entrou
    assert dev2.pick()["id"] == ids[1]                                             # volta à fila sozinho
    assert dev2.run_once().status == "proposto"                                    # refeito sobre a main nova


def test_main_que_andou_e_quebra_o_pr_e_rejeitada_antes_de_empurrar(circle, repo):  # noqa: F811
    ids = _itens(circle, 1)
    gh = GHVarios(repo.parent / "origin.git")

    class QuebraNaMainNova(FixAgent):
        def run(self, task, workdir):
            # depende do comportamento ATUAL de soma (a - b): passa na base velha...
            (Path(workdir) / "novo.py").write_text("from app import soma\n\ndef zero(x):\n    return soma(x, x)\n")
            (Path(workdir) / "test_novo.py").write_text("from novo import zero\n\ndef test_zero():\n    assert zero(3) == 0\n")
            return {"ok": True, "tokens": 1, "log": "ok"}
    # sem __pycache__: app.py muda de conteúdo com o mesmo tamanho no mesmo segundo e o .pyc velho mascararia a quebra
    cmd = ["python3", "-c", "import shutil; shutil.rmtree('__pycache__', ignore_errors=True); import novo,sys; sys.exit(0 if novo.zero(3)==0 else 1)"]
    dev = SelfDeveloper(circle.ctx, repo, QuebraNaMainNova(), gh, test_cmd=cmd)
    original = dev._agente

    def agente_e_main_anda(task, wt, titulo, **kw):
        out = original(task, wt, titulo, **kw)
        # ...mas enquanto o agente trabalhava a main corrigiu soma (a + b): o PR quebra na main de agora
        (repo / "app.py").write_text("def soma(a, b):\n    return a + b\n")
        git(repo, "add", "-A")
        git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "main andou")
        git(repo, "push", "-q", "origin", "main")
        return out
    dev._agente = agente_e_main_anda
    r = dev.run_once()
    assert r.status == "revisor_rejeitou" and "quebra na main atual" in r.detalhe and gh.prs == {}
    assert circle.store.one("SELECT status, evidencia FROM roadmap WHERE id=?", (ids[0],))["evidencia"].startswith("revisor:")
    assert json.loads(circle.store.one("SELECT evidencia FROM revisoes ORDER BY id DESC LIMIT 1")["evidencia"])["testes_na_main"] is False


def test_no_gate_o_pr_mais_novo_que_cruza_um_mais_antigo_e_fechado_e_o_item_volta(circle, repo):  # noqa: F811
    ids = _itens(circle, 2)
    gh = GHVarios(repo.parent / "origin.git")
    for i in range(2):
        assert SelfDeveloper(circle.ctx, repo, AgenteDeArquivo(f"g{i}.py"), gh, test_cmd=OK_CMD).run_once().status == "proposto"
    n1, n2 = sorted(gh.prs)
    # depois de abertos, o segundo passou a tocar o arquivo do primeiro (ex.: conserto): o gate pega
    circle.store.x("UPDATE prs SET arquivos=? WHERE number=?", (json.dumps(["g0.py", "g1.py"]), n2))
    gh.pr_files = lambda n: [{"filename": f, "additions": 1, "deletions": 0}
                             for f in (["g0.py", "tests/test_g0.py"] if n == n1 else ["g0.py", "g1.py", "tests/test_g1.py"])]
    gh.pendentes = {n1}                                                            # o mais antigo ainda no CI
    vs = {v.number: v for v in MergeGate(circle.ctx, gh, "cmatosengenharia").run()}
    assert not vs[n1].merge and not vs[n2].merge and vs[n2].reason.startswith("Revisor:")
    assert gh.closed and gh.closed[0][0] == n2
    assert circle.store.one("SELECT status FROM prs WHERE number=?", (n2,))["status"] == "fechado"
    item = circle.store.one("SELECT status, evidencia FROM roadmap WHERE id=?", (ids[1],))
    assert item["status"] == "pendente" and item["evidencia"].startswith(f"aguarda PR #{n1}")


def test_regra_do_jev_e_painel(circle, painel):  # noqa: F811
    from circulo.decision import Question, SN
    q = Question("noul", "seguro?", SN("sim", "nao"))
    seguro = circle.ctx.dl.jev.ask_many({"conflito_main": False, "compartilhados": [], "linhas": 40}, {"revisor_seguro": q})[0]["revisor_seguro"]
    inseguro = circle.ctx.dl.jev.ask_many({"conflito_main": True, "compartilhados": [], "linhas": 40}, {"revisor_seguro": q})[0]["revisor_seguro"]
    assert float(seguro.value) > 0.5 > float(inseguro.value)
    with urllib.request.urlopen(painel + "/api/revisor", timeout=5) as r:
        d = json.loads(r.read())
    assert d["max_abertos"] == revisor.MAX_PRS_ABERTOS and "ultimas" in d
    from circulo.projects import kit_project_id
    with urllib.request.urlopen(painel + f"/missao/{kit_project_id(circle.store, 'circulo')}", timeout=5) as r:
        assert 'id="revLista"' in r.read().decode()
    with urllib.request.urlopen(painel + "/api/fluxo/obras", timeout=5) as r:
        json.loads(r.read())


def test_estado_do_revisor_seguro_traz_tamanho_categoria_e_teste_do_diff(circle, repo):  # noqa: F811
    """Pergunta do conselho #51: o estado do revisor_seguro tem os números do numstat; diffs distintos, confianças distintas."""
    from circulo.decision import Question, SN
    docs = revisor.estado_do_diff("12\t3\tREADME.md\n4\t0\tdocs/guia.md\n")
    pequeno = revisor.estado_do_diff("30\t5\tcirculo/x.py\n20\t0\ttests/test_x.py\n-\t-\tdocs/logo.png\n")
    grande = revisor.estado_do_diff("".join(f"80\t20\tcirculo/m{i}.py\n" for i in range(6)))
    assert docs == {"linhas": 19, "n_arquivos": 2, "categoria_dominante": "docs", "toca_teste": False}
    assert pequeno == {"linhas": 55, "n_arquivos": 3, "categoria_dominante": "código", "toca_teste": True}
    assert grande == {"linhas": 600, "n_arquivos": 6, "categoria_dominante": "código", "toca_teste": False}
    assert revisor.estado_do_diff("12\t3\tREADME.md\n4\t0\ttests/test_x.py\n")["categoria_dominante"] == "docs"
    assert revisor.estado_do_diff("2\t0\ta.py\n40\t0\ttests/test_x.py\n")["categoria_dominante"] == "testes"
    q = Question("noul", "seguro?", SN("sim", "nao"))
    base = {"conflito_main": False, "compartilhados": [], "conflito_prs": [], "testes_na_main": None}
    confs = [circle.ctx.dl.jev.ask_many({**base, **e}, {"revisor_seguro": q})[0]["revisor_seguro"].confidence
             for e in (docs, pequeno, grande)]
    assert confs[0] > confs[1] > confs[2]
    # no fluxo, sem outro PR aberto, o estado já vem medido
    _itens(circle, 1)
    gh = GHVarios(repo.parent / "origin.git")
    assert SelfDeveloper(circle.ctx, repo, AgenteDeArquivo("h.py"), gh, test_cmd=OK_CMD).run_once().status == "proposto"
    ev = json.loads(circle.store.one("SELECT evidencia FROM revisoes WHERE momento='antes_do_pr' ORDER BY id DESC LIMIT 1")["evidencia"])
    assert ev["linhas"] > 0 and ev["n_arquivos"] >= 2 and ev["toca_teste"] is True and ev["categoria_dominante"]


# ------------------------------------------------------------ pré-voo do revisar_prs: adiar sem gastar
class GateFalso:
    """Gate que falha com o erro dado (rede) ou devolve os vereditos dados (estado dos PRs)."""

    def __init__(self, erro=None, motivos=()):
        self.erro, self.motivos, self.rodadas = erro, list(motivos), 0

    def run(self):
        self.rodadas += 1
        if self.erro is not None:
            raise self.erro
        from circulo.merge_gate import Verdict
        return [Verdict(100 + i, "abc", False, m) for i, m in enumerate(self.motivos)]


@pytest.fixture
def erro_urlerror():
    return GateFalso(erro=urllib.error.URLError(TimeoutError("timed out")))


@pytest.fixture
def erro_http_502():
    return GateFalso(erro=urllib.error.HTTPError("https://api.github.com/repos/x/pulls", 502, "Bad Gateway", {}, None))


@pytest.fixture
def erro_timeout():
    return GateFalso(erro=TimeoutError("The read operation timed out"))


@pytest.fixture
def prs_checks_pendentes():
    return GateFalso(motivos=["checks em andamento: Testes (Python 3.12)", "checks em andamento: Lint"])


@pytest.fixture
def prs_atras_da_main():
    return GateFalso(motivos=["branch 3 commit(s) atrás da main: atualizada, o CI roda de novo"])


CAUSAS = [("erro_urlerror", "adiar:rede_transitoria"), ("erro_http_502", "adiar:rede_transitoria"),
          ("erro_timeout", "adiar:rede_transitoria"), ("prs_checks_pendentes", "adiar:checks_pendentes"),
          ("prs_atras_da_main", "adiar:atras_da_main")]


def _estado_ou_erro(g):
    return {"erro": g.erro} if g.erro is not None else {"estado": {"motivos": g.motivos}}


@pytest.mark.parametrize("fixture,causa", CAUSAS)
def test_pre_voo_classifica_a_causa_de_cada_falha(request, fixture, causa):
    assert revisor.pre_voo(**_estado_ou_erro(request.getfixturevalue(fixture))) == causa


def test_pre_voo_executa_quando_a_causa_nao_e_adiavel():
    assert revisor.pre_voo() == "executar"
    assert revisor.pre_voo(erro=urllib.error.HTTPError("u", 404, "Not Found", {}, None)) == "executar"
    assert revisor.pre_voo(erro=KeyError("head")) == "executar"
    assert revisor.pre_voo(estado={"motivos": ["checks em andamento: Lint", "checks falhando: Testes"]}) == "executar"


@pytest.mark.parametrize("fixture,causa", CAUSAS)
def test_adiamento_vira_evento_adiado_e_nao_falha(circle, request, fixture, causa):
    g, s = request.getfixturevalue(fixture), circle.store
    assert revisor.revisar(s, g, rng=lambda: 0.5) == causa          # não levanta: não é falha
    ev = s.one("SELECT momento, veredito, motivo FROM revisoes ORDER BY id DESC LIMIT 1")
    assert (ev["momento"], ev["veredito"], ev["motivo"]) == ("pre_voo", "adiado", causa.split(":", 1)[1])
    assert revisor.em_espera(s)


def test_adiamento_tem_backoff_limitado_com_jitter_e_limite_de_tentativas(circle, erro_http_502):
    s = circle.store
    esperas = []
    for _ in range(revisor.ADIAR_MAX_TENTATIVAS):
        revisor.revisar(s, erro_http_502, rng=lambda: 0.999)
        esperas.append(s.get(revisor.ADIADO)["ate_tick"] - s.tick)
    assert esperas == sorted(esperas) and max(esperas) <= revisor.ADIAR_TETO_GIROS and esperas[0] >= 1
    assert revisor.espera_em_giros(4, rng=lambda: 0.0) < revisor.espera_em_giros(4, rng=lambda: 0.999)   # jitter
    with pytest.raises(urllib.error.HTTPError):           # passou do limite: aí é falha de verdade
        revisor.revisar(s, erro_http_502, rng=lambda: 0.5)
    assert s.get(revisor.ADIADO) is None


def test_no_loop_o_502_do_revisar_prs_e_adiado_sem_incidente_e_o_giro_idle_espera(circle, erro_http_502):
    circle.gate = erro_http_502
    circle._run_idle_task("revisar_prs")
    assert circle.store.one("SELECT COUNT(*) n FROM incidents WHERE stage='idle:revisar_prs'")["n"] == 0
    for _ in range(3):
        assert circle.idle() != "revisar_prs"
    assert erro_http_502.rodadas == 1

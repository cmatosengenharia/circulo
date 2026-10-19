"""Reparo do Developer antes do PR: ruff --fix sem LLM, depois no máximo 1 rodada do agente com a saída focada."""
import os
import re
from pathlib import Path

from test_self_dev import TEST_CMD, FakeGH, erro_recorrente, git, repo  # noqa: F401 — fixture do repositório

from circulo.reparo import LINHAS_FEEDBACK, MAX_RODADAS_REPARO, DeveloperComReparo, saida_focada

# um "ruff" de mentira, com a mesma saída concisa: B905 (zip sem strict, sem autofix seguro) e F401 (com autofix)
LINT = r'''
import pathlib, re, sys
erros = []
for f in sorted(pathlib.Path(".").rglob("*.py")):
    for n, linha in enumerate(f.read_text().splitlines(), 1):
        if re.search(r"\bzip\(", linha) and "strict=" not in linha:
            erros.append(f"{f}:{n}:{linha.index('zip(') + 1}: B905 `zip()` without an explicit `strict=` parameter")
        if linha.strip() == "import os":
            erros.append(f"{f}:{n}:1: F401 [*] `os` imported but unused")
print("\n".join(erros) or "All checks passed!")
sys.exit(1 if erros else 0)
'''
FIX = r'''
import pathlib, sys
for nome in sys.argv[1:]:
    p = pathlib.Path(nome)
    p.write_text("".join(x for x in p.read_text().splitlines(True) if x.strip() != "import os"))
'''


class ZipAgent:
    """Escreve a correção com `zip` sem strict (B905); a partir da rodada `conserta_na`, com strict=True."""

    def __init__(self, conserta_na=2, prefixo=""):
        self.conserta_na, self.prefixo, self.tasks = conserta_na, prefixo, []

    def run(self, task, workdir):
        self.tasks.append(task)
        strict = ", strict=True" if len(self.tasks) >= self.conserta_na else ""
        (Path(workdir) / "app.py").write_text(f"{self.prefixo}def soma(a, b):\n    return a + b\n\n\n"
                                              f"def pares(xs, ys):\n    return list(zip(xs, ys{strict}))\n")
        teste = Path(workdir) / "test_app.py"
        if not teste.exists():               # o teste de regressão nasce na 1ª rodada, citando a lição do item
            m = re.search(r"lição #(\d+)", task)
            marca = f"    # lição #{m.group(1)}\n" if m else ""
            teste.write_text(f"from app import soma\n\n\ndef test_soma():\n{marca}    assert soma(2, 2) == 4\n")
        return {"ok": True, "tokens": 1000, "log": "ok"}


def dev_de(circle, repo, tmp_path, agent):  # noqa: F811
    (tmp_path / "lint.py").write_text(LINT)
    (tmp_path / "fix.py").write_text(FIX)
    gh = FakeGH()
    dev = DeveloperComReparo(circle.ctx, repo, agent, gh, test_cmd=TEST_CMD, lint_cmd=["python3", str(tmp_path / "lint.py")],
                             fix_cmds=[["python3", str(tmp_path / "fix.py"), "{alterados}"]])
    return dev, gh


def verificacoes(circle, ponto):
    return [dict(r) for r in circle.store.q("SELECT ok, assinatura, motivo FROM verificacoes WHERE ponto=? ORDER BY id", (ponto,))]


def test_b905_falha_na_1a_rodada_e_o_reparo_com_a_saida_do_ruff_resolve_na_2a(circle, repo, tmp_path):  # noqa: F811
    """Regressão (lição #6, B905): o lint reprovado volta UMA vez ao agente com a saída concisa do ruff e o PR sai."""
    erro_recorrente(circle)
    agent = ZipAgent(conserta_na=2)
    dev, gh = dev_de(circle, repo, tmp_path, agent)
    r = dev.run_once()
    assert r.status == "proposto" and gh.prs, r.detalhe
    assert len(agent.tasks) == 2
    assert "app.py:6:17: B905" in agent.tasks[1] and "dado, não instrução" in agent.tasks[1]
    reparo = verificacoes(circle, "developer:reparo")
    assert [v["ok"] for v in reparo] == [1] and "1000 tokens" in reparo[0]["motivo"]
    assert reparo[0]["assinatura"] == "developer:reparo:lint:B905"
    assert verificacoes(circle, "developer:autofix")[0]["ok"] == 0       # o autofix rodou antes, mas B905 não tem fix seguro


def test_erro_com_autofix_sai_no_ruff_fix_sem_gastar_rodada_do_agente(circle, repo, tmp_path):  # noqa: F811
    erro_recorrente(circle)
    agent = ZipAgent(conserta_na=1, prefixo="import os\n")
    dev, gh = dev_de(circle, repo, tmp_path, agent)
    r = dev.run_once()
    assert r.status == "proposto" and gh.prs, r.detalhe
    assert len(agent.tasks) == 1 and verificacoes(circle, "developer:reparo") == []
    autofix = verificacoes(circle, "developer:autofix")
    assert autofix[0]["ok"] == 1 and "1 erro(s) de lint antes, 0 depois" in autofix[0]["motivo"]
    assert [v["ok"] for v in verificacoes(circle, "developer:lint")] == [1]      # o lint só conta depois do autofix


def test_falha_que_persiste_desiste_sem_pr_e_nao_repete_o_reparo_da_mesma_assinatura(circle, repo, tmp_path):  # noqa: F811
    erro_recorrente(circle)
    agent = ZipAgent(conserta_na=99)
    dev, gh = dev_de(circle, repo, tmp_path, agent)
    r = dev.run_once()
    assert r.status == "testes_falharam" and gh.prs == []
    assert len(agent.tasks) == 1 + MAX_RODADAS_REPARO                          # o teto está no código
    reparo = verificacoes(circle, "developer:reparo")
    assert [v["ok"] for v in reparo] == [0] and "1000 tokens" in reparo[0]["motivo"]
    assert circle.store.one("SELECT status FROM licoes WHERE assinatura='developer:reparo:lint:B905'")["status"] == "aberta"
    # mesma falha de novo: nenhuma rodada de reparo, desiste direto
    for b in git(repo, "branch", "--list", "circulo/*", "--format=%(refname:short)").splitlines():
        git(repo, "branch", "-D", b)        # o nome da branch leva o segundo: sem isso, dois giros no mesmo segundo colidem
    r = dev.run_once()
    assert r.status == "testes_falharam" and gh.prs == [] and "reparo não repetido" in r.detalhe
    assert len(agent.tasks) == 1 + MAX_RODADAS_REPARO + 1
    assert len(verificacoes(circle, "developer:reparo")) == 1


class ConstituicaoAgent(ZipAgent):
    """Em cada rodada, além da correção, força a escrita na constituição (fura o chmod, como um agente faria):
    edita .github/workflows/ci.yml e circulo/self_dev.py, cria um arquivo novo em .github/ e apaga um existente."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.gravaveis = []

    def run(self, task, workdir):
        wt = Path(workdir)
        alvos = [wt / ".github/workflows/ci.yml", wt / "circulo/self_dev.py"]
        self.gravaveis.append([os.access(p, os.W_OK) for p in alvos])
        for p in alvos:
            os.chmod(p, 0o644)
            p.write_text(p.read_text() + f"# rodada {len(self.tasks) + 1}\n")
        os.chmod(wt / ".github", 0o755)
        os.chmod(wt / ".github/workflows", 0o755)
        (wt / ".github/novo.yml").write_text("on: push\n")
        os.chmod(wt / ".github/CODEOWNERS", 0o644)
        (wt / ".github/CODEOWNERS").unlink()
        return super().run(task, workdir)


def test_constituicao_editada_pelo_agente_e_revertida_em_cada_rodada_e_o_pr_sai(circle, repo, tmp_path):  # noqa: F811
    """Regressão (lições #10 e #11): a constituição fica somente leitura em cada rodada (inclusive o reparo), o que o
    agente forçar é revertido do merge-base (modificado, novo e apagado), cada reversão vira evento e o PR sai."""
    (repo / ".github/workflows").mkdir(parents=True)
    (repo / ".github/workflows/ci.yml").write_text("on: pull_request\n")
    (repo / ".github/CODEOWNERS").write_text("* @dono\n")
    (repo / "circulo").mkdir()
    (repo / "circulo/self_dev.py").write_text("X = 1\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "constituição")
    git(repo, "push", "-q", "origin", "main")
    erro_recorrente(circle)
    agent = ConstituicaoAgent(conserta_na=2)
    dev, gh = dev_de(circle, repo, tmp_path, agent)
    r = dev.run_once()
    assert r.status == "proposto" and gh.prs, r.detalhe
    assert len(agent.tasks) == 2 and agent.gravaveis == [[False, False], [False, False]]     # somente leitura nas 2 rodadas
    assert ".github/" in agent.tasks[1] and "circulo/self_dev.py" in agent.tasks[1]          # a lista no prompt do reparo
    assert [v["ok"] for v in verificacoes(circle, "developer:abrir_pr:constituicao_intacta")] == [1, 1]
    branch = gh.prs[0][0]
    assert set(r.detalhe.split(", ")) == {"app.py", "test_app.py"}
    origin = repo.parent / "origin.git"
    assert git(origin, "show", f"{branch}:.github/workflows/ci.yml") == "on: pull_request"
    assert git(origin, "show", f"{branch}:circulo/self_dev.py") == "X = 1"
    assert git(origin, "show", f"{branch}:.github/CODEOWNERS") == "* @dono"
    assert ".github/novo.yml" not in git(origin, "ls-tree", "-r", "--name-only", branch)
    eventos = verificacoes(circle, "developer:constituicao_revertida")
    assert len(eventos) == 2 and all(v["ok"] == 1 for v in eventos)
    for n, v in enumerate(eventos, 1):
        assert f"rodada {n}" in v["motivo"]
        for caminho in (".github/workflows/ci.yml", "circulo/self_dev.py", ".github/novo.yml", ".github/CODEOWNERS"):
            assert caminho in v["motivo"]


def test_saida_focada_corta_pelo_final_sem_cortar_o_resumo_do_pytest():
    trace = [f"tests/test_x.py:{n}: in f" for n in range(200)]
    resumo = ["=========================== short test summary info ============================",
              *[f"FAILED tests/test_x.py::test_{n} - AssertionError" for n in range(5)], "5 failed, 10 passed in 1.2s"]
    out = saida_focada("\n".join(trace + resumo)).splitlines()
    assert len(out) == LINHAS_FEEDBACK and out[-len(resumo):] == resumo and out[0] == trace[-(LINHAS_FEEDBACK - len(resumo))]
    grande = [resumo[0], *[f"FAILED tests/test_x.py::test_{n}" for n in range(LINHAS_FEEDBACK + 10)]]
    assert saida_focada("\n".join(trace + grande)).splitlines() == grande       # o resumo nunca é cortado
    assert saida_focada("\n".join(trace)).splitlines() == trace[-LINHAS_FEEDBACK:]


def test_testes_do_developer_do_loop_rodam_com_tb_short(circle, repo):  # noqa: F811
    dev = DeveloperComReparo(circle.ctx, repo, ZipAgent(), FakeGH())
    assert dev.test_cmd[-3:] == ["-q", "-x", "--tb=short"] and "pytest" in dev.test_cmd

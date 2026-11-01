"""1.70 — agentes de validação entre o Developer e o PR (circulo/validador.py).

Lição #87 (29/10): o agente de código deixou `.shim297/tmp…/0/repo/` (clone de fixture, sem commit) dentro do
worktree e o `git add -A` quebrou: "não tem um commit em checkout". O validador da árvore apaga o lixo antes do commit
(o erro fica impossível) e o revisor independente lê o diff e só reprova com problema concreto; reprovado é UMA rodada
de correção local, nunca descarte, e sem LLM o veredito é 'aprovado'."""
import subprocess
from pathlib import Path

from circulo import validador
from circulo.self_dev import SelfDeveloper

from test_self_dev import TEST_CMD, FakeGH, FixAgent, erro_recorrente, git, repo  # noqa: F401 — fixture do repositório


def _arvore_com_lixo(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=wt, check=True)
    (wt / "app.py").write_text("x = 1\n")
    shim = wt / ".shim297" / "tmp1fyp7oxz" / "0" / "repo"
    shim.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=shim, check=True)              # repositório aninhado sem commit (lição #87)
    (wt / ".shim297" / "run.py").write_text("print('runner improvisado')\n")
    fixture = wt / "tests" / "dados" / "clone"
    fixture.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=fixture, check=True)           # clone de fixture esquecido fora do .shim
    (wt / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
    (wt / "__pycache__").mkdir()
    return wt


def test_limpar_worktree_apaga_shim_cache_e_repositorio_aninhado_e_o_git_add_passa(tmp_path):
    wt = _arvore_com_lixo(tmp_path)
    p = subprocess.run(["git", "add", "-A"], cwd=wt, capture_output=True, text=True)
    assert p.returncode != 0 and "repo" in (p.stderr + p.stdout)              # reproduz a lição #87
    apagados = validador.limpar_worktree(wt)
    assert ".shim297/" in apagados and "__pycache__/" in apagados
    assert any(a.startswith("tests/dados/clone/") for a in apagados)
    assert not (wt / ".shim297").exists() and not (wt / "tests" / "dados" / "clone").exists()
    assert (wt / "app.py").exists() and (wt / "tests" / "test_x.py").exists() and (wt / ".git").is_dir()
    assert subprocess.run(["git", "add", "-A"], cwd=wt).returncode == 0
    assert validador.limpar_worktree(wt) == []                                 # idempotente


def test_validar_worktree_registra_a_verificacao_sem_parar_o_item(circle, tmp_path):
    wt = _arvore_com_lixo(tmp_path)
    assert validador.validar_worktree(circle.ctx, wt, item_id=7)
    r = circle.store.one("SELECT ok, motivo FROM verificacoes WHERE ponto=? ORDER BY id DESC", (validador.PONTO_WORKTREE,))
    assert r["ok"] == 0 and ".shim297/" in r["motivo"]
    assert validador.validar_worktree(circle.ctx, wt, item_id=7) == []
    assert circle.store.one("SELECT ok FROM verificacoes WHERE ponto=? ORDER BY id DESC", (validador.PONTO_WORKTREE,))["ok"] == 1
    assert circle.store.one("SELECT COUNT(*) n FROM roadmap WHERE origem='erro'")["n"] == 0   # não vira lição nem item


def test_agente_que_escreve_no_repositorio_principal_e_nao_no_worktree_vira_falha(circle, repo):  # noqa: F811
    wt = repo.parent / "wt-item"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "circulo/fix-x", str(wt)], cwd=repo, check=True)
    (wt / "certo.py").write_text("x = 1\n")
    assert validador.escritas_fora(wt) == []
    validador.validar_worktree(circle.ctx, wt, item_id=7)
    assert circle.store.one("SELECT ok FROM verificacoes WHERE ponto=? ORDER BY id DESC", (validador.PONTO_FORA,))["ok"] == 1
    (repo / "app.py").write_text("def soma(a, b):\n    return a + b\n")                   # o agente gravou na árvore principal
    (repo / "novo.py").write_text("y = 2\n")
    assert validador.escritas_fora(wt) == ["app.py", "novo.py"]
    validador.validar_worktree(circle.ctx, wt, item_id=7)
    r = circle.store.one("SELECT ok, motivo FROM verificacoes WHERE ponto=? ORDER BY id DESC", (validador.PONTO_FORA,))
    assert r["ok"] == 0 and "app.py" in r["motivo"] and "novo.py" in r["motivo"]
    assert validador.escritas_fora(repo) == []                                          # o principal não é worktree de ninguém


def test_veredito_tolerante_e_reprova_so_com_problema_concreto():
    assert validador.veredito_de('```json\n{"aprovado": false, "problemas": ["o teste não chama soma()"], "risco": "alto"}\n```') == \
        {"aprovado": False, "problemas": ["o teste não chama soma()"], "risco": "alto"}
    assert validador.veredito_de('{"aprovado": false, "problemas": [], "risco": "medio"}')["aprovado"] is True   # sem problema concreto não reprova
    assert validador.veredito_de("não sei") is None and validador.veredito_de('{"x": 1}') is None


def test_revisar_pr_sem_llm_aprova_e_registra(circle, tmp_path):
    wt = _arvore_com_lixo(tmp_path)
    validador.limpar_worktree(wt)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-am", "base", "--allow-empty"], cwd=wt)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, capture_output=True, text=True).stdout.strip()
    circle.ctx.dl.llm = None
    v = validador.revisar_pr(circle.ctx, wt, base, {"id": 7, "titulo": "x", "detalhe": "y"})
    assert v["aprovado"] and v["fonte"] == "indisponivel"
    v = validador.revisar_pr(circle.ctx, wt, base, {"id": 7, "titulo": "x"}, chamar=lambda s, p: "sem json")
    assert v["aprovado"] and v["fonte"] == "sem_veredito"
    visto = {}

    def chamar(system, prompt):
        visto["prompt"] = prompt
        return '{"aprovado": false, "problemas": ["mudança fora do escopo em app.py"], "risco": "medio"}'
    (wt / "app.py").write_text("x = 2\n")
    v = validador.revisar_pr(circle.ctx, wt, base, {"id": 7, "titulo": "Somar certo", "detalhe": "d"}, chamar=chamar)
    assert not v["aprovado"] and v["fonte"] == "llm" and "app.py" in visto["prompt"] and "Somar certo" in visto["prompt"]
    assert "x = 2" in visto["prompt"]                                              # o diff inclui o que ainda não foi commitado
    r = circle.store.one("SELECT ok, motivo FROM verificacoes WHERE ponto=? ORDER BY id DESC", (validador.PONTO_REVISAO,))
    assert r["ok"] == 0 and "fora do escopo" in r["motivo"]
    assert "fora do escopo" in validador.feedback_validador(v)


def test_developer_limpa_a_arvore_antes_do_commit_e_o_pr_sai_sem_lixo(circle, repo):  # noqa: F811
    class AgenteBagunceiro(FixAgent):
        def run(self, task, workdir):
            out = super().run(task, workdir)
            shim = Path(workdir) / ".shim297" / "tmp" / "0" / "repo"
            shim.mkdir(parents=True)
            subprocess.run(["git", "init", "-q"], cwd=shim, check=True)       # o que quebrou o git add -A na lição #87
            return out
    item = erro_recorrente(circle)
    agent, gh = AgenteBagunceiro(), FakeGH()
    r = SelfDeveloper(circle.ctx, repo, agent, gh, test_cmd=TEST_CMD).run_once()
    assert r.status == "proposto" and r.item_id == item["id"]
    arquivos = git(repo.parent / "origin.git", "ls-tree", "-r", "--name-only", gh.prs[0][0]).splitlines()
    assert not any(a.startswith(".shim") for a in arquivos) and "app.py" in arquivos
    assert circle.store.one("SELECT COUNT(*) n FROM verificacoes WHERE ponto=? AND ok=0", (validador.PONTO_WORKTREE,))["n"] >= 1


def test_developer_reprovado_pelo_validador_corrige_uma_vez_e_segue(circle, repo, monkeypatch):  # noqa: F811
    item = erro_recorrente(circle)
    chamadas = []

    def chamar(system, prompt):
        chamadas.append(prompt)
        return '{"aprovado": false, "problemas": ["falta o caso negativo no teste"], "risco": "baixo"}'
    monkeypatch.setattr(validador, "_chamar_llm", lambda ctx, it: chamar)
    agent, gh = FixAgent(), FakeGH()
    r = SelfDeveloper(circle.ctx, repo, agent, gh, test_cmd=TEST_CMD).run_once()
    assert r.status == "proposto" and r.item_id == item["id"] and len(gh.prs) == 1   # reprovado não descarta: corrige e segue
    assert len(agent.tasks) == 2 and "Validador" in agent.tasks[1] and "caso negativo" in agent.tasks[1]   # UMA rodada de correção
    assert len(chamadas) == 1                                                      # uma revisão por PR; depois só os portões

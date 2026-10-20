"""Developer: causa classificada em cada falha de developer:testes e pré-voo dos testes afetados na main limpa.

Pergunta do conselho #37: developer:testes barrado 6 de 22 vezes em 24 h, sem causa comum agregada (lições #7, #12,
#13, #14 e #21 são testes diferentes). A causa normalizada (tipo de exceção + arquivo de teste, sem o caminho do
worktree) agrega as falhas; o pré-voo separa a falha herdada da main da falha causada pelo agente (Agentless, SWE
Atlas: os testes rodam no código original antes de julgar o patch) e não gasta tokens com base quebrada."""
import time

from circulo.reparo import DeveloperComReparo, causa_testes

from test_self_dev import FakeGH, git, repo  # noqa: F401 — fixture do repositório

TESTE_APP = "from app import soma\n\n\ndef test_soma():\n    assert soma(2, 2) == 4\n"


class ContaAgent:
    def __init__(self):
        self.tasks = []

    def run(self, task, workdir):
        self.tasks.append(task)
        return {"ok": True, "tokens": 5000, "log": "ok"}


def item(circle, detalhe):
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    agora = time.time()
    return s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,estudo) "
               "VALUES('Ajustar a soma',?,'loop','pendente','x',999,?,?,'estudado')", (detalhe, agora, agora))


def main_com_teste(repo, corpo_app):  # noqa: F811
    (repo / "app.py").write_text(corpo_app)
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_app.py").write_text(TESTE_APP)
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "teste")
    git(repo, "push", "-q", "origin", "main")


def test_main_com_teste_vermelho_impede_a_chamada_e_grava_a_causa(circle, repo):  # noqa: F811
    main_com_teste(repo, "def soma(a, b):\n    return a - b\n")                  # vermelho já na main
    it = item(circle, "Mudar a soma em app.py para aceitar negativos.")
    agent = ContaAgent()
    dev = DeveloperComReparo(circle.ctx, repo, agent, FakeGH(), lint_cmd=[], fix_cmds=[])
    r = dev.run_once(item_id=it, autorizado=True)
    assert agent.tasks == []                                                       # nenhum token gasto
    assert r.status == "base_quebrada" and "tests/test_app.py" in r.detalhe
    v = circle.store.one("SELECT * FROM verificacoes WHERE ponto='developer:base' ORDER BY id DESC LIMIT 1")
    assert v["ok"] == 0 and v["causa"] == "AssertionError@tests/test_app.py"
    assert circle.store.one("SELECT 1 FROM licoes WHERE ponto='developer:base'")      # lição de base quebrada
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (it,))["status"] == "pendente"


def test_main_verde_segue_para_a_chamada(circle, repo):  # noqa: F811
    main_com_teste(repo, "def soma(a, b):\n    return a + b\n")
    it = item(circle, "Mudar a soma em app.py para aceitar negativos.")
    agent = ContaAgent()
    dev = DeveloperComReparo(circle.ctx, repo, agent, FakeGH(), lint_cmd=[], fix_cmds=[])
    dev.run_once(item_id=it, autorizado=True)
    assert len(agent.tasks) == 1
    assert not circle.store.one("SELECT 1 FROM verificacoes WHERE ponto='developer:base' AND ok=0")


def test_falha_de_testes_grava_a_causa_sem_o_caminho_do_worktree(circle, repo):  # noqa: F811
    saida = ("=========================== short test summary info ============================\n"
             "FAILED /Users/x/.circulo-wt-12/tests/test_vigia.py::test_a - assert 0 == 1\n"
             "ERROR tests/test_jev_replay.py - ModuleNotFoundError: No module named 'x'\n2 failed in 0.1s")
    dev = DeveloperComReparo(circle.ctx, repo, ContaAgent(), FakeGH(), lint_cmd=[], fix_cmds=[],
                             test_cmd=["python3", "-c", f"print({saida!r}); raise SystemExit(1)"])
    wt = repo.parent / ".circulo-wt-12"
    wt.mkdir()
    assert dev.verificar(wt)[0] is False
    v = circle.store.one("SELECT causa FROM verificacoes WHERE ponto='developer:testes' AND ok=0")
    assert v["causa"] == "AssertionError@tests/test_vigia.py, ModuleNotFoundError@tests/test_jev_replay.py"


def test_causa_sem_resumo_do_pytest_ainda_e_classificada():
    assert causa_testes("Timeout: 900s") == "sem_resumo"
    assert causa_testes("FAILED tests/test_a.py::t - RuntimeError: x\nFAILED tests/test_a.py::u - RuntimeError: y") \
        == "RuntimeError@tests/test_a.py"

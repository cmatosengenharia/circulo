"""Developer: teto de tokens por item checado ANTES de cada chamada e corte na 2ª falha igual, rumo ao fatiador.

O teto é max(2× a mediana de tokens dos PRs entregues em 24 h, piso fixo): um dia ruim não encolhe o teto abaixo do
piso. Estourar o teto ou repetir a mesma falha (node id + linha do erro normalizada) não gasta outra chamada: o
trabalho parcial fica guardado e o item vai para o fatiador, sem exceção."""
import time
from pathlib import Path

from circulo import fatiador
from circulo.merge_gate import CONSTITUICAO
from circulo.planejador import Planejador
from circulo.reparo import DeveloperComReparo, assinatura_falha
from circulo.registro import registrar as registrar_llm

from test_fatiador import DivLLM
from test_self_dev import FakeGH, git, repo  # noqa: F401 — fixture do repositório

SAIDA = "=========================== short test summary info ============================\n" \
        "FAILED test_app.py::test_soma - assert 0 == 4\n1 failed in 0.03s"
TESTE_VERMELHO = ["python3", "-c", f"print({SAIDA!r}); raise SystemExit(1)"]


class RepeteAgent:
    """Agente simulado: sempre a mesma correção errada, e tenta mexer na constituição."""

    def __init__(self):
        self.tasks = []

    def run(self, task, workdir):
        self.tasks.append(task)
        (Path(workdir) / "app.py").write_text("def soma(a, b):\n    return a * 0\n")
        (Path(workdir) / "test_app.py").write_text("from app import soma\n\n\ndef test_soma():\n    assert soma(2, 2) == 4\n")
        (Path(workdir) / "circulo").mkdir(exist_ok=True)
        (Path(workdir) / "circulo" / "policy.py").write_text("LIVRE = True\n")
        return {"ok": True, "tokens": 5000, "log": "ok"}


def preparar(circle, repo, **kw):  # noqa: F811
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    agora = time.time()
    item = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,estudo) "
               "VALUES('Item que repete a falha','consertar a soma','loop','pendente','x',999,?,?,'estudado')", (agora, agora))
    circle.ctx.dl.llm = DivLLM()
    agent = RepeteAgent()
    dev = DeveloperComReparo(circle.ctx, repo, agent, FakeGH(), test_cmd=TESTE_VERMELHO, lint_cmd=[], fix_cmds=[], **kw)
    circle.self_dev = dev
    circle.planejador = Planejador(circle.ctx, dev)
    return item, dev, agent


def gasto(circle, entrada, tokens):
    registrar_llm(circle.store, tick=0, project_id=None, papel="developer", modelo="Claude Code", tokens=tokens, entrada=entrada)


def status(circle, item):
    return circle.store.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"]


def constituicao_em_alguma_branch(repo):  # noqa: F811
    return [b for b in git(repo, "branch", "-a", "--format=%(refname:short)").splitlines()
            if git(repo, "ls-tree", "-r", "--name-only", b, "--", *CONSTITUICAO)]


def test_mesma_falha_da_rodada_anterior_corta_sem_nova_chamada_e_fatia(circle, repo):  # noqa: F811
    item, dev, agent = preparar(circle, repo)
    wt = repo.parent / fatiador.sujeito(item)
    wt.mkdir()
    assert dev.verificar(wt) == (False, SAIDA)                                    # a rodada anterior falhou assim
    wt.rmdir()
    assert fatiador.proximo(circle.ctx, dev, circle.planejador) == item          # 1 falha só: ainda não fatia
    r = dev.run_once(item_id=item, autorizado=True)
    assert r.status == "testes_falharam" and "reparo não repetido" in r.detalhe
    assert len(agent.tasks) == 1                                                  # nenhuma rodada de reparo paga
    alvo = fatiador.proximo(circle.ctx, dev, circle.planejador)                   # fatia na 2ª falha, não na 3ª
    assert status(circle, item) == "dividido" and alvo != item
    assert constituicao_em_alguma_branch(repo) == []


def test_teto_estourado_antes_da_chamada_nao_chama_o_agente_e_manda_ao_fatiador(circle, repo):  # noqa: F811
    item, dev, agent = preparar(circle, repo, piso_teto=10_000)
    gasto(circle, "Item que repete a falha", 9_000)                               # 9.000 + ~9.000 da próxima > 10.000
    r = dev.run_once(item_id=item, autorizado=True)                               # sem exceção
    assert agent.tasks == [] and r.status == "teto" and "teto" in r.detalhe
    assert status(circle, item) == "pendente"
    fatiador.proximo(circle.ctx, dev, circle.planejador)
    assert status(circle, item) == "dividido"


def test_teto_estourado_no_reparo_guarda_o_trabalho_parcial(circle, repo):  # noqa: F811
    item, dev, agent = preparar(circle, repo, piso_teto=12_000)
    gasto(circle, "Item que repete a falha", 4_000)                               # 4.000 + 4.000 cabe; depois do 1º, não
    r = dev.run_once(item_id=item, autorizado=True)
    assert len(agent.tasks) == 1 and r.status == "testes_falharam" and "teto" in r.detalhe
    wip = (circle.store.get("self_dev_wip") or {})[str(item)]
    assert "return a * 0" in git(repo, "show", f"{wip['branch']}:app.py")         # o parcial ficou na branch
    assert constituicao_em_alguma_branch(repo) == []
    fatiador.proximo(circle.ctx, dev, circle.planejador)
    assert status(circle, item) == "dividido"


def test_teto_e_o_dobro_da_mediana_dos_prs_entregues_com_piso(circle, repo):  # noqa: F811
    item, dev, agent = preparar(circle, repo, piso_teto=50_000)
    assert dev.teto() == 50_000                                                   # sem PR entregue: o piso
    agora = time.time()
    for n, (titulo, tokens) in enumerate([("A", 30_000), ("B", 40_000), ("C", 90_000)], 1):
        circle.store.x("INSERT INTO prs(number,titulo,status,created_at,updated_at) VALUES(?,?,'mergeado',?,?)",
                       (n, titulo, agora, agora))
        gasto(circle, titulo, tokens - 1_000)
        gasto(circle, f"reparo: {titulo}", 1_000)
    assert dev.teto() == 80_000
    circle.store.x("UPDATE prs SET updated_at=? WHERE titulo='C'", (agora - 2 * 86400,))   # fora das 24 h
    assert dev.teto() == 70_000


def test_assinatura_da_falha_e_node_id_mais_linha_do_erro_normalizada():
    a = assinatura_falha(SAIDA)
    assert a == assinatura_falha(SAIDA.replace("0.03s", "1.20s"))
    assert "test_app.py::test_soma" in a and "assert 0 == 4" in a
    assert a != assinatura_falha(SAIDA.replace("assert 0 == 4", "NameError: name 'x' is not defined"))
    assert assinatura_falha("app.py:6:17: B905 `zip()` without strict") == assinatura_falha("app.py:9:3: B905 `zip()` without strict")
    assert assinatura_falha("algo quebrou sem formato") == ""

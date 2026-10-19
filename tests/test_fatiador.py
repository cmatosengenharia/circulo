"""Item que acumula 3 falhas locais vira sub-itens validados um a um (lição #13).

Só o sub-item que falhou é repetido, com o erro anterior no prompt; a divisão tem profundidade máxima 1."""
import json
import time

from circulo import fatiador
from circulo.planejador import Planejador
from circulo.self_dev import SelfDeveloper

from test_self_dev import TEST_CMD, FakeGH, FixAgent, repo  # noqa: F401 — fixture do repositório


class DivLLM:
    def __init__(self):
        self.prompts = []

    def complete(self, system, prompt, max_tokens):
        self.prompts.append(prompt)
        return json.dumps({"sub_itens": [
            {"titulo": "Parte A: contar falhas", "detalhe": "contar as falhas locais", "teste": "tests/test_a.py"},
            {"titulo": "Parte B: dividir o item", "detalhe": "criar os sub-itens", "teste": "tests/test_b.py"},
        ]}), 300


def preparar(circle, repo):  # noqa: F811
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    agora = time.time()
    item = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,estudo) "
               "VALUES('Item grande demais','mexer em tudo','loop','pendente','x',999,?,?,'estudado')", (agora, agora))
    llm = DivLLM()
    circle.ctx.dl.llm = llm
    agent = FixAgent()
    dev = SelfDeveloper(circle.ctx, repo, agent, FakeGH(), test_cmd=TEST_CMD)
    circle.self_dev = dev
    circle.planejador = Planejador(circle.ctx, dev)
    return item, dev, agent, llm


def falhar(circle, item_id, motivo="AssertionError: soma(2, 2) == 0", n=1):
    for _ in range(n):
        circle.licoes.verificar("developer:testes", False, sujeito=f".circulo-wt-{item_id}", motivo=motivo, licao=False)


def subs(circle, pai):
    return [dict(r) for r in circle.store.q("SELECT * FROM roadmap WHERE pai=? ORDER BY ordem", (pai,))]


def test_tres_falhas_dividem_o_item_e_ele_nao_e_reexecutado_inteiro(circle, repo):  # noqa: F811
    """lição #13: 3 falhas locais no mesmo sujeito geram sub-itens; o item inteiro não volta para o Developer."""
    item, dev, agent, llm = preparar(circle, repo)
    falhar(circle, item, n=2)
    assert fatiador.proximo(circle.ctx, dev, circle.planejador) == item      # abaixo do limite: segue inteiro
    falhar(circle, item)
    alvo = fatiador.proximo(circle.ctx, dev, circle.planejador)
    a, b = subs(circle, item)
    assert alvo == a["id"] and "tests/test_a.py" in a["detalhe"]
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "dividido"
    assert dev.pick() is None                                                # o pai saiu da fila
    assert circle._tem_trabalho("corrigir_codigo")                           # mas o sub-item é trabalho
    assert "AssertionError" in llm.prompts[0]                                # o Planejador vê o erro que motivou
    circle._run_idle_task("corrigir_codigo")
    assert len(agent.tasks) == 1 and "Parte A" in agent.tasks[0] and "mexer em tudo" not in agent.tasks[0]
    # sub-item seguinte só depois que o anterior passou
    assert fatiador.proximo(circle.ctx, dev, circle.planejador) is None or dev.busy()


def test_falha_de_sub_item_repete_so_ele_com_o_erro_anterior(circle, repo):  # noqa: F811
    item, dev, agent, llm = preparar(circle, repo)
    falhar(circle, item, n=3)
    fatiador.proximo(circle.ctx, dev, circle.planejador)
    a, b = subs(circle, item)
    circle.store.x("UPDATE roadmap SET status='feito' WHERE id=?", (a["id"],))   # A validado (teste passou, PR mergeado)
    falhar(circle, b["id"], motivo="NameError: name 'dividir' is not defined")
    assert fatiador.proximo(circle.ctx, dev, circle.planejador) == b["id"]
    assert fatiador.proximo(circle.ctx, dev, circle.planejador) == b["id"]   # perguntar de novo não acumula o erro
    assert circle.store.one("SELECT detalhe FROM roadmap WHERE id=?", (b["id"],))["detalhe"].count(fatiador.MARCA) == 1
    r = dev.run_once(item_id=b["id"], autorizado=True)
    assert r.status == "proposto"
    assert "Parte B" in agent.tasks[0] and "NameError" in agent.tasks[0] and "Parte A" not in agent.tasks[0]
    assert len(llm.prompts) == 1                                             # não pede nova divisão


def test_divisao_tem_profundidade_maxima_1_e_sub_item_com_3_falhas_e_descartado(circle, repo):  # noqa: F811
    item, dev, agent, llm = preparar(circle, repo)
    falhar(circle, item, n=3)
    fatiador.proximo(circle.ctx, dev, circle.planejador)
    a, b = subs(circle, item)
    falhar(circle, a["id"], n=3)
    assert fatiador.proximo(circle.ctx, dev, circle.planejador) is None
    assert subs(circle, a["id"]) == [] and len(llm.prompts) == 1             # não divide de novo
    st = {r["id"]: r["status"] for r in circle.store.q("SELECT id, status FROM roadmap WHERE id IN (?,?,?)", (item, a["id"], b["id"]))}
    assert st == {item: "descartado", a["id"]: "descartado", b["id"]: "descartado"}
    assert circle.store.one("SELECT COUNT(*) n FROM licoes WHERE ponto='developer:fatiador'")["n"] == 1
    assert not circle._tem_trabalho("corrigir_codigo")


def test_ultimo_sub_item_feito_conclui_o_pai(circle, repo):  # noqa: F811
    item, dev, agent, llm = preparar(circle, repo)
    falhar(circle, item, n=3)
    fatiador.proximo(circle.ctx, dev, circle.planejador)
    circle.store.x("UPDATE roadmap SET status='feito' WHERE pai=?", (item,))
    assert fatiador.proximo(circle.ctx, dev, circle.planejador) is None
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "feito"

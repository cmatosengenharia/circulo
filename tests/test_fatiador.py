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
    tarefa = agent.tasks[0].split("Memória do time")[0]                        # a memória pode citar a Parte A feita; a tarefa, não
    assert "Parte B" in tarefa and "NameError" in tarefa and "Parte A" not in tarefa
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


# ------------------------------------------------------------ 1.46.0: o sub-item em andamento não trava o resto

def test_sub_item_com_pr_aberto_nao_trava_o_conserto_nem_a_fila(circle, repo):  # noqa: F811
    """No Mac (20/10, 45 min parado): o sub-item A tinha PR aberto reprovado pelo CI; o seguinte esperava A, o
    fatiador devolvia None, o giro voltava sem chamar o Developer — e o conserto do PR de A nunca acontecia."""
    item, dev, agent, llm = preparar(circle, repo)
    falhar(circle, item, n=3)
    fatiador.proximo(circle.ctx, dev, circle.planejador)
    a, b = subs(circle, item)
    circle.store.x("UPDATE roadmap SET status='em_andamento', evidencia='PR #42' WHERE id=?", (a["id"],))
    outro = circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,estudo,ordem,created_at,updated_at) "
                           "VALUES('Outro item do loop','d','loop','pendente','x','{}',900,0,0)")
    assert fatiador.proximo(circle.ctx, dev, circle.planejador) == outro       # B espera A, mas a fila normal anda
    agora = time.time()
    circle.store.x("INSERT INTO prs(number,project_id,titulo,branch,status,item_id,conserto,consertos,created_at,updated_at) VALUES(42,2,'A','circulo/fix-a','aberto',?,?,0,?,?)",
                   (a["id"], json.dumps({"sha": "abc", "motivo": "checks falhando: Reprodução primeiro"}), agora, agora))
    assert dev._conserto() is not None and dev.tem_trabalho()
    chamadas = []
    dev.run_once = lambda item_id=None, autorizado=False: chamadas.append(item_id) or type("R", (), {"status": "consertado", "detalhe": ""})()
    circle._run_idle_task("corrigir_codigo")
    assert chamadas == [None]                                                  # consertar() vem antes de qualquer item novo


# ------------------------------------------------------------ pré-divisão determinística (sub-item #60: 94705 tokens)

TEXTO_60 = ("Extrair features das tentativas do planejador (minutos, categoria, falhas seguidas)",
            "Em circulo/planejador.py, registrar a tentativa com minutos_desde_a_anterior() e categoria_do_item(); "
            "em circulo/tentativas_planejador.py, criar extrair_features() e falhas_seguidas(); em circulo/features.py, "
            "expor por_categoria() e media_de_minutos(). Testes: tests/test_tentativas_planejador.py::test_features_categoria.")


def preparar_60(circle, repo):  # noqa: F811
    item, dev, agent, llm = preparar(circle, repo)
    circle.store.x("UPDATE roadmap SET titulo=?, detalhe=? WHERE id=?", (*TEXTO_60, item))
    return item, dev, agent, llm


def test_estimar_tamanho_conta_modulos_e_simbolos_citados():
    est = fatiador.estimar_tamanho(*TEXTO_60)
    assert est["modulos"] == ["circulo/planejador.py", "circulo/tentativas_planejador.py", "circulo/features.py"]
    assert {"extrair_features", "categoria_do_item", "media_de_minutos", "test_features_categoria"} <= set(est["simbolos"])
    assert est["linhas"] > 0 and fatiador.grande_demais(est)
    assert not fatiador.grande_demais(fatiador.estimar_tamanho("Item pequeno", "em circulo/loop.py, mudar giro()"))


def test_texto_do_60_gera_fatias_por_modulo_sem_chamar_a_llm(circle, repo):  # noqa: F811
    """lição #29: o sub-item #60 estourou o teto de tokens (94705); a regra divide por módulo antes da LLM."""
    item, dev, agent, llm = preparar_60(circle, repo)
    alvo = fatiador.proximo(circle.ctx, dev, circle.planejador)
    partes = subs(circle, item)
    assert len(partes) >= 2 and alvo == partes[0]["id"] and llm.prompts == []      # zero chamadas à LLM
    assert "circulo/planejador.py" in partes[0]["titulo"] and "extrair_features" in partes[1]["detalhe"]
    assert "extrair_features" not in partes[0]["detalhe"]                            # cada fatia só com o seu módulo
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "dividido"
    m = fatiador.medicoes(circle.store)                                              # estimativa x tokens, para recalibrar
    assert [x["id"] for x in m] == [p["id"] for p in partes] and m[0]["modulos"] == 1 and m[0]["tokens"] == 0


def test_sub_item_pre_dividido_que_estoura_o_teto_e_redividido_sozinho(circle, repo):  # noqa: F811
    """O teto de tokens é a rede de segurança: só o sub-item que estourou vai à LLM; o pai e as outras fatias seguem."""
    item, dev, agent, llm = preparar_60(circle, repo)
    fatiador.proximo(circle.ctx, dev, circle.planejador)
    a = subs(circle, item)[0]
    circle.licoes.verificar("developer:teto", False, sujeito=f".circulo-wt-{a['id']}", licao=False,
                            motivo="teto de tokens do item: 94705 gastos + ~5919 da próxima chamada > 100000")
    alvo = fatiador.proximo(circle.ctx, dev, circle.planejador)
    partes = subs(circle, item)
    assert partes[0]["id"] == a["id"] and partes[0]["status"] == "dividido" and len(llm.prompts) == 1
    assert alvo == partes[1]["id"] and "Parte A" in partes[1]["titulo"] and "Parte B" in partes[2]["titulo"]
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "dividido"   # pai segue
    circle.store.x("UPDATE roadmap SET status='feito' WHERE pai=? AND status!='dividido'", (item,))
    fatiador.proximo(circle.ctx, dev, circle.planejador)
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "feito"

import json
from pathlib import Path

from circulo.planejador import MAX_POR_DIA, Planejador, _parse

from test_self_dev import TEST_CMD, FakeGH, FixAgent, repo  # noqa: F401 — fixture do repositório
from circulo.self_dev import SelfDeveloper


class PlanLLM:
    def __init__(self, titulo="Pergunta do worth_spending com estado mais rico"):
        self.titulo = titulo
        self.prompts = []

    def complete(self, system, prompt, max_tokens):
        self.prompts.append(prompt)
        return json.dumps({"titulo": self.titulo, "detalhe": "incluir histórico de aceitação no estado",
                           "sucesso": "menos de 50% das decisões do worth_spending abaixo de jev_incerto"}), 400


def preparar(circle, repo, llm):  # noqa: F811
    circle.store.x("UPDATE roadmap SET status='feito'")              # nada para o Developer pegar
    circle.ctx.dl.llm = llm
    dev = SelfDeveloper(circle.ctx, repo, FixAgent(), FakeGH(), test_cmd=TEST_CMD)
    return dev, Planejador(circle.ctx, dev)


def test_roteiro_vazio_vira_item_planejado_que_o_developer_pega(circle, repo):  # noqa: F811
    llm = PlanLLM()
    dev, plan = preparar(circle, repo, llm)
    assert dev.pick() is None and plan.precisa()
    item = plan.run()
    assert item and item["id"]
    assert any("dado, não instrução" in x and "jev_em_duvida" in x for x in llm.prompts)
    r = circle.store.one("SELECT origem, status FROM roadmap WHERE id=?", (item["id"],))
    assert (r["origem"], r["status"]) == ("loop", "pendente")
    assert dev.pick() is None                                        # pedido é hipótese: antes, o estudo
    from circulo.estudo import Estudo
    plan.estudo = Estudo(circle.ctx)
    assert not plan.precisa()                                         # item esperando estudo: não planeja outro
    plan.estudo.run()
    assert dev.pick()["id"] == item["id"]
    assert not plan.precisa()                                         # já tem trabalho: não planeja de novo
    assert circle.store.one("SELECT papel FROM llm_calls ORDER BY id DESC LIMIT 1")["papel"] == "planejador"


def test_planejador_respeita_intervalo_limite_diario_e_repeticao(circle, repo):  # noqa: F811
    dev, plan = preparar(circle, repo, PlanLLM(titulo="Rodar 24/7"))   # título de item que já existe
    assert plan.run() is None
    assert not plan.precisa()                                         # intervalo entre tentativas
    circle.store.set("planejador", {"em": 0})
    for i in range(MAX_POR_DIA):
        circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                       "VALUES(?,?,'loop','feito','x',?,strftime('%s','now'),strftime('%s','now'))", (f"t{i}", "d", 900 + i))
    assert not plan.precisa()


def test_sem_llm_ou_sem_developer_nao_planeja(circle):
    assert not Planejador(circle.ctx, None).precisa()


def test_parse():
    assert _parse('ok {"titulo": "a", "detalhe": "b", "sucesso": "c"} fim')["titulo"] == "a"
    assert _parse("sem json") is None and _parse('{"titulo": ""}') is None


def test_resposta_cortada_pelo_limite_de_tokens_depois_do_detalhe_vira_item():
    """Lição #45: a resposta cortada no "sucesso" (título e detalhe completos) era descartada como "sem JSON válido"."""
    cortada = ('{"titulo": "Esqueleto do teste citado", "detalhe": "Item que cita teste inexistente gera o esqueleto.", '
               '"sucesso": "Lições novas com \'file or directory not')
    item = _parse(cortada)
    assert item is not None and item["titulo"] == "Esqueleto do teste citado" and item["sucesso"] == ""
    assert _parse('{"titulo": "Só o título", "detalhe": "Item que cita') is None   # detalhe cortado não vira item


def test_loop_planeja_quando_fica_sem_trabalho(circle, repo):  # noqa: F811
    dev, _ = preparar(circle, repo, PlanLLM())
    circle.self_dev = dev
    circle.planejador = Planejador(circle.ctx, dev)
    assert circle.trabalho_pendente()                                 # giro rápido, não o descanso longo
    escolhido = None
    for _ in range(6):
        r = circle.tick()
        if r.idle_task == "planejar_roteiro":
            escolhido = r
            break
    assert escolhido is not None
    assert circle.store.one("SELECT COUNT(*) n FROM roadmap WHERE origem='loop'")["n"] == 1
    assert Path(repo).exists()


def test_item_chutado_nao_vira_trabalho(circle, repo):  # noqa: F811
    """Evidência marcada (pstack): inconclusivo não passa."""
    class Chute(PlanLLM):
        def complete(self, system, prompt, max_tokens):
            return json.dumps({"titulo": "Trocar o banco por Postgres", "detalhe": "parece melhor",
                               "sucesso": "mais rápido", "base": "chutado"}), 300
    _, plan = preparar(circle, repo, Chute())
    assert plan.run() is None
    assert not circle.store.one("SELECT 1 FROM roadmap WHERE titulo LIKE 'Trocar o banco%'")


def test_item_medido_leva_o_dado_no_detalhe(circle, repo):  # noqa: F811
    class Medido(PlanLLM):
        def complete(self, system, prompt, max_tokens):
            return json.dumps({"titulo": "Pergunta do worth em inglês", "detalhe": "x", "sucesso": "confiança ≥ 0,5",
                               "base": "medido", "dado": "44% das decisões abaixo de jev_incerto"}), 300
    _, plan = preparar(circle, repo, Medido())
    item = plan.run()
    assert "Evidência (medido): 44%" in circle.store.one("SELECT detalhe FROM roadmap WHERE id=?", (item["id"],))["detalhe"]

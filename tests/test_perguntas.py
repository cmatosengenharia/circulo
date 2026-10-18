"""Conselho de perguntas: a evolução parte de perguntas diversas, escolhidas por dor medida e custo, sem LLM."""
import json
import time

from circulo.perguntas import Conselho


class PlanLLM:
    def __init__(self, resposta):
        self.resposta = resposta
        self.prompts = []

    def complete(self, system, prompt, max_tokens):
        self.prompts.append(prompt)
        return json.dumps(self.resposta, ensure_ascii=False), 300


def pedido_painel(circle):
    circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                   "VALUES('Dash do loop em camadas','x','pedido_cassio','feito','PR #7',900,?,?)", (time.time(), time.time()))


def test_pergunta_do_usuario_nasce_dos_pedidos_sobre_o_painel(circle):
    pedido_painel(circle)
    ids = {p.id: p for p in Conselho(circle.ctx).candidatas()}
    p = ids["usuario:painel_metricas"]
    assert "Como usuário" in p.texto and p.evidencia["pedidos_recentes_sobre_painel"]


def test_perguntas_sao_diversas_e_baratas(circle):
    pedido_painel(circle)
    circle.tick()
    personas = {p.persona for p in Conselho(circle.ctx).candidatas()}
    assert len(personas) >= 3                                       # várias perspectivas, não um olhar só
    assert circle.store.one("SELECT COUNT(*) n FROM llm_calls")["n"] == 0   # gerar e priorizar não gasta LLM


def test_diversidade_tira_forca_da_persona_recente(circle):
    c = Conselho(circle.ctx)
    p = c.candidatas()[0]
    antes = p.score
    c.registrar(p)
    circle.store.x("UPDATE perguntas SET status='descartada'")     # fechada, mas recente
    depois = next(x for x in c.candidatas() if x.id == p.id).score
    assert depois < antes


def test_planejador_responde_a_pergunta_e_liga_o_item(circle, tmp_path):
    from circulo.planejador import Planejador
    from circulo.self_dev import SelfDeveloper
    circle.store.x("UPDATE roadmap SET status='feito'")
    pedido_painel(circle)
    llm = PlanLLM({"titulo": "Gráfico de tendência no topo do dash", "detalhe": "x", "sucesso": "y"})
    circle.ctx.dl.llm = llm
    plan = Planejador(circle.ctx, SelfDeveloper(circle.ctx, tmp_path, agent=None, github=None))
    r = plan.run(autorizado=True)
    assert r and r["pergunta"] and "Pergunta do conselho" in llm.prompts[0]
    q = circle.store.one("SELECT persona, status, item_id FROM perguntas ORDER BY id DESC LIMIT 1")
    assert q["status"] == "virou_item" and q["item_id"] == r["id"]
    assert circle.store.one("SELECT evidencia FROM roadmap WHERE id=?", (r["id"],))["evidencia"].startswith("pergunta do conselho")
    # a pergunta em andamento não é feita de novo
    assert q["persona"] + ":" not in {p.id[:len(q['persona']) + 1] for p in Conselho(circle.ctx).candidatas()
                                      if p.id == circle.store.one("SELECT chave FROM perguntas")["chave"]}


def test_resposta_sem_item_nao_gasta_roteiro(circle, tmp_path):
    from circulo.planejador import Planejador
    from circulo.self_dev import SelfDeveloper
    circle.store.x("UPDATE roadmap SET status='feito'")
    circle.ctx.dl.llm = PlanLLM({"sem_item": "o Developer já corrige uma vez antes do PR (MAX_CORRECOES_LOCAIS)"})
    antes = circle.store.one("SELECT COUNT(*) n FROM roadmap")["n"]
    assert Planejador(circle.ctx, SelfDeveloper(circle.ctx, tmp_path, agent=None, github=None)).run(autorizado=True) is None
    assert circle.store.one("SELECT COUNT(*) n FROM roadmap")["n"] == antes
    assert circle.store.one("SELECT status FROM perguntas")["status"] == "descartada"


def test_placar_aprende_quem_pergunta_bem(circle):
    c = Conselho(circle.ctx)
    for status in ("entregue", "entregue"):
        circle.store.x("INSERT INTO perguntas(chave,persona,texto,status,created_at,updated_at) VALUES('a','usuario','x',?,0,0)", (status,))
    for status in ("contestada", "repetida"):
        circle.store.x("INSERT INTO perguntas(chave,persona,texto,status,created_at,updated_at) VALUES('b','cetico','x',?,0,0)", (status,))
    w = c.pesos()
    assert w["usuario"] > 1.0 > w["cetico"]


def test_entregue_fecha_o_placar(circle):
    c = Conselho(circle.ctx)
    iid = circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                         "VALUES('t','d','loop','feito','PR #9 mergeado',1,0,0)")
    circle.store.x("INSERT INTO perguntas(chave,persona,texto,status,item_id,created_at,updated_at) VALUES('k','usuario','x','virou_item',?,0,0)", (iid,))
    assert c.acompanhar() == 1
    assert circle.store.one("SELECT status FROM perguntas")["status"] == "entregue"

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
    assert r and r["pergunta"] and any("Pergunta do conselho" in x for x in llm.prompts)
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


# ------------------------------------------------------------------ Questionador (LLM especializada em evolução)

class Questionador:
    def __init__(self, resposta):
        self.resposta = resposta
        self.chamadas = []

    def complete(self, system, prompt, max_tokens):
        self.chamadas.append(system)
        return json.dumps(self.resposta, ensure_ascii=False), 500


NOVAS = {"perguntas": [
    {"persona": "economista", "texto": "Quais conflitos de PR poderiam ser evitados se o Developer trouxesse a main antes de começar?",
     "metrica": "conflitos_pr", "por_que_agora": "x"},
    {"persona": "novato", "objetivo_da_persona": "quem abre o painel pela primeira vez", "metrica": "pedidos_humano",
     "texto": "Um novato entende em 10 segundos o que o loop está fazendo?"},
    {"persona": "economista", "texto": "pergunta sem métrica válida", "metrica": "inexistente"},
]}


def test_questionador_especializado_cria_perguntas_presas_a_metricas(circle):
    from circulo.perguntas import QUESTIONADOR, gerar, personas
    q = Questionador(NOVAS)
    circle.ctx.dl.llm = q
    ids = gerar(circle.ctx)
    assert len(ids) == 2                                            # a sem métrica do catálogo é descartada
    assert "QUESTIONADOR" in q.chamadas[0] and q.chamadas[0] == QUESTIONADOR
    assert "novato" in personas(circle.store)                      # perspectiva nova criada por ele
    assert gerar(circle.ctx) == []                                  # no máximo 1 vez por dia
    cands = {p.texto: p for p in Conselho(circle.ctx).candidatas()}
    assert "Um novato entende em 10 segundos o que o loop está fazendo?" not in cands or \
        cands["Um novato entende em 10 segundos o que o loop está fazendo?"].evidencia["metrica"] == "pedidos_humano"
    assert circle.store.one("SELECT papel FROM llm_calls ORDER BY id DESC LIMIT 1")["papel"] == "questionador"


def test_pergunta_gerada_que_nao_rende_e_desativada(circle):
    from circulo.perguntas import gerar
    mid = circle.store.x("INSERT INTO perguntas_modelo(persona,texto,metrica,origem,ativo,created_at) "
                         "VALUES('cetico','x','estagnacao','gerada',1,0)")
    for st in ("contestada", "repetida", "descartada"):
        circle.store.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,created_at,updated_at) VALUES(?,'cetico','x',?,'loop',0,0)",
                       (f"gerada:{mid}", st))
    circle.ctx.dl.llm = None
    gerar(circle.ctx)
    assert circle.store.one("SELECT ativo FROM perguntas_modelo WHERE id=?", (mid,))["ativo"] == 0


def test_cada_tipo_de_missao_tem_suas_perspectivas_e_a_pergunta_do_ciclo_nao_gasta_llm(circle):
    from circulo.perguntas import pergunta_da_missao
    q = Questionador({"personas": [{"chave": "fotografo", "objetivo": "entregar fotos sem retrabalho"},
                                   {"chave": "cliente_final", "objetivo": "achar e baixar as fotos fácil"}]})
    circle.ctx.dl.llm = q
    proj = {"id": 77, "tipo": "portal", "pedido": "portal admin de fotógrafo"}
    _, t1 = pergunta_da_missao(circle.ctx, proj, "galeria carrega em menos de 2 s")
    _, t2 = pergunta_da_missao(circle.ctx, proj, "galeria carrega em menos de 2 s")
    assert len(q.chamadas) == 1                                     # perspectivas geradas uma vez por tipo
    assert t1.startswith("Como fotografo") or t1.startswith("Como cliente final")
    assert t1 != t2                                                 # rodízio entre perspectivas


def test_falha_local_no_worktree_e_do_item_e_nunca_do_diretorio(circle):
    """A falha local grava o item do roteiro no registro; o ranking agrupa por id do item e mostra o título."""
    from circulo.licoes import registrar
    from circulo.perguntas import _arquiteto
    s, agora = circle.store, time.time()
    item = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
               "VALUES('Simplificar o fatiador','x','loop','em_andamento','',1,?,?)", (agora, agora))
    registrar(circle.ctx, "developer:testes", False, sujeito=f".circulo-wt-{item}", motivo="tests/a.py:1: AssertionError")
    gravada = s.one("SELECT item_id, item_titulo FROM verificacoes WHERE ponto='developer:testes' ORDER BY id DESC LIMIT 1")
    assert (gravada["item_id"], gravada["item_titulo"]) == (item, "Simplificar o fatiador")
    # registro antigo, sem item gravado: o diretório só resolve o item na leitura; sem item, cai em 'sem_item'
    for tick, sujeito in enumerate((f".circulo-wt-{item}", f".circulo-wt-{item}", ".circulo-wt-999", ".circulo-wt-999"),
                                   start=s.tick + 1):
        s.x("INSERT INTO verificacoes(tick,ponto,sujeito,ok,motivo,created_at) VALUES(?,'developer:lint',?,0,'E1',?)",
            (tick, sujeito, agora))
    ranking = _arquiteto(s, agora)[0].evidencia["itens_com_mais_falhas_locais"]
    assert ranking[0] == {"item": item, "titulo": "Simplificar o fatiador", "n": 3, "linhas": 3}
    assert {"item": "sem_item", "titulo": "sem_item", "n": 2, "linhas": 2} in ranking
    assert not [x for x in ranking if ".circulo-wt-" in str(x)]


def test_falhas_locais_contam_execucoes_distintas_e_nao_linhas(circle):
    """Pergunta #160: 1 execução do Developer com 50 linhas de falha é n=1; as linhas vão à parte."""
    from circulo.perguntas import _arquiteto
    s, agora = circle.store, time.time()
    item = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
               "VALUES('Item que repete linhas','x','loop','em_andamento','',1,?,?)", (agora, agora))
    outro = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                "VALUES('Item que refaz','x','loop','em_andamento','',2,?,?)", (agora, agora))
    for i in range(50):
        s.x("INSERT INTO verificacoes(tick,ponto,sujeito,ok,assinatura,motivo,created_at,item_id) "
            "VALUES(7,'developer:testes','x',0,?,'falhou',?,?)", (f"sig{i % 3}", agora, item))
    for tick in (1, 2):
        s.x("INSERT INTO verificacoes(tick,ponto,sujeito,ok,assinatura,motivo,created_at,item_id) "
            "VALUES(?,'developer:testes','x',0,'sig','falhou',?,?)", (tick, agora, outro))
    ranking = _arquiteto(s, agora)[0].evidencia["itens_com_mais_falhas_locais"]
    assert ranking[0] == {"item": outro, "titulo": "Item que refaz", "n": 2, "linhas": 2}
    assert ranking[1] == {"item": item, "titulo": "Item que repete linhas", "n": 1, "linhas": 50}

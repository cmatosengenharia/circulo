"""Memória do time (circulo/memoria.py): o que o loop já viu volta por relevância, na hora em que um agente precisa."""
import json
import time

from circulo import estudo as es
from circulo.memoria import Memoria, jaccard, termos
from circulo.state import Store


def _semear(s, agora=None):
    agora = agora or time.time()
    s.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,created_at,updated_at) "
        "VALUES('developer:worktree:lint','developer','trabalho','ruff reclamou de import não usado no worktree','rode o ruff antes de abrir o PR','validada',3,1,?,?)", (agora, agora))
    s.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,created_at,updated_at) "
        "VALUES('gate:ci:timeout','gate','ambiente','CI do GitHub demorou','esperar','aberta',1,0,?,?)", (agora, agora))
    est = json.dumps({"veredito": "adotar", "justificativa": "planejar cedo reduz fila", "achados": [{"ideia": "planejar no mesmo giro", "base": "medido"}], "fontes": ["a", "b"]})
    itens = [("Vigia: citar o motivo da última recusa do porteiro", "feito", None),
             ("Planejador roda no mesmo giro da pergunta validada", "pendente", est),
             ("Teto de tokens por item do Developer", "feito", None)]
    ids = []
    for i, (tit, st, e) in enumerate(itens):
        ids.append(s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (tit, "detalhe " + tit, "loop", st, "PR #1 mergeado", 900 + i, e, agora, agora)))
    return ids


def test_termos_e_parecenca_ignoram_acentos_e_palavras_vazias():
    assert termos("O Planejador não planeja porque está sem LLM") == ["planejador", "planeja", "porque", "llm"]
    assert jaccard("Teto de tokens por item do Developer", "teto de tokens por item no developer") == 1.0
    assert jaccard("Vigia: pergunta parada", "Jardineiro: podar noqa") == 0.0


def test_indice_recupera_por_relevancia_com_resultado_e_tambem_sem_fts5():
    s = Store(":memory:")
    m = Memoria(s)
    assert m.fts is True                                                     # o SQLite deste ambiente tem FTS5
    _semear(s)
    assert m.reindexar(forcar=True) == {"licoes": 2, "roadmap": 3}
    hits = m.buscar("Developer: lint falhou no worktree antes do PR")
    assert hits[0]["tipo"] == "licao" and hits[0]["resultado"] == "validada" and hits[0]["score"] > hits[1]["score"]
    assert {h["tipo"] for h in hits} <= {"licao", "item", "estudo"} and all("timeout" not in h["titulo"] for h in hits)   # a lição de CI não é parecida
    bloco = m.contexto("Developer lint worktree", "corrigir_codigo")
    assert bloco.startswith("Memória do time") and "lição #1 · validada" in bloco and len(bloco) <= 1700
    assert s.one("SELECT agente, assunto FROM memoria_uso")["agente"] == "corrigir_codigo"   # cada uso fica registrado
    assert m.reindexar(forcar=True) == {}                                    # incremental: nada mudou, nada reindexa
    m.fts = False                                                            # sem FTS5: o BM25 em Python acha o mesmo
    assert m.buscar("Developer: lint falhou no worktree antes do PR")[0]["tipo"] == "licao"


def test_estudo_parecido_e_item_parecido():
    s = Store(":memory:")
    m = Memoria(s)
    ids = _semear(s)
    par = m.estudo_parecido({"id": 999, "titulo": "Planejador rodar no mesmo giro que a pergunta validada"})
    assert par and par["de_item"] == ids[1] and par["parecido"] >= 0.6 and par["estudo"]["fontes"] == ["a", "b"]
    assert m.estudo_parecido({"id": ids[1], "titulo": "Planejador roda no mesmo giro da pergunta validada"}) is None   # não reaproveita a si mesmo
    assert m.estudo_parecido({"id": 999, "titulo": "Vigia: pergunta parada há horas"}) is None
    dup = m.item_parecido("Teto de tokens por item no Developer")
    assert dup and dup["id"] == ids[2] and dup["parecido"] == 1.0
    assert m.item_parecido("Orçamento do dia em custo, não em tokens") is None


def test_arquiteto_reaproveita_estudo_parecido_sem_gastar(circle):
    s = circle.store
    ids = _semear(s)
    agora = time.time()
    novo = dict(s.one("SELECT * FROM roadmap WHERE id=?", (s.x(
        "INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,'pendente',?,?,?,?)",
        ("Planejador rodar no mesmo giro que a pergunta validada", "d", "pedido_cassio", "pedido pelo painel", 950, agora, agora)),)))
    assert es.modo_do_estudo(novo) == "completo"                              # custaria um estudo completo
    r = circle.estudo.run(novo)
    assert r["modo"] == "reaproveitado" and r["de_item"] == ids[1] and r["fontes"] == ["a", "b"]
    assert s.one("SELECT COUNT(*) n FROM llm_calls WHERE papel='estudo'")["n"] == 0
    uso = s.one("SELECT agente, poupou_tokens FROM memoria_uso WHERE poupou_tokens>0")
    assert uso["agente"] == "estudar_pedido" and uso["poupou_tokens"] == es.MODOS["completo"]["est"]
    assert "reaproveitado do estudo do item" in json.loads(s.one("SELECT estudo FROM roadmap WHERE id=?", (novo["id"],))["estudo"])["justificativa"]
    res = circle.memoria.resumo()
    assert res["reaproveitados_24h"] == 1 and res["tokens_poupados_24h"] == es.MODOS["completo"]["est"] and res["total"] >= 5


def test_desenvolvedor_recebe_memoria_da_tarefa_e_episodio_fica_gravado(circle):
    from circulo import self_dev as sd
    s = circle.store
    ids = _semear(s)
    dev = sd.SelfDeveloper.__new__(sd.SelfDeveloper)
    dev.ctx, dev.s = circle.ctx, s
    txt = dev._licoes_txt(ids[2])
    assert "Memória do time" in txt and "lição #1" in txt and "Erros que o círculo já cometeu" in txt
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,item_id,arquivos,consertos,created_at,updated_at) VALUES(41,2,'Teto de tokens por item do Developer','b','aberto',?,?,1,?,?)",
        (ids[2], json.dumps(["circulo/self_dev.py"]), time.time(), time.time()))
    dev._salvar_pr = lambda *a, **k: None
    dev.pr_closed(41, True)
    ep = s.one("SELECT * FROM memoria WHERE tipo='episodio'")
    assert ep and ep["resultado"] == "mergeado" and "circulo/self_dev.py" in ep["texto"] and "PR #41" in ep["titulo"]
    assert any(h["tipo"] == "episodio" for h in circle.memoria.buscar("teto de tokens developer self_dev"))


def test_equipe_mostra_o_que_o_agente_lembrou(circle):
    from circulo import equipe
    s = circle.store
    cur = equipe.cursor_inicial(s)
    _semear(s)
    circle.memoria.contexto("Developer lint worktree", "corrigir_codigo")
    circle.memoria.poupou("estudar_pedido", "x", 30000, [{"tipo": "estudo", "ref": 2, "titulo": "t"}])
    msgs, _ = equipe.mensagens(s, cur)
    assert any(m["de"] == "corrigir_codigo" and m["para"] == "licoes" and "lembrei de" in m["texto"] for m in msgs)
    assert any(m["de"] == "estudar_pedido" and m["tom"] == "entrega" and "30.000 tokens" in m["texto"] for m in msgs)


def test_gerente_de_produto_nao_abre_item_que_ja_existe_com_outras_palavras(circle, monkeypatch):
    import sys
    sys.path.insert(0, "tests")
    from test_planejador_mesmo_giro import LLMSeq, _pergunta, _plan
    s = circle.store
    pid = _pergunta(circle)
    agora = time.time()
    existente = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    ("Teto de tokens por item do Developer", "d", "loop", "pendente", "x", 990, agora, agora))
    plan = _plan(circle, LLMSeq(titulo="Teto de tokens por item no Developer"))     # mesma ideia, outras palavras
    antes = s.one("SELECT COUNT(*) n FROM roadmap")["n"]
    plan.run()
    p = s.one("SELECT status, item_id FROM perguntas WHERE id=?", (pid,))
    assert p["status"] == "repetida" and p["item_id"] == existente
    assert s.one("SELECT COUNT(*) n FROM roadmap")["n"] == antes                 # nenhum item novo

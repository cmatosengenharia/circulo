"""Velocidade da autoevolução: o planejador não para por teto fixo, o Indagador não seca e o Vigia não fica mudo.

No Mac (19/10) o loop ficou 10 h sem item novo com 3 perguntas validadas esperando: o teto de 6 itens/dia do
planejador tinha sido atingido às 01:31 e a trava do Vigia, já 'tratada', não agiu de novo em 777 passagens.
"""
import time

from circulo import indagador, planejador as pl, vigia
from circulo.planejador import Planejador

from test_planejador import PlanLLM, preparar
from test_self_dev import repo  # noqa: F401 — fixture do repositório


def _itens_loop(s, n, ha=0):
    agora = time.time() - ha
    for i in range(n):
        s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,'loop','feito','x',?,?,?)",
            (f"v{i}", "d", 700 + i, agora, agora))


def _prs(s, status):
    agora = time.time()
    for i, st in enumerate(status):
        s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (500 + i, 1, f"pr {i}", f"b{i}", st, agora - i, agora - i))


def test_seis_itens_no_dia_nao_param_mais_o_planejador(circle, repo):  # noqa: F811
    _, plan = preparar(circle, repo, PlanLLM())
    _itens_loop(circle.store, 6)
    assert plan.precisa() and circle.store.get(pl.GATE)["motivo"] is None
    _itens_loop(circle.store, pl.MAX_POR_DIA)
    assert not plan.precisa() and "teto diário" in circle.store.get(pl.GATE)["motivo"]


def test_qualidade_ruim_freia_o_teto(circle, repo):  # noqa: F811
    _, plan = preparar(circle, repo, PlanLLM())
    _prs(circle.store, ["fechado", "fechado", "mergeado", "fechado"])
    assert plan.teto() == pl.FREIO_POR_DIA
    _itens_loop(circle.store, pl.FREIO_POR_DIA)
    assert not plan.precisa() and "freado" in circle.store.get(pl.GATE)["motivo"]
    circle.store.x("UPDATE prs SET status='mergeado'")
    assert plan.teto() == pl.MAX_POR_DIA and plan.precisa()


def test_fila_vazia_planeja_em_minutos_e_com_item_na_fila_espera_mais(circle, repo):  # noqa: F811
    _, plan = preparar(circle, repo, PlanLLM())
    s = circle.store
    s.set("planejador", {"em": time.time() - pl.INTERVALO_RAPIDO - 1})
    assert plan.precisa()                                              # fila vazia: 2 min bastam
    agora = time.time()
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES('a','d','loop','pendente','e',1,?,?)", (agora, agora))
    assert not plan.precisa() and "intervalo" in s.get(pl.GATE)["motivo"]
    s.set("planejador", {"em": time.time() - pl.INTERVALO - 1})
    assert plan.precisa()


def test_sem_developer_o_motivo_fica_registrado(circle):
    assert not Planejador(circle.ctx, None).precisa()
    assert circle.store.get(pl.GATE)["motivo"] == "sem LLM ou sem Developer"


def test_indagador_volta_logo_quando_nao_ha_pergunta_valida(circle):
    s = circle.store
    s.set("indagador", {"loop": time.time() - indagador.INTERVALO_FOME - 1})
    assert indagador.proximo_cerebro(s) is not None                   # sem válida esperando: 30 min, não 6 h
    agora = time.time()
    for i in range(indagador.MAX_VALIDAS):
        s.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,score,created_at,updated_at) VALUES(?,'arquiteto','q?','valida','loop',0.5,?,?)",
            (f"k{i}", agora, agora))
    assert indagador.proximo_cerebro(s) is None                       # estoque cheio: volta ao intervalo longo
    s.x("DELETE FROM perguntas")
    s.set("indagador_vazio", {"loop": time.time()})                   # última passagem sem candidata nova: espera mais
    assert indagador.proximo_cerebro(s) is None
    s.set("indagador", {"loop": time.time() - indagador.INTERVALO_VAZIO - 1})
    assert indagador.proximo_cerebro(s) is not None


def test_vigia_cita_o_motivo_medido_do_planejador_e_age_de_novo_se_a_trava_persiste(circle):
    s = circle.store
    antes = time.time() - vigia.ESPERA_PERGUNTA - vigia.INTERVALO - 60
    s.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,score,created_at,updated_at) VALUES('k','arquiteto','q?','valida','loop',0.5,?,?)",
        (antes, antes))
    s.set(pl.GATE, {"em": time.time(), "motivo": "teto diário: 6 itens em 24 h (teto 6)"})
    achado = {a["chave"]: a for a in vigia.sondar(s)}["pergunta_valida_parada"]
    assert "teto diário" in achado["sugestao"] and achado["evidencia"]["planejador_motivo"].startswith("teto")
    agora = time.time()
    s.x("INSERT INTO vigia(chave,titulo,evidencia,sugestao,gravidade,veredito,acao,conf,classificacao,status,item_id,primeira_em,ultima_em,vezes) "
        "VALUES('pergunta_valida_parada','t','{}','s',0.8,'trava','alertar',0.6,'{}','aberta',NULL,?,?,5)", (agora - vigia.REAGIR - 60, agora))
    v = vigia.Vigia(circle.ctx)
    assert "pergunta_valida_parada" in v.rodar()["agiu"]               # trava antiga, ação antiga: age de novo
    assert "pergunta_valida_parada" not in v.rodar()["agiu"]           # e não repete na passagem seguinte


# ------------------------------------------------------------------ 1.27.0: o que travou depois (medido no Mac, 19/10 à tarde)
def test_502_do_github_e_erro_de_ambiente_e_nao_trava_a_evolucao(circle):
    from circulo import licoes
    assert licoes.classificar("execucao:idle:revisar_prs", "HTTPError: HTTP Error 502: Bad Gateway") == "ambiente"
    assert licoes.classificar("execucao:idle:revisar_prs", "HTTPError: HTTP Error 503: Service Unavailable") == "ambiente"
    assert licoes.classificar("execucao:idle:qualquer", "KeyError: 'x'") == "estrutural"
    s = circle.store
    agora = time.time()
    item = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,'erro','pendente','lição #99',1,?,?)",
               ("Lição #99: Corrigir erro: HTTPError em idle:revisar_prs", "d", agora, agora))
    s.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,item_id,primeira_tick,ultima_tick,created_at,updated_at) "
        "VALUES('x','execucao:idle:revisar_prs','estrutural','execucao:idle:revisar_prs: HTTPError: HTTP Error 502: Bad Gateway','p','aberta',1,0,?,1,1,?,?)",
        (item, agora, agora))
    lic = circle.ctx.licoes
    assert lic.bloqueia_evolucao() is False                                 # reclassifica na hora: não trava
    assert s.one("SELECT classe FROM licoes WHERE assinatura='x'")["classe"] == "ambiente"
    assert s.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "descartado"   # o Developer não vai "consertar" o GitHub


def test_indagador_nao_rejulga_pergunta_descartada_nem_insiste_na_inconclusa(circle):
    s = circle.store
    agora = time.time()
    for chave, status, ha in (("a", "descartada", 3600), ("b", "inconclusa", 600), ("c", "inconclusa", 10 * 3600), ("d", "entregue", 7200),
                              ("e", "inconclusa", 20 * 3600), ("e", "inconclusa", 8 * 3600), ("f", "descartada", 5 * 86400)):
        s.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,created_at,updated_at) VALUES(?,?,?,?,'loop',?,?)",
            (chave, "x", "q?", status, agora - ha, agora - ha))
    fora = indagador.ja_julgadas(s, "loop", agora)
    assert {"a", "b", "d", "e"} <= fora                                      # descartada/entregue há pouco, inconclusa recente, inconclusa 2x
    assert "c" not in fora and "f" not in fora                               # inconclusa há 10 h volta; descartada há 5 dias volta


def test_funil_medido_vira_a_primeira_pergunta_do_loop(circle):
    s = circle.store
    agora = time.time()
    assert indagador.candidatas_funil(s) == [] or all(c["chave"] == "funil:planejador_parado" for c in indagador.candidatas_funil(s))
    for i in range(3):                                                       # 3 perguntas que levaram 60 min para virar item (alvo 15)
        rid = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,'loop','feito',?,?,?,?)",
                  (f"i{i}", "d", f"PR #{900 + i} mergeado", 800 + i, agora - 3600, agora))
        s.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,item_id,created_at,updated_at) VALUES(?,?,?,?,'loop',?,?,?)",
            (f"p{i}", "arquiteto", "q?", "entregue", rid, agora - 3600 - 3600, agora))
        s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (900 + i, 1, "t", "b", "mergeado", agora - 3000, agora))
        s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,?,1,'ok','',?)", (900 + i, "abc", agora - 2400))
    f = indagador.funil(s)
    assert f["etapas"]["pergunta_para_item"]["mediana_min"] == 60 and f["etapas"]["pergunta_para_item"]["atraso"] == 4.0
    assert f["etapas"]["item_para_pr"]["mediana_min"] == 10 and f["etapas"]["pr_para_merge"]["mediana_min"] == 10
    c = indagador.candidatas_funil(s)
    assert c and c[0]["chave"] == "funil:pergunta_para_item" and c[0]["evidencia"]["base"] == "medido" and "60 min" in c[0]["texto"]
    cands = indagador.candidatas(circle.ctx, None)                                              # 1.71: produto vai na frente;
    assert [c["chave"] for c in cands if c.get("eixo") != "produto"][0] == "funil:pergunta_para_item"   # o funil é a primeira das demais
    r = indagador.indagar(circle.ctx, None)
    row = s.one("SELECT status, eixo FROM perguntas WHERE chave='funil:pergunta_para_item'")
    assert row and row["status"] in ("valida", "inconclusa") and r["candidatas"] >= 1
    assert indagador.resumo(s)["funil"]["etapas"]["pergunta_para_item"]["amostras"] == 3


def test_trabalho_em_voo_nao_dorme_cinco_minutos(circle):
    """Medido no Mac: 121 de 180 min eram descanso longo com um PR no CI. Em voo, o giro volta em segundos."""
    from circulo import loop as lp
    pol = circle.ctx.policy["loop"]
    slept = []
    circle.run_forever(max_ticks=2, sleep=slept.append)
    assert sum(slept) == pol["idle_interval_seconds"] and circle.store.get("ritmo")["modo"] == "ocioso"
    circle.store.x("INSERT INTO prs(number,titulo,status,created_at,updated_at) VALUES(7,'x','aberto',0,0)")
    circle.store.set("idle_last", {"revisar_prs": circle.store.tick + 5})     # PR aberto, mas revisar_prs ainda no espaçamento
    assert not circle.trabalho_pendente() and circle.em_voo()
    slept.clear()
    circle.run_forever(max_ticks=2, sleep=slept.append)
    assert sum(slept) == lp.ESPERA_EM_VOO and circle.store.get("ritmo")["modo"] == "em_voo"
    circle.store.x("DELETE FROM prs")
    circle.store.set("corpo", {"estado": "validando"})
    assert circle.em_voo()                                                    # código novo em prova: também é trabalho a caminho


def test_indagador_especialista_pergunta_por_assunto_com_evidencia(circle):
    """1.30: lição que reincide, trava do Vigia, pergunta em que o Jev duvida, PR fechado — cada assunto vira pergunta própria."""
    s = circle.store
    agora = time.time()
    s.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,primeira_tick,ultima_tick,created_at,updated_at) "
        "VALUES('a','developer:testes','trabalho','developer:testes: tests/test_x.py falhou','p','validada',4,1,1,2,?,?)", (agora, agora))
    s.x("INSERT INTO vigia(chave,titulo,evidencia,sugestao,gravidade,veredito,acao,conf,classificacao,status,primeira_em,ultima_em,vezes) "
        "VALUES('pr_preso','PR #9 preso há 70 min','{}','s',0.8,'trava','alertar',0.7,'{}','aberta',?,?,12)", (agora - 4200, agora))
    for i in range(24):
        s.x("INSERT INTO decisions(tick,question,value,confidence,source,created_at) VALUES(?,?,?,?,?,?)",
            (i, "worth_spending", "0.5", 0.1, "local" if i % 2 else "jev", agora - 60 * i))
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(77,1,'PR que caiu','b','fechado',?,?)", (agora - 600, agora - 60))
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(77,'s',0,'checks falhando: Testes','{}',?)", (agora - 120,))
    chaves = {c["chave"] for c in indagador.candidatas_especialista(s)}
    lic = s.one("SELECT id FROM licoes WHERE assinatura='a'")["id"]
    assert {f"licao:{lic}", "vigia:pr_preso", "jev:worth_spending", "pr_fechado:77"} <= chaves
    cands = indagador.candidatas(circle.ctx, None)
    assert cands and all(c["evidencia"]["base"] == "medido" for c in cands) and len(cands) <= indagador.MAX_CANDIDATAS
    r = indagador.indagar(circle.ctx, None)
    assert r["candidatas"] >= 4
    assert s.one("SELECT COUNT(*) n FROM perguntas WHERE chave LIKE 'licao:%' OR chave LIKE 'vigia:%' OR chave LIKE 'jev:%'")["n"] >= 2
    # a passagem seguinte não repete o que já foi julgado; sem candidata nova marca "vazio" e espera mais
    antes = s.one("SELECT COUNT(*) n FROM perguntas")["n"]
    for _ in range(3):
        indagador.indagar(circle.ctx, None)
    assert s.one("SELECT COUNT(*) n FROM perguntas")["n"] - antes <= indagador.MAX_CANDIDATAS * 2
    assert "loop" in (s.get("indagador_vazio") or {}) or s.one("SELECT COUNT(*) n FROM perguntas")["n"] > antes


def test_indagar_e_trabalho_real_roda_assim_que_precisa(circle):
    """1.30: indagar deixou o rodízio de manutenção; com vaga na fila de válidas, é escolhido já no giro."""
    from circulo import loop as lp
    assert "indagar" in lp.TRABALHO
    s = circle.store
    s.set("indagador", {"loop": time.time() - indagador.INTERVALO_FOME - 1})
    assert circle._tem_trabalho("indagar") and circle.trabalho_pendente()
    r = circle.tick()
    assert r.idle_task == "indagar"
    assert time.time() - float((s.get("indagador") or {}).get("loop", 0)) < 60


def test_jev_nao_com_confianca_media_nao_para_a_esteira(circle):
    """Mac, 19/10 à noite: 4 h sem evolução porque o Jev recusava o estudo (p≈0,3, confiança 0,3–0,4) com o Developer parado
    e dois itens esperando estudo. Confiança média alerta, não age: a regra decide; confiança alta continua barrando."""
    from circulo.decision import Decision
    s = circle.store
    agora = time.time()
    s.x("UPDATE roadmap SET status='feito'")
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES('Canário de falha','d','loop','pendente','pergunta do conselho: auditor',1,?,?)", (agora, agora))

    class JevRecusaFraco:
        source, ultimo_modelo = "jev", "jev-1.13.0"

        def __init__(self, conf):
            self.conf = conf

        def ask_many(self, state, qs):
            out = {}
            for qid, q in qs.items():
                if qid == "worth_spending":
                    out[qid] = Decision(qid, "noul", 0.3, self.conf, "jev")
                elif q.kind == "noul":
                    out[qid] = Decision(qid, "noul", 0.9, 0.8, "jev")
                elif q.kind == "choice":
                    out[qid] = Decision(qid, "choice", q.options()[0], 0.8, "jev")
                else:
                    out[qid] = Decision(qid, "score", 1.0, 0.8, "jev")
            return out, 10

    class Dev:
        def pick(self): return None
        def busy(self): return False
        def em_espera(self): return False
        def tem_trabalho(self): return False
        def alvo(self): return None
    circle.self_dev = Dev()
    assert circle.estudo.precisa() and circle._tem_trabalho("estudar_pedido")
    circle.ctx.dl.jev = JevRecusaFraco(0.38)
    circle.idle()
    assert s.one("SELECT estudo FROM roadmap WHERE titulo='Canário de falha'")["estudo"] is not None    # estudado: a regra autorizou
    assert circle.store.one("SELECT COUNT(*) n FROM decisions WHERE question='worth_spending' AND source='jev'")["n"] >= 1   # o não do Jev ficou registrado
    s.x("UPDATE roadmap SET estudo=NULL WHERE titulo='Canário de falha'")
    s.set("progresso", {"sem": 0, "recusas": {}})
    s.set("idle_last", {})
    circle.ctx.dl.jev = JevRecusaFraco(0.85)                                   # confiança alta no não: continua barrando
    circle.idle()
    assert s.one("SELECT estudo FROM roadmap WHERE titulo='Canário de falha'")["estudo"] is None


# ------------------------------------------------------------------ 1.32.1: o orçamento do dia ia todo em estudos com busca
def test_estudo_proporcional_a_evidencia_e_custo_medido(circle):
    from circulo import estudo as es
    s = circle.store
    agora = time.time()
    def item(titulo, origem, ev):
        return dict(s.one("SELECT * FROM roadmap WHERE id=?", (s.x(
            "INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,'pendente',?,?,?,?)",
            (titulo, "d", origem, ev, 500 + len(titulo), agora, agora)),)))
    vig = item("Vigia: pergunta parada", "loop", "Vigia (medido): pergunta_valida_parada")
    jar = item("Jardineiro: podar noqa", "loop", "medido pelo jardineiro")
    con = item("Planejador: vetar item", "loop", "pergunta do conselho #26: operador")
    ped = item("Pedido seu", "pedido_cassio", "pedido pelo painel")
    assert [es.modo_do_estudo(x) for x in (vig, jar, con, ped)] == ["dispensado", "dispensado", "leve", "completo"]
    e = circle.estudo
    assert e.custo_estimado(vig) == 0 and e.custo_estimado(con) == es.MODOS["leve"]["est"] and e.custo_estimado(ped) == es.MODOS["completo"]["est"]
    for t in (31000, 35000, 29000, 40000):                                   # custo medido substitui a estimativa
        s.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,ok,entrada,created_at) VALUES(1,'estudo','m','jev',?,1,'[completo] x',?)", (t, agora))
    assert e.custo_estimado(ped) == 35000
    # dispensado: estudo gravado sem gastar nada
    r = e.run(vig)
    assert r["veredito"] == "adotar" and r["modo"] == "dispensado"
    assert s.one("SELECT estudo FROM roadmap WHERE id=?", (vig["id"],))["estudo"] is not None
    assert s.one("SELECT COUNT(*) n FROM llm_calls WHERE papel='estudo' AND created_at>?", (agora + 0.5,))["n"] == 0


def test_vigia_avisa_quando_o_orcamento_nao_paga_o_proximo_estudo(circle):
    from datetime import datetime
    from circulo import vigia
    from circulo.budget import TZ
    s = circle.store
    s.set("orcamento_modo", {"modo": "limite"})     # estes testes provam o corte: modo com limite
    agora = time.time()
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES('Pedido seu','d','pedido_cassio','pendente','pedido',1,?,?)", (agora, agora))
    s.set("orcamento_limite", {"limite": 400000})
    hoje = datetime.fromtimestamp(agora, TZ).date().isoformat()
    s.x("INSERT INTO budget(day,tokens,jev_calls,llm_calls) VALUES(?,392000,0,0) ON CONFLICT(day) DO UPDATE SET tokens=392000", (hoje,))
    a = {x["chave"]: x for x in vigia.sondar(s, agora)}
    assert "orcamento_curto" in a and a["orcamento_curto"]["evidencia"]["restam"] == 8000 and a["orcamento_curto"]["evidencia"]["base"] == "medido"
    s.x("UPDATE roadmap SET evidencia='Vigia (medido): x', origem='loop' WHERE titulo='Pedido seu'")
    assert "orcamento_curto" not in {x["chave"] for x in vigia.sondar(s, agora)}   # item dispensado não gasta: sem trava

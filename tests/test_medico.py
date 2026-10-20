"""O Médico do loop (circulo/medico.py): padrão medido → diagnóstico único → o Jev decide → escada de resposta.
Os três casos são os do Mac em 20/10: treino do aluno quebrando 8× na meta, o Redator abrindo PR atrás de PR, e o
Desenvolvedor mudo (OAuth expirado)."""
import json
import time

from circulo import aprovacoes, medico
from circulo.medico import Medico


def _erro_meta(circle, n=8):
    inc = circle.incidents.record("meta", json.JSONDecodeError("Unterminated string", "x", 0))
    for _ in range(n - 1):
        circle.incidents.record("meta", json.JSONDecodeError("Unterminated string", "x", 0))
    return inc


def _docs_em_cadeia(s, n=4):
    agora = time.time()
    for i in range(n):
        s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(?,2,'docs','circulo/docs-17925%d','mergeado',?,?)" % (20000 + i), (34 + i, agora - 600 * (n - i), agora))


def _dev_mudo(s, n=5):
    agora = time.time()
    for i in range(n):
        s.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,duracao_ms,ok,erro,created_at) VALUES(1,'developer','claude','fixo',0,26,0,'Failed to authenticate: OAuth session expired',?)", (agora - 90 * i,))


def test_evento_isolado_nao_e_diagnostico_e_padrao_vira_um_so(circle):
    s = circle.store
    m = Medico(circle.ctx)
    circle.incidents.record("meta", ValueError("uma vez"))
    assert medico.sondar(s) == []                                             # 1 erro não é padrão
    _erro_meta(circle, 8)
    achados = medico.sondar(s)
    assert len(achados) == 1 and achados[0]["tipo"] == "erro_repetido" and achados[0]["evidencia"]["vezes_1h"] == 8
    r1 = m.rodar()
    r2 = m.rodar()
    assert r1["novos"] == 1 and r2["novos"] == 0                                # a segunda passagem só conta
    d = s.one("SELECT * FROM diagnosticos")
    assert d["vezes"] == 2 and s.one("SELECT COUNT(*) n FROM diagnosticos")["n"] == 1   # impressão digital: um diagnóstico, contador


def test_erro_repetido_do_codigo_vira_item_urgente_na_frente_da_fila(circle):
    s = circle.store
    agora = time.time()
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES('Item normal','d','loop','pendente','x',5,?,?)", (agora, agora))
    _erro_meta(circle, 8)
    m = Medico(circle.ctx)
    m.rodar()
    d = dict(s.one("SELECT * FROM diagnosticos"))
    v = json.loads(d["veredito"])
    assert d["acao"] in ("corrigir", "conter", "observar", "escalar") and v["dono"] in medico.DONOS
    if d["acao"] == "corrigir":                                                # com o decisor local a regra pode variar; o caminho de corrigir é este
        item = s.one("SELECT * FROM roadmap WHERE id=?", (d["item_id"],))
        assert item["origem"] == "erro" and item["titulo"].startswith("Urgente:") and item["evidencia"].startswith("Médico (medido)")
        assert item["ordem"] < 5                                               # na frente da fila
        assert circle.self_dev is None or circle.self_dev.pick()["id"] == item["id"]
    assert s.one("SELECT COUNT(*) n FROM medico_acoes")["n"] == 1


def test_corrigir_forcado_abre_item_e_so_um_em_voo(circle):
    s = circle.store
    m = Medico(circle.ctx)
    a = {"chave": "erro:meta:x", "tipo": "erro_repetido", "titulo": "JSONDecodeError em meta repetiu 8×", "evidencia": {"etapa": "meta", "base": "medido"},
         "veredito": {"bloqueia": True, "dono": "codigo_do_loop", "remedio": 2, "fonte": "jev"}}
    assert medico.decidir(a) == "corrigir"
    did = s.x("INSERT INTO diagnosticos(chave,tipo,titulo,evidencia,status,primeira_em,ultima_em) VALUES('erro:meta:x','erro_repetido','t','{}','observando',1,1)")
    assert m.corrigir(a, did, time.time()).startswith("item urgente")
    s.x("UPDATE diagnosticos SET status='corrigindo' WHERE id=?", (did,))
    did2 = s.x("INSERT INTO diagnosticos(chave,tipo,titulo,evidencia,status,primeira_em,ultima_em) VALUES('erro:meta:y','erro_repetido','t','{}','observando',1,1)")
    assert "em voo" in m.corrigir({**a, "chave": "erro:meta:y"}, did2, time.time())   # 1 item urgente por vez


def test_repeticao_sem_progresso_e_contida_pausando_a_tarefa(circle):
    s = circle.store
    _docs_em_cadeia(s, 4)
    achados = medico.sondar(s)
    assert any(a["tipo"] == "repeticao_sem_progresso" and a["evidencia"]["tarefa"] == "documentar" for a in achados)
    m = Medico(circle.ctx)
    a = next(a for a in achados if a["tipo"] == "repeticao_sem_progresso")
    a["veredito"] = {"bloqueia": True, "dono": "codigo_do_loop", "remedio": 1, "fonte": "jev"}
    assert medico.decidir(a) == "conter"
    did = s.x("INSERT INTO diagnosticos(chave,tipo,titulo,evidencia,status,primeira_em,ultima_em) VALUES(?,?,?,?,'observando',1,1)", (a["chave"], a["tipo"], a["titulo"], "{}"))
    assert "pausada" in m.conter(a, did, time.time())
    assert medico.tarefa_pausada(s, "documentar") and not medico.tarefa_pausada(s, "indagar")
    assert "documentar" not in circle.idle_tasks() if hasattr(circle, "idle_tasks") else True


def test_desenvolvedor_mudo_vira_escalada_e_precisa_de_voce(circle):
    s = circle.store
    _dev_mudo(s, 5)
    [a] = [x for x in medico.sondar(s) if x["tipo"] == "agente_mudo"]
    assert a["evidencia"]["vezes_1h"] == 5 and "OAuth" in a["evidencia"]["erro"]
    a["veredito"] = {"bloqueia": True, "dono": "humano", "remedio": 1, "fonte": "jev"}
    assert medico.decidir(a) == "escalar"
    m = Medico(circle.ctx)
    did = s.x("INSERT INTO diagnosticos(chave,tipo,titulo,evidencia,status,primeira_em,ultima_em) VALUES(?,?,?,?,'observando',1,1)", (a["chave"], a["tipo"], a["titulo"], "{}"))
    m.escalar(a, did, time.time())
    pend = aprovacoes.pendentes(s, diagnostico=False)
    assert pend[0]["tipo"] == "medico" and "mudo" in pend[0]["titulo"] and pend[0]["prioridade"] == 0


def test_regras_contra_ruido_duvida_custo_proprio_e_contexto_conhecido(circle):
    s = circle.store
    base = {"chave": "x", "tipo": "erro_repetido", "titulo": "t", "evidencia": {}}
    assert medico.decidir({**base, "veredito": {"bloqueia": True, "dono": "codigo_do_loop", "remedio": 2, "fonte": "duvida"}}) == "observar"
    assert medico.decidir({**base, "veredito": {"bloqueia": True, "dono": "custo", "remedio": 2, "fonte": "jev"}}) == "observar"
    assert medico.decidir({**base, "veredito": {"bloqueia": False, "dono": "codigo_do_loop", "remedio": 2, "fonte": "jev"}}) == "observar"
    assert medico.decidir({**base, "proprio": True, "veredito": {"bloqueia": True, "dono": "codigo_do_loop", "remedio": 2, "fonte": "jev"}}) == "escalar"
    _dev_mudo(s, 5)
    _docs_em_cadeia(s, 4)
    s.set("self_dev_espera", {"ate": time.time() + 600, "motivo": "deslogado", "precisa_de_voce": True})
    assert medico.contexto_conhecido(s, time.time()) == "desenvolvedor_parado_por_voce"
    assert all(a["tipo"] == "erro_repetido" for a in medico.sondar(s))        # fila parada com causa conhecida: silêncio


def test_orcamento_de_acoes_e_fechamento_pelo_sintoma(circle):
    s = circle.store
    m = Medico(circle.ctx)
    agora = time.time()
    for _ in range(medico.ACOES_POR_DIA):
        s.x("INSERT INTO medico_acoes(diagnostico_id,acao,detalhe,created_at) VALUES(0,'conter','x',?)", (agora,))
    assert m._acoes_hoje(agora) == medico.ACOES_POR_DIA
    did = s.x("INSERT INTO diagnosticos(chave,tipo,titulo,evidencia,status,acao,primeira_em,ultima_em) VALUES('erro:meta:z','erro_repetido','t','{}','contido','conter',?,?)", (agora - 7200, agora - 3600))
    s.set("medico_pausas", {"documentar": {"ate": agora + 3600, "diagnostico": did}})
    m.rodar(agora)                                                            # sem ocorrência há 1 h: fecha e libera a pausa
    assert s.one("SELECT status FROM diagnosticos WHERE id=?", (did,))["status"] == "fechado"
    assert not medico.tarefa_pausada(s, "documentar")
    res = medico.resumo(s)
    assert res["fechados"] == 1 and res["acoes_24h"] == medico.ACOES_POR_DIA and res["orcamento_dia"] == medico.ACOES_POR_DIA


def test_vigia_roda_o_medico_e_painel_expoe(circle, painel):  # noqa: F811
    import urllib.request
    r = circle.vigia.rodar()
    assert "medico" in r and r["medico"]["achados"] == 0
    j = json.loads(urllib.request.urlopen(painel + "/api/medico", timeout=5).read())
    assert j["abertos"] == [] and j["orcamento_dia"] == medico.ACOES_POR_DIA
    assert "Médico do loop" in urllib.request.urlopen(painel + "/loop", timeout=5).read().decode()


from test_painel import painel  # noqa: E402,F401 — fixture do servidor do painel

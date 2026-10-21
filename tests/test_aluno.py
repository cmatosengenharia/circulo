"""O aluno do Jev (circulo/aluno.py): aprende com as decisões do Jev, palpita em sombra e só é 'pronto' com prova."""
import json
import random
import time

from circulo import aluno
from circulo.state import Store


def _decisao(s, q, estado, valor, conf=0.95, fonte="jev", em=None):
    s.x("INSERT INTO decisions(tick,question,value,confidence,source,created_at,estado) VALUES(1,?,?,?,?,?,?)",
        (q, json.dumps(valor), conf, fonte, em or time.time(), json.dumps(estado)))


def _semear(s, n=400, seed=7):
    """Um Jev sintético com regra escondida: worth_spending = sim quando o valor é alto e o orçamento sobra;
    categoria = pelo texto. O aluno não vê a regra, só as respostas."""
    rnd = random.Random(seed)
    t0 = time.time() - 3600
    for i in range(n):
        v, b, tok = rnd.random(), rnd.random(), rnd.choice([500, 3000, 20000, 60000])
        estado = {"action": rnd.choice(["idle_evolution", "developer_feature", "estudo_pedido"]), "value_signal": round(v, 2),
                  "budget_left_ratio": round(b, 2), "est_tokens": tok}
        sim = v > 0.5 and b > 0.3 and not (tok >= 60000 and b < 0.6)
        _decisao(s, f"worth_spending_{i % 3}", estado, "sim" if sim else "nao", em=t0 + i)
        texto = rnd.choice(["ifood almoço rua", "uber corrida centro", "farmácia remédio", "mercado compras do mês"])
        cat = {"ifoo": "alimentação", "uber": "transporte", "farm": "saúde", "merc": "mercado"}[texto[:4]]
        _decisao(s, "category", {"texto": texto, "valor": rnd.choice([12.5, 38.9, 120.0])}, cat, em=t0 + i + 0.5)
    for i in range(30):                                                     # baixa confiança e regra: fora do treino
        _decisao(s, "worth_spending_1", {"action": "x", "value_signal": 0.5}, "nao", conf=0.4, em=t0 + 5000 + i)
        _decisao(s, "worth_spending_1", {"action": "x", "value_signal": 0.5}, "sim", fonte="local", em=t0 + 5000 + i)


def test_features_e_rotulos_sao_estaveis():
    f = aluno.features({"action": "idle_evolution", "value_signal": 0.7, "est_tokens": 30000, "texto": "ifood almoço", "ok": True, "lista": ["a", 2]})
    assert f == aluno.features({"action": "idle_evolution", "value_signal": 0.7, "est_tokens": 30000, "texto": "ifood almoço", "ok": True, "lista": ["a", 2]})
    assert len(f) >= 8 and all(0 <= k < aluno.DIM for k in f)
    assert aluno.rotulo("sim") == "sim" and aluno.rotulo(0.66) == "0.7" and aluno.rotulo(True) == "true"
    assert aluno.pergunta("indaga_pert_5") == "indaga_pert" and aluno.pergunta("worth_spending") == "worth_spending"


def test_aluno_aprende_a_regra_escondida_do_jev_e_mede_no_holdout():
    s = Store(":memory:")
    _semear(s)
    rel = aluno.treinar(s)
    m = rel["modelos"]
    assert set(m) == {"worth_spending", "category"}                        # nomes normalizados; baixa confiança e regra ficaram de fora
    assert m["worth_spending"]["n"] == 400 and m["category"]["n"] == 400
    assert m["category"]["acuracia"] >= 0.95 and m["category"]["status"] == "pronto_para_sombra"
    assert m["worth_spending"]["acuracia"] >= 0.85 and m["worth_spending"]["acuracia"] > m["worth_spending"]["baseline"]
    assert rel["resumo"]["perguntas"] == 2 and s.get(aluno.KV)["decisoes_vistas"] == rel["decisoes_vistas"]
    # palpite coerente com a regra escondida
    p = aluno.palpite(s, "category", {"texto": "ifood jantar", "valor": 50.0})
    assert p and p[0] == "alimentação" and p[1] > 0.6
    assert aluno.palpite(s, "pergunta_que_nao_existe", {}) is None


def test_poucos_exemplos_nao_viram_modelo_e_retreino_so_quando_precisa():
    s = Store(":memory:")
    for _ in range(20):
        _decisao(s, "pick_model", {"role": "researcher"}, "haiku")
    rel = aluno.treinar(s, agora=1000.0)
    assert rel["modelos"]["pick_model"]["status"] == "poucos_exemplos" and aluno.palpite(s, "pick_model", {}) is None
    assert aluno.treinar_se_preciso(s, agora=1000.0 + 60) is None            # acabou de treinar, nada novo
    for _ in range(aluno.NOVOS_PARA_TREINAR):
        _decisao(s, "pick_model", {"role": "researcher"}, "haiku")
    assert aluno.treinar_se_preciso(s, agora=1000.0 + 120) is not None       # chegaram decisões novas: treina
    assert aluno.treinar_se_preciso(s, agora=1000.0 + 120 + aluno.TREINAR_A_CADA + 1) is not None   # ou passou o tempo


def test_em_sombra_o_aluno_palpita_sem_decidir_e_pronto_exige_prova(circle):
    s = circle.store
    _semear(s)
    aluno.treinar(s)
    dl = circle.ctx.dl
    antes = s.one("SELECT COUNT(*) n FROM decisions")["n"]
    g = dl.worth_spending("idle_evolution", {"est_tokens": 500, "value_signal": 0.9})
    assert g.allowed                                                          # a decisão real não mudou de dono
    d = s.one("SELECT source, estado FROM decisions WHERE question='worth_spending' ORDER BY id DESC LIMIT 1")
    assert d["estado"] and json.loads(d["estado"])["action"] == "idle_evolution"   # o estado agora fica gravado
    assert s.one("SELECT COUNT(*) n FROM decisions")["n"] > antes
    r = aluno.observar(s, "category", {"texto": "uber corrida", "valor": 20.0}, "transporte")
    assert r and r["previsto"] == "transporte" and r["concorda"] is True
    c = aluno.concordancia(s)["category"]
    assert c["n"] >= 1 and c["concorda"] == 1.0
    assert not aluno.pronto_para_decidir(s, "category")                     # 1 palpite não prova nada
    for _ in range(aluno.MIN_SOMBRA):
        aluno.observar(s, "category", {"texto": "farmácia remédio", "valor": 20.0}, "saúde")
    assert aluno.pronto_para_decidir(s, "category")
    res = aluno.resumo(s)
    assert res["decide"] is False and any(p["pergunta"] == "category" and p["pronta_para_decidir"] for p in res["perguntas"])


from test_painel import painel  # noqa: E402,F401 — fixture do servidor do painel


def test_meta_learner_treina_o_aluno_e_painel_expoe(circle, painel):  # noqa: F811
    import urllib.request
    s = circle.store
    _semear(s, n=150)
    log = circle.meta.step()
    assert any("aluno do Jev treinado" in linha for linha in log)
    j = json.loads(urllib.request.urlopen(painel + "/api/aluno", timeout=5).read())
    assert j["resumo"]["perguntas"] >= 2 and j["criterios"]["concordancia_min"] == aluno.CONCORDANCIA_MIN
    assert "Aluno do Jev" in urllib.request.urlopen(painel + "/loop", timeout=5).read().decode()


def test_estado_compacto_sempre_fecha_e_registro_cortado_nao_derruba_o_treino():
    """No Mac: estado JSON cortado em 1.500 caracteres → JSONDecodeError no treino, 8 giros seguidos com erro na meta."""
    grande = {"tarefa": "x" * 5000, "lista": list(range(100)), "d": {str(i): "y" * 300 for i in range(40)}, "n": 3}
    s = aluno.compactar(grande)
    assert len(s) <= 1500 and json.loads(s)["n"] == 3
    st = Store(":memory:")
    st.x("INSERT INTO decisions(tick,question,value,confidence,source,created_at,estado) VALUES(1,'q','\"a\"',0.9,'jev',1,'{\"tarefa\": \"cortado no mei')")
    for i in range(3):
        _decisao(st, "q", {"k": i}, "a")
    ex = aluno.exemplos_de(st)
    assert len(ex["q"]) == 3                                                    # o registro quebrado foi ignorado, o resto treina


def test_licao_43_estado_com_uma_chave_aninhada_grande_ainda_vira_json_valido():
    """Lição #43: JSONDecodeError na meta (treino do aluno). Com uma única chave grande o `compactar` cortava a string
    do JSON no limite e gravava estado que não fecha; qualquer estado precisa sair JSON válido dentro do limite."""
    rnd = random.Random(43)
    casos = [{"d": {str(i): ["y" * 80] * 8 for i in range(12)}},
             {"lista": [{"a": "z" * 80, "b": list(range(8))}] * 8}]
    for _ in range(200):
        casos.append({f"k{rnd.randrange(60)}": rnd.choice(["x" * rnd.randrange(400), list(range(rnd.randrange(20))),
                                                            {str(j): "w" * 90 for j in range(rnd.randrange(15))}, 3.5])
                      for _ in range(rnd.randrange(1, 4))})
    for estado in casos:
        s = aluno.compactar(estado)
        assert len(s) <= 1500
        assert isinstance(json.loads(s), dict)

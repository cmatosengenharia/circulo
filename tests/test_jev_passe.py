"""1.47.0 — o passe do Jev lab nas quatro perguntas em que o Jev mais duvidava (20/10: worth_spending 0,49, should_evolve
0,39, dado_na_evidencia 0,31, indaga_pert 0,38): estado enxuto com features medidas, critérios com número, cache de
estado idêntico nas perguntas de rotina (vigia_trava 353×/dia), e a medição antes × depois no painel."""
import json
import time

from circulo import jev_lab
from circulo.decision import SN, Decision, Question


class JevContador:
    """Um Jev que conta chamadas e responde sempre igual: prova que o cache poupa a chamada."""
    source = "jev"
    model = "jev-1.13.0"

    def __init__(self):
        self.chamadas = []

    def ask_many(self, state, questions):
        self.chamadas.append(sorted(questions))
        return {qid: Decision(qid, q.kind, 0.9 if q.kind == "noul" else (q.options()[0] if q.kind == "choice" else 1.0), 0.8, "jev") for qid, q in questions.items()}, 10


def test_estado_identico_nas_perguntas_de_rotina_vem_do_cache(circle):
    circle.ctx.dl.jev = jev = JevContador()
    q = Question("noul", "A trava `achados.0.titulo` é real?", SN("sim", "não"))
    st = {"achados": [{"titulo": "Item #85 parado há 45 min", "gravidade": 0.7}]}
    d1 = circle.ctx.dl.ask_many(st, {"vigia_trava_0": q})["vigia_trava_0"]
    d2 = circle.ctx.dl.ask_many(st, {"vigia_trava_0": q})["vigia_trava_0"]
    assert len(jev.chamadas) == 1 and d1.value == d2.value and d2.probabilities.get("cache") is True and d2.source == "jev"
    circle.ctx.dl.ask_many({"achados": [{"titulo": "outra", "gravidade": 0.5}]}, {"vigia_trava_0": q})
    assert len(jev.chamadas) == 2                                               # estado diferente: pergunta de novo
    circle.ctx.dl.ask_many(st, {"worth_spending": Question("noul", "vale?", SN("s", "n"))})
    assert len(jev.chamadas) == 3                                               # worth_spending não é cacheável
    r = jev_lab.resumo(circle.store)
    assert r["cache_24h"] >= 1


def test_worth_spending_recebe_features_medidas_e_criterio_com_numero(circle):
    s = circle.store
    visto = {}
    original = circle.ctx.dl.ask

    def espiao(name, q, state):
        visto[name] = (q, dict(state))
        return original(name, q, state)
    circle.ctx.dl.ask = espiao
    circle.ctx.dl.worth_spending("estudar_pedido", {"est_tokens": 30000, "value_signal": 0.85, "item_esperando_estudo": "x", "fila_do_developer": 0})
    q, st = visto["worth_spending"]
    assert set(st) >= {"action", "est_tokens", "value_signal", "custo_pct_dia", "orcamento", "desbloqueia_fila", "fila_do_developer", "rodou_hoje_sem_render", "rodou_hoje"}
    assert st["desbloqueia_fila"] is True and st["orcamento"].startswith("sem limite") and "budget_left_ratio" not in st
    assert "≥ 0.7" in q.criteria["true"] and "rodou_hoje_sem_render" in q.criteria["false"]
    circle.ctx.dl.should_evolve("domain", {"occurrences": 4, "consistency": 1.0, "kind": "self_fix", "description": "x"})
    q2, st2 = visto["should_evolve"]
    assert st2["revertida_antes"] == 0 and st2["aplicada_hoje"] == 0 and st2["occurrences"] == 4 and "≥ 3" in q2.criteria["true"]
    s.x("INSERT INTO proposals(level,kind,fingerprint,description,patch,evidence,status,notes,created_at,updated_at,rollbacks) VALUES(1,'self_fix','f','x','{}','{}','rolled_back','',?,?,1)", (time.time(), time.time()))
    circle.ctx.dl.should_evolve("domain", {"occurrences": 4, "consistency": 1.0, "kind": "self_fix", "description": "x"})
    assert visto["should_evolve"][1]["revertida_antes"] >= 1


def test_dado_na_evidencia_e_conferido_mecanicamente_antes_do_jev():
    ev = json.dumps({"licao": 42, "ocorrencias": 18, "tokens_24h": 2398871})
    st = jev_lab.estado_dado("A lição #42 teve 18 ocorrências e 7 reincidências", ev)
    assert st["numeros_do_dado"] == ["42", "18", "7"] and st["numeros_na_evidencia"] == ["42", "18"] and st["fracao_encontrada"] == 0.67
    assert len(st["trechos_da_evidencia"]) == 2 and st["evidencia_tem_numeros"]
    st2 = jev_lab.estado_dado("o estudo falha mais à noite", ev)
    assert st2["fracao_encontrada"] is None and st2["numeros_do_dado"] == []


def test_po_manda_ao_jev_se_a_pergunta_ja_foi_feita_e_se_a_base_e_medida(circle, monkeypatch):
    from circulo import indagador
    from circulo import memoria as mod
    s, agora = circle.store, time.time()
    s.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,evidencia,created_at,updated_at) VALUES('x','usuario','Como usuário, qual componente do painel devo melhorar para facilitar a visualização das métricas?','virou_item','loop','{}',?,?)", (agora - 3600, agora - 1800))
    mod.Memoria(s).reindexar(forcar=True)
    visto = {}
    original = circle.ctx.dl.ask_many

    def espiao(state, qs):
        visto.update({"state": state, "qs": qs})
        return original(state, qs)
    monkeypatch.setattr(circle.ctx.dl, "ask_many", espiao)
    cands = [{"chave": "a", "texto": "Como usuário, qual componente do painel devo melhorar para facilitar a visualização das métricas?", "persona": "usuario", "evidencia": {"falhas_painel_24h": 2, "base": "medido"}},
             {"chave": "b", "texto": "Qual é o jeito mais barato de obter o mesmo resultado na etapa que mais gasta (estudo)?", "persona": "economista", "evidencia": {"tokens": 1, "base": "chutado"}}]
    indagador.classificar(circle.ctx, cands, {"missao": "loop", "tipo": "circulo", "pedido": "o próprio loop", "tokens_24h": 10})
    c0, c1 = visto["state"]["candidatas"]
    assert c0["ja_perguntada_7d"] >= 1 and c0["base_medida"] is True
    assert c1["ja_perguntada_7d"] == 0 and c1["base_medida"] is False
    assert "tokens_24h" not in visto["state"] and "ja_perguntada_7d" in visto["qs"]["indaga_pert_0"].criteria["false"]


def test_painel_mede_antes_e_depois_do_passe(circle):
    s = circle.store
    jev_lab.marcar_passe(s, jev_lab.PASSE_VERSAO)
    em = float(s.get("jev_passe")["em"])
    for conf, t in ((0.3, em - 100), (0.5, em - 50), (0.9, em + 10)):
        s.x("INSERT INTO decisions(tick,question,value,confidence,source,created_at) VALUES(1,'worth_spending','0.8',?,'jev',?)", (conf, t))
    r = jev_lab.resumo(s)
    w = next(p for p in r["passe"]["perguntas"] if p["pergunta"] == "worth_spending")
    assert w["antes_n"] == 2 and w["antes_conf"] == 0.4 and w["depois_n"] == 1 and w["depois_conf"] == 0.9
    jev_lab.marcar_passe(s, jev_lab.PASSE_VERSAO)
    assert float(s.get("jev_passe")["em"]) == em                                 # uma vez por versão

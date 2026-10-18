from circulo import atividade
from circulo.painel import estado
from circulo.projects import kit_project_id


def test_painel_mostra_giros_linha_do_tempo_e_ritmo(circle):
    circle.submit("38,90 ifood almoço")
    for _ in range(4):
        circle.tick()
    gs = atividade.giros(circle.store)
    assert gs and all(g["etapas"] and g["dur"] >= 0 for g in gs)
    assert any(e["etapa"] == "idle" and e["detalhe"] for g in gs for e in g["etapas"])   # o que a manutenção fez
    fin = kit_project_id(circle.store, "financas")
    assert atividade.giros(circle.store, fin)                                            # giros da missão
    r = atividade.ritmo(circle.store)
    assert sum(r["serie"]) > 0 and r["fontes"]
    zero = kit_project_id(circle.store, "circulo")
    e = estado(circle.store, zero)
    assert {"linha_do_tempo", "giros", "ritmo", "llm", "trabalho_agora"} <= set(e)
    assert e["trabalho_agora"]["nome"]


def test_linha_do_tempo_junta_evolucoes(circle):
    import time
    circle.store.x("INSERT INTO incidents(fingerprint,stage,kind,message,count,first_seen,last_seen,first_tick,last_tick,status) "
                   "VALUES('f','idle','RuntimeError','boom',2,?,?,1,2,'aberto')", (time.time(), time.time()))
    tl = atividade.linha_do_tempo(circle.store, zero=True)
    assert tl[0]["tipo"] == "erro" and "boom" in tl[0]["detalhe"]

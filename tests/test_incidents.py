from circulo.projects import cards, kit_project_id, roteiro


def boom(*a, **k):
    raise RuntimeError("falhou no giro 12")


def test_decisoes_fora_de_pedido_sao_do_proprio_circulo(circle):
    circle.tick()   # sem pedido: evolução natural
    circ = kit_project_id(circle.store, "circulo")
    rows = circle.store.q("SELECT DISTINCT project_id FROM decisions")
    assert {r["project_id"] for r in rows} == {circ}


def test_erro_vira_incidente_agrupado(circle):
    circle.shadow.evaluate = boom
    for _ in range(2):
        r = circle.tick()
        assert r.errors
    inc = circle.store.q("SELECT * FROM incidents")
    assert len(inc) == 1 and inc[0]["count"] == 2 and inc[0]["stage"] == "shadow"   # números diferentes, mesma impressão digital


def test_erro_recorrente_vira_item_do_roteiro(circle):
    circle.meta.step = boom
    circle.tick()
    circle.tick()
    item = circle.store.one("SELECT * FROM roadmap WHERE origem='erro'")
    assert item and "RuntimeError em meta" in item["titulo"] and item["status"] == "pendente"
    assert roteiro(circle.store)[0]["origem"] in ("erro", "pedido_cassio")


def test_autocorrecao_isola_etapa_com_backoff(circle):
    calls = []

    def flaky():
        calls.append(1)
        raise RuntimeError("quebrado")

    circle.shadow.evaluate = flaky
    for _ in range(3):
        circle.tick()
    q = circle.store.get("quarentena")["shadow"]
    assert q["nivel"] == 1 and q["ate_tick"] == circle.store.tick + 10
    n = len(calls)
    for _ in range(5):
        r = circle.tick()
        assert not r.errors                               # o resto do círculo segue
    assert len(calls) == n                                # etapa isolada não rodou
    assert circle.store.one("SELECT status FROM incidents")["status"] == "isolado"
    assert circle.store.one("SELECT 1 FROM alerts WHERE kind='saude' AND message LIKE 'Autocorreção%'")
    for _ in range(6):                                    # quarentena acaba; volta a falhar → nível 2 (dobra)
        circle.tick()
    assert circle.store.get("quarentena")["shadow"]["nivel"] == 2


def test_saude_nunca_entra_em_quarentena(circle):
    circle.health.check = boom
    for _ in range(6):
        circle.tick()
    assert "health" not in (circle.store.get("quarentena") or {})


def test_incidente_que_parou_de_acontecer_e_resolvido(circle):
    circle.meta.step = boom
    circle.tick()
    del circle.meta.step                                  # "corrigido"
    circle.store.set("tick", circle.store.tick + 300)
    circle.tick()
    assert circle.store.one("SELECT status FROM incidents")["status"] == "resolvido"


def test_card_do_circulo_mostra_roteiro_e_erros(circle):
    circle.meta.step = boom
    circle.tick()
    c = next(c for c in cards(circle.store) if c["kit"] == "circulo")
    assert c["roteiro"]["total"] >= 15 and c["roteiro"]["feito"] >= 8 and c["erros"]["abertos"] == 1


def test_pedido_que_falha_registra_incidente_no_projeto(circle):
    circle.categorizer.categorize = boom
    circle.submit("38 ifood")
    circle.tick()
    inc = circle.store.one("SELECT * FROM incidents")
    assert inc["stage"] == "pedido:mensagem" and inc["project_id"] == kit_project_id(circle.store, "financas")


def test_tarefa_ociosa_respeita_quarentena_do_componente(circle):
    circle.store.set("quarentena", {"meta": {"ate_tick": 10**6, "nivel": 1}})
    tasks = {circle.tick().idle_task for _ in range(12)}
    assert "revisar_baixa_confianca" not in tasks

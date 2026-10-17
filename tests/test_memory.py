from circulo.memory import Memory


def mem(circle):
    return Memory(circle.store, circle.ctx.dl)


def test_bm25_com_rerank_do_jev(circle):
    m = mem(circle)
    m.add("achado", "Landing pages com formulário de até 3 campos convertem mais leads", tipo="landing_page", source="https://x", trust="nao_confiavel")
    m.add("achado", "Receita de pão de queijo mineiro", tipo="conteudo")
    m.add("achado", "Prova social perto do CTA aumenta a conversão de landing pages", tipo="landing_page")
    for i in range(10):
        m.add("achado", f"nota irrelevante número {i} sobre outra coisa", tipo="landing_page")
    r = m.search("como aumentar conversão de leads na landing page", tipo="landing_page", k=2)
    assert len(r) == 2 and all("landing" in x["text"].lower() for x in r)


def test_duplicata_nao_entra_duas_vezes(circle):
    m = mem(circle)
    assert m.add("licao", "A", tipo="plano") == m.add("licao", "A", tipo="plano")


def test_licao_nasce_em_quarentena_e_e_confirmada_pelo_ganho(circle):
    m = mem(circle)
    lid = m.add("licao", "Começar pelo CTA", tipo="landing_page", status="quarentena")
    assert [x["id"] for x in m.playbook("landing_page")] == [lid]          # entra como exploração
    m.lesson_outcome([lid], gain=0.05, min_gain=0.02)
    assert circle.store.one("SELECT status FROM memory WHERE id=?", (lid,))["status"] == "ativa"


def test_licao_inutil_e_aposentada_nao_apagada(circle):
    m = mem(circle)
    lid = m.add("licao", "Usar fonte serifada", tipo="landing_page", status="quarentena")
    for _ in range(3):
        m.lesson_outcome([lid], gain=0.0, min_gain=0.02)
    row = circle.store.one("SELECT status FROM memory WHERE id=?", (lid,))
    assert row["status"] == "aposentada"
    assert m.playbook("landing_page") == []

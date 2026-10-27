"""Resumo semanal para a equipe: o changelog (produto/infra com o pedido de origem e a fração contra a meta), os PRs
sem pedido listados à parte e o uso medido do digest. Reaproveita `changelog` e `digest_semanal`, não refaz."""
from circulo import norte, resumo_semanal
from circulo.cli import main
from conftest import NOON

PRS = [
    {"number": 21, "titulo": "Exportar CSV", "produto": True, "pedido": "pedido: exportar lançamentos"},
    {"number": 20, "titulo": "Painel da equipe ao vivo", "produto": True, "pedido": None},
    {"number": 24, "titulo": "Filtro por assunto", "produto": True, "pedido": "pergunta #311 (pm): o que falta?"},
    {"number": 22, "titulo": "Conserto do vigia", "produto": False, "pedido": "lição #15"},
    {"number": 23, "titulo": "Cache da LLM", "produto": False, "pedido": None},
]


def _secao(texto, titulo):
    return next(b for b in texto.split("\n## ") if b.startswith(titulo))


def test_todo_pr_de_produto_aparece_com_o_pedido_de_origem():
    t = resumo_semanal.texto(PRS, leituras=0)
    produto = _secao(t, "Produto (3)")
    for p in PRS:
        if p["produto"]:
            assert f"- #{p['number']} {p['titulo']} · {p['pedido'] or 'sem pedido'}" in produto
    assert "3 de 5 PRs foram produto (fração 0.60, meta 0.5)" in t


def test_prs_sem_pedido_ficam_listados_a_parte():
    t = resumo_semanal.texto(PRS, leituras=0)
    assert [linha for linha in _secao(t, "Sem pedido (2)").splitlines() if linha.startswith("- ")] == [
        "- #20 Painel da equipe ao vivo (produto)", "- #23 Cache da LLM (infra)"]


def test_uso_medido_do_resumo_aparece_no_texto():
    assert "Lido 3 vezes nos últimos 7 dias." in resumo_semanal.texto(PRS, leituras=3)


def test_semana_vazia_nao_divide_por_zero_e_nao_inventa_sem_pedido():
    t = resumo_semanal.texto([], leituras=0)
    assert "0 de 0 PRs foram produto (fração —, meta 0.5)" in t
    assert "## Sem pedido (0)" in t


def test_semana_monta_da_base_e_conta_a_leitura(circle):
    s, agora = circle.store, NOON.timestamp()
    item = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
               "VALUES('Exportar CSV','exportar lançamentos','pedido_cassio','feito','',1,?,?)", (agora, agora))
    s.x("INSERT INTO prs(number,titulo,branch,status,item_id,created_at,updated_at) VALUES(601,'PR 601','b601',"
        "'mergeado',?,?,?)", (item, agora - 600, agora - 600))
    resumo_semanal.semana(s, agora)
    t = resumo_semanal.semana(s, agora)
    assert "- #601 PR 601 · pedido: exportar lançamentos" in _secao(t, "Produto (1)")
    assert "Lido 2 vezes nos últimos 7 dias." in t


def test_cada_pr_de_produto_mostra_consultas_7d_e_os_sem_uso_ficam_sinalizados():
    t = resumo_semanal.texto(PRS, leituras=0, consultas={21: 2})
    linhas = [linha for linha in _secao(t, "Consultas 7d").splitlines() if linha.startswith("- ")]
    assert linhas == ["- #20 Painel da equipe ao vivo · consultas 7d: 0", "- #21 Exportar CSV · consultas 7d: 2",
                      "- #24 Filtro por assunto · consultas 7d: 0"]
    assert [linha for linha in _secao(t, "Produto sem uso (2)").splitlines() if linha.startswith("- ")] == [
        "- #20 Painel da equipe ao vivo", "- #24 Filtro por assunto"]


def test_semana_registra_cada_consulta_em_uso_resumo_e_conta_so_7_dias(circle):
    s, agora = circle.store, NOON.timestamp()
    for n in (701, 702):
        item = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                   "VALUES(?,?,'pedido_cassio','feito','',1,?,?)", (f"Item {n}", f"pedido {n}", agora, agora))
        s.x("INSERT INTO prs(number,titulo,branch,status,item_id,created_at,updated_at) VALUES(?,?,?,'mergeado',?,?,?)",
            (n, f"PR {n}", f"b{n}", item, agora - 600, agora - 600))
    resumo_semanal.semana(s, agora - 8 * 86400)
    primeira = resumo_semanal.semana(s, agora)
    assert "## Produto sem uso (2)" in primeira
    t = resumo_semanal.semana(s, agora + 60)
    assert "- #701 PR 701 · consultas 7d: 1" in _secao(t, "Consultas 7d")
    assert "## Produto sem uso (0)" in t
    recursos = [r["recurso"] for r in s.q("SELECT recurso FROM uso_resumo WHERE created_at>=?", (agora,))]
    assert sorted(recursos) == ["pr:701", "pr:701", "pr:702", "pr:702", "resumo", "resumo"]


def test_pedidos_sem_pr_de_produto_mergeado_saem_do_mais_velho_ao_mais_novo():
    agora = NOON.timestamp()
    pedidos = [{"id": 1, "titulo": "Exportar CSV", "created_at": agora - 10 * 86400},
               {"id": 2, "titulo": "Filtro por assunto", "created_at": agora - 2 * 86400},
               {"id": 3, "titulo": "Alerta no Slack", "created_at": agora - 30 * 86400},
               {"id": 4, "titulo": "Painel ao vivo", "created_at": agora - 5 * 86400}]
    prs = [{"item_id": 1}, {"item_id": None}, {"item_id": 99}]
    assert resumo_semanal.pedidos_sem_entrega(pedidos, prs, agora) == [
        {"id": 3, "titulo": "Alerta no Slack", "dias": 30}, {"id": 4, "titulo": "Painel ao vivo", "dias": 5},
        {"id": 2, "titulo": "Filtro por assunto", "dias": 2}]


def test_todo_resumo_traz_a_secao_pedidos_sem_entrega():
    assert "## Pedidos sem entrega (0)" in resumo_semanal.texto(PRS, leituras=0)
    t = resumo_semanal.texto(PRS, leituras=0, sem_entrega=[{"id": 3, "titulo": "Alerta no Slack", "dias": 30},
                                                           {"id": 7, "titulo": "Painel", "dias": 1}])
    assert [linha for linha in _secao(t, "Pedidos sem entrega (2)").splitlines() if linha.startswith("- ")] == [
        "- item #3 Alerta no Slack · 30 dias", "- item #7 Painel · 1 dia"]


def test_semana_lista_pedidos_abertos_sem_pr_mergeado_de_qualquer_idade(circle):
    s, agora = circle.store, NOON.timestamp()
    s.x("DELETE FROM roadmap")                         # sem o roteiro semente
    ids = {}
    for titulo, status, dias in [("Entregue", "pendente", 40), ("Aberto velho", "pendente", 20),
                                 ("Aberto novo", "em_andamento", 1), ("Já feito", "feito", 50)]:
        ids[titulo] = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                          "VALUES(?,?,'pedido_cassio',?,'',1,?,?)",
                          (titulo, titulo, status, agora - dias * 86400, agora - dias * 86400))
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
        "VALUES('Item do loop','x','loop','pendente','',1,?,?)", (agora - 9 * 86400, agora))
    s.x("INSERT INTO prs(number,titulo,branch,status,item_id,created_at,updated_at) VALUES(801,'PR 801','b801',"
        "'mergeado',?,?,?)", (ids["Entregue"], agora - 30 * 86400, agora - 30 * 86400))
    linhas = [linha for linha in _secao(resumo_semanal.semana(s, agora), "Pedidos sem entrega").splitlines()
              if linha.startswith("- ")]
    assert linhas == [f"- item #{ids['Aberto velho']} Aberto velho · 20 dias",
                      f"- item #{ids['Aberto novo']} Aberto novo · 1 dia"]


def test_comando_relatorio_imprime_o_resumo_com_a_mesma_fracao_do_norte(circle, capsys):
    """`circulo relatorio`: o resumo semanal sai pela linha de comando, cada PR com o pedido de origem ou 'sem
    pedido', e a fração de produto é a mesma que o Norte mede (pergunta #387)."""
    s, agora = circle.store, NOON.timestamp()
    item = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
               "VALUES('Exportar CSV','exportar lançamentos','pedido_cassio','feito','',1,?,?)", (agora, agora))
    for n, item_id in ((901, item), (902, None), (903, None), (904, None)):
        s.x("INSERT INTO prs(number,titulo,branch,status,item_id,created_at,updated_at) VALUES(?,?,?,'mergeado',?,?,?)",
            (n, f"PR {n}", f"b{n}", item_id, agora - 600, agora - 600))
    main(["--data", str(circle.data_dir), "relatorio"])
    out = capsys.readouterr().out
    assert norte.medir(s)["fracao_produto"]["valor"] == 0.25
    assert "1 de 4 PRs foram produto (fração 0.25, meta 0.5)" in out
    assert "- #901 PR 901 · pedido: exportar lançamentos" in _secao(out, "Produto (1)")
    assert "- #902 PR 902 · sem pedido" in _secao(out, "Infra (3)")
    assert s.one("SELECT COUNT(*) n FROM uso_resumo WHERE recurso='resumo'")["n"] == 1

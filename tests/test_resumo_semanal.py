"""Resumo semanal para a equipe: o changelog (produto/infra com o pedido de origem e a fração contra a meta), os PRs
sem pedido listados à parte e o uso medido do digest. Reaproveita `changelog` e `digest_semanal`, não refaz."""
from circulo import resumo_semanal
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

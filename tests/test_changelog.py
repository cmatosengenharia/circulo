"""Changelog semanal: os PRs mergeados em 7 dias agrupados em produto e infra, cada um com o pedido de origem, e a
fração de produto contra a meta de 50%. PR sem pedido de origem aparece marcado 'sem pedido', nunca omitido."""
from circulo import changelog
from conftest import NOON

PRS = [
    {"number": 21, "titulo": "Exportar CSV", "produto": True, "pedido": "pedido: exportar lançamentos"},
    {"number": 20, "titulo": "Painel da equipe ao vivo", "produto": True, "pedido": None},
    {"number": 22, "titulo": "Conserto do vigia", "produto": False, "pedido": "lição #15"},
    {"number": 23, "titulo": "Cache da LLM", "produto": False, "pedido": None},
]


def _secao(texto, titulo):
    blocos = texto.split("\n## ")
    return next(b for b in blocos if b.startswith(titulo))


def test_changelog_agrupa_produto_e_infra_com_o_pedido_de_origem_e_a_fracao_contra_a_meta():
    t = changelog.texto(PRS)
    assert t.startswith("# Changelog semanal")
    assert "2 de 4 PRs foram produto (fração 0.50, meta 0.5)" in t
    produto, infra = _secao(t, "Produto (2)"), _secao(t, "Infra (2)")
    assert produto.splitlines()[1:] == ["- #20 Painel da equipe ao vivo · sem pedido",
                                        "- #21 Exportar CSV · pedido: exportar lançamentos"]
    assert infra.splitlines()[1:] == ["- #22 Conserto do vigia · lição #15", "- #23 Cache da LLM · sem pedido"]


def test_todo_pr_de_produto_aparece_mesmo_sem_pedido():
    t = changelog.texto(PRS)
    for p in PRS:
        assert f"#{p['number']} {p['titulo']}" in t


def test_semana_monta_da_base_com_o_pedido_de_origem(circle):
    s, agora = circle.store, NOON.timestamp()
    item = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
               "VALUES('Exportar CSV','exportar lançamentos','pedido_cassio','feito','',1,?,?)", (agora, agora))
    for n, item_id in ((601, item), (602, None)):
        s.x("INSERT INTO prs(number,titulo,branch,status,item_id,created_at,updated_at) VALUES(?,?,?,'mergeado',?,?,?)",
            (n, f"PR {n}", f"b{n}", item_id, agora - 600, agora - 600))
    t = changelog.semana(s, agora)
    assert "- #601 PR 601 · pedido: exportar lançamentos" in _secao(t, "Produto (1)")
    assert "- #602 PR 602 · sem pedido" in _secao(t, "Infra (1)")


def test_semana_vazia_nao_divide_por_zero():
    t = changelog.texto([])
    assert "0 de 0 PRs foram produto (fração —, meta 0.5)" in t
    assert "## Produto (0)" in t and "## Infra (0)" in t

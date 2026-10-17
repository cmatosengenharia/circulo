import pytest

from circulo.projects import cards, kit_project_id, nome_do_pedido


def criar(circle, pedido):
    circle.submit_project(pedido)
    r = circle.tick()
    assert not r.errors
    return circle.store.one("SELECT * FROM projects ORDER BY id DESC LIMIT 1")


def test_financas_e_o_projeto_semente(circle):
    rows = circle.store.q("SELECT * FROM projects")
    assert len(rows) == 1 and rows[0]["kit"] == "financas" and rows[0]["status"] == "ativo"


@pytest.mark.parametrize("pedido,tipo,status", [
    ("Crie uma landing page para captar leads do Instagram", "landing_page", "aguardando_kit"),
    ("Crie um portal admin para fotógrafos", "produto_software", "aguardando_kit"),
    ("Monte um plano para a construção da casa no lote", "plano", "aguardando_kit"),
])
def test_intake_classifica_com_jev(circle, pedido, tipo, status):
    p = criar(circle, pedido)
    assert p["tipo"] == tipo and p["status"] == status and p["pedido"] == pedido
    d = circle.store.one("SELECT question, project_id FROM decisions WHERE question='project_type'")
    assert d["project_id"] == p["id"]   # a decisão do intake passa a ser a primeira do projeto


def test_pedido_de_financas_nao_duplica_projeto(circle):
    criar(circle, "Me ajude a economizar dinheiro com os gastos da família")
    assert circle.store.one("SELECT COUNT(*) n FROM projects")["n"] == 1


def test_decisoes_e_evolucoes_ficam_no_projeto(circle):
    fin = kit_project_id(circle.store, "financas")
    for i in range(3):
        circle.submit(f"{50 + i} sacolão")
        circle.tick()
        circle.submit(f"corrige {i + 1} mercado")
        circle.tick()
    assert circle.store.one("SELECT COUNT(*) n FROM decisions WHERE project_id=?", (fin,))["n"] > 0
    assert circle.store.one("SELECT project_id FROM proposals WHERE kind='add_rule'")["project_id"] == fin
    c = next(c for c in cards(circle.store) if c["id"] == fin)
    assert c["evolucoes_aplicadas"] == 1 and c["giros"] >= 6 and sum(c["atividade_24h"]) > 0


def test_mensagem_para_projeto_sem_kit_nao_vira_lancamento(circle):
    p = criar(circle, "Crie uma landing page para captar leads do Instagram")
    circle.store.enqueue("mensagem", {"text": "38,90 ifood", "projeto": p["id"]})
    circle.tick()
    assert circle.store.one("SELECT COUNT(*) n FROM ledger")["n"] == 0
    assert "espera o kit" in circle.store.one("SELECT message FROM alerts WHERE project_id=? ORDER BY id DESC", (p["id"],))["message"]


def test_nome_curto_vem_do_pedido():
    assert nome_do_pedido("Crie uma landing page para captar leads do Instagram") == "Landing page para captar leads do Instagram"
    assert nome_do_pedido("crie um portal admin para fotógrafos, com agenda") == "Portal admin para fotógrafos"
    assert len(nome_do_pedido("Crie " + "x " * 80)) <= 57


def test_banco_antigo_ganha_colunas_novas(tmp_path):
    import sqlite3
    from circulo.state import Store
    db = tmp_path / "velho.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE decisions (id INTEGER PRIMARY KEY, tick INTEGER, question TEXT, value TEXT, confidence REAL, source TEXT, created_at REAL)")
    con.execute("INSERT INTO decisions(tick,question,value,confidence,source,created_at) VALUES(1,'x','1',1,'local',0)")
    con.commit()
    con.close()
    s = Store(db)
    assert s.one("SELECT project_id FROM decisions")["project_id"] is None
    assert s.one("SELECT COUNT(*) n FROM decisions")["n"] == 1

from circulo.norte import SEMANA
from circulo.state import Store
from circulo.uso_entregas import entregas_sem_uso, listar_sem_uso, registrar_esperado

AGORA = 1_000_000_000.0
DIA = 86400


def _pr(number, dias_desde_merge, evento="painel_aberto", produto=True):
    return {"number": number, "produto": produto, "evento_esperado": evento,
            "merged_at": AGORA - dias_desde_merge * DIA}


def test_lista_so_entregas_de_produto_com_7_dias_sem_uso_depois_do_merge():
    com_uso = _pr(1, 8, "assunto_executado")
    sem_uso = _pr(2, 8, "changelog_aberto")
    uso_antes = _pr(3, 10, "digest_lido")
    recente = _pr(4, 3, "tela_nova")
    infra = _pr(5, 9, "nada", produto=False)
    eventos = [{"nome": "assunto_executado", "created_at": com_uso["merged_at"] + DIA},
               {"nome": "digest_lido", "created_at": uso_antes["merged_at"] - DIA},
               {"nome": "painel_aberto", "created_at": AGORA}]

    saida = entregas_sem_uso([com_uso, sem_uso, uso_antes, recente, infra], eventos, AGORA)

    assert [p["number"] for p in saida] == [2, 3]


def test_exatamente_7_dias_ja_conta_e_evento_no_instante_do_merge_nao_e_uso():
    pr = {"number": 7, "produto": True, "evento_esperado": "x", "merged_at": AGORA - SEMANA}
    assert entregas_sem_uso([pr], [{"nome": "x", "created_at": pr["merged_at"]}], AGORA) == [pr]


def test_registro_duplicado_nao_cria_linha_e_entrega_sem_uso_ha_7_dias_aparece():
    conn = Store().db
    registrar_esperado(conn, 10, "assunto_executado", agora=AGORA - 8 * DIA)
    registrar_esperado(conn, 10, "assunto_executado", agora=AGORA - 2 * DIA)
    registrar_esperado(conn, 11, "painel_aberto", agora=AGORA - 9 * DIA)
    registrar_esperado(conn, 12, "tela_nova", agora=AGORA - 3 * DIA)
    conn.execute("INSERT INTO events(kind,payload,created_at) VALUES('painel_aberto','{}',?)", (AGORA - DIA,))

    assert conn.execute("SELECT COUNT(*) FROM entrega_uso_esperado WHERE pr=10").fetchone()[0] == 1
    assert [p["number"] for p in listar_sem_uso(conn, AGORA)] == [10]


def test_listar_sem_uso_sem_nada_gravado_e_vazio():
    assert listar_sem_uso(Store().db, AGORA) == []

import sqlite3
import threading
import time

import pytest

from circulo.revisao_uso import abrir_pedidos_revisao_uso, decidir, fechar
from circulo.state import Store
from circulo.uso_entregas import registrar_esperado

AGORA = 1_000_000_000.0
DIA = 86400


def _entregas(conn):
    registrar_esperado(conn, 10, "assunto_executado", agora=AGORA - 8 * DIA)
    registrar_esperado(conn, 11, "painel_aberto", agora=AGORA - 9 * DIA)
    registrar_esperado(conn, 12, "tela_nova", agora=AGORA - 3 * DIA)
    registrar_esperado(conn, 13, "digest_lido", agora=AGORA - 10 * DIA)
    conn.execute("INSERT INTO events(kind,payload,created_at) VALUES('digest_lido','{}',?)", (AGORA - DIA,))


def _pedidos(conn):
    return [tuple(r) for r in conn.execute("SELECT pr_numero, evento, status FROM revisao_uso ORDER BY pr_numero")]


def test_duas_execucoes_seguidas_deixam_um_pedido_por_entrega_sem_uso():
    conn = Store().db
    _entregas(conn)

    assert abrir_pedidos_revisao_uso(conn, AGORA) == [10, 11]
    assert abrir_pedidos_revisao_uso(conn, AGORA + DIA) == []

    assert _pedidos(conn) == [(10, "assunto_executado", "aberto"), (11, "painel_aberto", "aberto")]


def test_duas_execucoes_em_paralelo_em_conexoes_separadas_deixam_um_pedido_por_pr(tmp_path):
    caminho = tmp_path / "circulo.db"
    _entregas(Store(caminho).db)
    largada = threading.Barrier(2)
    abertos, erros = [], []

    def rodar():
        conn = sqlite3.connect(caminho, isolation_level=None, timeout=30.0)
        try:
            largada.wait()
            abertos.append(abrir_pedidos_revisao_uso(conn, AGORA))
        except Exception as exc:  # noqa: BLE001 — o assert abaixo mostra o erro da thread
            erros.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=rodar) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not erros
    assert sorted(pr for lote in abertos for pr in lote) == [10, 11]
    assert _pedidos(sqlite3.connect(caminho)) == [(10, "assunto_executado", "aberto"), (11, "painel_aberto", "aberto")]


def test_giro_do_loop_abre_o_pedido_depois_do_painel_e_o_seguinte_nao_duplica(tmp_path):
    from circulo.decision import LocalJev
    from circulo.loop import Circle
    c = Circle(tmp_path, jev=LocalJev())
    registrar_esperado(c.store.db, 20, "tela_nova", agora=time.time() - 8 * DIA)

    c.tick()
    c.tick()

    assert _pedidos(c.store.db) == [(20, "tela_nova", "aberto")]


def test_pedido_fechado_nunca_reabre_nem_ganha_outro():
    conn = Store().db
    _entregas(conn)
    abrir_pedidos_revisao_uso(conn, AGORA)
    fechar(conn, 10, agora=AGORA + DIA)

    assert abrir_pedidos_revisao_uso(conn, AGORA + 30 * DIA) == [12]
    assert _pedidos(conn) == [(10, "assunto_executado", "fechado"), (11, "painel_aberto", "aberto"),
                              (12, "tela_nova", "aberto")]


def test_primeiro_destino_fica_e_repeticao_diferente_vira_divergencia():
    conn = Store().db
    _entregas(conn)
    abrir_pedidos_revisao_uso(conn, AGORA)

    assert decidir(conn, 10, "remover", agora=AGORA) == "remover"
    assert decidir(conn, 10, "remover", agora=AGORA + 1) == "remover"
    assert decidir(conn, 10, "usar", agora=AGORA + 2) == "remover"

    assert [tuple(r) for r in conn.execute(
        "SELECT pr_numero, destino, destino_novo FROM revisao_uso_divergencia")] == [(10, "remover", "usar")]
    with pytest.raises(ValueError):
        decidir(conn, 11, "divulgar")


def _pm(s):
    return s.x("INSERT INTO perguntas(chave,persona,texto,status,created_at,updated_at) "
               "VALUES('uso','pm','Quantas entregas têm uso depois do merge?','feita',0,0)")


def _itens(s):
    return [(r["titulo"], r["pergunta_id"]) for r in s.q("SELECT titulo, pergunta_id FROM roadmap ORDER BY id")]


def test_cada_entrega_sem_uso_tem_exatamente_um_item_de_revisao_por_pr_mesmo_com_o_mesmo_evento_e_em_14_dias():
    """Pergunta do conselho #362 (pm): duas entregas com o mesmo evento esperado são dois itens (a chave é o PR, não o
    evento), e 14 dias de giros não duplicam nenhum, nem depois de o item ser resolvido."""
    from circulo.revisao_uso import cobrar_no_roteiro
    s = Store()
    pm = _pm(s)
    registrar_esperado(s.db, 30, "painel_aberto", agora=AGORA - 8 * DIA)
    registrar_esperado(s.db, 31, "painel_aberto", agora=AGORA - 9 * DIA)

    novos = cobrar_no_roteiro(s, pm, AGORA)
    s.x("UPDATE roadmap SET status='feito' WHERE id=?", (novos[0],))
    for dia in range(1, 15):
        assert cobrar_no_roteiro(s, pm, AGORA + dia * DIA) == []

    itens = _itens(s)
    assert len(novos) == 2 and len(itens) == 2 and {p for _, p in itens} == {pm}
    assert "#30" in itens[0][0] and "#31" in itens[1][0] and all("remover" in t for t, _ in itens)
    assert [tuple(r) for r in s.db.execute("SELECT pr_numero, item_id FROM revisao_uso ORDER BY pr_numero")] == [
        (30, novos[0]), (31, novos[1])]


def test_pedido_aberto_antes_sem_item_ganha_o_seu_uma_vez():
    from circulo.revisao_uso import cobrar_no_roteiro
    s = Store()
    _entregas(s.db)
    abrir_pedidos_revisao_uso(s.db, AGORA)                 # aberto pelo giro antes de existir a pergunta do PM
    pm = _pm(s)

    assert len(cobrar_no_roteiro(s, pm, AGORA)) == 2
    assert cobrar_no_roteiro(s, pm, AGORA) == []
    assert len(_itens(s)) == 2


def test_giro_do_loop_com_pergunta_do_pm_abre_um_item_por_entrega_e_o_seguinte_nao_duplica(tmp_path):
    from circulo.decision import LocalJev
    from circulo.loop import Circle
    c = Circle(tmp_path, jev=LocalJev())
    pm = _pm(c.store)
    registrar_esperado(c.store.db, 40, "tela_nova", agora=time.time() - 8 * DIA)

    c.tick()
    c.tick()

    assert [p for t, p in _itens(c.store) if "#40" in t] == [pm]

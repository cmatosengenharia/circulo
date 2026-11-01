import json
import sqlite3

from circulo.condensador import comparar, condensar, gravar, veredito


def _eventos(n: int) -> list[dict]:
    evs = [{"id": i, "tipo": "passo", "texto": f"passo {i}"} for i in range(n)]
    evs[5].update(tipo="arquivo", arquivo="circulo/a.py")
    evs[9].update(tipo="erro", texto="AssertionError em test_a")
    evs[12].update(tipo="gate", texto="ruff: B905")
    evs[20].update(tipo="erro", texto="ImportError em b")
    evs[25].update(tipo="arquivo", arquivo="circulo/b.py")
    return evs


def test_cinquenta_eventos_cabem_em_vinte_com_os_primeiros_e_os_recentes_intactos():
    evs = _eventos(50)
    c = condensar(evs, max_size=20, keep_first=2)
    assert len(c.eventos) <= 20
    assert c.eventos[:2] == evs[:2]
    assert c.eventos[-10:] == evs[-10:]
    mantidos = {e["id"] for e in c.eventos if e["tipo"] != "condensacao"}
    assert set(c.esquecidos) == {e["id"] for e in evs} - mantidos
    assert c.esquecidos and 2 not in mantidos


def test_resumo_deterministico_guarda_ultimo_erro_arquivos_e_decisoes_do_gate():
    c = condensar(_eventos(50), max_size=20, keep_first=2)
    resumo = next(e for e in c.eventos if e["tipo"] == "condensacao")
    assert "ImportError em b" in resumo["texto"] and "AssertionError" not in resumo["texto"]
    assert "circulo/a.py" in resumo["texto"] and "circulo/b.py" in resumo["texto"]
    assert "ruff: B905" in resumo["texto"]
    assert resumo["esquecidos"] == c.esquecidos


def test_recondensar_nao_perde_o_que_o_resumo_anterior_guardava():
    c1 = condensar(_eventos(50), max_size=20, keep_first=2)
    mais = c1.eventos + [{"id": 100 + i, "tipo": "passo", "texto": "x"} for i in range(20)]
    c2 = condensar(mais, max_size=20, keep_first=2)
    resumo = next(e for e in c2.eventos if e["tipo"] == "condensacao")
    assert "circulo/a.py" in resumo["texto"] and "ImportError em b" in resumo["texto"]
    assert set(c1.esquecidos) <= set(resumo["esquecidos"])


def test_abaixo_do_limite_nada_muda_e_o_llm_e_opcional():
    evs = _eventos(50)[:15]
    c = condensar(evs, max_size=20, keep_first=2)
    assert c.eventos == evs and c.esquecidos == []
    c = condensar(_eventos(50), max_size=20, keep_first=2, resumir=lambda meio: f"LLM: {len(meio)} eventos")
    assert any(e["texto"] == "LLM: 31 eventos" for e in c.eventos)


def test_gravar_registra_a_condensacao_com_os_ids_esquecidos():
    conn = sqlite3.connect(":memory:")
    c = condensar(_eventos(50), max_size=20, keep_first=2)
    gravar(conn, 7, c, antes=50)
    item, esquecidos, antes, depois = conn.execute("SELECT item_id, esquecidos, antes, depois FROM condensacoes").fetchone()
    assert (item, antes, depois) == (7, 50, len(c.eventos))
    assert json.loads(esquecidos) == c.esquecidos


def _base_medida(com_conserto_condensado: int) -> sqlite3.Connection:
    """10 PRs mergeados por grupo; o Developer gasta 1000 tokens por PR sem condensação e 600 com."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE prs (number INTEGER PRIMARY KEY, titulo TEXT, status TEXT, item_id INTEGER, "
                 "consertos INTEGER, created_at REAL)")
    conn.execute("CREATE TABLE llm_calls (papel TEXT, tokens INTEGER, entrada TEXT, created_at REAL)")
    c = condensar(_eventos(50), max_size=20, keep_first=2)
    for n in range(20):
        condensado = n >= 10
        conserto = int(condensado and n - 10 < com_conserto_condensado)
        conn.execute("INSERT INTO prs VALUES(?,?,?,?,?,?)", (n, f"item {n}", "mergeado", n, conserto, 100.0 + n))
        conn.execute("INSERT INTO llm_calls VALUES('developer',?,?,?)", (600 if condensado else 1000, f"item {n}", 100.0 + n))
        conn.execute("INSERT INTO llm_calls VALUES('planejador',5000,?,?)", (f"item {n}", 100.0 + n))
        if condensado:
            gravar(conn, n, c, antes=50, em=100.0 + n)
    return conn


def test_tokens_do_developer_por_pr_mergeado_com_e_sem_condensacao():
    m = comparar(_base_medida(com_conserto_condensado=2), desde=0, ate=1000)
    assert m["sem"] == {"prs": 10, "mergeados": 10, "tokens_por_pr": 1000, "merge_sem_conserto": 1.0}
    assert m["com"] == {"prs": 10, "mergeados": 10, "tokens_por_pr": 600, "merge_sem_conserto": 0.8}
    assert veredito(m)["ok"] is True


def test_economia_que_derruba_o_merge_sem_conserto_abaixo_de_0_7_nao_vale():
    v = veredito(comparar(_base_medida(com_conserto_condensado=4), desde=0, ate=1000))
    assert v["ok"] is False and "0.7" in v["motivo"]
    sem_dados = veredito(comparar(sqlite3.connect(":memory:"), desde=0, ate=1000))
    assert sem_dados["ok"] is None

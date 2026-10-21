"""Migração do roadmap: itens antigos sem pergunta de origem viram 'legado'; com pergunta válida, 'ok'."""
import sqlite3
import time

from circulo.roadmap import migrar
from circulo.state import Store


def _item(s: Store, titulo: str) -> int:
    now = time.time()
    return s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
               "VALUES(?,?,?,?,?,?,?,?)", (titulo, "", "loop", "pendente", "", 1, now, now))


def _pergunta(s: Store, item_id: int | None) -> int:
    now = time.time()
    return s.x("INSERT INTO perguntas(chave,persona,texto,status,item_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
               ("k", "p", "por quê?", "virou_item", item_id, now, now))


def _estado(s: Store) -> dict:
    return {r["titulo"]: (r["pergunta_id"], r["origem_status"])
            for r in s.q("SELECT titulo, pergunta_id, origem_status FROM roadmap")}


def test_itens_sem_origem_viram_legado_e_com_pergunta_valida_ficam_ok(tmp_path):
    s = Store(tmp_path / "c.db")
    com = _item(s, "com pergunta")
    _item(s, "sem pergunta")
    orfao = _item(s, "pergunta apagada")
    pid = _pergunta(s, com)
    s.x("DELETE FROM perguntas WHERE id=?", (_pergunta(s, orfao),))
    s.x("UPDATE roadmap SET origem_status=NULL")       # banco de antes da migração
    s.x("UPDATE roadmap SET pergunta_id=999 WHERE id=?", (orfao,))
    migrar(s.db)
    assert _estado(s) == {"com pergunta": (pid, "ok"), "sem pergunta": (None, "legado"),
                          "pergunta apagada": (999, "legado")}


def test_banco_antigo_sem_as_colunas_ganha_as_colunas_e_migrar_2x_nao_muda_nada(tmp_path):
    db = sqlite3.connect(tmp_path / "antigo.db")
    db.executescript("CREATE TABLE roadmap (id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, "
                     "detalhe TEXT NOT NULL, origem TEXT NOT NULL, status TEXT NOT NULL, evidencia TEXT NOT NULL, "
                     "ordem INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL);"
                     "INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                     "VALUES('velho','','loop','feito','',1,0,0),('ligado','','loop','feito','',2,0,0);")
    db.close()
    s = Store(tmp_path / "antigo.db")                    # abrir o banco roda a migração
    ligado = s.one("SELECT id FROM roadmap WHERE titulo='ligado'")["id"]
    pid = _pergunta(s, ligado)
    s.x("UPDATE roadmap SET pergunta_id=NULL, origem_status=NULL")
    migrar(s.db)
    antes = _estado(s)
    assert antes == {"velho": (None, "legado"), "ligado": (pid, "ok")}
    migrar(s.db)
    assert _estado(s) == antes
    assert Store(tmp_path / "antigo.db") and _estado(s) == antes

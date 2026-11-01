"""Meu trabalho: marcar uma pendência como feita pela tela (POST /api/trabalho/pendencia {id, feita}); a daily deixa
de listá-la e a ficha (assuntos.ver, /trabalho/assunto/<nome>) mostra 'feita em <data>'."""
import sqlite3
import time
from pathlib import Path

from circulo import assuntos, daily, trabalho
from circulo.state import Store

HOJE_8H = time.mktime((2026, 10, 26, 8, 5, 0, 0, 0, -1))
ONTEM = time.mktime((2026, 10, 25, 15, 0, 0, 0, 0, -1))
TELAS = Path(assuntos.__file__).parent


def _pendencia(s):
    aid = assuntos.criar(s, "svc-sms", "envio de SMS")
    return assuntos.arquivar(s, "pendência: trocar o provedor de SMS", aid, agora=ONTEM - 86400)["id"]


def test_marcar_feita_tira_da_daily_e_a_ficha_mostra_a_data(circle):
    s, dados = circle.store, circle.data_dir
    nid = _pendencia(s)
    assert "trocar o provedor" in " ".join(daily.pauta(dados, HOJE_8H, s))
    r, status = trabalho.api_post(s, dados, "/api/trabalho/pendencia", {"id": nid, "feita": True})
    assert status == 200 and r["ok"] and r["nota"]["feita"]
    assert "trocar o provedor" not in " ".join(daily.pauta(dados, time.time() + 86400 * 3, s))
    assuntos.marcar_feita(s, nid, True, agora=ONTEM)
    pauta = " ".join(daily.pauta(dados, HOJE_8H, s))
    assert "trocar o provedor" not in pauta                                              # nem em "hoje" nem em "ontem"
    ficha = trabalho.api_get(s, dados, "/api/trabalho/ficha", {"nome": ["svc-sms"]})
    assert ficha["pendencias"][0]["feita"] == "25/10/2026"
    v = trabalho.visao(s, dados)
    assert not v["pendencias"] and v["assuntos"][0]["pendencias"] == 0                   # a tela conta só as abertas
    trabalho.api_post(s, dados, "/api/trabalho/pendencia", {"id": nid, "feita": False})    # desfazer reabre
    assert assuntos.ver(s, "svc-sms")["pendencias"][0]["feita"] is None
    assert "hoje: trocar o provedor" in " ".join(daily.pauta(dados, HOJE_8H, s))


def test_as_telas_marcam_e_a_ficha_escreve_feita_em():
    for tela in ("trabalho.html", "assunto.html"):
        assert "/api/trabalho/pendencia" in (TELAS / tela).read_text(encoding="utf-8"), tela
    assert "feita em ${" in (TELAS / "assunto.html").read_text(encoding="utf-8")       # texto, não só cor


def test_pedido_invalido_e_400(circle):
    s, dados = circle.store, circle.data_dir
    nid = _pendencia(s)
    decisao = assuntos.arquivar(s, "decidimos usar um provedor só", 1)["id"]
    for corpo in ({"feita": True}, {"id": "1", "feita": True}, {"id": nid}, {"id": 999, "feita": True},
                  {"id": decisao, "feita": True}):
        assert trabalho.api_post(s, dados, "/api/trabalho/pendencia", corpo)[1] == 400, corpo


def test_migracao_da_coluna_feita_em_e_idempotente(tmp_path):
    db = tmp_path / "velho.db"
    c = sqlite3.connect(db)
    c.executescript("CREATE TABLE assunto_notas (id INTEGER PRIMARY KEY AUTOINCREMENT, assunto_id INTEGER NOT NULL, "
                    "tipo TEXT NOT NULL, texto TEXT NOT NULL, origem TEXT NOT NULL, confianca REAL, graft_id TEXT, "
                    "created_at REAL NOT NULL);"
                    "INSERT INTO assunto_notas(assunto_id, tipo, texto, origem, created_at) VALUES(1,'pendencia','x','x',1);")
    c.commit()
    c.close()
    for _ in range(2):
        s = Store(db)
        assuntos.preparar(s)
        assert "feita_em" in {r["name"] for r in s.q("PRAGMA table_info(assunto_notas)")}
        assert s.one("SELECT feita_em FROM assunto_notas")["feita_em"] is None

import pytest

from app.logica import NOME, saude


def test_saude():
    assert saude() == {"status": "ok", "servico": NOME}


def test_rota_saude():
    cliente = pytest.importorskip("fastapi.testclient")
    from app.main import app
    assert cliente.TestClient(app).get("/saude").json() == saude()

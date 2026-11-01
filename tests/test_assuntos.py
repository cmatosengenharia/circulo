"""Espaço de trabalho por assunto: anotar em uma frase, o Jev arquiva no assunto certo, o Graft indexa, e
'o que decidimos sobre X?' volta com a data e a nota de origem."""
from datetime import datetime

import pytest

from circulo import assuntos, graft, trabalho
from circulo.budget import TZ


@pytest.fixture
def ws(circle):
    s = circle.store
    assuntos.criar(s, "Tribo", "minha tribo: pessoas, rituais e prioridades")
    assuntos.criar(s, "Squad", "minha squad: time, cerimônias e entregas")
    assuntos.criar(s, "Serviço de SMS", "microsserviço de comunicação que envia SMS")
    assuntos.criar(s, "Migração Blip → Amazon Connect", "migração dos chatbots da Blip para o Amazon Connect",
                   links=["https://docs.aws.amazon.com/connect/"])
    return circle


def test_frase_vai_para_o_assunto_certo_com_o_tipo_certo(ws):
    s, dl = ws.store, ws.ctx.dl
    agora = datetime(2026, 10, 26, 10, 0, tzinfo=TZ).timestamp()
    a = assuntos.anotar(s, dl, "decidimos usar fila SQS no serviço de SMS", agora=agora)
    b = assuntos.anotar(s, dl, "pendência: exportar os fluxos dos chatbots da Blip", agora=agora)
    c = assuntos.anotar(s, dl, "link do runbook do Amazon Connect https://exemplo.interno/runbook", agora=agora)
    assert (a["assunto"], a["tipo"]) == ("Serviço de SMS", "decisao")
    assert (b["assunto"], b["tipo"]) == ("Migração Blip → Amazon Connect", "pendencia")
    assert (c["assunto"], c["tipo"]) == ("Migração Blip → Amazon Connect", "link")
    ficha = assuntos.ver(s, "Serviço de SMS")
    assert ficha["descricao"].startswith("microsserviço")
    assert [n["texto"] for n in ficha["decisoes"]] == ["usar fila SQS no serviço de SMS"]
    assert assuntos.ver(s, "Migração Blip → Amazon Connect")["links"][0] == "https://docs.aws.amazon.com/connect/"


def test_o_que_decidimos_volta_com_data_e_nota_de_origem(ws):
    s, dl = ws.store, ws.ctx.dl
    assuntos.anotar(s, dl, "decidimos usar fila SQS no serviço de SMS", agora=datetime(2026, 10, 20, 9, tzinfo=TZ).timestamp())
    assuntos.anotar(s, dl, "pendência: revisar custo do SMS", agora=datetime(2026, 10, 21, 9, tzinfo=TZ).timestamp())
    r = assuntos.perguntar(s, "o que decidimos sobre a fila do SMS?")
    assert len(r) == 1 and r[0]["tipo"] == "decisao"
    assert r[0]["data"] == "20/10/2026" and r[0]["origem"] == "decidimos usar fila SQS no serviço de SMS"
    assert "20/10/2026" in assuntos.responder(r) and "Serviço de SMS" in assuntos.responder(r)


def test_graft_indexa_e_acha_por_significado(ws, monkeypatch):
    s, dl = ws.store, ws.ctx.dl
    inseridos = []
    monkeypatch.setattr(graft, "inserir", lambda tipo, ref, titulo, texto, **k: inseridos.append((tipo, ref)) or "abc")
    n = assuntos.anotar(s, dl, "decidimos que o bot de boas-vindas sai da Blip primeiro")
    assert inseridos == [("assunto_nota", n["id"])]
    # nenhuma palavra em comum com a nota: só a busca semântica do Graft a acha
    monkeypatch.setattr(graft, "recuperar", lambda texto, k=12: [{"tipo": "assunto_nota", "ref": str(n["id"]), "score": 0.9}])
    r = assuntos.perguntar(s, "o que decidimos sobre a ordem de saída dos assistentes virtuais?")
    assert [x["id"] for x in r] == [n["id"]]


def test_achada_so_por_significado_vem_marcada_e_cita_a_nota_de_origem(ws, monkeypatch):
    s, dl = ws.store, ws.ctx.dl
    monkeypatch.setattr(graft, "inserir", lambda *a, **k: None)
    sig = assuntos.anotar(s, dl, "decidimos que o bot de boas-vindas sai da Blip primeiro")
    pal = assuntos.anotar(s, dl, "decidimos usar fila SQS no serviço de SMS")
    monkeypatch.setattr(graft, "recuperar", lambda texto, k=12: [{"tipo": "assunto_nota", "ref": str(sig["id"]), "score": 0.9},
                                                                  {"tipo": "assunto_nota", "ref": str(pal["id"]), "score": 0.5}])
    r = assuntos.perguntar(s, "o que decidimos sobre a ordem de saída dos assistentes virtuais e a fila do SMS?")
    assert [(x["id"], x["por"]) for x in r] == [(sig["id"], "significado"), (pal["id"], "palavra")]
    linhas = assuntos.responder(r).splitlines()
    assert "por significado" in linhas[0] and "decidimos que o bot de boas-vindas sai da Blip primeiro" in linhas[0]
    assert "por significado" not in linhas[1]
    via_tela = trabalho.api_get(s, ws.data_dir, "/api/trabalho/perguntar", {"q": ["o que decidimos sobre os assistentes virtuais?"]})
    assert via_tela["notas"][0]["por"] == "significado" and "por significado" in via_tela["texto"]


def test_console_anota_e_pergunta(tmp_path):
    import contextlib
    import io

    from circulo.cli import main
    dados = str(tmp_path / "dados")
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida):
        main(["--data", dados, "assunto", "novo", "Serviço de e-mail", "--descricao", "microsserviço que envia e-mail"])
        main(["--data", dados, "assunto", "anotar", "decidimos", "trocar", "o", "provedor", "do", "serviço", "de", "e-mail"])
        main(["--data", dados, "assunto", "perguntar", "o que decidimos sobre o provedor de e-mail?"])
    out = saida.getvalue()
    assert "arquivada em Serviço de e-mail" in out
    assert "trocar o provedor do serviço de e-mail" in out and "decidimos trocar" in out


def test_codigo_e_credencial_nao_entram(ws):
    s, dl = ws.store, ws.ctx.dl
    for frase in ("senha do banco de homologação: hunter2", "token: ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789",
                  "AKIA" + "ABCDEFGHIJKLMNOP no serviço de SMS", "```python\nimport boto3\n```"):
        with pytest.raises(ValueError):
            assuntos.anotar(s, dl, frase)
    assert s.one("SELECT COUNT(*) n FROM assunto_notas")["n"] == 0

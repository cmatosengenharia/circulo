import json
import threading
import urllib.request

from circulo.projects import cards, kit_project_id
from circulo.painel import serve
from conftest import say


def card(circle, kit):
    return next(c for c in cards(circle.store) if c["kit"] == kit)


def test_metricas_do_loop(circle):
    for _ in range(3):
        circle.tick()
    circle.store.x("INSERT INTO prs(number,project_id,titulo,status,created_at,updated_at) VALUES(7,?, 'fix', 'mergeado', 0, 0)",
                   (kit_project_id(circle.store, "circulo"),))
    m = card(circle, "circulo")["metricas"]
    assert m["ciclos"] == 3 and m["versao"] == "política v1" and m["prs"] == {"abertos": 0, "mergeados": 1}
    assert "Jev local" in m["modelos"] and "Claude Code" in m["modelos"]
    assert m["principal"]["rotulo"] == "Roteiro concluído" and 0 < m["principal"]["valor"] < 1
    assert card(circle, "circulo")["nome"] == "O Loop"


def test_metricas_de_financas(circle):
    for i in range(3):
        say(circle, f"{50 + i} sacolão")
        say(circle, f"corrige {i + 1} mercado")
    say(circle, "20 netflix")
    m = card(circle, "financas")["metricas"]
    assert m["versao"] == "regras v2" and m["evolucoes"] == 1 and m["lancamentos"] == 4
    assert m["principal"]["valor"] == 0.25          # só a netflix foi categorizada sozinha e certa


def test_metricas_do_motor(tmp_path, clock):
    from test_engine import FakeGen
    from circulo.decision import LocalJev
    from circulo.loop import Circle
    c = Circle(tmp_path, jev=LocalJev(), llm=FakeGen(), now=clock)
    c.submit_project("Crie uma landing page para captar leads do Instagram")
    c.tick()
    pid = c.store.one("SELECT id FROM projects WHERE tipo='landing_page'")["id"]
    for _ in range(3):
        c.engine.cycle(pid)
    m = next(x for x in cards(c.store) if x["id"] == pid)["metricas"]
    assert m["versao"] == "v2" and m["evolucoes"] == 1 and m["aceitacao"] == 1.0
    assert len(m["principal"]["historico"]) == 2 and m["principal"]["historico"][1] > m["principal"]["historico"][0]
    assert any(x.startswith("Sonnet") for x in m["modelos"]) and m["tokens"] > 0 and m["tokens_por_ponto"]


def test_trilha_de_etapas_no_sse(circle):
    srv = serve(circle.store.path, port=0, background=True)
    got = []

    def read():
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/eventos?desde=0", timeout=8) as r:
            for line in r:
                if line.startswith(b"data:") and b'"etapa"' in line and b'"seq"' in line:
                    got.append(json.loads(line[5:]))
                if len(got) >= 4:
                    return

    th = threading.Thread(target=read, daemon=True)
    th.start()
    import time
    time.sleep(0.8)
    circle.tick()
    th.join(6)
    srv.shutdown()
    assert [g["etapa"] for g in got][:2] == ["orquestrador", "idle"]


def test_falar_com_o_loop_vira_pedido_no_roteiro(circle):
    pid = kit_project_id(circle.store, "circulo")
    circle.store.enqueue("mensagem", {"text": "Priorize pesquisar antes de construir", "projeto": pid})
    circle.tick()
    r = circle.store.one("SELECT * FROM roadmap ORDER BY id DESC LIMIT 1")
    assert r["titulo"] == "Priorize pesquisar antes de construir" and r["origem"] == "pedido_cassio" and r["status"] == "pendente"
    assert circle.store.one("SELECT COUNT(*) n FROM ledger")["n"] == 0

import json
import threading
import urllib.error
import urllib.request

import pytest

from circulo.painel import estado, serve
from circulo.projects import kit_project_id
from conftest import say


@pytest.fixture
def painel(circle):
    srv = serve(circle.store.path, port=0, background=True)
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_estado_reflete_o_loop(circle):
    say(circle, "38,90 ifood almoço")
    s = estado(circle.store)
    assert s["loop"]["tick"] == 1 and s["loop"]["etapa"]["nome"] == "descanso"
    assert s["saude"]["invariantes"] == [] and s["saude"]["decisoes_24h"] >= 2
    assert s["projetos"][0]["lancamentos"] == 1 and s["ultima_decisao"] >= 2


def test_pagina_e_api(painel):
    with urllib.request.urlopen(painel + "/", timeout=5) as r:
        assert b"<title>" in r.read()
    with urllib.request.urlopen(painel + "/api/estado", timeout=5) as r:
        assert json.loads(r.read())["loop"]["status"] in ("parado", "rodando")


def test_controles_exigem_cabecalho_e_origem_local(painel):
    assert post(painel + "/api/controle", {"acao": "pausar"})[0] == 403
    assert post(painel + "/api/controle", {"acao": "pausar"}, {"X-Circulo": "1", "Origin": "https://evil.example"})[0] == 403
    code, body = post(painel + "/api/controle", {"acao": "pausar"}, {"X-Circulo": "1"})
    assert code == 200 and body["controle"]["pausado"] is True


def test_pausa_pelo_painel_para_o_loop(circle, painel):
    post(painel + "/api/controle", {"acao": "pausar"}, {"X-Circulo": "1"})
    r = circle.tick()
    assert r.paused and r.pause_reason == "humano" and circle.store.get("loop_status") == "pausado_humano"
    post(painel + "/api/controle", {"acao": "retomar"}, {"X-Circulo": "1"})
    assert not circle.tick().paused


def test_modo_seguro_congela_evolucao(circle):
    circle.set_control(modo_seguro=True)
    for i in range(3):
        say(circle, f"{50 + i} sacolão")
        say(circle, f"corrige {i + 1} mercado")
    assert circle.ctx.policies.active()[0] == 1            # nada aprendido em modo seguro
    tasks = {circle.tick().idle_task for _ in range(10)}
    assert tasks <= {"analisar_padroes", "rodar_regressao", "resumo", None}
    circle.set_control(modo_seguro=False)
    circle.tick()
    assert circle.ctx.policies.active()[0] == 2            # ao sair, aprende com o que acumulou


def test_pedido_pelo_painel_entra_na_fila(circle, painel):
    code, body = post(painel + "/api/pedido", {"texto": "19,90 netflix"}, {"X-Circulo": "1"})
    assert code == 200
    assert circle.tick().handled_event == body["evento"]


def test_feed_ao_vivo_sse(circle, painel):
    say(circle, "38,90 ifood almoço")
    got = []

    def read():
        with urllib.request.urlopen(painel + "/api/eventos?desde=0", timeout=5) as r:
            for line in r:
                if line.startswith(b"event: decisao"):
                    got.append(line)
                if len(got) >= 2:
                    return

    t = threading.Thread(target=read, daemon=True)
    t.start()
    t.join(5)
    assert len(got) >= 2


def test_home_e_cards(circle, painel):
    with urllib.request.urlopen(painel + "/", timeout=5) as r:
        assert "Nova missão" in r.read().decode()
    for rota in ("/projeto/1", "/missao/1"):
        with urllib.request.urlopen(painel + rota, timeout=5) as r:
            assert "Todas as missões" in r.read().decode()
    code, body = post(painel + "/api/projeto", {"pedido": "Crie um portal admin para fotógrafos"}, {"X-Circulo": "1"})
    assert code == 200
    circle.tick()
    with urllib.request.urlopen(painel + "/api/projetos", timeout=5) as r:
        data = json.loads(r.read())
    assert {p["tipo"] for p in data["projetos"]} == {"circulo", "financas", "produto_software"}
    assert data["projetos"][0]["kit"] == "circulo"             # o próprio círculo fica fixado no topo


def test_pedido_curto_demais_e_recusado(painel):
    assert post(painel + "/api/projeto", {"pedido": "oi"}, {"X-Circulo": "1"})[0] == 400


def test_estado_filtrado_por_projeto(circle):
    say(circle, "38,90 ifood almoço")
    circle.submit_project("Crie uma landing page para captar leads do Instagram")
    circle.tick()
    lp = circle.store.one("SELECT id FROM projects WHERE tipo='landing_page'")["id"]
    s = estado(circle.store, lp)
    assert s["projeto"]["status"] == "ativo" and s["projeto"]["kit"] == "geral" and s["projetos"] == [] and s["aguardando"] == []
    assert estado(circle.store, 1)["projeto"]["decisoes"] >= 2


def test_painel_sobe_antes_do_loop_e_mostra_desligado(tmp_path):
    srv = serve(tmp_path / "novo.db", port=0, background=True)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/projetos", timeout=5) as r:
            data = json.loads(r.read())
        assert data["loop"]["vivo"]["estado"] == "desligado" and data["projetos"][0]["kit"] == "circulo"
    finally:
        srv.shutdown()


def test_desativar_item_do_roteiro_tira_da_fila_do_developer(circle, painel):
    from circulo.self_dev import SelfDeveloper
    dev = SelfDeveloper(circle.ctx, circle.data_dir, agent=None, github=None)
    circle.store.x("UPDATE roadmap SET estudo='{}'")                 # já estudados (o estudo tem teste próprio)
    primeiro = dev.pick()
    assert primeiro is not None
    code, _ = post(painel + "/api/roteiro", {"id": primeiro["id"], "ativo": False}, {"X-Circulo": "1"})
    assert code == 200
    assert dev.pick()["id"] != primeiro["id"]                       # o Developer pula o item desativado
    item = next(r for r in estado(circle.store, kit_project_id(circle.store, "circulo"))["roteiro"] if r["id"] == primeiro["id"])
    assert item["desativado"] == 1
    assert post(painel + "/api/roteiro", {"id": primeiro["id"], "ativo": True}, {"X-Circulo": "1"})[0] == 200
    assert dev.pick()["id"] == primeiro["id"]                       # reativado: volta ao lugar dele
    assert post(painel + "/api/roteiro", {"id": primeiro["id"], "ativo": False})[0] == 403    # sem o cabeçalho do painel


def test_conversa_liga_cada_resposta_a_sua_mensagem(circle, painel):
    zero = kit_project_id(circle.store, "circulo")
    post(painel + "/api/pedido", {"texto": "Priorize corrigir erros", "projeto": str(zero)}, {"X-Circulo": "1"})
    circle.tick()
    c = estado(circle.store, zero)["conversa"]
    assert c[-1]["texto"] == "Priorize corrigir erros" and c[-1]["status"] == "done"
    assert "item #" in c[-1]["respostas"][0]["message"]

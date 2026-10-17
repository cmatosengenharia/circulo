import json
import threading
import urllib.error
import urllib.request

import pytest

from circulo.painel import estado, serve
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

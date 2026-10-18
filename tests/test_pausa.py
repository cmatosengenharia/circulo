"""Pausar missão por missão: o loop e as outras missões seguem; a pausada não gasta, não muda e guarda os pedidos."""
import json

import pytest

from circulo import pausa

from test_engine import FakeGen, motor  # noqa: F401 — fixture do motor
from test_painel import post


def test_missao_pausada_nao_entra_em_ciclo_e_volta_ao_retomar(motor):  # noqa: F811
    c, _, pid = motor
    assert pid in [x["id"] for x in c.engine.candidates()]
    st = pausa.pausar(c.store, pid)
    assert st["estado"] == "pausada" and st["pausada"]
    assert pid not in [x["id"] for x in c.engine.candidates()]
    r = c.engine.cycle(pid)                                          # mesmo chamada direto, não começa
    assert r.fase == "pausada" and not c.store.one("SELECT 1 FROM cycles WHERE project_id=?", (pid,))
    assert "pausou a missão" in c.store.one("SELECT message FROM alerts WHERE kind='controle' ORDER BY id DESC")["message"]
    pausa.retomar(c.store, pid)
    assert pid in [x["id"] for x in c.engine.candidates()]
    assert "retomou" in c.store.one("SELECT message FROM alerts WHERE kind='controle' ORDER BY id DESC")["message"]
    rel = [e["relacao"] for e in map(dict, c.store.q("SELECT relacao FROM elos WHERE de=? ORDER BY id", (f"missao:{pid}",)))]
    assert rel == ["pausada", "retomada"]                            # fica no rastro da missão


def test_pausa_no_meio_do_ciclo_nao_aplica_o_resultado(motor):  # noqa: F811
    c, _, pid = motor
    gen = FakeGen()
    c.ctx.dl.llm = gen
    c.engine.cycle(pid)                                              # pesquisa + régua
    vistos = {}

    class PausaNoMeio(FakeGen):
        def generate(self, *, system, prompt, model, max_tokens, web_search=0):
            if "Builder" in system and not vistos:
                vistos["estado"] = pausa.pausar(c.store, pid)["estado"]   # você pausa enquanto o Builder trabalha
            return super().generate(system=system, prompt=prompt, model=model, max_tokens=max_tokens, web_search=web_search)
    c.ctx.dl.llm = PausaNoMeio()
    r = c.engine.cycle(pid)
    assert vistos["estado"] == "parando"                             # o ciclo em curso ainda não terminou
    assert r.aceita is False and "pausada no meio do ciclo" in r.nota
    assert c.engine.current(pid) is None                             # nenhuma versão passou a valer
    assert c.store.one("SELECT status FROM deliverables WHERE project_id=?", (pid,))["status"] == "descartada"
    assert pausa.estado(c.store, pid)["estado"] == "pausada"         # confirmada pelo motor ao terminar


def test_pedidos_da_missao_pausada_ficam_guardados(motor):  # noqa: F811
    c, _, pid = motor
    pausa.pausar(c.store, pid)
    c.store.enqueue("mensagem", {"text": "Use tons de azul no topo", "projeto": pid})
    outro = c.store.enqueue("novo_projeto", {"pedido": "Crie um guia de viagem para Ouro Preto"})
    assert c.store.pending_count() == 1                              # só o que pode andar conta
    ev = c.store.claim_next_event()
    assert ev["id"] == outro                                         # a missão nova anda; o pedido guardado espera
    assert pausa.estado(c.store, pid)["pedidos_guardados"] == 1
    pausa.retomar(c.store, pid)
    ev = c.store.claim_next_event()
    assert json.loads(ev["payload"])["projeto"] == pid               # ao retomar, é atendido


def test_o_proprio_loop_nao_se_pausa_por_missao(circle):
    from circulo.projects import kit_project_id
    with pytest.raises(ValueError, match="Pausar o loop"):
        pausa.pausar(circle.store, kit_project_id(circle.store, "circulo"))


def test_api_e_card_da_pausa(motor):  # noqa: F811
    from circulo.painel import serve
    from circulo.projects import cards
    c, _, pid = motor
    srv = serve(c.store.path, port=0, background=True)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        code, r = post(base + "/api/missao/pausa", {"id": pid, "acao": "pausar"}, {"X-Circulo": "1"})
        assert code == 200 and r["estado"] == "pausada"
        card = next(x for x in cards(c.store) if x["id"] == pid)
        assert card["pausa"]["pausada"]
        code, _ = post(base + "/api/missao/pausa", {"id": pid, "acao": "pausar"})       # sem o cabeçalho do painel
        assert code == 403
        code, r = post(base + "/api/missao/pausa", {"id": pid, "acao": "retomar"}, {"X-Circulo": "1"})
        assert code == 200 and r["estado"] == "rodando"
    finally:
        srv.shutdown()


def test_central_de_confianca_mostra_missoes_pausadas(motor):  # noqa: F811
    from circulo.confianca import confianca
    c, _, pid = motor
    pausa.pausar(c.store, pid)
    ck = {x["id"]: x for x in confianca(c.store)["checks"]}
    assert ck["missoes_pausadas"]["valor"] == "1 missão(ões)"


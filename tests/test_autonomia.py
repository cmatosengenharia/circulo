"""Autonomia: missões em paralelo, missões que se conhecem e evidência de acerto antes de avançar."""
import threading
import time

import pytest

from circulo.decision import LocalJev
from circulo.llm import LLMResult
from circulo.loop import Circle
from test_engine import LANDING_V1, LANDING_V2, FakeGen


class SlowGen(FakeGen):
    """Cada geração demora 0,3s; registra quantas rodam ao mesmo tempo."""

    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.agora = 0
        self.pico = 0

    def generate(self, **kw):
        with self.lock:
            self.agora += 1
            self.pico = max(self.pico, self.agora)
        time.sleep(0.3)
        try:
            return super().generate(**kw)
        finally:
            with self.lock:
                self.agora -= 1


def nova(c, pedido):
    c.submit_project(pedido)
    c.tick()
    return c.store.one("SELECT id FROM projects ORDER BY id DESC LIMIT 1")["id"]


@pytest.fixture
def eco(tmp_path, clock):
    gen = SlowGen()
    c = Circle(tmp_path, jev=LocalJev(), llm=gen, now=clock)
    lp = nova(c, "Crie uma landing page para captar leads de fotógrafos no Instagram")
    portal = nova(c, "Crie um portal admin para fotógrafos gerenciarem leads e clientes")
    plano = nova(c, "Monte um plano para a construção da casa no lote")
    return c, gen, lp, portal, plano


def test_missoes_evoluem_em_paralelo(eco):
    c, gen, lp, portal, plano = eco
    t0 = time.time()
    res = c.engine.run_parallel()
    dt = time.time() - t0
    assert len(res) == 3 and gen.pico >= 2                    # pesquisas rodaram ao mesmo tempo
    assert dt < 3 * 2 * 0.3 + 0.5                             # mais rápido que em fila (3 missões × 2 gerações)
    assert {r.project_id for r in res} == {lp, portal, plano}
    trilha = {r["project_id"] for r in c.store.q("SELECT project_id FROM trail WHERE etapa='projeto'")}
    assert {lp, portal, plano} <= trilha


def test_paralelo_respeita_orcamento(eco):
    c, gen, *_ = eco
    c.ctx.budget.charge(c.ctx.budget.limit - c.ctx.budget.reserve - 10_000)
    assert len(c.engine.run_parallel()) == 1                  # só cabe um ciclo no que sobrou


def test_missoes_se_conhecem_ao_nascer(eco):
    c, gen, lp, portal, plano = eco
    lig = {x["id"]: x["relacao"] for x in c.graph.ligadas(lp)}
    assert lig.get(portal) == "complementa" and plano not in lig
    assert "Jev" in c.graph.ligadas(portal)[0]["evidencia"]


def test_integracao_vira_criterio_e_contexto_compartilhado(eco):
    c, gen, lp, portal, plano = eco
    c.engine.cycle(portal)                                    # portal pesquisa e monta régua
    c.engine.cycle(lp)                                        # landing pesquisa e monta régua
    rub = c.engine.rubric(lp)
    integ = [x for x in rub["criteria"] if x.get("integracao") == portal]
    assert integ and "Portal admin" in integ[0]["texto"]
    c.engine.cycle(portal)                                    # portal ganha entrega
    ctxt = c.graph.contexto(lp)
    assert "Portal admin" in ctxt and "Entrega atual v1" in ctxt
    c.engine.cycle(lp)
    builder_prompts = [x for x in gen.calls if x[0].startswith("Você é o Builder")]
    assert builder_prompts                                    # o Builder da landing trabalhou com o contexto do portal


def test_memoria_compartilhada_entre_missoes_ligadas(eco):
    c, gen, lp, portal, plano = eco
    c.memory.add("achado", "Fotógrafos respondem melhor a formulários com WhatsApp", tipo="produto_software",
                 project_id=portal, trust="nao_confiavel")
    r = c.memory.search("formulário whatsapp fotógrafos", kinds=("achado",), tipo="landing_page", project_id=lp,
                        also=c.graph.ids_ligados(lp))
    assert any("WhatsApp" in x["text"] for x in r)
    r2 = c.memory.search("formulário whatsapp fotógrafos", kinds=("achado",), tipo="plano", project_id=plano,
                         also=c.graph.ids_ligados(plano))
    assert not any("WhatsApp" in x["text"] for x in r2)       # missão sem ligação não enxerga


def test_licao_confirmada_viaja_para_missao_ligada(eco):
    c, gen, lp, portal, plano = eco
    lid = c.memory.add("licao", "Pôr prova social perto do botão", tipo="landing_page", project_id=lp, status="quarentena")
    ativ = c.memory.lesson_outcome([lid], gain=0.1, min_gain=0.02)
    assert ativ == [lid]
    assert c.graph.transferir(lid) == 1
    copia = c.store.one("SELECT * FROM memory WHERE kind='licao' AND project_id=?", (portal,))
    assert copia["status"] == "quarentena" and copia["tipo"] == "produto_software"   # chega para ser testada, não imposta


def test_evidencia_registrada_em_cada_avanco(eco):
    c, gen, lp, portal, plano = eco
    for _ in range(3):
        c.engine.cycle(lp)
    ev = c.store.q("SELECT * FROM evidence WHERE project_id=? ORDER BY id", (lp,))
    assert [e["decisao"] for e in ev] == ["base", "avancar"]
    assert ev[1]["depois"] > ev[1]["antes"] and ev[1]["jev_avanca"] >= 0.6 and ev[1]["jev_contraprova"] <= 0.4
    assert "Jev avança" in ev[1]["motivo"]


def test_jev_que_se_contradiz_nao_avanca(eco, monkeypatch):
    c, gen, lp, portal, plano = eco
    c.engine.cycle(lp)
    c.engine.cycle(lp)
    real = c.ctx.dl.ask_many

    def contraditorio(state, questions):
        out = real(state, questions)
        if "contraprova" in questions:
            from circulo.decision import Decision
            out["contraprova"] = Decision("contraprova", "noul", 0.9, 0.8, "local")   # "piorou" — contradiz o avanço
        return out

    monkeypatch.setattr(c.ctx.dl, "ask_many", contraditorio)
    r = c.engine.cycle(lp)
    assert r.aceita is False and "autoconsistência" in r.nota
    assert c.store.one("SELECT decisao FROM evidence WHERE project_id=? ORDER BY id DESC LIMIT 1", (lp,))["decisao"] == "refazer"


def test_missao_cumprida_quando_bate_a_meta_duas_vezes(tmp_path, clock):
    class Perfeito(FakeGen):
        def generate(self, **kw):
            r = super().generate(**kw)
            if "Builder" in kw["system"] or "Improver" in kw["system"]:
                html = LANDING_V2.replace("</body>", "<p>Botão de chamada para ação visível no topo. Mostra prova social com números. "
                                                     "Tem formulário com no máximo 3 campos. Exibe depoimento de cliente.</p></body>")
                return LLMResult(html, r.tokens, r.model)
            return r

    c = Circle(tmp_path, jev=LocalJev(), llm=Perfeito(), now=clock)
    lp = nova(c, "Crie uma landing page para captar leads do Instagram")
    from circulo.policy import PolicyStore
    pol = c.ctx.policies
    pol.add_version(PolicyStore.patched(pol.get(), [{"op": "set", "path": "portfolio.target_score", "value": 0.6}]), "active", "teste")
    for _ in range(4):
        c.engine.cycle(lp)
        if c.store.one("SELECT status FROM projects WHERE id=?", (lp,))["status"] == "cumprida":
            break
    assert c.store.one("SELECT status FROM projects WHERE id=?", (lp,))["status"] == "cumprida"
    assert c.store.one("SELECT 1 FROM evidence WHERE project_id=? AND decisao='cumprida'", (lp,))
    assert lp not in [x["id"] for x in c.engine.candidates()]      # sai da fila; volta só por pesquisa/tempo


def test_nenhuma_mensagem_do_loop_pede_acao_sua(eco):
    c, gen, *_ = eco
    for _ in range(15):
        c.tick()
    pedidos = c.store.q("SELECT message FROM alerts WHERE message LIKE '%responda%' OR message LIKE '%aguarda você%' "
                        "OR message LIKE '%confere?%'")
    assert pedidos == []


_ = LANDING_V1


def test_missao_ligada_que_muda_reabre_a_outra(eco):
    c, gen, lp, portal, plano = eco
    c.store.x("UPDATE projects SET status='manutencao' WHERE id=?", (lp,))
    c.engine.cycle(portal)
    c.engine.cycle(portal)          # portal ganha v1
    assert c.store.one("SELECT status FROM projects WHERE id=?", (lp,))["status"] == "ativo"
    assert c.store.one("SELECT status FROM projects WHERE id=?", (plano,))["status"] == "ativo"   # (não estava parado)

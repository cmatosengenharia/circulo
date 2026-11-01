"""Da pergunta validada ao item no mesmo giro: o Planejador é chamado logo após a validação, repete UMA vez (com
espera curta e jitter) só em 5xx ou timeout, reagenda com prazo em vez de esperar o idle_task, nunca duplica o item e
deixa na trilha cada sub-etapa com o id da pergunta (lição #15: o item nunca perde a cadeia até a pergunta)."""
import json
import time
import urllib.error

import pytest

from circulo import indagador
from circulo import planejador as pl
from circulo.planejador import Planejador
from test_planejador import EXPERIMENTO


class Dev:
    def em_espera(self):
        return False


class ErroHTTP(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


class LLMSeq:
    """Levanta as exceções da sequência, na ordem; depois responde com um item."""
    def __init__(self, *falhas, titulo="Item da pergunta validada"):
        self.falhas = list(falhas)
        self.chamadas = 0
        self.titulo = titulo

    def complete(self, system, prompt, max_tokens):
        self.chamadas += 1
        if self.falhas:
            raise self.falhas.pop(0)
        return json.dumps({"titulo": self.titulo, "detalhe": "mudar x", "sucesso": "y", "experimento": EXPERIMENTO}), 400


@pytest.fixture
def esperas(monkeypatch):
    feitas = []
    monkeypatch.setattr(pl, "dormir", feitas.append)
    return feitas


def _plan(circle, llm):
    circle.store.x("UPDATE roadmap SET status='feito'")
    circle.store.set("conselho_gerado", {"em": time.time()})    # o Questionador já rodou hoje: não consome a falha roteirizada
    circle.ctx.dl.llm = llm
    return Planejador(circle.ctx, Dev())


def _pergunta(circle, texto="q?"):
    t = time.time()
    return circle.store.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,score,created_at,updated_at) "
                          "VALUES('k','operador',?,'valida','loop',0.5,?,?)", (texto, t, t))


def _itens(circle):
    return circle.store.q("SELECT id, detalhe FROM roadmap WHERE origem='loop'")


def test_pergunta_validada_vira_item_no_mesmo_giro_com_a_cadeia_inteira(circle, monkeypatch, esperas):
    """Lição #15: validada → porteiro → planejador → item no mesmo giro, cada evento com o id da pergunta."""
    circle.store.x("UPDATE roadmap SET status='feito'")
    circle.ctx.dl.llm = LLMSeq()
    circle.planejador.dev = Dev()
    cand = {"chave": "funil:pergunta_para_item", "persona": "operador", "texto": "Onde a espera da etapa está?",
            "relevancia": 0.9, "evidencia": {"base": "medido"}}
    monkeypatch.setattr(indagador, "candidatas", lambda ctx, project: [dict(cand)])
    monkeypatch.setattr(indagador, "classificar", lambda ctx, cands, ctxt: [
        {**c, "veredito": "valida", "eixo": "velocidade", "pertinencia": 0.9, "acionavel": 2, "classificacao": {}} for c in cands])
    circle._run_idle_task("indagar")
    p = circle.store.one("SELECT id, status, item_id FROM perguntas WHERE chave='funil:pergunta_para_item'")
    assert p["status"] == "virou_item" and p["item_id"]
    assert f"#{p['id']}" in circle.store.one("SELECT detalhe FROM roadmap WHERE id=?", (p["item_id"],))["detalhe"]
    etapas = [e["etapa"] for e in pl.eventos(circle.store, p["id"])]
    assert etapas == ["validada", "porteiro_decidiu", "planejador_chamado", "item_gravado"]


@pytest.mark.parametrize("falha", [ErroHTTP(502), ErroHTTP(503), TimeoutError("sem resposta")])
def test_5xx_e_timeout_sao_repetidos_uma_vez_com_espera_curta_e_jitter(circle, esperas, falha):
    pid = _pergunta(circle)
    llm = LLMSeq(falha)
    item = _plan(circle, llm).run()
    assert item and llm.chamadas == 2
    assert len(esperas) == 1 and pl.ESPERA_RETRY <= esperas[0] <= pl.ESPERA_RETRY + pl.JITTER <= 10
    tentativas = [e["detalhe"] for e in pl.eventos(circle.store, pid) if e["etapa"] == "planejador_chamado"]
    assert [t["tentativa"] for t in tentativas] == [1, 2] and tentativas[1]["motivo"] in ("5xx", "timeout")


def test_5xx_duas_vezes_reagenda_com_prazo_em_vez_de_esperar_o_idle_task(circle, esperas):
    pid = _pergunta(circle)
    llm = LLMSeq(ErroHTTP(502), ErroHTTP(502))
    plan = _plan(circle, llm)
    with pytest.raises(ErroHTTP):
        plan.run()
    assert llm.chamadas == 2                                       # só uma nova tentativa no cliente, nada além
    reag = circle.store.get(pl.REAGENDA)
    assert reag["pergunta_id"] == pid and 0 < reag["vence_em"] - time.time() <= 15 * 60
    assert plan.no_giro() is None                                   # ainda não venceu: o giro não repete
    circle.store.set(pl.REAGENDA, {**reag, "vence_em": time.time() - 1})
    assert plan.no_giro() and circle.store.one("SELECT status FROM perguntas WHERE id=?", (pid,))["status"] == "virou_item"


def test_reagendamento_vencido_sai_do_kv_mesmo_com_o_planejador_travado(circle, esperas):
    plan = _plan(circle, LLMSeq())
    plan.dev = None                                                 # travado: sem Developer
    circle.store.set(pl.REAGENDA, {"pergunta_id": _pergunta(circle), "vence_em": time.time() - 1})
    assert plan.no_giro() is None
    assert not circle.store.get(pl.REAGENDA)                        # senão o loop acha que sempre há trabalho


def test_4xx_nao_e_repetido_nem_reagendado(circle, esperas):
    pid = _pergunta(circle)
    llm = LLMSeq(urllib.error.HTTPError("u", 400, "bad request", None, None))
    with pytest.raises(urllib.error.HTTPError):
        _plan(circle, llm).run()
    assert llm.chamadas == 1 and esperas == []
    assert not circle.store.get(pl.REAGENDA)
    assert circle.store.one("SELECT status FROM perguntas WHERE id=?", (pid,))["status"] == "quarentenada"


def test_item_nao_e_duplicado_quando_a_pergunta_volta_para_a_fila(circle, esperas):
    pid = _pergunta(circle)
    plan = _plan(circle, LLMSeq())
    item = plan.run()
    circle.store.x("UPDATE perguntas SET status='valida' WHERE id=?", (pid,))    # a mesma pergunta de novo (retry)
    plan.ctx.dl.llm = LLMSeq(titulo="Outro título para a mesma pergunta")
    plan.run()
    assert [r["id"] for r in _itens(circle)] == [item["id"]]
    assert [e["etapa"] for e in pl.eventos(circle.store, pid)].count("item_gravado") == 1


def test_cada_passagem_tem_a_espera_atribuida_a_uma_sub_etapa(circle, esperas):
    pid = _pergunta(circle)
    pl.marcar_etapa(circle.store, pid, "validada")
    _plan(circle, LLMSeq(ErroHTTP(500))).run()
    passagens = pl.esperas(circle.store, pid)
    assert passagens and all(p["etapa"] in pl.ETAPAS and p["espera_s"] >= 0 and p["pergunta_id"] == pid for p in passagens)
    assert [p["etapa"] for p in passagens] == ["porteiro_decidiu", "planejador_chamado", "planejador_chamado", "item_gravado"]

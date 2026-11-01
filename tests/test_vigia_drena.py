"""Vigia drena sozinho a pergunta validada mais antiga quando a fila passa do prazo: 1 por ciclo, sem repetir a que
falhou, e com disjuntor quando o planejador falha seguidas vezes (falha sistêmica não esvazia a fila às cegas)."""
import json
import time

from circulo import vigia
from circulo.planejador import SYSTEM, Planejador
from test_planejador import EXPERIMENTO


class LLMItem:
    def __init__(self):
        self.n = 0

    def complete(self, system, prompt, max_tokens):
        if system != SYSTEM:                                                 # o Questionador também chama a LLM
            return "{}", 10
        self.n += 1
        return json.dumps({"titulo": f"Item novo {self.n}", "detalhe": "mudar x", "sucesso": "y", "experimento": EXPERIMENTO}), 400


class LLMFalha:
    def __init__(self):
        self.pedidos = []

    def complete(self, system, prompt, max_tokens):
        if system == SYSTEM:
            self.pedidos.append(prompt)
        raise ConnectionError("rede fora")


def _seis_paradas(circle, ha_min=50):
    agora = time.time()
    return [circle.store.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,score,created_at,updated_at) "
                           "VALUES(?,?,?,'valida','loop',?,?,?)",
                           (f"k{i}", "operador", f"pergunta {i}?", 0.9 - i * 0.1, agora - (ha_min + i) * 60, agora - (ha_min + i) * 60))
            for i in range(6)]


def _vigia(circle, llm):
    circle.ctx.dl.llm = llm
    v = vigia.Vigia(circle.ctx)
    v.planejador = Planejador(circle.ctx, None)
    return v


def _validas(circle):
    return circle.store.one("SELECT COUNT(*) n FROM perguntas WHERE status='valida'")["n"]


def test_cada_ciclo_drena_a_pergunta_mais_antiga_e_o_item_guarda_o_id_dela(circle):
    ids = _seis_paradas(circle)
    v = _vigia(circle, LLMItem())
    for n in range(6, 2, -1):
        v.rodar()
        assert _validas(circle) == n - 1                                     # cada ciclo reduz a fila em 1
    mais_antiga = ids[-1]                                                    # a de menor score: a idade decide, não o score
    r = circle.store.one("SELECT status, item_id FROM perguntas WHERE id=?", (mais_antiga,))
    assert r["status"] == "virou_item" and r["item_id"]
    item = circle.store.one("SELECT detalhe, evidencia FROM roadmap WHERE id=?", (r["item_id"],))
    assert f"#{mais_antiga}" in item["detalhe"] and f"#{mais_antiga}" in item["evidencia"]


def test_pergunta_recente_nao_e_drenada(circle):
    _seis_paradas(circle, ha_min=35)                                         # já é trava (> 31 min), ainda não passou do prazo
    llm = LLMItem()
    _vigia(circle, llm).rodar()
    assert llm.n == 0 and _validas(circle) == 6


def test_falha_registra_a_tentativa_e_o_ciclo_seguinte_tenta_outra_pergunta(circle):
    ids = _seis_paradas(circle)
    llm = LLMFalha()
    v = _vigia(circle, llm)
    tentadas = []
    for _ in range(vigia.DISJUNTOR):
        v.rodar()
        d = circle.store.get(vigia.DRENAGEM)
        tentadas.append(d["ultima"]["pergunta_id"])
        assert d["ultima"]["desfecho"] == "falhou" and "rede fora" in d["ultima"]["motivo"]
    assert tentadas == list(reversed(ids))[:vigia.DISJUNTOR]                # da mais antiga para a mais nova, sem repetir
    assert len(llm.pedidos) == vigia.DISJUNTOR


def test_falhas_seguidas_abrem_o_disjuntor_e_param_de_chamar_o_planejador(circle):
    _seis_paradas(circle)
    llm = LLMFalha()
    v = _vigia(circle, llm)
    for _ in range(vigia.DISJUNTOR + 3):
        v.rodar()
    assert len(llm.pedidos) == vigia.DISJUNTOR                               # falha sistêmica: pausa em vez de queimar a fila
    d = circle.store.get(vigia.DRENAGEM)
    assert d["pausa_ate"] > time.time()
    assert circle.store.one("SELECT COUNT(*) n FROM alerts WHERE message LIKE 'Vigia: drenagem pausada%'")["n"] == 1

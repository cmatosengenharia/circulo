"""Detector de travamento por padrões (portado do StuckDetector do OpenHands): o Vigia nomeia o padrão e o limiar."""
import json
import time

from circulo import vigia
from circulo.decision import Decision
from circulo.estagnacao import ESTAGNADO, anotar_giro


def _ev(acao, resultado="sem avanço", **extra):
    return {"acao": acao, "resultado": resultado, **extra}


def test_quatro_padroes_sinteticos_e_uma_sequencia_saudavel():
    assert (vigia.REPETICAO, vigia.ERRO_REPETIDO, vigia.MONOLOGO, vigia.ALTERNANCIA) == (4, 3, 3, 6)   # limiares do OpenHands
    rep = [_ev("resumo", "sem avanço", em=i, id=i) for i in range(vigia.REPETICAO)]      # ids e tempo não contam
    assert vigia.detectar_travamento(rep) == {"padrao": "acao_repetida", "ciclos": 4, "limiar": 4}
    assert vigia.detectar_travamento(rep[1:]) is None
    erro = [_ev("corrigir_codigo", f"erro em developer #{i} 12:0{i}") for i in range(vigia.ERRO_REPETIDO)]
    assert vigia.detectar_travamento(erro) == {"padrao": "erro_repetido", "ciclos": 3, "limiar": 3}
    assert vigia.detectar_travamento(erro[1:]) is None
    mono = [_ev(None)] * vigia.MONOLOGO
    assert vigia.detectar_travamento(mono) == {"padrao": "monologo", "ciclos": 3, "limiar": 3}
    assert vigia.detectar_travamento(mono[1:]) is None
    alt = [_ev("resumo"), _ev("rodar_regressao")] * (vigia.ALTERNANCIA // 2)
    assert vigia.detectar_travamento(alt) == {"padrao": "alternancia", "ciclos": 6, "limiar": 6}
    assert vigia.detectar_travamento(alt[1:]) is None
    saudavel = [_ev("resumo"), _ev("rodar_regressao"), _ev("analisar_padroes"), _ev("resumo"), _ev("corrigir_codigo", "erro em gate")]
    assert vigia.detectar_travamento(saudavel) is None
    assert vigia.detectar_travamento([]) is None


def test_giro_parado_vira_evento_e_o_disparo_grava_o_padrao(circle):
    class R:
        idle_task, handled_event, errors = "rodar_regressao", None, ["developer: falhou o teste 3"]
    st = {"sem": 0}
    for _ in range(ESTAGNADO):
        anotar_giro(st, R())
    assert st["eventos"][-1] == {"acao": "rodar_regressao", "resultado": "erro em developer"}

    class Jev:
        source, ultimo_modelo = "jev", "jev-1.13.0"

        def ask_many(self, state, qs):
            return {qid: Decision(qid, "noul", 0.9, 0.9, "jev") if q.kind == "noul" else Decision(qid, "choice", "alertar", 0.9, "jev")
                    for qid, q in qs.items()}, 10
    s = circle.store
    circle.ctx.dl.jev = Jev()
    s.set("progresso", {**st, "sem": ESTAGNADO, "recusas": {}})
    vigia.Vigia(circle.ctx).rodar(time.time())
    d = s.one("SELECT * FROM vigia_disparos WHERE chave='estagnacao'")
    assert d["padrao"] == "erro_repetido" and json.loads(d["evidencia"])["padrao"]["limiar"] == vigia.ERRO_REPETIDO
    t = s.one("SELECT titulo FROM vigia WHERE chave='estagnacao'")["titulo"]
    assert "erro_repetido" in t and f"limiar {vigia.ERRO_REPETIDO}" in t          # o card de travamento mostra o título
    assert vigia.padrao_7d(s, "estagnacao") == {"disparos": 1, "com_padrao": 1, "fracao": 1.0, "alvo": vigia.ALVO_PADRAO}
    assert vigia.resumo(s)["padrao_7d"]["estagnacao"]["com_padrao"] == 1


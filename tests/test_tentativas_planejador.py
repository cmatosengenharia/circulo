"""Cada tentativa real do planejador deixa registro (pergunta, first_seen_at, tentativas, classe da falha, motivo);
a pergunta validada vira item ou vai para a quarentena com motivo, sem esperar sem fim; o Vigia cita o resultado."""
import json
import time

import pytest

from circulo import planejador as pl
from circulo import vigia
from circulo.planejador import Planejador
from test_planejador import EXPERIMENTO


class LLMFalha:
    def __init__(self, exc):
        self.exc = exc

    def complete(self, system, prompt, max_tokens):
        raise self.exc


class LLMItem:
    def complete(self, system, prompt, max_tokens):
        return json.dumps({"titulo": "Item novo da pergunta antiga", "detalhe": "mudar x", "sucesso": "y",
                           "experimento": EXPERIMENTO}), 400


def _pergunta(circle, ha_s):
    t = time.time() - ha_s
    return circle.store.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,score,created_at,updated_at) "
                          "VALUES('k','arquiteto','q?','valida','loop',0.5,?,?)", (t, t))


def _plan(circle, llm):
    circle.ctx.dl.llm = llm
    return Planejador(circle.ctx, None)


def _status(circle, pid):
    return circle.store.one("SELECT status, motivo FROM perguntas WHERE id=?", (pid,))


def test_pergunta_com_843_min_de_espera_e_quarentenada_com_motivo_na_primeira_falha(circle):
    pid = _pergunta(circle, 843 * 60)
    with pytest.raises(TimeoutError):
        _plan(circle, LLMFalha(TimeoutError("LLM não respondeu"))).run(autorizado=True)
    u = circle.store.get(pl.TENTATIVAS)["ultima"]
    assert u["pergunta_id"] == pid and u["tentativas"] == 1 and u["classe_da_falha"] == "transitoria"
    assert u["first_seen_at"] < time.time() - 842 * 60 and "LLM não respondeu" in u["motivo"]
    r = _status(circle, pid)
    assert r["status"] == "quarentenada" and "LLM não respondeu" in r["motivo"]
    assert "pergunta_valida_parada" not in {a["chave"] for a in vigia.sondar(circle.store)}


def test_pergunta_com_843_min_de_espera_vira_item_quando_a_tentativa_da_certo(circle):
    pid = _pergunta(circle, 843 * 60)
    item = _plan(circle, LLMItem()).run(autorizado=True)
    assert item and _status(circle, pid)["status"] == "virou_item"
    reg = circle.store.get(pl.TENTATIVAS)
    assert reg["ultima"]["desfecho"] == "virou_item" and reg["ultima"]["classe_da_falha"] is None
    assert time.time() - reg["ultimo_progresso_em"] < 60


def test_falha_transitoria_devolve_a_pergunta_e_quarentena_na_quarta_tentativa(circle):
    pid = _pergunta(circle, 60)
    plan = _plan(circle, LLMFalha(ConnectionError("rede fora")))
    for n in range(1, pl.MAX_TENTATIVAS):
        with pytest.raises(ConnectionError):
            plan.run(autorizado=True)
        assert _status(circle, pid)["status"] == "valida"                    # volta para a fila: a próxima tentativa a pega
        assert circle.store.get(pl.TENTATIVAS)["ultima"]["tentativas"] == n
    with pytest.raises(ConnectionError):
        plan.run(autorizado=True)
    r = _status(circle, pid)
    assert r["status"] == "quarentenada" and "4 tentativas" in r["motivo"]


def test_falha_permanente_quarentena_na_hora(circle):
    pid = _pergunta(circle, 60)
    with pytest.raises(KeyError):
        _plan(circle, LLMFalha(KeyError("campo"))).run(autorizado=True)
    assert circle.store.get(pl.TENTATIVAS)["ultima"]["classe_da_falha"] == "permanente"
    assert _status(circle, pid)["status"] == "quarentenada"


def test_vigia_cita_a_ultima_tentativa_real_e_nao_o_intervalo(circle):
    s = circle.store
    pid = _pergunta(circle, vigia.ESPERA_PERGUNTA + vigia.INTERVALO + 60)
    s.set(pl.GATE, {"em": time.time(), "motivo": "intervalo: última tentativa há 27 s (espera 900 s)"})
    pl.registrar_tentativa(s, pid, "falhou", "OSError: disco cheio", classe="desconhecida", now=time.time() - 27)
    s.x("UPDATE perguntas SET status='valida' WHERE id=?", (pid,))
    a = {x["chave"]: x for x in vigia.sondar(s)}["pergunta_valida_parada"]
    assert "intervalo" not in a["sugestao"] and "disco cheio" in a["sugestao"] and "desconhecida" in a["sugestao"]
    assert a["evidencia"]["ultima_tentativa"]["pergunta_id"] == pid
    assert "sem_progresso_min" in a["evidencia"] and "último progresso" in a["titulo"]

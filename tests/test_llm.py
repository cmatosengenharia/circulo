"""Retry de neurônio (pergunta #563): no máximo 1, só para causa transitória por regra, com os tokens do retry gravados."""
from __future__ import annotations

import subprocess
import time

import pytest

from circulo import llm_cache, registro
from circulo.llm import MAX_RETRY, LLMResult, causa_da_falha
from circulo.state import Store


class LLMQueFalha:
    """Falha com `erro` nas primeiras `falhas` chamadas; depois responde com 300 tokens."""

    def __init__(self, erro: BaseException, falhas: int = 1):
        self.erro, self.falhas, self.chamadas = erro, falhas, 0

    def generate(self, *, system, prompt, model, max_tokens, web_search=0):
        self.chamadas += 1
        if self.chamadas <= self.falhas:
            raise self.erro
        return LLMResult("ok", 0, model, entrada=200, saida=100)


def _gerar(store, llm):
    return llm_cache.gerar(store, llm, papel="builder", project_id=1, system="sys", prompt="faça X", model="m", max_tokens=100)


def _linhas(store):
    return [dict(r) for r in store.q("SELECT ok, retry, tokens FROM llm_calls ORDER BY id")]


def test_causa_por_regra_timeout_e_saida_invalida_sao_transitorias():
    assert causa_da_falha(subprocess.TimeoutExpired("claude", 600)) == "transitoria"
    assert causa_da_falha(TimeoutError("timed out")) == "transitoria"
    assert causa_da_falha(ValueError("JSONDecodeError: Expecting value: line 1 column 1")) == "transitoria"
    assert causa_da_falha(KeyError("falta_chave")) == "deterministica"
    assert causa_da_falha(RuntimeError("provedor caiu")) == "desconhecida"


def test_causa_desconhecida_nao_gera_retry():
    s, llm = Store(), LLMQueFalha(RuntimeError("provedor caiu"))
    with pytest.raises(RuntimeError):
        _gerar(s, llm)
    assert llm.chamadas == 1
    assert _linhas(s) == [{"ok": 0, "retry": 0, "tokens": 0}]


def test_causa_deterministica_nao_gera_retry():
    s, llm = Store(), LLMQueFalha(KeyError("falta_chave"))
    with pytest.raises(KeyError):
        _gerar(s, llm)
    assert llm.chamadas == 1


def test_transitoria_gera_exatamente_um_retry_e_os_tokens_dele_ficam_registrados():
    s, llm = Store(), LLMQueFalha(TimeoutError("timed out"))
    out = _gerar(s, llm)
    assert out.text == "ok" and llm.chamadas == 2
    assert _linhas(s) == [{"ok": 0, "retry": 0, "tokens": 0}, {"ok": 1, "retry": 1, "tokens": 300}]
    assert registro.tokens_retry(s) == {"builder": 300}


def test_tokens_retry_7d_por_papel_aparecem_na_metrica_falha_neuronio():
    from circulo.perguntas import METRICAS
    s = Store()
    _gerar(s, LLMQueFalha(TimeoutError("timed out")))
    s.x("INSERT INTO verificacoes(tick,ponto,ok,motivo,created_at) VALUES(0,'builder',0,'TimeoutError: timed out',?)",
        (time.time(),))
    _, ctx = METRICAS["falha_neuronio"][1](s, time.time())
    assert ctx["tokens_retry_7d"] == {"builder": 300}


def test_transitoria_que_volta_a_falhar_para_no_primeiro_retry():
    s, llm = Store(), LLMQueFalha(TimeoutError("timed out"), falhas=5)
    with pytest.raises(TimeoutError):
        _gerar(s, llm)
    assert MAX_RETRY == 1 and llm.chamadas == 2
    assert [r["retry"] for r in _linhas(s)] == [0, 1]

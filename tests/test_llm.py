"""Retry de neurônio (pergunta #563): no máximo 1, só para causa transitória por regra, com os tokens do retry gravados.
A/B de modelo menor por papel (item #320): flag desligada por padrão, balde por hash salgado, variante gravada, reversão."""
from __future__ import annotations

import json
import subprocess
import time

import pytest

from circulo import llm as modelos
from circulo import llm_cache, registro
from circulo.llm import MAX_RETRY, LLMResult, causa_da_falha
from circulo.planejador import SYSTEM, Planejador
from circulo.self_dev import SelfDeveloper
from circulo.state import Store

from test_self_dev import TEST_CMD, FakeGH, FixAgent, repo  # noqa: F401 — fixture do repositório


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


# ---------------------------------------------------------------- A/B de modelo menor (item #320)
class PlanGen:
    def __init__(self):
        self.modelos = []

    def generate(self, *, system, prompt, model, max_tokens, web_search=0):
        if system == SYSTEM:                       # só as do Planejador: o Questionador também chama esta LLM
            self.modelos.append(model)
        return LLMResult(json.dumps({"titulo": "Pergunta do worth_spending com estado mais rico",
                                     "detalhe": "incluir histórico de aceitação no estado",
                                     "sucesso": "menos de 50% das decisões abaixo de jev_incerto"}), 400, model)


def _planejar(circle, repo):  # noqa: F811
    circle.store.x("UPDATE roadmap SET status='feito'")
    circle.ctx.dl.llm = gen = PlanGen()
    Planejador(circle.ctx, SelfDeveloper(circle.ctx, repo, FixAgent(), FakeGH(), test_cmd=TEST_CMD)).run()
    return gen, circle.store.one("SELECT modelo, variante, aceita FROM llm_calls WHERE papel='planejador' ORDER BY id DESC LIMIT 1")


def test_divisao_perto_de_10_por_cento_deterministica_e_salgada_pelo_experimento():
    menores = sum(modelos.balde("planejador", i) < modelos.FATIA_MENOR for i in range(10_000))
    assert 700 <= menores <= 1300
    assert [modelos.balde("planejador", i) for i in range(50)] == [modelos.balde("planejador", i) for i in range(50)]
    # o sal inclui o papel: outro experimento sorteia baldes independentes para os mesmos ids
    assert [modelos.balde("planejador", i) for i in range(50)] != [modelos.balde("questionador", i) for i in range(50)]


def test_flag_desligada_por_padrao_nao_muda_nada(circle, repo):  # noqa: F811
    assert modelos.variante(circle.store, "planejador", 1) is None
    gen, r = _planejar(circle, repo)
    assert r["variante"] is None and gen.modelos == [r["modelo"]]


def test_flag_ligada_grava_a_variante_e_usa_o_modelo_da_variante(circle, repo):  # noqa: F811
    modelos.ligar_modelo_menor(circle.store, "planejador")
    gen, r = _planejar(circle, repo)
    assert r["variante"] in ("controle", "menor") and r["aceita"] == 1
    assert gen.modelos == [r["modelo"]]
    assert modelos.modelo_da_variante("claude-sonnet-5-5", "menor") == "claude-haiku-5-5"
    assert modelos.modelo_da_variante("claude-sonnet-5-5", "controle") == "claude-sonnet-5-5"
    assert {modelos.variante(circle.store, "planejador", i) for i in range(200)} == {"controle", "menor"}


def _chamadas(store, var, n, falhas=0, tokens=100, aceitas=None):
    for i in range(n):
        cid = registro.registrar(store, tick=1, project_id=None, papel="planejador", modelo="m", tokens=tokens,
                                 ok=i >= falhas, variante=var)
        store.x("UPDATE llm_calls SET aceita=? WHERE id=?", (int(i < (n if aceitas is None else aceitas)), cid))


def test_reverte_com_duas_falhas_no_menor_acima_do_controle(circle):
    modelos.ligar_modelo_menor(circle.store, "planejador")
    _chamadas(circle.store, "controle", 20)
    _chamadas(circle.store, "menor", 3, falhas=1)
    assert modelos.reverter_se_preciso(circle.store, "planejador") is None          # 1 falha só: ainda não
    _chamadas(circle.store, "menor", 1, falhas=1)
    assert "falha" in modelos.reverter_se_preciso(circle.store, "planejador")
    assert modelos.variante(circle.store, "planejador", 1) is None


def test_reverte_se_tokens_por_item_aceito_nao_caem_com_n_30_por_braco(circle):
    modelos.ligar_modelo_menor(circle.store, "planejador")
    _chamadas(circle.store, "controle", 30, tokens=100)
    _chamadas(circle.store, "menor", 29, tokens=60, aceitas=10)              # 174 tokens/aceito, mas n<30
    assert modelos.reverter_se_preciso(circle.store, "planejador") is None
    _chamadas(circle.store, "menor", 1, tokens=60, aceitas=0)
    assert "tokens" in modelos.reverter_se_preciso(circle.store, "planejador")
    assert not circle.store.get("modelo_menor:planejador")["ligada"]


def test_menor_mais_barato_por_item_aceito_mantem_a_flag(circle):
    modelos.ligar_modelo_menor(circle.store, "planejador")
    _chamadas(circle.store, "controle", 30, tokens=100)
    _chamadas(circle.store, "menor", 30, tokens=60)
    assert modelos.reverter_se_preciso(circle.store, "planejador") is None
    assert modelos.variante(circle.store, "planejador", 1) is not None

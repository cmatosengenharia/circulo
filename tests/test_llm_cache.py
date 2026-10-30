"""Cache de respostas da LLM: mede em modo sombra e só serve quando a repetição medida em 24 h passa do limiar."""
from __future__ import annotations

import pytest

from circulo import llm_cache
from circulo.llm import LLMResult
from circulo.registro import marcar_resultado
from circulo.state import Store


class LLMContada:
    def __init__(self, falha: bool = False):
        self.chamadas, self.falha = 0, falha

    def generate(self, *, system, prompt, model, max_tokens, web_search=0):
        self.chamadas += 1
        if self.falha:
            raise RuntimeError("provedor caiu")
        return LLMResult(f"resposta {self.chamadas}", 0, model, entrada=100, saida=50)


def _gerar(store, llm, prompt="faça X", projeto=1):
    return llm_cache.gerar(store, llm, papel="builder", project_id=projeto, system="sys", prompt=prompt,
                           model="m", max_tokens=100)


def _aceitar(store, projeto=1):
    marcar_resultado(store, projeto, store.tick, True)


def _ligar(store):
    """Histórico de 24 h com repetição acima do limiar: o cache passa a servir."""
    for i in range(llm_cache.MIN_AMOSTRAS):
        store.x("INSERT INTO llm_cache(chave,papel,acerto_potencial,created_at) VALUES(?,?,?,strftime('%s','now'))",
                (f"h{i}", "builder", int(i % 2 == 0)))


def test_modo_sombra_registra_o_acerto_potencial_de_toda_chamada_sem_servir():
    s, llm = Store(), LLMContada()
    _gerar(s, llm)
    _aceitar(s)
    _gerar(s, llm, prompt="  faça\n X ")          # mesmo prompt depois de normalizar
    _gerar(s, llm, prompt="outra coisa")
    assert llm.chamadas == 3                      # sombra: nunca serve
    assert [r["acerto_potencial"] for r in s.q("SELECT acerto_potencial FROM llm_cache ORDER BY id")] == [0, 1, 0]
    assert llm_cache.taxa(s) == {"chamadas": 3, "acertos": 1, "taxa": pytest.approx(1 / 3), "servindo": False}


def test_chamada_nao_aceita_ou_fora_do_ttl_nao_conta_como_acerto():
    s, llm = Store(), LLMContada()
    _gerar(s, llm)                                # nunca aceita
    _gerar(s, llm)
    _aceitar(s)
    s.x("UPDATE llm_cache SET created_at=created_at-?", (llm_cache.TTL_S + 1,))
    _gerar(s, llm)
    assert [r["acerto_potencial"] for r in s.q("SELECT acerto_potencial FROM llm_cache ORDER BY id")] == [0, 0, 0]


def test_segunda_chamada_identica_vem_do_cache_e_registra_zero_tokens():
    s, llm = Store(), LLMContada()
    _ligar(s)
    primeira = _gerar(s, llm)
    _aceitar(s)
    segunda = _gerar(s, llm)
    assert llm.chamadas == 1
    assert segunda.text == primeira.text == "resposta 1"
    assert segunda.tokens == 0
    assert [r["tokens"] for r in s.q("SELECT tokens FROM llm_calls ORDER BY id")] == [150, 0]
    assert llm_cache.taxa(s)["servindo"] is True


def test_resposta_de_chamada_com_falha_nunca_e_armazenada():
    s = Store()
    _ligar(s)
    with pytest.raises(RuntimeError):
        _gerar(s, LLMContada(falha=True))
    _aceitar(s)
    assert s.one("SELECT COUNT(*) n FROM llm_cache WHERE texto IS NOT NULL")["n"] == 0
    assert s.one("SELECT ok FROM llm_calls")["ok"] == 0
    llm = LLMContada()
    assert _gerar(s, llm).text == "resposta 1" and llm.chamadas == 1


def test_resposta_recusada_pela_catraca_nao_e_servida():
    s, llm = Store(), LLMContada()
    _ligar(s)
    _gerar(s, llm)
    marcar_resultado(s, 1, s.tick, False)
    _gerar(s, llm)
    assert llm.chamadas == 2

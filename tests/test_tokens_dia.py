"""Orçamento diário vindo da configuração (CIRCULO_TOKENS_DIA, padrão 1 milhão), com aviso em 50% e 80% antes do corte
em 100%, e o uso de cada chamada separado em entrada, saída e cache (o cache de prompt faz o mesmo teto render mais)."""
import json
import time
from types import SimpleNamespace

from circulo.budget import definir_limite
from circulo.llm import AnthropicLLM, LLMResult
from circulo.orcamento_dia import TOKENS_DIA, limite_hoje, tokens_dia
from circulo.policy import HARD_DAILY_TOKEN_CAP


def _avisos(circle):
    return [r["message"] for r in circle.store.q("SELECT message FROM alerts WHERE kind='orcamento' ORDER BY id")]


def _gastar(circle, tokens):
    circle.ctx.budget._row()
    circle.store.x("UPDATE budget SET tokens=?", (tokens,))


def test_padrao_e_um_milhao_por_dia(circle):
    assert TOKENS_DIA == 1_000_000
    assert circle.ctx.budget.limit == 1_000_000 == limite_hoje(circle.store)


def test_teto_vem_da_configuracao_e_respeita_o_teto_duro(circle, monkeypatch):
    monkeypatch.setenv("CIRCULO_TOKENS_DIA", "300000")
    assert circle.ctx.budget.limit == 300_000
    monkeypatch.setenv("CIRCULO_TOKENS_DIA", str(HARD_DAILY_TOKEN_CAP * 10))
    assert tokens_dia() == HARD_DAILY_TOKEN_CAP
    monkeypatch.setenv("CIRCULO_TOKENS_DIA", "um milhão")
    assert tokens_dia() == TOKENS_DIA


def test_limite_escolhido_por_voce_no_painel_continua_valendo(circle):
    definir_limite(circle.store, 400_000, tokens_dia())
    assert circle.ctx.budget.limit == 400_000 == limite_hoje(circle.store)


def test_avisa_em_50_e_80_por_cento_uma_vez_cada_antes_do_corte(circle):
    circle.store.set("orcamento_modo", {"modo": "limite"})     # os marcos só existem com corte
    _gastar(circle, 499_000)
    circle.tick()
    assert _avisos(circle) == []
    _gastar(circle, 500_000)
    circle.tick()
    circle.tick()
    assert len(_avisos(circle)) == 1 and "50%" in _avisos(circle)[0]
    _gastar(circle, 810_000)
    circle.tick()
    assert len(_avisos(circle)) == 2 and "80%" in _avisos(circle)[1]
    _gastar(circle, 1_000_000)
    r = circle.tick()
    assert r.paused and r.pause_reason == "orcamento"
    assert len(_avisos(circle)) == 3 and "100%" in _avisos(circle)[2] and "painel" in _avisos(circle)[2]
    circle.tick()
    assert len(_avisos(circle)) == 3


def test_salto_direto_ao_corte_ainda_avisa(circle):
    circle.store.set("orcamento_modo", {"modo": "limite"})     # os marcos só existem com corte
    _gastar(circle, 1_000_000)
    assert circle.tick().paused
    assert len(_avisos(circle)) == 1 and "100%" in _avisos(circle)[0]


def test_chamada_liga_cache_no_prefixo_fixo_e_separa_o_uso():
    enviados = {}

    def create(**kw):
        enviados.update(kw)
        usage = SimpleNamespace(input_tokens=100, output_tokens=50, cache_read_input_tokens=9000, cache_creation_input_tokens=0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok", citations=None)], usage=usage)

    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    r = llm.generate(system="constituição", prompt="p", model="m", max_tokens=10, web_search=2)
    assert enviados["system"] == [{"type": "text", "text": "constituição", "cache_control": {"type": "ephemeral"}}]
    assert (r.entrada, r.saida, r.cache_lido, r.cache_escrito) == (100, 50, 9000, 0)
    assert r.tokens == 100 + 50 + 900            # leitura do cache conta 1/10, como no preço


def test_cada_chamada_registra_entrada_saida_e_cache(circle):
    from circulo.registro import registrar
    out = LLMResult("ok", 0, "m", entrada=10, saida=5, cache_lido=300, cache_escrito=20)
    i = registrar(circle.store, tick=1, project_id=None, papel="builder", modelo="m", uso=out)
    r = circle.store.one("SELECT tokens, tokens_entrada, tokens_saida, cache_lido, cache_escrito FROM llm_calls WHERE id=?", (i,))
    assert tuple(r) == (out.tokens, 10, 5, 300, 20) and out.tokens == 10 + 5 + 20 + 30


def test_cada_chamada_fica_atribuida_ao_job_do_jev_da_missao(circle):
    from circulo.orcamento_dia import tokens_por_job
    from circulo.projects import kit_project_id
    from circulo.registro import registrar
    s, agora = circle.store, time.time()
    ant = s.x("INSERT INTO projects(nome,pedido,tipo,kit,status,proposito,created_at,updated_at) "
              "VALUES('antecipar:conteudo','p','conteudo','geral','ativo','x',?,?)", (agora, agora))
    pedida = s.x("INSERT INTO projects(nome,pedido,tipo,kit,status,proposito,created_at,updated_at) "
                 "VALUES('m','p','plano','geral','ativo','x',?,?)", (agora, agora))
    s.x("INSERT INTO events(kind,payload,status,created_at,job) VALUES('mensagem',?,'done',?,'pesquisa_decisao')",
        (json.dumps({"projeto": pedida, "text": "compare"}), agora))
    for pid, n in ((ant, 100), (pedida, 200), (pedida, 50), (kit_project_id(s, "circulo"), 7), (None, 3)):
        registrar(s, tick=1, project_id=pid, papel="builder", modelo="m", uso=LLMResult("ok", 0, "m", entrada=n))
    por_job = tokens_por_job(s)
    assert (por_job["conteudo"], por_job["pesquisa_decisao"], por_job["evoluir_loop"]) == (100, 250, 7)
    assert por_job["desconhecido"] == 3
    assert s.one("SELECT COUNT(*) n FROM llm_calls WHERE job IS NULL")["n"] == 0

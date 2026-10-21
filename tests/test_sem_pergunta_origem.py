"""Pergunta do conselho #39 (lição #15): item do loop sem a pergunta que o originou é recusado antes de gastar.

O rastro:cadeia barrava 3 de 13 entregas com "item planejado pelo loop sem a pergunta do conselho que o originou",
depois que o planejador, o estudo e o Developer já tinham gastado. A regra fica numa função tipada do planejador:
sem pergunta existente, nada é gravado nem enviado à LLM, e a falha do rastro:cadeia leva a causa 'sem_pergunta_origem'.
"""
import time

import pytest

from circulo import perguntas, planejador, rastro
from circulo.perguntas import Conselho

from test_planejador import PlanLLM, preparar
from test_self_dev import repo  # noqa: F401 — fixture do repositório


def test_item_sem_pergunta_de_origem_e_recusado_sem_tokens_licao_15(circle, repo, monkeypatch):  # noqa: F811
    s = circle.store
    monkeypatch.setattr(Conselho, "registrar", lambda self, p: 987654)     # pergunta que não está na tabela
    monkeypatch.setattr(perguntas, "gerar", lambda ctx: [])                 # o Questionador diário é outro papel
    llm = PlanLLM(titulo="Item que nasceria sem a pergunta de origem")
    _, plan = preparar(circle, repo, llm)
    itens = s.one("SELECT COUNT(*) n FROM roadmap")["n"]
    assert plan.run() is None
    assert llm.prompts == []                                                 # 0 tokens: a LLM nem foi chamada
    assert not s.one("SELECT 1 FROM llm_calls WHERE papel='planejador'")
    assert s.one("SELECT COUNT(*) n FROM roadmap")["n"] == itens
    v = s.one("SELECT ok, causa FROM verificacoes WHERE ponto=? ORDER BY id DESC LIMIT 1", (rastro.PONTO,))
    assert (v["ok"], v["causa"]) == (0, rastro.SEM_PERGUNTA_ORIGEM)
    assert (s.get(planejador.TENTATIVAS) or {})["ultima"]["motivo"].startswith(rastro.SEM_PERGUNTA_ORIGEM)


def test_item_com_pergunta_de_origem_passa_e_fica_ligado_a_ela_licao_15(circle, repo):  # noqa: F811
    s = circle.store
    llm = PlanLLM(titulo="Item que nasce da pergunta do conselho")
    _, plan = preparar(circle, repo, llm)
    item = plan.run()
    assert item and llm.prompts
    assert s.one("SELECT 1 FROM perguntas WHERE item_id=?", (item["id"],))
    assert not s.one("SELECT 1 FROM verificacoes WHERE ponto=? AND causa=?", (rastro.PONTO, rastro.SEM_PERGUNTA_ORIGEM))


def test_barramento_do_rastro_sem_pergunta_leva_a_causa_separada_licao_15(circle):
    """O que ainda escapar (item gravado por outro caminho) é contado à parte: a meta é 0 em 24 h."""
    s = circle.store
    agora = time.time()
    s.x("INSERT INTO perguntas(chave,persona,texto,status,created_at,updated_at) VALUES('k','operador','?','valida',?,?)",
        (agora - 20 * 3600, agora))
    i = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
            "VALUES('Sem origem','d','loop','feito','x',99,?,?)", (agora - 10 * 3600, agora - 10 * 3600))
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(7,NULL,'t',?,'mergeado',?,?)",
        (f"circulo/fix-{i}-1", agora - 5 * 3600, agora - 5 * 3600))
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(7,'abc',1,'ok','{}',?)", (agora - 4 * 3600,))
    assert rastro.verificar(circle.ctx) == [i]
    v = s.one("SELECT ok, causa FROM verificacoes WHERE ponto=?", (rastro.PONTO,))
    assert (v["ok"], v["causa"]) == (0, rastro.SEM_PERGUNTA_ORIGEM)


@pytest.mark.parametrize("pid", [None, 0, 987654])
def test_gravar_item_exige_pergunta_existente_licao_15(circle, pid):
    s = circle.store
    antes = s.one("SELECT COUNT(*) n FROM roadmap")["n"]
    with pytest.raises(planejador.SemPerguntaOrigem):
        planejador.gravar_item(s, pid, "Título", "Detalhe", "evidência")
    assert s.one("SELECT COUNT(*) n FROM roadmap")["n"] == antes

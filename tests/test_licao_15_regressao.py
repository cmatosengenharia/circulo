"""Lição #15 (rastro:lacuna, neurônio rastro:cadeia): "item planejado pelo loop sem a pergunta do conselho que o originou".

O ponto único `roadmap.gravar_item` já prende cada item à pergunta (roadmap.pergunta_id), mas também reaponta
perguntas.item_id para o item mais novo. Quando uma pergunta origina vários itens (revisao_uso cobra um item por PR com
a mesma pergunta do PM; jobs.propor_item a cada giro), só o último ficava ligado por perguntas.item_id, e o rastro, que
lia só esse lado, acusava a lacuna nos anteriores, que tinham pergunta.
"""
import time

from circulo import rastro, roadmap


def _pergunta(s) -> int:
    agora = time.time()
    return s.x("INSERT INTO perguntas(chave,persona,texto,status,created_at,updated_at) VALUES('k','pm','?','valida',?,?)",
               (agora - 3600, agora))


def test_pergunta_que_origina_varios_itens_nao_deixa_lacuna_licao_15(circle):
    """Lição #15: dois itens gravados pelo ponto único com a mesma pergunta têm, os dois, a pergunta de origem no fio."""
    s = circle.store
    pid = _pergunta(s)
    itens = [roadmap.gravar_item(s, pid, f"Revisar a entrega #{n}", "d", "e") for n in (1, 2)]
    for i in itens:
        c = rastro.cadeia_item(s, i)
        assert rastro.LACUNA_SEM_PERGUNTA not in c["lacunas"], f"item #{i}: {c['lacunas']}"
        assert c["passos"][0]["no"] == f"pergunta:{pid}"


def test_item_do_loop_sem_pergunta_ainda_e_lacuna_licao_15(circle):
    """Lição #15: o que escapa do ponto único (sem pergunta_id nem perguntas.item_id) continua sendo pego."""
    s = circle.store
    _pergunta(s)
    agora = time.time()
    i = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
            "VALUES('Sem origem','d','loop','pendente','x',99,?,?)", (agora, agora))
    assert rastro.LACUNA_SEM_PERGUNTA in rastro.cadeia_item(s, i)["lacunas"]

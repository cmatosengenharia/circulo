"""Pergunta #138 (entrevistador_jtbd): o agrupador de jobs (#146) ligado ao loop. Cada job com ≥3 pedidos em 7 dias
vira exatamente 1 proposta antecipada no roteiro, presa à pergunta do conselho que a originou (lição #15)."""
import json
import time

from circulo import jobs, jtbd


def _pedidos(s, rotulos):
    for i, j in enumerate(rotulos):
        eid = s.x("INSERT INTO events(kind,payload,status,created_at) VALUES('novo_projeto',?,'done',?)",
                  (json.dumps({"pedido": f"pedido {i}"}), time.time() - i * 8640))
        s.x("UPDATE events SET job=? WHERE id=?", (j, eid))


def _pergunta(s):
    agora = time.time()
    return s.x("INSERT INTO perguntas(chave,persona,texto,status,created_at,updated_at) "
               "VALUES('jtbd',?,'qual job se repete e o loop poderia ter entregue sem ser pedido?','feita',?,?)",
               (jtbd.PERSONA, agora, agora))


def _propostas(s):
    return s.q("SELECT titulo, status, origem, pergunta_id FROM roadmap WHERE titulo LIKE 'antecipar:%' ORDER BY titulo")


def test_cada_job_recorrente_dos_32_pedidos_vira_uma_unica_proposta_pelo_loop_licao_15(circle):
    s = circle.store
    perg = _pergunta(s)
    _pedidos(s, ["conteudo"] * 5 + ["financas"] * 4 + ["plano"] * 3 + ["landing_page"] * 2 + ["desconhecido"] * 18)
    assert len(jobs.pedidos_7d(s)) == 32
    assert jtbd.precisa(s)

    circle._run_idle_task("antecipar")
    props = _propostas(s)
    assert [p["titulo"].split(" ")[0] for p in props] == ["antecipar:conteudo", "antecipar:financas", "antecipar:plano"]
    assert all(p["status"] == "proposto" and p["origem"] == "loop" and p["pergunta_id"] == perg for p in props)
    assert s.one("SELECT COUNT(*) n FROM projects WHERE nome LIKE 'antecipar:%'")["n"] == 3

    circle._run_idle_task("antecipar")                       # idempotente: a mesma semana não duplica
    assert len(_propostas(s)) == 3
    assert not jtbd.precisa(s)

    s.x("UPDATE roadmap SET status='descartado' WHERE titulo LIKE 'antecipar:plano%'")
    assert jtbd.propor(s) == []                               # descartada na semana também não renasce


def test_sem_pergunta_do_conselho_o_job_recorrente_nao_vira_proposta(circle):
    s = circle.store
    _pedidos(s, ["conteudo"] * 3)
    assert jtbd.propor(s) == []
    circle._run_idle_task("antecipar")
    assert _propostas(s) == [] and not s.one("SELECT 1 FROM roadmap WHERE pergunta_id IS NULL AND origem='loop'")

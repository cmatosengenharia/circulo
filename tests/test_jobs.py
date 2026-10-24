"""Job de cada pedido humano: regra do Jev primeiro (confiança e margem calibradas numa amostra rotulada),
'desconhecido' explícito e só então a LLM, que devolve um rótulo e nunca uma confiança. Jobs que se repetem
em 7 dias viram a missão 'antecipar:<job>' no idle."""
import json
import time

from circulo import jobs
from circulo.state import Store


class LLMFalsa:
    """Responde sempre o mesmo rótulo e declara confiança alta: a autoconfiança dela não pode valer nada."""

    def __init__(self, resposta: str):
        self.resposta, self.chamadas = resposta, 0

    def complete(self, system, prompt, max_tokens):
        self.chamadas += 1
        return self.resposta, 10


def _pedido(s: Store, texto: str, dias: float = 0, kind: str = "novo_projeto", origem: str | None = None) -> int:
    payload = {"pedido" if kind == "novo_projeto" else "text": texto, **({"origem": origem} if origem else {})}
    return s.x("INSERT INTO events(kind,payload,status,created_at) VALUES(?,?, 'done', ?)",
               (kind, json.dumps(payload), time.time() - dias * 86400))


def _job(s: Store, eid: int) -> dict:
    return dict(s.one("SELECT job, job_fonte, job_conf, job_margem FROM events WHERE id=?", (eid,)))


def test_regra_confiante_grava_o_job_sem_chamar_a_llm_mesmo_que_a_llm_erraria(circle):
    llm = LLMFalsa("conteudo (confiança 0.99)")
    circle.ctx.dl.llm = llm
    eid = _pedido(circle.store, "Pesquise e compare os melhores notebooks e recomende qual vale a pena comprar")
    assert jobs.registrar(circle.ctx, eid) == "pesquisa_decisao"
    j = _job(circle.store, eid)
    assert j["job_fonte"] == "regra" and j["job_conf"] > 0 and j["job_margem"] > 0
    assert llm.chamadas == 0


def test_pedido_ambiguo_vira_desconhecido_e_so_entao_a_llm_escolhe_um_rotulo(circle):
    ambiguo = "Monte um plano e compare"                      # dois jobs empatados: margem zero
    assert jobs.classificar(ambiguo).margem == 0
    eid = _pedido(circle.store, ambiguo)
    assert jobs.registrar(circle.ctx, eid) == "desconhecido"  # sem LLM: o rótulo explícito fica
    assert _job(circle.store, eid)["job_fonte"] == "desconhecido"

    llm = LLMFalsa("plano")
    circle.ctx.dl.llm = llm
    eid2 = _pedido(circle.store, ambiguo)
    assert jobs.registrar(circle.ctx, eid2) == "plano"
    assert llm.chamadas == 1
    j = _job(circle.store, eid2)
    assert j["job_fonte"] == "llm" and j["job_conf"] is None  # a confiança nunca vem da LLM


def test_llm_que_responde_fora_dos_jobs_deixa_desconhecido(circle):
    circle.ctx.dl.llm = LLMFalsa("acho que é marketing, confiança 0.9")
    eid = _pedido(circle.store, "faz aquilo de novo")
    assert jobs.registrar(circle.ctx, eid) == "desconhecido"


def test_limiar_e_calibrado_na_amostra_rotulada_e_nao_fixo():
    amostra = jobs.amostra_rotulada()
    assert len(amostra) == 31
    cal = jobs.calibrar(amostra)
    assert cal["precisao"] >= 0.85 and cal["cobertura"] >= 0.9   # ≥85% de acerto no que a regra decide
    # amostra em que o pedido de um único termo costuma estar errado: a calibração deixa de aceitá-lo pela regra
    ruim = [("post", "plano"), ("post", "plano"), ("post e legenda", "conteudo"), ("plano de ação com cronograma", "plano")]
    boa = [(t, "conteudo") if t == "post" else (t, j) for t, j in ruim]
    um_termo = jobs.classificar("post")
    assert not jobs.aceita(um_termo, jobs.calibrar(ruim))
    assert jobs.aceita(um_termo, jobs.calibrar(boa))


def test_amostra_rotulada_do_data_dir_substitui_a_embutida(tmp_path):
    (tmp_path / "jobs_rotulados.json").write_text(json.dumps([{"texto": "post", "job": "plano"}]))
    assert jobs.amostra_rotulada(tmp_path) == [("post", "plano")]


def test_tres_pedidos_do_mesmo_job_em_7_dias_viram_missao_antecipar_no_idle(circle):
    s = circle.store
    for i, t in enumerate(["Escreva 5 posts para o Instagram", "Crie legendas para os posts da semana",
                           "Escreva um post sobre a promoção"]):
        jobs.registrar(circle.ctx, _pedido(s, t, dias=i))
    jobs.registrar(circle.ctx, _pedido(s, "Monte um plano de viagem com cronograma"))
    jobs.registrar(circle.ctx, _pedido(s, "Escreva um post antigo", dias=9))      # fora da janela
    jobs.registrar(circle.ctx, _pedido(s, "Escreva um post de teste", origem="demo"))   # não é humano
    assert jobs.recorrentes(jobs.pedidos_7d(s)).jobs == {"conteudo": 3}
    assert jobs.precisa(s)

    circle._run_idle_task("antecipar")
    m = s.one("SELECT * FROM projects WHERE nome='antecipar:conteudo'")
    assert m is not None and m["kit"] == "geral" and m["status"] == "ativo" and m["tipo"] == "conteudo"
    assert not jobs.precisa(s)
    circle._run_idle_task("antecipar")                 # repetido: não duplica a missão da semana
    assert s.one("SELECT COUNT(*) n FROM projects WHERE nome LIKE 'antecipar:%'")["n"] == 1


def test_cada_pedido_atendido_pelo_loop_ganha_job_em_90_por_cento(circle):
    s = circle.store
    for t, _ in jobs.amostra_rotulada():
        circle.submit_project(t)
    for _ in range(31):
        circle.tick()
    r = s.one("SELECT COUNT(*) n, SUM(job IS NOT NULL AND job!='desconhecido') ok FROM events WHERE kind='novo_projeto'")
    assert r["n"] == 31 and r["ok"] / r["n"] >= 0.9


def test_recorrentes_agrupa_32_pedidos_por_job_e_aponta_o_dominante():
    """Pergunta #119: dos pedidos de 7d, quais jobs se repetem e qual o loop antecipa. Pura: sem DB nem LLM."""
    rotulos = (["conteudo"] * 12 + ["financas"] * 9 + ["plano"] * 5 + ["landing_page"] * 2
               + ["pesquisa_decisao"] + ["desconhecido"] * 2 + [None])
    pedidos = [{"job": j} for j in rotulos]
    assert len(pedidos) == 32
    r = jobs.recorrentes(pedidos)
    assert r.total == 32 and r.cobertura == round(29 / 32, 3) and r.cobertura >= 0.9
    assert list(r.jobs.items()) == [("conteudo", 12), ("financas", 9), ("plano", 5)]   # só ≥3, do maior ao menor
    assert r.fracao == {"conteudo": 0.375, "financas": 0.281, "plano": 0.156}          # fração dos 32
    assert r.dominante == "conteudo"
    assert jobs.recorrentes(pedidos, minimo=10).jobs == {"conteudo": 12}
    assert jobs.recorrentes(pedidos, minimo=13).dominante is None
    vazio = jobs.recorrentes([])
    assert vazio.total == 0 and vazio.cobertura == 0.0 and vazio.jobs == {} and vazio.dominante is None


def test_recorrentes_da_amostra_real_classifica_90_por_cento_e_tem_job_recorrente():
    pedidos = [{"job": jobs.classificar(t).job} for t, _ in jobs.amostra_rotulada()]
    r = jobs.recorrentes(pedidos)
    assert r.cobertura >= 0.9 and r.jobs and r.dominante in r.jobs


def test_cobertura_de_antecipacao_conta_so_o_item_proativo_criado_antes_do_pedido():
    """Pergunta #128: que fração dos pedidos de 7d já tinha um item 'antecipar:<job>' aberto? Pura: sem DB nem LLM."""
    from circulo import antecipacao
    pedidos = ([{"job": "conteudo", "created_at": t} for t in (10, 20, 30)]      # antecipado antes de todos
               + [{"job": "financas", "created_at": t} for t in (10, 20, 30)]    # antecipado só depois
               + [{"job": "plano", "created_at": t} for t in (10, 20)])          # nunca antecipado, não recorrente
    itens = [{"nome": "antecipar:conteudo", "created_at": 5}, {"nome": "antecipar:financas", "created_at": 40}]
    r = antecipacao.cobertura(pedidos, itens)
    assert r.total == 8 and r.antecipados == 3 and r.cobertura == 0.375 and r.cobertura >= antecipacao.META
    assert r.sem_antecipacao == ["financas"]                     # recorrente (≥3) e nenhum pedido antecipado
    assert antecipacao.cobertura(pedidos, [{"nome": "antecipar:financas", "created_at": 15}]).antecipados == 2
    vazio = antecipacao.cobertura([], itens)
    assert vazio.total == 0 and vazio.cobertura == 0.0 and vazio.sem_antecipacao == []


def test_cobertura_de_antecipacao_medida_nos_pedidos_humanos_de_7_dias(circle):
    from circulo import antecipacao
    s = circle.store
    for i, t in enumerate(["Escreva 5 posts para o Instagram", "Crie legendas para os posts da semana",
                           "Escreva um post sobre a promoção"]):
        jobs.registrar(circle.ctx, _pedido(s, t, dias=3 - i))
    jobs.antecipar(s, agora=time.time() - 3600)                  # o item proativo nasce depois dos 3 pedidos
    jobs.registrar(circle.ctx, _pedido(s, "Escreva um post para o fim de semana"))
    r = antecipacao.medir(s)
    assert r.total == 4 and r.antecipados == 1 and r.cobertura == 0.25 and r.sem_antecipacao == []


def test_job_recorrente_vira_um_unico_item_proposto_com_a_pergunta_de_origem_licao_15(circle):
    """Pergunta #132: dos 32 pedidos de 7d, o job que se repete vira 1 item 'proposto' do roteiro, preso à pergunta do
    conselho (lição #15); uma segunda chamada na mesma semana não duplica, e sem pergunta não nasce item."""
    import pytest

    from circulo.planejador import SemPerguntaOrigem
    s = circle.store
    agora = time.time()
    perg = s.x("INSERT INTO perguntas(chave,persona,texto,status,created_at,updated_at) "
               "VALUES('jtbd','entrevistador_jtbd','qual job se repete?','feita',?,?)", (agora, agora))
    rotulos = ["conteudo"] * 4 + ["financas"] * 2 + ["plano"] * 2 + ["desconhecido"] * 24
    for i, j in enumerate(rotulos):
        s.x("UPDATE events SET job=? WHERE id=?", (j, _pedido(s, f"pedido {i}", dias=i / 10)))
    assert len(jobs.pedidos_7d(s)) == 32
    antes = s.one("SELECT COUNT(*) n FROM roadmap")["n"]
    with pytest.raises(SemPerguntaOrigem):
        jobs.propor_item(s, None)
    assert s.one("SELECT COUNT(*) n FROM roadmap")["n"] == antes

    rid = jobs.propor_item(s, perg)
    it = s.one("SELECT * FROM roadmap WHERE id=?", (rid,))
    assert it["status"] == "proposto" and it["origem"] == "loop" and it["pergunta_id"] == perg
    assert it["titulo"].startswith("antecipar:conteudo")
    assert s.one("SELECT item_id FROM perguntas WHERE id=?", (perg,))["item_id"] == rid
    assert jobs.propor_item(s, perg) is None                       # mesma semana: não duplica
    assert s.one("SELECT COUNT(*) n FROM roadmap")["n"] == antes + 1
    assert not s.one("SELECT 1 FROM roadmap WHERE status='proposto' AND pergunta_id IS NULL")


def test_proposta_antecipada_vira_antecipou_redundante_ou_ignorada_pelos_pedidos_dos_7_dias_seguintes():
    """Pergunta #155: cada proposta 'antecipar:<job>' cruzada com os pedidos do mesmo job nos 7 dias seguintes.
    Aceita antes de o humano pedir de novo: antecipou; não aceita e o humano pediu: redundante; nem uma coisa nem
    outra: ignorada. Pura: sem DB nem LLM."""
    d = 86400
    propostas = [{"titulo": "antecipar:conteudo — lote", "status": "feito", "created_at": 0},
                 {"titulo": "antecipar:financas — resumo", "status": "proposto", "created_at": 0},
                 {"titulo": "antecipar:plano — plano", "status": "descartado", "created_at": 0}]
    pedidos = ([{"job": "conteudo", "created_at": 2 * d}, {"job": "financas", "created_at": 3 * d},
                {"job": "financas", "created_at": 5 * d}]
               + [{"job": "plano", "created_at": -d}, {"job": "plano", "created_at": 8 * d}])   # fora da janela
    r = jobs.desfecho_propostas(propostas, pedidos)
    assert r.desfechos == ["antecipou", "redundante", "ignorada"]
    assert r.total == 3 and r.contagem == {"antecipou": 1, "redundante": 1, "ignorada": 1}
    assert r.taxa == 0.333 and r.pedidos_depois == {"conteudo": 1, "financas": 2, "plano": 0}
    vazio = jobs.desfecho_propostas([], pedidos)
    assert vazio.total == 0 and vazio.taxa == 0.0 and vazio.desfechos == []


def test_evidencia_da_pergunta_jtbd_traz_a_taxa_de_antecipacao_das_propostas(circle):
    from circulo.perguntas import METRICAS
    s = circle.store
    agora = time.time()
    _, fn = METRICAS["pedidos_humano"]
    assert fn(s, agora)[1]["antecipacao"] == {"propostas": 0, "taxa": 0.0, "antecipou": 0, "redundante": 0,
                                              "ignorada": 0, "pedidos_depois": {}}       # medida mesmo sem proposta
    perg = s.x("INSERT INTO perguntas(chave,persona,texto,status,created_at,updated_at) "
               "VALUES('jtbd','entrevistador_jtbd','qual job se repete?','feita',?,?)", (agora, agora))
    for i in range(3):
        s.x("UPDATE events SET job='conteudo' WHERE id=?", (_pedido(s, f"post {i}", dias=3 + i),))
    jobs.propor_item(s, perg, agora=agora)
    s.x("UPDATE events SET job='conteudo' WHERE id=?", (_pedido(s, "mais um post", dias=-0.5),))   # pedido depois dela
    ev = fn(s, agora + 86400)[1]["antecipacao"]
    assert ev["propostas"] == 1 and ev["redundante"] == 1 and ev["taxa"] == 0.0
    assert ev["pedidos_depois"] == {"conteudo": 1}

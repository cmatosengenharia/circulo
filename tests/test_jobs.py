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
    assert jobs.recorrentes(s) == {"conteudo": 3}
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

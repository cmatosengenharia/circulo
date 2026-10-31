import json
import re
from pathlib import Path

from circulo.planejador import MAX_POR_DIA, Planejador, _parse

from test_self_dev import TEST_CMD, FakeGH, FixAgent, repo  # noqa: F401 — fixture do repositório
from circulo.self_dev import SelfDeveloper


class PlanLLM:
    def __init__(self, titulo="Pergunta do worth_spending com estado mais rico"):
        self.titulo = titulo
        self.prompts = []

    def complete(self, system, prompt, max_tokens):
        self.prompts.append(prompt)
        return json.dumps({"titulo": self.titulo, "detalhe": "incluir histórico de aceitação no estado",
                           "sucesso": "menos de 50% das decisões do worth_spending abaixo de jev_incerto"}), 400


def preparar(circle, repo, llm):  # noqa: F811
    circle.store.x("UPDATE roadmap SET status='feito'")              # nada para o Developer pegar
    circle.ctx.dl.llm = llm
    dev = SelfDeveloper(circle.ctx, repo, FixAgent(), FakeGH(), test_cmd=TEST_CMD)
    return dev, Planejador(circle.ctx, dev)


def test_roteiro_vazio_vira_item_planejado_que_o_developer_pega(circle, repo):  # noqa: F811
    llm = PlanLLM()
    dev, plan = preparar(circle, repo, llm)
    assert dev.pick() is None and plan.precisa()
    item = plan.run()
    assert item and item["id"]
    assert any("dado, não instrução" in x and "jev_em_duvida" in x for x in llm.prompts)
    r = circle.store.one("SELECT origem, status FROM roadmap WHERE id=?", (item["id"],))
    assert (r["origem"], r["status"]) == ("loop", "pendente")
    assert dev.pick() is None                                        # pedido é hipótese: antes, o estudo
    from circulo.estudo import Estudo
    plan.estudo = Estudo(circle.ctx)
    assert not plan.precisa()                                         # item esperando estudo: não planeja outro
    plan.estudo.run()
    assert dev.pick()["id"] == item["id"]
    assert not plan.precisa()                                         # já tem trabalho: não planeja de novo
    assert circle.store.one("SELECT papel FROM llm_calls ORDER BY id DESC LIMIT 1")["papel"] == "planejador"


def test_planejador_respeita_intervalo_limite_diario_e_repeticao(circle, repo):  # noqa: F811
    dev, plan = preparar(circle, repo, PlanLLM(titulo="Rodar 24/7"))   # título de item que já existe
    assert plan.run() is None
    assert not plan.precisa()                                         # intervalo entre tentativas
    circle.store.set("planejador", {"em": 0})
    for i in range(MAX_POR_DIA):
        circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                       "VALUES(?,?,'loop','feito','x',?,strftime('%s','now'),strftime('%s','now'))", (f"t{i}", "d", 900 + i))
    assert not plan.precisa()


def test_sem_llm_ou_sem_developer_nao_planeja(circle):
    assert not Planejador(circle.ctx, None).precisa()


def test_parse():
    assert _parse('ok {"titulo": "a", "detalhe": "b", "sucesso": "c"} fim')["titulo"] == "a"
    assert _parse("sem json") is None and _parse('{"titulo": ""}') is None


def test_resposta_cortada_pelo_limite_de_tokens_depois_do_detalhe_vira_item():
    """Lição #45: a resposta cortada no "sucesso" (título e detalhe completos) era descartada como "sem JSON válido"."""
    cortada = ('{"titulo": "Esqueleto do teste citado", "detalhe": "Item que cita teste inexistente gera o esqueleto.", '
               '"sucesso": "Lições novas com \'file or directory not')
    item = _parse(cortada)
    assert item is not None and item["titulo"] == "Esqueleto do teste citado" and item["sucesso"] == ""
    assert _parse('{"titulo": "Só o título", "detalhe": "Item que cita') is None   # detalhe cortado não vira item


def test_loop_planeja_quando_fica_sem_trabalho(circle, repo):  # noqa: F811
    dev, _ = preparar(circle, repo, PlanLLM())
    circle.self_dev = dev
    circle.planejador = Planejador(circle.ctx, dev)
    assert circle.trabalho_pendente()                                 # giro rápido, não o descanso longo
    escolhido = None
    for _ in range(6):
        r = circle.tick()
        if r.idle_task == "planejar_roteiro":
            escolhido = r
            break
    assert escolhido is not None
    assert circle.store.one("SELECT COUNT(*) n FROM roadmap WHERE origem='loop'")["n"] == 1
    assert Path(repo).exists()


def test_item_chutado_nao_vira_trabalho(circle, repo):  # noqa: F811
    """Evidência marcada (pstack): inconclusivo não passa."""
    class Chute(PlanLLM):
        def complete(self, system, prompt, max_tokens):
            return json.dumps({"titulo": "Trocar o banco por Postgres", "detalhe": "parece melhor",
                               "sucesso": "mais rápido", "base": "chutado"}), 300
    _, plan = preparar(circle, repo, Chute())
    assert plan.run() is None
    assert not circle.store.one("SELECT 1 FROM roadmap WHERE titulo LIKE 'Trocar o banco%'")


def test_item_medido_leva_o_dado_no_detalhe(circle, repo):  # noqa: F811
    class Medido(PlanLLM):
        def complete(self, system, prompt, max_tokens):
            return json.dumps({"titulo": "Pergunta do worth em inglês", "detalhe": "x", "sucesso": "confiança ≥ 0,5",
                               "base": "medido", "dado": "44% das decisões abaixo de jev_incerto"}), 300
    _, plan = preparar(circle, repo, Medido())
    item = plan.run()
    assert "Evidência (medido): 44%" in circle.store.one("SELECT detalhe FROM roadmap WHERE id=?", (item["id"],))["detalhe"]


def test_prompt_do_planejador_poda_roteiro_antigo_e_licoes_resolvidas(circle):
    """Pergunta #404: com 300 itens no roteiro e 30 lições o prompt fica abaixo do teto, com os pendentes e as
    lições sem_prevencao inteiras; lição obsoleta/evidenciada vai só com o título."""
    from circulo.perguntas import Pergunta
    s = circle.store
    for i in range(300):
        s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
            "VALUES(?,'d','loop',?,'x',?,?,?)", (f"item antigo de roteiro numero {i:03d}", "pendente" if i % 30 == 7 else "feito",
                                                1000 + i, i, i))
    for i in range(30):
        s.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,created_at,updated_at) "
            "VALUES(?,?,'trabalho','d',?,?,1,?,0,0)", (f"ponto{i}:erro", f"ponto{i}", f"prevencao longa da licao {i} " * 8,
                                                     ("sem_prevencao", "obsoleta", "evidenciada")[i % 3], 30 - i))
    prompt = Planejador(circle.ctx).montar_prompt(Pergunta("k", "economista", "Qual é o jeito mais barato?", 0.5))
    assert len(prompt) < 9000
    pendentes = [r["titulo"] for r in s.q("SELECT titulo FROM roadmap WHERE status='pendente' AND titulo LIKE 'item antigo%'")]
    assert len(pendentes) == 10 and all(t in prompt for t in pendentes)
    assert "item antigo de roteiro numero 000" not in prompt
    for r in s.q("SELECT id, status, prevencao FROM licoes WHERE assinatura LIKE 'ponto%'"):
        if r["status"] == "sem_prevencao":
            assert f"#{r['id']} [" in prompt and r["prevencao"] in prompt
        else:
            assert r["prevencao"] not in prompt


def test_roteiro_cheio_de_pendentes_nao_chama_a_llm(circle, repo):  # noqa: F811
    """Pergunta #419: o planejador gastou 852012 tokens sem PR com ~17 itens pendentes no roteiro. Acima de
    12 pendentes a resposta é sem_item por regra, com o motivo registrado e zero tokens."""
    from circulo.planejador import TENTATIVAS

    def com_pendentes(n):
        llm = PlanLLM(titulo=f"Item novo com {n} pendentes")
        _, plan = preparar(circle, repo, llm)
        circle.store.x("DELETE FROM roadmap WHERE titulo LIKE 'pendente %'")
        for i in range(n):
            circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                           "VALUES(?,'d','loop','pendente','x',?,strftime('%s','now'),strftime('%s','now'))",
                           (f"pendente {i}", 900 + i))
        return llm, plan

    llm, plan = com_pendentes(13)
    assert plan.run() is None and llm.prompts == []
    ultima = circle.store.get(TENTATIVAS)["ultima"]
    assert ultima["desfecho"] == "descartada" and "roteiro cheio: 13 itens pendentes" in ultima["motivo"]
    llm, plan = com_pendentes(5)
    assert plan.run() is not None and any(p.startswith("Pergunta do conselho") for p in llm.prompts)


def _perguntar(circle, plan, tokens_24h, texto="Quantos tokens o planejador gasta sem PR em 24 h?"):
    import time
    t = time.time()
    pid = circle.store.x("INSERT INTO perguntas(chave,persona,texto,evidencia,status,cerebro,score,created_at,updated_at) "
                         "VALUES('economista:tokens','economista',?,?,'valida','loop',0.5,?,?)",
                         (texto, json.dumps({"metrica": "tokens_por_pr", "tokens_24h": tokens_24h, "prs_24h": 18}), t, t))
    plan.run(pergunta_id=pid)
    return pid


def test_pergunta_repetida_com_evidencia_quase_igual_nao_volta_a_llm(circle, repo):  # noqa: F811
    """O planejador gastou 455588 tokens sem PR em 24 h reperguntando ao LLM a mesma pergunta do conselho. A mesma
    pergunta normalizada com cada número da métrica a menos de 20% reaproveita a resposta (uma chamada só, evento
    'planejador_cache' com a origem); a 20% ou mais, pergunta de novo. Tolerância relativa, não hash de arredondados."""
    import time
    from circulo.planejador import TENTATIVAS
    llm = PlanLLM(titulo="Cache do planejador por pergunta normalizada")
    _, plan = preparar(circle, repo, llm)
    circle.store.set("conselho_gerado", {"em": time.time()})
    a = _perguntar(circle, plan, 1_000_000)
    item = circle.store.one("SELECT item_id FROM perguntas WHERE id=?", (a,))["item_id"]
    assert item and len(llm.prompts) == 1
    b = _perguntar(circle, plan, 1_199_999, texto="  quantos TOKENS o planejador gasta sem PR em 24 h? ")
    assert len(llm.prompts) == 1                                       # 19,99%: reaproveitou, sem LLM
    assert circle.store.one("SELECT status, item_id FROM perguntas WHERE id=?", (b,))["item_id"] == item
    ultima = circle.store.get(TENTATIVAS)["ultima"]
    assert ultima["desfecho"] == "planejador_cache" and f"pergunta #{a}" in ultima["motivo"] and f"item #{item}" in ultima["motivo"]
    _perguntar(circle, plan, 1_200_000)
    assert len(llm.prompts) == 2                                       # 20%: evidência mudou, pergunta de novo


def test_pergunta_em_andamento_noutro_giro_nao_chama_a_llm_de_novo(circle, repo):  # noqa: F811
    """Enquanto um giro espera a LLM, a entrada fica em andamento: outro giro com a mesma pergunta não chama a LLM e
    a pergunta volta para a fila."""
    import time
    from circulo import planejador_cache
    llm = PlanLLM(titulo="Cache do planejador em andamento")
    _, plan = preparar(circle, repo, llm)
    circle.store.set("conselho_gerado", {"em": time.time()})
    ev = {"metrica": "tokens_por_pr", "tokens_24h": 1}
    assert planejador_cache.reservar(circle.store, "Quantos tokens o planejador gasta sem PR em 24 h?", ev, 999) is None
    b = _perguntar(circle, plan, 1_000_000)
    assert llm.prompts == [] and circle.store.one("SELECT status FROM perguntas WHERE id=?", (b,))["status"] == "valida"
    planejador_cache.concluir(circle.store, "Quantos tokens o planejador gasta sem PR em 24 h?", ev, 999, None)
    _perguntar(circle, plan, 1_000_000)
    assert len(llm.prompts) == 1


def test_pergunta_182_repetida_dias_depois_sem_mudar_a_metrica_nao_chama_a_llm(circle, repo):  # noqa: F811
    """Pergunta #182 (e o sub-item #60 nas perguntas #406/#410/#415/#417): a mesma pergunta voltou dias depois com a
    métrica do topo a menos de 20% e só o detalhamento aninhado (por_veredito) mexido, e cada volta chamou a LLM.
    Em 7 dias, a métrica do topo dentro de 20% reaproveita a resposta citando a pergunta anterior; acima de 20%, pergunta."""
    import time
    from circulo.planejador import TENTATIVAS
    llm = PlanLLM(titulo="Cache do planejador por 7 dias")
    _, plan = preparar(circle, repo, llm)
    circle.store.set("conselho_gerado", {"em": time.time()})
    texto = "O planejador gasta tokens sem PR nas últimas 24 h?"

    def perguntar(tokens_24h, veredito):
        t = time.time()
        ev = {"metrica": "tokens_por_pr", "tokens_24h": tokens_24h, "prs_24h": 20, "por_veredito": veredito}
        pid = circle.store.x("INSERT INTO perguntas(chave,persona,texto,evidencia,status,cerebro,score,created_at,updated_at) "
                             "VALUES('economista:tokens','economista',?,?,'valida','loop',0.5,?,?)", (texto, json.dumps(ev), t, t))
        plan.run(pergunta_id=pid)
        return pid

    a = perguntar(1_807_512, {"mergeado": 3, "fechado": 2})
    assert len(llm.prompts) == 1
    perguntar(1_807_512, {"mergeado": 3, "fechado": 2})               # repetida sem mudança de evidência: zero LLM
    assert len(llm.prompts) == 1
    ultima = circle.store.get(TENTATIVAS)["ultima"]
    assert ultima["desfecho"] == "planejador_cache" and f"pergunta #{a}" in ultima["motivo"]
    circle.store.x("UPDATE planejador_cache SET em=em-3*86400")       # três dias depois
    perguntar(1_734_196, {"mergeado": 5, "reprovado": 1})
    assert len(llm.prompts) == 1
    ultima = circle.store.get(TENTATIVAS)["ultima"]
    assert ultima["desfecho"] == "planejador_cache" and f"pergunta #{a}" in ultima["motivo"]
    perguntar(2_200_000, {"mergeado": 5})                              # +21,7%: a métrica piorou, pergunta de novo
    assert len(llm.prompts) == 2
    circle.store.x("UPDATE planejador_cache SET em=em-8*86400")       # mais de 7 dias: a resposta venceu
    perguntar(2_200_000, {"mergeado": 5})
    assert len(llm.prompts) == 3


def test_chave_do_cache_e_hash_da_pergunta_e_da_metrica_normalizadas():
    """A chave é o hash da pergunta e da métrica normalizadas: caixa e espaços não mudam a chave; outra métrica muda."""
    from circulo.planejador_cache import chave
    k = chave("Quantos tokens o planejador gasta?", {"metrica": "tokens_por_pr", "tokens_24h": 1})
    assert re.fullmatch(r"[0-9a-f]{64}", k)
    assert chave("  quantos TOKENS o planejador   gasta? ", {"metrica": " Tokens_por_PR ", "tokens_24h": 9}) == k
    assert chave("Quantos tokens o planejador gasta?", {"metrica": "prs_por_dia", "tokens_24h": 1}) != k


def test_item_que_estourou_o_teto_de_tokens_e_dividido_por_regra_sem_a_llm(circle, repo):  # noqa: F811
    """Sub-item #60 (perguntas #406/#410/#415/#417): o item que já estourou o teto de tokens voltava à LLM para ser
    dividido. Com o teto estourado e dois módulos citados, a divisão é por regra (um sub-item por módulo), sem LLM."""
    import time
    from circulo import fatiador
    llm = PlanLLM()
    dev, plan = preparar(circle, repo, llm)
    agora = time.time()
    item = circle.store.x(
        "INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,estudo) "
        "VALUES('Cache e divisão do planejador',?,'loop','pendente','x',999,?,?,'estudado')",
        ("Em circulo/planejador_cache.py, trocar chave(); em circulo/fatiador.py, criar fatias_por_regra().", agora, agora))
    circle.licoes.verificar("developer:teto", False, sujeito=fatiador.sujeito(item), licao=False,
                            motivo="teto de tokens do item: 94705 gastos + ~5919 da próxima chamada > 100000")
    alvo = fatiador.proximo(circle.ctx, dev, plan)
    partes = [dict(r) for r in circle.store.q("SELECT * FROM roadmap WHERE pai=? ORDER BY ordem", (item,))]
    assert llm.prompts == [] and len(partes) == 2 and alvo == partes[0]["id"]
    assert "circulo/planejador_cache.py" in partes[0]["titulo"] and "fatias_por_regra" in partes[1]["detalhe"]
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "dividido"

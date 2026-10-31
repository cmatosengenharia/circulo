"""Girar sem avançar é erro de estrutura: o loop percebe a estagnação, diz a causa e para de girar à toa."""
import time

from circulo.loop import ESTAGNADO


def estagnar(circle, recusas=None):
    """Simula trabalho pendente que nunca avança (o porteiro do gasto recusa tudo)."""
    circle.trabalho_pendente = lambda ignorar_estagnacao=False: (ignorar_estagnacao or
                                                                int((circle.store.get("progresso") or {}).get("sem", 0)) < 3)
    circle._tem_trabalho = lambda t: False
    for _ in range(ESTAGNADO):
        circle.tick()
        if recusas:
            pg = circle.store.get("progresso")
            pg["recusas"] = recusas
            circle.store.set("progresso", pg)


def test_estagnacao_vira_licao_com_a_causa_e_derruba_a_confianca(circle):
    from circulo.confianca import confianca
    estagnar(circle, recusas={"estudar_pedido": 27})
    lic = circle.store.one("SELECT classe, item_id FROM licoes WHERE assinatura='loop:estagnado'")
    assert lic["classe"] == "estrutural" and lic["item_id"]
    assert circle.store.one("SELECT 1 FROM alerts WHERE message LIKE 'Estagnação%estudar_pedido recusado 27x%'")
    circle.store.set("batimento", {"em": time.time(), "pid": 1})
    c = {x["id"]: x for x in confianca(circle.store)["checks"]}["progresso"]
    assert c["estado"] == "falha" and "estudar_pedido" in c["porque"]


def test_estagnacao_sem_recusa_diz_o_que_rodou_sem_avancar(circle):
    """Lição #47: "causa provável: sem recusa registrada" deixava o loop cego. Sem recusa, a causa é o que os giros
    parados fizeram de fato (tarefa que rodou sem avançar, erro), medido giro a giro."""
    circle.trabalho_pendente = lambda ignorar_estagnacao=False: True
    circle.idle = lambda: "corrigir_codigo"                        # roda, mas não muda nada do que conta como avanço
    for _ in range(ESTAGNADO):
        circle.tick()
    alerta = circle.store.one("SELECT message FROM alerts WHERE message LIKE 'Estagnação%' ORDER BY id DESC LIMIT 1")
    assert alerta and f"corrigir_codigo rodou sem avançar {ESTAGNADO}x" in alerta["message"]
    assert "sem recusa registrada" not in alerta["message"]


def test_estagnado_vai_para_o_descanso_longo(circle):
    circle.store.set("progresso", {"sem": 3})
    assert not circle.trabalho_pendente()
    assert isinstance(circle.trabalho_pendente(ignorar_estagnacao=True), bool)


def test_avanco_zera_a_contagem(circle):
    circle.store.set("progresso", {"sem": ESTAGNADO + 2, "recusas": {"x": 3}})
    antes = circle._progresso()
    circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                   "VALUES('novo','d','loop','pendente','',999,0,1)")
    circle._vigiar_progresso(True, antes, None)
    assert circle.store.get("progresso")["sem"] == 0
    assert circle.store.one("SELECT ok FROM verificacoes WHERE ponto='loop:progresso' ORDER BY id DESC LIMIT 1")["ok"] == 1


def test_recusa_espera_cada_vez_mais(circle):
    """Recusado pelo porteiro do gasto, a mesma tarefa não é tentada de novo no giro seguinte."""
    circle.store.set("progresso", {"sem": 0, "recusas": {"estudar_pedido": 3}})
    circle.store.set("idle_last", {"estudar_pedido": circle.store.tick})
    circle.self_dev = object()
    circle.estudo.precisa = lambda: True
    escolhidas = {circle.tick().idle_task for _ in range(5)}
    assert "estudar_pedido" not in escolhidas                    # 2^3 = 8 giros de espera


def test_um_porteiro_so(circle):
    """O loop decide o gasto uma vez; o estudo chamado por ele não pergunta de novo com outro limiar."""
    from circulo.estudo import Estudo
    perguntas = []
    original = circle.ctx.dl.worth_spending
    circle.ctx.dl.worth_spending = lambda a, c: perguntas.append(a) or original(a, c)
    Estudo(circle.ctx).run(autorizado=True)
    assert "estudo_pedido" not in perguntas


def test_correcao_unica_do_orcamento(circle):
    from datetime import datetime

    from circulo.budget import TZ, tirar_assinatura_do_orcamento
    dia = datetime.now(TZ).date().isoformat()
    circle.store.set("orcamento_sem_assinatura", None)
    circle.store.x("INSERT OR IGNORE INTO budget(day) VALUES(?)", (dia,))
    circle.store.x("UPDATE budget SET tokens=150000 WHERE day=?", (dia,))
    circle.store.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,ok,created_at) VALUES(1,'developer','x','fixo',100000,1,?)", (time.time(),))
    assert tirar_assinatura_do_orcamento(circle.store) == 100000
    assert circle.store.one("SELECT tokens FROM budget WHERE day=?", (dia,))["tokens"] == 50000
    assert tirar_assinatura_do_orcamento(circle.store) == 0        # só uma vez


def test_esperar_o_espacamento_nao_e_estagnacao(circle):
    """Conserto do Developer espera o espaçamento desde a última tentativa: isso não conta como trabalho parado."""
    circle._tem_trabalho = lambda t: t == "corrigir_codigo"
    circle.store.set("idle_last", {"corrigir_codigo": circle.store.tick})
    assert not circle.trabalho_pendente(ignorar_estagnacao=True)
    circle.store.set("idle_last", {"corrigir_codigo": circle.store.tick - 2})
    assert circle.trabalho_pendente(ignorar_estagnacao=True)


def test_licao_47_nenhum_disparo_com_mais_de_30_giros_fica_sem_desfecho(circle):
    """Lição #47: 13 de 15 disparos da estagnação ficavam sem resultado, e a taxa_destravou=1.0 vinha de 2 casos.
    Todo disparo fecha no mesmo registro: 'destravou' quando o avanço volta, 'expirou' após 30 giros sem avanço."""
    from circulo.estagnacao import EXPIRA_EM, medir_disparos
    s = circle.store
    for giro in range(80):
        if giro in (0, 5, 40):
            s.x("INSERT INTO vigia_disparos(chave,acao,evidencia,em,giro) VALUES('estagnacao','alertar','{}',?,?)", (time.time(), giro))
        medir_disparos(s, giro, avancou=giro == 25)      # um avanço 25 giros depois do 1º disparo; o 3º nunca destrava
    d = {r["giro"]: (r["resultado"], r["giros_ate_destravar"]) for r in s.q("SELECT * FROM vigia_disparos")}
    assert EXPIRA_EM == 30
    assert d == {0: ("destravou", 25), 5: ("destravou", 20), 40: ("expirou", None)}
    assert not s.one("SELECT COUNT(*) n FROM vigia_disparos WHERE resultado IS NULL AND giro<=?", (79 - EXPIRA_EM,))["n"]


def test_licao_47_disparo_grava_o_estado_de_cada_pendencia_e_a_causa_por_regra(circle):
    """Lição #47: no lugar do palpite, o disparo guarda o último estado de cada pendência (CI, teto, LLM, tarefa
    elegível) e a causa sai da primeira que segura o loop."""
    from circulo import vigia
    s = circle.store
    s.set("progresso", {"sem": ESTAGNADO, "recusas": {"estudar_pedido": 4}})
    p = vigia.s_estagnacao(s, time.time())["evidencia"]["pendencias"]
    assert p == {"aguardando_ci": 0, "aguardando_teto": 4, "aguardando_llm": False, "sem_tarefa_elegivel": False,
                 "causa": "aguardando teto"}
    s.x("INSERT INTO prs(number,titulo,status,created_at,updated_at) VALUES(9,'t','aberto',0,0)")
    assert vigia.s_estagnacao(s, time.time())["evidencia"]["pendencias"]["causa"] == "aguardando CI"
    s.x("UPDATE prs SET status='mergeado'")
    s.set("progresso", {"sem": ESTAGNADO})
    s.set("self_dev_espera", {"ate": time.time() + 600, "motivo": "limite"})
    assert vigia.s_estagnacao(s, time.time())["evidencia"]["pendencias"]["causa"] == "aguardando LLM"
    s.set("self_dev_espera", None)
    assert vigia.s_estagnacao(s, time.time())["evidencia"]["pendencias"]["causa"] == "sem tarefa elegível"

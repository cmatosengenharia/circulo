"""Pergunta #159 (entrevistador_jtbd): os 32 pedidos da semana que a métrica conta são os itens 'pedido_cassio' do
roteiro, mas o agrupador só via o job gravado nos eventos: havia padrão repetido e antecipacao.propostas ficava em 0.
Agora o job sai das palavras-chave do próprio pedido e cada job com ≥3 pedidos vira uma proposta antecipada."""
import time

from circulo import antecipacao, jobs, jtbd, perguntas

PADRAO = ["Mostrar no painel do loop quantos PRs o developer abriu", "No painel, separar os PRs do developer por dia",
          "Quero ver no painel o que o loop aprendeu hoje", "O loop deveria explicar no painel por que parou"]
SOLTOS = ["Corrigir o bug do botão de enviar", "Trocar a cor do cabeçalho", "Responder mais rápido", "Mudar o nome do botão"]


def _pedidos(s, textos):
    agora = time.time()
    s.x("DELETE FROM roadmap WHERE origem='pedido_cassio'")    # o roteiro semente não entra na contagem da semana
    for i, t in enumerate(textos):
        s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
            "VALUES(?,?,'pedido_cassio','pendente','pedido pelo painel',?,?,?)", (t[:160], t, i, agora - i * 3600, agora))


def _pergunta(s):
    agora = time.time()
    return s.x("INSERT INTO perguntas(chave,persona,texto,status,created_at,updated_at) "
               "VALUES('jtbd',?,'qual job se repete e o loop poderia ter entregue sem ser pedido?','feita',?,?)",
               (jtbd.PERSONA, agora, agora))


def _propostas(s):
    return s.q("SELECT titulo, status, origem, pergunta_id FROM roadmap WHERE titulo LIKE 'antecipar:%'")


def test_agrupar_pelo_texto_do_pedido_aponta_o_job_que_se_repete():
    pedidos = [{"titulo": t, "detalhe": t, "created_at": 0.0} for t in PADRAO + SOLTOS * 7]
    assert len(pedidos) == 32
    assert antecipacao.agrupar(pedidos).jobs == {"evoluir_loop": 4}


def test_32_pedidos_do_roteiro_com_padrao_repetido_viram_uma_proposta_medida(circle):
    s = circle.store
    perg = _pergunta(s)
    _pedidos(s, PADRAO + SOLTOS * 7)
    assert perguntas._m_pedidos_humano(s, time.time())[1]["pedidos_7d"] == 32
    assert jtbd.precisa(s)

    circle._run_idle_task("antecipar")
    props = _propostas(s)
    assert [p["titulo"].split(" ")[0] for p in props] == ["antecipar:evoluir_loop"]
    assert props[0]["status"] == "proposto" and props[0]["origem"] == "loop" and props[0]["pergunta_id"] == perg
    medida = perguntas._m_pedidos_humano(s, time.time())[1]["antecipacao"]
    assert medida["propostas"] == 1 and medida["ignorada"] == 1

    s.x("UPDATE roadmap SET status='pendente' WHERE titulo LIKE 'antecipar:%'")     # o humano aceitou a proposta
    assert jobs.medir_propostas(s).taxa == 1.0

    circle._run_idle_task("antecipar")                     # idempotente: a mesma semana não duplica
    assert len(_propostas(s)) == 1
    assert not jtbd.precisa(s)


def test_sem_pergunta_do_conselho_o_padrao_do_roteiro_nao_vira_proposta(circle):
    s = circle.store
    _pedidos(s, PADRAO)
    assert jtbd.propor(s) == []
    assert _propostas(s) == []


def _medida(s):
    return perguntas._m_pedidos_humano(s, time.time())[1]["antecipacao"]


def test_32_pedidos_sem_grupo_de_3_dizem_que_o_limiar_barrou_a_proposta(circle):
    """Pergunta #167: 32 pedidos e propostas=0 sem dizer por quê; a métrica expõe o maior grupo e o motivo."""
    s = circle.store
    _pergunta(s)
    _pedidos(s, PADRAO[:2] + SOLTOS * 7 + SOLTOS[:2])
    assert perguntas._m_pedidos_humano(s, time.time())[1]["pedidos_7d"] == 32
    circle._run_idle_task("antecipar")
    medida = _medida(s)
    assert medida["propostas"] == 0
    assert medida["job_maior_grupo"] == 2 and medida["motivo_sem_proposta"] == "maior grupo 2 < limiar 3"


def test_32_pedidos_sem_job_classificado_dizem_que_a_classificacao_barrou(circle):
    s = circle.store
    _pergunta(s)
    _pedidos(s, SOLTOS * 8)
    circle._run_idle_task("antecipar")
    medida = _medida(s)
    assert medida["propostas"] == 0
    assert medida["job_maior_grupo"] == 0 and medida["motivo_sem_proposta"] == "pedidos sem job classificado"


def test_padrao_sem_pergunta_do_conselho_diz_por_que_nao_virou_proposta(circle):
    s = circle.store
    _pedidos(s, PADRAO)
    medida = _medida(s)
    assert medida["propostas"] == 0 and medida["job_maior_grupo"] == 4
    assert medida["motivo_sem_proposta"] == "sem pergunta do entrevistador_jtbd"


def test_com_proposta_o_motivo_fica_vazio_e_o_maior_grupo_continua(circle):
    s = circle.store
    _pergunta(s)
    _pedidos(s, PADRAO)
    circle._run_idle_task("antecipar")
    medida = _medida(s)
    assert medida["propostas"] == 1 and medida["job_maior_grupo"] == 4 and medida["motivo_sem_proposta"] == ""

"""Disjuntor por assinatura na seleção do roadmap: 5 falhas locais iguais no item o tiram da fila ('bloqueado', com
motivo e data, registrado para o conselho); depois do cooldown, ou quando o node id muda, ele ganha UMA tentativa
(meio-aberto). Item de lição fechada só sai da fila se o node id passar isolado no main (o curador do item #37)."""
import time

from circulo import fatiador, licoes, reparo, roadmap


class Fila:
    """O `pick` do Developer: o primeiro pendente na ordem."""
    repo = "repo-falso"

    def __init__(self, store):
        self.s = store

    def pick(self):
        r = self.s.one("SELECT * FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 ORDER BY ordem LIMIT 1")
        return dict(r) if r else None


def _item(s, titulo, ordem):
    return s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
               "VALUES(?,'d','erro','pendente','',?,0,0)", (titulo, ordem))


def _falhar(circle, item_id, n, motivo="FAILED tests/test_x.py::test_y - AssertionError: assert 0 == 1"):
    for i in range(n):
        circle.licoes.verificar("developer:base", False, sujeito=f"roteiro #{item_id}", item_id=item_id, licao=False,
                                motivo=motivo.replace("{i}", str(i)))


def _licao(s, item_id, status):
    return s.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,status,ocorrencias,reincidencias,item_id,node_id,"
               "created_at,updated_at) VALUES('sig','developer:testes','trabalho','d',?,1,0,?,'tests/test_x.py::test_y',0,0)",
               (status, item_id))


def _proximo(circle):
    return fatiador.proximo(circle.ctx, Fila(circle.store), None)


def test_item_com_11_falhas_iguais_nao_e_escolhido_e_fica_bloqueado_com_motivo_e_data(circle):
    s = circle.store
    preso, livre = _item(s, "preso", 1), _item(s, "livre", 2)
    _falhar(circle, preso, 11)
    assert _proximo(circle) == livre
    st = s.one("SELECT status, evidencia FROM roadmap WHERE id=?", (preso,))
    assert st["status"] == "bloqueado" and "11 falhas locais iguais" in st["evidencia"]
    assert "developer:base:teste:tests/test_x.py::test_y" in st["evidencia"]
    assert time.strftime("%Y-%m-%d") in st["evidencia"]                  # a data
    conselho = s.one("SELECT * FROM verificacoes WHERE ponto=?", (roadmap.PONTO,))
    assert conselho["item_id"] == preso and conselho["ok"] == 0


def test_falhas_com_assinaturas_diferentes_nao_abrem_o_disjuntor(circle):
    s = circle.store
    item = _item(s, "variado", 1)
    _falhar(circle, item, 11, motivo="FAILED tests/test_x.py::test_{i} - AssertionError")
    assert _proximo(circle) == item


def test_meio_aberto_da_uma_tentativa_depois_do_cooldown_e_a_falha_seguinte_bloqueia_de_novo(circle):
    s = circle.store
    item, outro = _item(s, "preso", 1), _item(s, "outro", 2)
    _falhar(circle, item, 10)
    assert _proximo(circle) == outro
    d = s.get(roadmap.DISJUNTOR)
    s.set(roadmap.DISJUNTOR, {str(item): {**d[str(item)], "em": d[str(item)]["em"] - roadmap.COOLDOWN - 1}})
    assert _proximo(circle) == item                                        # meio-aberto: uma tentativa
    _falhar(circle, item, 1)
    assert _proximo(circle) == outro                                       # falhou de novo: abre na hora
    d = s.get(roadmap.DISJUNTOR)[str(item)]
    assert d["vezes"] == 2 and s.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "bloqueado"
    s.set(roadmap.DISJUNTOR, {str(item): {**d, "em": d["em"] - roadmap.COOLDOWN - 1}})
    assert _proximo(circle) == outro                                       # o cooldown dobra a cada reabertura


def test_node_id_novo_reabre_o_item_bloqueado_antes_do_cooldown(circle):
    s = circle.store
    item = _item(s, "preso", 1)
    lid = _licao(s, item, "aberta")
    _falhar(circle, item, 10)
    assert _proximo(circle) != item
    s.x("UPDATE licoes SET node_id='tests/test_x.py::test_z' WHERE id=?", (lid,))
    assert _proximo(circle) == item


def _licao_fechada(s, item):
    _licao(s, item, "validada")


def test_item_de_licao_fechada_com_node_id_verde_no_main_nao_e_escolhido(circle, monkeypatch):
    s = circle.store
    fechado, livre = _item(s, "Lição #1: x", 1), _item(s, "livre", 2)
    _licao_fechada(s, fechado)
    rodados = []
    monkeypatch.setattr(licoes, "reexecutar_no_main", lambda repo, nodes, *a, **k: (rodados.append((repo, nodes)) or
                                                                                    ("abc123", {n: 0 for n in nodes})))
    assert _proximo(circle) == livre
    assert rodados == [("repo-falso", ["tests/test_x.py::test_y"])]       # o node id isolado, no main
    st = s.one("SELECT status, evidencia FROM roadmap WHERE id=?", (fechado,))
    assert st["status"] == "feito" and "tests/test_x.py::test_y" in st["evidencia"] and "abc123" in st["evidencia"]


def test_item_de_licao_fechada_com_node_id_vermelho_no_main_segue_na_fila(circle, monkeypatch):
    s = circle.store
    fechado = _item(s, "Lição #1: x", 1)
    _licao_fechada(s, fechado)
    monkeypatch.setattr(licoes, "reexecutar_no_main", lambda repo, nodes, *a, **k: ("abc123", {n: 1 for n in nodes}))
    assert _proximo(circle) == fechado
    assert s.one("SELECT status FROM roadmap WHERE id=?", (fechado,))["status"] == "pendente"


def test_deve_bloquear_no_teto_de_5_falhas_com_a_mesma_assinatura():
    assert not roadmap.deve_bloquear(4) and roadmap.deve_bloquear(5) and roadmap.deve_bloquear(6)
    assert roadmap.deve_bloquear(1, limite=1) and not roadmap.deve_bloquear(0, limite=1)


def test_6_falhas_iguais_levam_a_bloqueado_e_o_item_nao_e_escalado(circle):
    s = circle.store
    preso, livre = _item(s, "preso", 1), _item(s, "livre", 2)
    _falhar(circle, preso, 6)
    assert _proximo(circle) == livre
    st = s.one("SELECT status, evidencia FROM roadmap WHERE id=?", (preso,))
    assert st["status"] == "bloqueado" and "6 falhas locais iguais" in st["evidencia"]
    assert "tests/test_x.py::test_y" in s.get(roadmap.DISJUNTOR)[str(preso)]["sig"]        # a assinatura gravada
    s.x("UPDATE roadmap SET status='feito' WHERE id=?", (livre,))
    assert _proximo(circle) != preso                                        # sem o livre, segue sem ser escalado
    assert s.one("SELECT status FROM roadmap WHERE id=?", (preso,))["status"] == "bloqueado"


def test_4_falhas_iguais_e_2_diferentes_nao_acionam_o_bloqueio(circle):
    s = circle.store
    item = _item(s, "misto", 1)
    _falhar(circle, item, 4)
    _falhar(circle, item, 2, motivo="FAILED tests/test_x.py::test_outro_{i} - AssertionError")
    assert _proximo(circle) == item
    assert s.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "pendente"


def test_base_vermelha_repetida_6_vezes_bloqueia_mesmo_com_um_unico_evento(circle):
    """A base vermelha grava um evento por (item, assinatura) e conta as repetições no kv (item #144: 3786 falhas
    locais sem o disjuntor abrir); o teto conta as duas."""
    s = circle.store
    preso, livre = _item(s, "preso", 1), _item(s, "livre", 2)
    _falhar(circle, preso, 1)
    base = {"sig": "tests/test_x.py::test_y AssertionError", "n": 6, "chave": "t"}
    s.set(reparo.BASE_VERMELHA, {str(preso): base})
    assert _proximo(circle) == livre
    st = s.one("SELECT status, evidencia FROM roadmap WHERE id=?", (preso,))
    assert st["status"] == "bloqueado" and "6 falhas locais iguais" in st["evidencia"]
    d = s.get(roadmap.DISJUNTOR)[str(preso)]
    s.set(roadmap.DISJUNTOR, {str(preso): {**d, "em": d["em"] - roadmap.COOLDOWN - 1}})
    assert _proximo(circle) == preso                                       # meio-aberto: o contador antigo não conta
    s.set(reparo.BASE_VERMELHA, {str(preso): {**base, "n": 7}})
    assert _proximo(circle) == livre                                       # a mesma base vermelha de novo: bloqueia


def test_entrega_sem_uso_apos_7_dias_vira_um_item_de_decisao_por_evento_esperado(circle):
    """Pergunta do conselho #342 (pm): a entrega sem uso há 7+ dias vira 1 item de decisão (divulgar ou remover) preso
    à pergunta; uma segunda execução não duplica e a entrega com uso não gera nenhum."""
    from circulo.uso_entregas import registrar_esperado
    s, agora = circle.store, time.time()
    pm = s.x("INSERT INTO perguntas(chave,persona,texto,status,created_at,updated_at) "
             "VALUES('uso','pm','Quantas entregas têm uso depois do merge?','feita',0,0)")
    registrar_esperado(s.db, 10, "changelog_aberto", agora=agora - 8 * 86400)
    registrar_esperado(s.db, 11, "assunto_executado", agora=agora - 8 * 86400)
    s.x("INSERT INTO events(kind,payload,created_at) VALUES('assunto_executado','{}',?)", (agora - 86400,))

    novos = roadmap.decidir_sem_uso(s, pm, agora)
    assert roadmap.decidir_sem_uso(s, pm, agora) == []

    itens = s.q("SELECT * FROM roadmap WHERE pergunta_id=?", (pm,))
    assert [i["id"] for i in itens] == novos and len(novos) == 1
    assert "changelog_aberto" in itens[0]["titulo"] and "divulgar ou remover" in itens[0]["titulo"]
    assert itens[0]["status"] == "pendente" and itens[0]["origem_status"] == "ok"
    s.x("UPDATE roadmap SET status='feito' WHERE id=?", (novos[0],))
    assert roadmap.decidir_sem_uso(s, pm, agora) == []                      # resolvido também não duplica


def test_cobertura_conta_cada_entrega_sem_uso_com_exatamente_um_item_e_aponta_a_duplicata(circle):
    """Pergunta do conselho #370 (pm): a medida do sucesso sai do DB do loop: 100% das entregas sem uso 7+ dias com
    exatamente 1 item de revisão; a entrega com uso fica fora e um item repetido conta como duplicata."""
    from circulo.planejador import gravar_item
    from circulo.revisao_uso import titulo
    from circulo.uso_entregas import registrar_esperado
    s, agora = circle.store, time.time()
    pm = s.x("INSERT INTO perguntas(chave,persona,texto,status,created_at,updated_at) "
             "VALUES('uso','pm','Quantas entregas têm uso depois do merge?','feita',0,0)")
    registrar_esperado(s.db, 40, "changelog_aberto", agora=agora - 8 * 86400)
    registrar_esperado(s.db, 41, "changelog_aberto", agora=agora - 9 * 86400)
    registrar_esperado(s.db, 42, "assunto_executado", agora=agora - 8 * 86400)
    s.x("INSERT INTO events(kind,payload,created_at) VALUES('assunto_executado','{}',?)", (agora - 86400,))
    assert roadmap.cobertura_sem_uso(s, agora) == {"sem_uso": 2, "com_1_item": 0, "duplicadas": 0, "cobertura": 0.0}

    roadmap.decidir_sem_uso(s, pm, agora)
    roadmap.decidir_sem_uso(s, pm, agora)
    assert roadmap.cobertura_sem_uso(s, agora) == {"sem_uso": 2, "com_1_item": 2, "duplicadas": 0, "cobertura": 1.0}

    gravar_item(s, pm, titulo(41, "changelog_aberto"), "repetido", "repetido")
    assert roadmap.cobertura_sem_uso(s, agora) == {"sem_uso": 2, "com_1_item": 1, "duplicadas": 1, "cobertura": 0.5}


def test_mergeados_7d_sem_criterio_e_criterio_sem_numero_e_unidade_sao_listados_com_a_proporcao_mensuravel():
    """Pergunta #186: dos PRs mergeados em 7 dias, quais não têm critério de sucesso e quais têm critério sem métrica
    com alvo numérico (número + unidade). PR fora da janela não conta; PR sem item é órfão."""
    dia, agora = 86400, 100 * 86400
    itens = {1: "Faz X.\nSucesso: lead time mediano cai de 120 min para ≤60 min",
             2: "Faz Y.\nSucesso: painel mais claro para o usuário",
             3: "Faz Z, sem linha de sucesso",
             4: "Sucesso: proporção de PRs com critério de 60% para ≥90%",
             5: "Sucesso: 0 falhas em 7 dias"}
    prs = [{"pr": 10, "item": 1, "mergeado_em": agora - dia},
           {"pr": 11, "item": 2, "mergeado_em": agora - 2 * dia},
           {"pr": 12, "item": 3, "mergeado_em": agora - 3 * dia},
           {"pr": 13, "item": None, "mergeado_em": agora - 4 * dia},
           {"pr": 14, "item": 4, "mergeado_em": agora - 5 * dia},
           {"pr": 15, "item": 5, "mergeado_em": agora - 8 * dia}]
    r = roadmap.criterios_dos_mergeados(prs, itens, agora)
    assert r["prs_7d"] == 5
    assert r["sem_criterio"] == [12, 13]
    assert r["sem_metrica"] == [{"pr": 11, "item": 2, "criterio": "painel mais claro para o usuário"}]
    assert r["mensuraveis"] == 2 and r["proporcao"] == 0.4 and not r["atingiu"]
    assert roadmap.criterios_dos_mergeados([], itens, agora)["proporcao"] == 1.0

    j = roadmap.criterios_dos_mergeados(prs, itens, agora, justificados={13: "PR humano de versão, sem item"})
    assert j["sem_criterio"] == [12] and j["justificados"] == [{"pr": 13, "motivo": "PR humano de versão, sem item"}]


def test_proporcao_mensuravel_e_lida_do_db_amostrada_no_giro_e_exposta_na_tela(circle):
    """Pergunta #186: a proporção sai dos PRs mergeados (branch circulo/fix-<item>-…) no DB, cada amostra fica na série
    (uma por dia) para medir a meta de ≥90% em duas semanas, e GET /api/trabalho/criterios a mostra com os órfãos."""
    from circulo import trabalho
    s, agora = circle.store, time.time()
    mensuravel = _item(s, "a", 1)
    vago = _item(s, "b", 2)
    s.x("UPDATE roadmap SET detalhe='Sucesso: p99 abaixo de 2 s' WHERE id=?", (mensuravel,))
    s.x("UPDATE roadmap SET detalhe='Sucesso: tela melhor' WHERE id=?", (vago,))
    for pr, branch, em in ((1, f"circulo/fix-{mensuravel}-1", agora - 86400), (2, f"circulo/fix-{vago}-1", agora - 86400),
                           (3, "humano/versao", agora - 2 * 86400), (4, f"circulo/fix-{mensuravel}-2", agora - 9 * 86400)):
        s.x("INSERT INTO prs(number,titulo,branch,status,created_at,updated_at) VALUES(?,'t',?,'mergeado',?,?)",
            (pr, branch, em, em))
        s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,'x',1,'ok','',?)", (pr, em))

    r = roadmap.amostrar_criterios(s, agora)
    assert (r["prs_7d"], r["mensuraveis"], r["sem_criterio"]) == (3, 1, [3])
    assert r["sem_metrica"] == [{"pr": 2, "item": vago, "criterio": "tela melhor"}]
    roadmap.amostrar_criterios(s, agora + 60)                               # mesmo dia: a série não duplica
    roadmap.amostrar_criterios(s, agora + 86400)
    assert [a["proporcao"] for a in roadmap.ler_criterios(s, agora)["serie"]] == [1 / 3, 1 / 3]

    s.set(roadmap.JUSTIFICADOS, {"3": "PR humano de versão"})
    tela = trabalho.api_get(s, circle.data_dir, "/api/trabalho/criterios", {})
    assert tela["sem_criterio"] == [] and tela["justificados"][0]["pr"] == 3 and tela["meta"] == 0.9

"""Equipe ao vivo: os agentes como um time; cada mensagem nasce de um registro real; o quadro vai da pergunta à produção."""
import json
import time
import urllib.request

from circulo import equipe

from test_painel import painel  # noqa: F401 — fixture do servidor do painel


def _cenario(s):
    agora = time.time() + 1          # tudo acontece DEPOIS do cursor inicial (o relógio do teste anda para a frente)
    i = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,created_at,updated_at) VALUES(?,?,'loop','em_andamento','PR #17',900,'ok',?,?)",
            ("Teto de tokens", "d", agora - 100, agora + 0.1))
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,item_id,arquivos,created_at,updated_at) VALUES(17,1,'t','b','aberto',?,'[]',?,?)", (i, agora - 50, agora - 50))
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(17,'s',0,'checks falhando: Testes','{}',?)", (agora + 0.2,))
    j = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,created_at,updated_at) VALUES(?,?,'loop','pendente','aguarda PR #17: compartilha x.py com o PR #17',901,'ok',?,?)",
            ("Gravar o id", "d", agora - 90, agora + 0.4))
    s.x("INSERT INTO revisoes(pr,item_id,momento,veredito,motivo,evidencia,conf,fonte,created_at) VALUES(NULL,?,'antes_do_pr','rejeitado','compartilha x.py com o PR #17','{}',0.6,'jev',?)", (j, agora + 0.3))
    s.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,eixo,pertinencia,score,created_at,updated_at) VALUES('k','arquiteto','Qual parte erra mais?','valida','loop','arquitetura',0.86,0.5,?,?)", (agora + 0.5, agora + 0.5))
    s.x("INSERT INTO vigia(chave,titulo,evidencia,sugestao,gravidade,veredito,acao,conf,classificacao,status,primeira_em,ultima_em,vezes) VALUES('pr_preso','PR #17 preso','{}','s',0.8,'trava','alertar',0.7,'{}','aberta',?,?,3)", (agora + 0.6, agora + 0.6))
    return i, j


def test_mensagens_nascem_dos_registros_e_citam_o_dado(circle):
    s = circle.store
    cur = equipe.cursor_inicial(s)
    assert equipe.mensagens(s, cur)[0] == []                                   # nada aconteceu: nenhuma mensagem
    i, j = _cenario(s)
    msgs, cur2 = equipe.mensagens(s, cur)
    por_tom = {}
    for m in msgs:
        por_tom.setdefault(m["tom"], []).append(m)
    assert all(m["de"] in equipe.EQUIPE and m["para"] in equipe.EQUIPE and m["tipo"] == "mensagem" for m in msgs)
    assert any(m["de"] == "corrigir_codigo" and m["para"] == "revisar_prs" and "PR #17" in m["texto"] for m in por_tom["entrega"])   # abriu o PR
    assert any(m["de"] == "revisar_prs" and m["para"] == "corrigir_codigo" and "checks falhando" in m["texto"] for m in por_tom["devolucao"])
    assert any(m["de"] == "revisor" and "aguarda PR #17" in m["texto"] for m in por_tom["devolucao"])                           # item devolvido
    # toda mensagem que fala de um item diz em que coluna do quadro ele fica agora: é o que move o cartão em tempo real
    com_item = [m for m in msgs if m.get("item") is not None and m["tom"] not in ("pergunta", "resposta")]
    assert com_item and all(m.get("coluna") in {"planejado", "pronto", "dev", "revisao", "devolvidos", "producao", "fora"} for m in com_item)
    assert any(m["de"] == "corrigir_codigo" and m.get("coluna") == "revisao" for m in com_item)
    assert any(m["de"] == "revisor" and m.get("coluna") == "devolvidos" for m in com_item)
    assert any(m["de"] == "indagar" and m["para"] == "jev" and "Qual parte" in m["texto"] for m in por_tom["pergunta"])
    assert any(m["de"] == "jev" and m["para"] == "indagar" and "86%" in m["texto"] for m in por_tom["resposta"])
    assert any(m["de"] == "vigia" and m["para"] == "orquestrador" and "PR #17 preso" in m["texto"] for m in por_tom["alerta"])
    assert [m["em"] for m in msgs] == sorted(m["em"] for m in msgs)
    assert equipe.mensagens(s, cur2)[0] == []                                  # o cursor andou: nada repete


def test_retrato_mostra_quem_faz_o_que_e_o_quadro(circle):
    s = circle.store
    i, j = _cenario(s)
    circle.tick()
    r = equipe.retrato(s)
    ids = {m["id"] for m in r["membros"]}
    assert ids == set(equipe.EQUIPE) and all(m["estado"] in ("trabalhando", "disponivel", "parado") for m in r["membros"])
    assert sum(m["estado"] == "trabalhando" for m in r["membros"]) <= 1 and r["rodando"]
    dev = next(m for m in r["membros"] if m["id"] == "corrigir_codigo")
    assert dev["carga"] >= 1 and dev["vagas"].endswith("PRs")
    cols = {c["chave"]: c for c in r["quadro"]}
    assert i in [k["id"] for k in cols["revisao"]["cards"]] and cols["revisao"]["cards"][0]["pr"] == 17
    assert j in [k["id"] for k in cols["devolvidos"]["cards"]]
    assert cols["ideias"]["cards"] and cols["ideias"]["cards"][0]["dono"] == "indagar"
    assert equipe.membro("shadow") == "meta_learner" and equipe.membro("tarefa_que_nasceu_depois") == "rotinas"


def test_pagina_equipe_api_e_menu_em_todas_as_telas(circle, painel):  # noqa: F811
    _cenario(circle.store)
    with urllib.request.urlopen(painel + "/api/equipe", timeout=5) as r:
        d = json.loads(r.read())
    assert d["membros"] and d["quadro"] and d["grupos"]
    for caminho in ("/equipe", "/", "/fluxo", "/rastros", "/integracoes"):
        with urllib.request.urlopen(painel + caminho, timeout=5) as r:
            html = r.read().decode()
        assert 'id="navTopo"' in html and 'href="/equipe"' in html and "Gestão do loop" in html, caminho
    pagina = urllib.request.urlopen(painel + "/equipe", timeout=5).read().decode()
    assert 'id="membros"' in pagina and 'id="msgs"' in pagina and 'id="colunas"' in pagina and "moverCard" in pagina and "#equipe" in pagina
    req = urllib.request.Request(painel + "/loop")
    with urllib.request.urlopen(req, timeout=5) as r:                           # /loop leva à missão do loop
        assert 'id="navTopo"' in r.read().decode() and "/missao/" in r.geturl()


def test_filtrar_por_pedido_mostra_a_linha_do_tempo_e_onde_esta_agora(circle, painel):  # noqa: F811
    """/api/equipe?pedido=evN: o fio daquele pedido (caixa → item → estudo → Developer/PR → merge) com o tempo de cada etapa."""
    s = circle.store
    t0 = time.time() - 3600
    ev = s.x("INSERT INTO events(kind,payload,status,created_at) VALUES('pedido',?,'done',?)",
             (json.dumps({"text": "Quero um atalho de busca"}), t0))
    i = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,'humano','pendente','',1,?,?)",
            ("Quero um atalho de busca", "d", t0 + 60, t0 + 60))
    s.x("INSERT INTO elos(de,para,relacao,em) VALUES(?,?,'virou_item',?)", (f"pedido:{ev}", f"item:{i}", t0 + 60))
    with urllib.request.urlopen(painel + f"/api/equipe?pedido=ev{ev}", timeout=5) as r:
        d = json.loads(r.read())
    assert d["membros"] and d["quadro"]                                         # a Equipe continua inteira
    p = d["pedido"]
    assert p["evento"] == ev and p["item"] == i and p["texto"] == "Quero um atalho de busca"
    etapas = {e["etapa"]: e for e in p["etapas"]}
    assert etapas["item"]["feita"] and abs(etapas["item"]["dur_s"] - 60) < 0.01     # o tempo da etapa caixa → item
    assert p["esperando"]["etapa"] == "estudo"                                  # onde está agora
    with urllib.request.urlopen(painel + "/api/equipe?pedido=ev999999", timeout=5) as r:
        assert json.loads(r.read())["pedido"] is None
    with urllib.request.urlopen(painel + "/api/equipe", timeout=5) as r:
        assert "pedido" not in json.loads(r.read())                             # sem filtro, o retrato de sempre

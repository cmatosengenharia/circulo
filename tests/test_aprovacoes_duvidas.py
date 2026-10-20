"""1.38.0: "Precisa de você" (tudo o que espera decisão humana, com ação), dúvidas do Jev estudadas pelo Arquiteto antes
de voltar ao Jev, e o pin automático da versão do Jev."""
import json
import time
import urllib.request

from circulo import aprovacoes, duvidas, indagador

from test_painel import painel, post  # noqa: F401 — fixture do servidor do painel


def test_precisa_de_voce_reune_tudo_com_a_acao_do_lado(circle):
    s = circle.store
    agora = time.time()
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES('Ligar as chaves','d','loop','pendente','diagnóstico: depende de você',1,?,?)", (agora, agora))
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES('Trocar o banco','d','pedido_cassio','contestado','contestado pelo estudo',2,?,?)", (agora, agora))
    s.x("INSERT INTO vigia(chave,titulo,evidencia,sugestao,gravidade,veredito,acao,conf,classificacao,status,primeira_em,ultima_em,vezes) VALUES('x','PR preso','{}','ver',0.9,'trava','alertar',0.8,'{}','aberta',?,?,3)", (agora - 8 * 3600, agora))
    s.x("INSERT INTO alerts(kind,message,created_at) VALUES('merge','Corpo subiu a 1.38.0',?)", (agora,))
    circle.set_control(pausado=True)
    itens = aprovacoes.pendentes(s, diagnostico=False)
    tipos = [i["tipo"] for i in itens]
    assert tipos[0] == "loop_pausado" and itens[0]["acoes"][0]["acao"] == "retomar"          # o mais urgente primeiro
    assert {"item_depende", "item_contestado", "trava", "aviso"} <= set(tipos)
    assert next(i for i in itens if i["tipo"] == "trava")["titulo"].startswith("Trava há 8 h")
    r = aprovacoes.resumo(s)
    assert r["total"] >= len(itens) and r["urgentes"] >= 3                     # o resumo soma o diagnóstico de configuração
    # cada ação passa pelo mesmo caminho do botão que já existia
    assert aprovacoes.agir(s, "retomar", None)["ok"] and not circle.controls()["pausado"]
    cid = next(i for i in itens if i["tipo"] == "item_contestado")["ref"]
    assert aprovacoes.agir(s, "reafirmar_item", cid)["ok"] and s.one("SELECT status FROM roadmap WHERE id=?", (cid,))["status"] == "pendente"
    did = next(i for i in itens if i["tipo"] == "item_depende")["ref"]
    assert aprovacoes.agir(s, "desativar_item", did)["ok"] and s.one("SELECT desativado FROM roadmap WHERE id=?", (did,))["desativado"] == 1
    aid = next(i for i in itens if i["tipo"] == "aviso")["ref"]
    assert aprovacoes.agir(s, "visto", aid)["ok"] and s.one("SELECT delivered FROM alerts WHERE id=?", (aid,))["delivered"] == 1
    assert not aprovacoes.agir(s, "explodir", 1)["ok"]
    depois = [i["tipo"] for i in aprovacoes.pendentes(s, diagnostico=False)]
    assert "trava" in depois and not {"loop_pausado", "item_contestado", "aviso"} & set(depois)   # o que tinha ação saiu
    assert depois.count("item_depende") == tipos.count("item_depende") - 1                       # (os itens de instalação do próprio loop ficam)


def test_pagina_e_api_precisa_de_voce_e_selo_no_menu(circle, painel):  # noqa: F811
    j = json.loads(urllib.request.urlopen(painel + "/api/aprovacoes?so=n", timeout=5).read())
    assert set(j) == {"total", "urgentes"}
    html = urllib.request.urlopen(painel + "/aprovacoes", timeout=5).read().decode()
    assert "Precisa de você" in html and 'id="seloAprov"' in html
    assert 'id="seloAprov"' in urllib.request.urlopen(painel + "/equipe", timeout=5).read().decode()   # o selo está em toda tela
    circle.set_control(pausado=True)
    assert json.loads(urllib.request.urlopen(painel + "/api/aprovacoes?so=n", timeout=5).read())["total"] >= 1
    st, r = post(painel + "/api/aprovacoes/acao", {"acao": "retomar", "ref": None}, {"X-Circulo": "1"})
    assert st == 200 and r["ok"] and not circle.controls()["pausado"]
    assert circle.store.one("SELECT COUNT(*) n FROM alerts WHERE message LIKE 'Você decidiu em%'")["n"] == 1


class LLMEstudo:
    """Arquiteto falso: devolve evidência medida e a pergunta reescrita."""
    def __init__(self):
        self.prompts = []

    def generate(self, system, prompt, model, max_tokens, web_search=0):
        self.prompts.append(prompt)
        from circulo.llm import LLMResult
        return LLMResult(json.dumps({"evidencia": [{"fato": "o planejador ficou 3 h parado medido na trilha", "base": "medido", "fonte": "trail"}],
                                     "pertinente": True, "motivo": "o dado existe", "eixo": "velocidade", "acionavel": 2,
                                     "pergunta_reescrita": "Qual regra do porteiro segurou o planejador por 3 h, e que sinal medido a destrava?",
                                     "fontes": ["https://exemplo"]}), 900, model)


def _duvida(s, texto="Como melhorar o sistema em geral?"):
    agora = time.time()
    return s.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,eixo,pertinencia,acionavel,evidencia,classificacao,created_at,updated_at) "
               "VALUES('k1','operador',?,'inconclusa','loop','nenhum',0.5,0,'{\"base\":\"inferido\"}','{\"pertinente\":{\"p\":0.5,\"conf\":0.1,\"fonte\":\"local\"}}',?,?)", (texto, agora, agora))


def test_duvida_do_jev_vai_para_o_arquiteto_e_volta_ao_jev_na_hora(circle):
    s = circle.store
    pid = _duvida(s)
    llm = LLMEstudo()
    circle.ctx.dl.llm = llm
    assert duvidas.pendente(s, "loop")["id"] == pid
    r = duvidas.estudar(circle.ctx, autorizado=True)
    assert r["resultado"] in ("valida", "descartada") and r["fatos"] == 1 and len(llm.prompts) == 1
    assert "Como melhorar o sistema" in llm.prompts[0] and "Axis keys" in llm.prompts[0]
    velha = s.one("SELECT status, classificacao FROM perguntas WHERE id=?", (pid,))
    assert velha["status"] == "estudada" and json.loads(velha["classificacao"])["estudo"]["nova"] == r["nova"]
    nova = s.one("SELECT texto, status, evidencia, classificacao FROM perguntas WHERE id=?", (r["nova"],))
    assert nova["texto"].startswith("Qual regra do porteiro") and json.loads(nova["evidencia"])["base"] == "medido"
    assert json.loads(nova["classificacao"])["apos_estudo"] is True
    assert s.one("SELECT COUNT(*) n FROM llm_calls WHERE papel='estudo_duvida'")["n"] == 1
    assert duvidas.pendente(s, "loop") is None                                  # cada dúvida é estudada uma vez
    res = indagador.resumo(s)["duvidas"]
    assert res["estudadas"] == 1 and (res["viraram_validas"] + res["apos_estudo"].get("descartada", 0)) == 1


def test_duvida_sem_llm_fica_marcada_e_nao_trava_nada(circle):
    s = circle.store
    pid = _duvida(s)
    circle.ctx.dl.llm = None
    assert duvidas.estudar(circle.ctx)["resultado"] == "sem_llm"
    assert json.loads(s.one("SELECT classificacao FROM perguntas WHERE id=?", (pid,))["classificacao"])["estudo"]["resultado"] == "sem_llm"
    assert duvidas.estudar(circle.ctx) is None                                  # não repete


def test_pin_automatico_da_versao_do_jev(tmp_path, clock, monkeypatch):
    from circulo.decision import JevHttpClient
    from circulo.loop import Circle
    monkeypatch.setenv("TYPESAFE_API_KEY", "x")
    c1 = Circle(tmp_path, now=clock)
    assert isinstance(c1.ctx.dl.jev, JevHttpClient) and c1.ctx.dl.jev.model == "jev-latest"     # nada visto ainda: alias
    c1.store.set("jev_modelo", "jev-1.13.0")                                      # a primeira resposta disse a versão exata
    c2 = Circle(tmp_path, now=clock)
    assert c2.ctx.dl.jev.model == "jev-1.13.0"                                    # o loop seguinte já sobe fixo nela
    monkeypatch.setenv("JEV_MODEL", "jev-1.12.0")
    assert Circle(tmp_path, now=clock).ctx.dl.jev.model == "jev-1.12.0"           # a sua escolha explícita vale mais

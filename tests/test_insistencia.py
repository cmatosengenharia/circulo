"""31/10: o loop estava faminto (280 giros, Developer em 12). Fila nunca vazia (épicos), perguntas de produto na frente
com o Jev só vetando, sub-itens mortos fora da fila, bloqueados antigos com nova rodada, lição esgotada não abre item."""
import time

from circulo import aprovacoes, higiene, indagador, insistencia, perguntas
from circulo.reparo import BLOQUEADO, DISJUNTOR


def _item(s, titulo, origem="loop", status="pendente", agora=None, evidencia="", desativado=0):
    agora = agora or time.time()
    return s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,created_at,updated_at,desativado) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (titulo, "d", origem, status, evidencia, 10, "e", agora, agora, desativado))


def test_epicos_enchem_a_fila_so_quando_nao_ha_item_de_produto(circle):
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    ps = {p.id: p for p in perguntas._epicos(s, time.time())}
    assert len(ps) == len(perguntas.EPICOS) and all(p.eixo == "produto" and p.persona == "pm" for p in ps.values())
    assert "epico:fabrica_segundo_repo" in ps and ps["epico:fabrica_segundo_repo"].evidencia["base"] == "medido"
    c = perguntas.Conselho(circle.ctx)
    assert any(p.id.startswith("epico:") for p in c.candidatas())
    _item(s, "Pedido do time", origem="pedido_cassio")                       # com item de produto pendente, os épicos calam
    assert perguntas._epicos(s, time.time()) == []
    s.set("norte_epicos", [{"chave": "x", "texto": "Como PM, o que falta em X?", "relevancia": 0.9}])
    s.x("UPDATE roadmap SET status='feito'")
    e = perguntas._epicos(s, time.time())
    assert [p.id for p in e] == ["epico:x"] and e[0].relevancia == 0.9                 # o kv sobrescreve a lista padrão


def test_perguntas_de_produto_vao_na_frente_e_o_jev_so_veta(circle):
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    cands = indagador.candidatas(circle.ctx, None)
    assert cands and all(c.get("eixo") == "produto" for c in cands[:indagador.VAGAS_PRODUTO])
    assert len(cands) <= indagador.MAX_CANDIDATAS
    # o Jev (regra local) classifica; a pergunta de produto passa sem p ≥ 0.6, só não passa se p < 0.25
    res = indagador.classificar(circle.ctx, cands[:2], indagador.contexto(s, None))
    assert all(r["veredito"] == "valida" and r["eixo"] != "nenhum" for r in res)
    r = indagador.indagar(circle.ctx, None)
    assert r["validas"] >= 1
    assert s.one("SELECT COUNT(*) n FROM perguntas WHERE status='valida' AND eixo='produto'")["n"] >= 1


def test_higiene_tira_sub_item_morto_e_reabre_bloqueado_antigo(circle):
    s = circle.store
    agora = time.time()
    morto = _item(s, "sub-item parado", origem="sub_item", agora=agora - 8 * 86400)
    vivo = _item(s, "sub-item novo", origem="sub_item", agora=agora - 2 * 86400)
    velho = _item(s, "bloqueado por lint", status=BLOQUEADO, agora=agora - 4 * 86400, desativado=1)
    velho2 = _item(s, "bloqueado por lint 2", status=BLOQUEADO, agora=agora - 5 * 86400, desativado=1)
    velho3 = _item(s, "bloqueado por lint 3", status=BLOQUEADO, agora=agora - 6 * 86400, desativado=1)
    teto = _item(s, "bloqueado pelo teto", status=BLOQUEADO, agora=agora - 9 * 86400, desativado=1, evidencia="disjuntor do teto: 400k")
    recente = _item(s, "bloqueado ontem", status=BLOQUEADO, agora=agora - 86400, desativado=1)
    s.set(DISJUNTOR, {str(velho): {"sig": "lint", "n": 2}, str(recente): {"sig": "lint", "n": 2}})
    rel = higiene.rodar(s, agora, forcar=True)
    assert rel["sub_itens"] == 1 and rel["reabertos"] == insistencia.REABERTURAS_POR_PASSAGEM
    est = {r["id"]: (r["status"], r["desativado"]) for r in s.q("SELECT id, status, desativado FROM roadmap")}
    assert est[morto][0] == "descartado" and est[vivo][0] == "pendente"
    assert est[velho3] == ("pendente", 0) and est[velho2] == ("pendente", 0)           # os 2 mais antigos primeiro
    assert est[velho][0] == BLOQUEADO and est[teto][0] == BLOQUEADO and est[recente][0] == BLOQUEADO
    assert "reaberto pela higiene" in s.one("SELECT evidencia FROM roadmap WHERE id=?", (velho3,))["evidencia"]
    assert str(velho) in s.get(DISJUNTOR)                                                 # só quem reabriu zera o contador
    assert insistencia.reabrir_bloqueados(s, agora + 3600) == [velho]                     # próxima passagem: o terceiro


def test_licao_com_tres_prs_que_ainda_reincide_nao_abre_mais_item(circle):
    s = circle.store
    agora = time.time()
    item = _item(s, "Lição #9: falha", origem="erro", status="feito")
    for n in (1, 2):
        s.x("INSERT INTO prs(number,titulo,branch,status,item_id,consertos,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (n, "t", "b", "mergeado", item, 0, agora, agora))
    lic = {"id": 9, "item_id": item, "descricao": "falha"}
    avisos = []
    assert not insistencia.licao_esgotada(s, lic, lambda m, k: avisos.append(m), agora)        # 2 PRs: ainda tenta
    s.x("INSERT INTO prs(number,titulo,branch,status,item_id,consertos,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (3, "t", "b", "mergeado", item, 0, agora, agora))
    assert insistencia.licao_esgotada(s, lic, lambda m, k: avisos.append(m), agora) and len(avisos) == 1
    assert insistencia.licao_esgotada(s, lic, lambda m, k: avisos.append(m), agora) and len(avisos) == 1    # avisa uma vez
    assert "esgotada" in avisos[0] and s.get(insistencia.KV_LICOES)["9"]["prs"] == 3
    assert any(i["tipo"] == "licao_esgotada" and i["ref"] == "9" for i in aprovacoes.pendentes(s, agora, diagnostico=False))
    assert not insistencia.licao_esgotada(s, {"id": 10, "item_id": None}, None, agora)


class _LLM:
    busca_web = True

    def __init__(self, texto):
        self.texto, self.prompts = texto, []

    def generate(self, *, system, prompt, model, max_tokens, web_search=0):
        from circulo.llm import LLMResult
        self.prompts.append((system, prompt))
        return LLMResult(self.texto, 0, model, [], entrada=10, saida=5)


def test_estudo_de_repositorio_vira_item_pronto_para_o_developer(circle):
    import json
    from circulo import mercado, norte
    from circulo.self_dev import SelfDeveloper
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    resposta = json.dumps({"perguntas": [{"texto": "Como tech lead, por que o loop não compacta o contexto por grafo?", "pratica": "graphiti", "fontes": [], "relevancia": 0.8}],
                           "itens": [{"titulo": "Portar a poda de contexto por grafo do graphiti: memoria.py envia só os nós ligados ao item",
                                      "detalhe": "lá: graphiti_core/search; aqui: memoria.para() filtra por aresta", "sucesso": "tokens por chamada do Developer caem 20% no teste",
                                      "fontes": ["https://github.com/getzep/graphiti/blob/main/README.md"]},
                                     {"titulo": "x", "detalhe": ""}]})
    circle.ctx.dl.llm = _LLM(resposta)
    avisos = []
    circle.ctx.reply = lambda m, k="": avisos.append(m)
    assert mercado.repo_devido(s)
    r = mercado.estudar_repositorio(circle.ctx)
    assert r["repo"] == mercado.REPOS[0] and len(r["itens"]) == 1 and "repositorio:" in circle.ctx.dl.llm.prompts[0][1]
    item = dict(s.one("SELECT * FROM roadmap WHERE id=?", (r["itens"][0],)))
    assert item["origem"] == "referencia" and item["estudo"] and item["status"] == "pendente" and "graphiti" in item["detalhe"]
    assert norte.e_produto(s, item) and norte.item_de_produto(s)["id"] == item["id"]
    dev = SelfDeveloper.__new__(SelfDeveloper)
    dev.s = s
    assert dev.pick()["id"] == item["id"]                                             # o Developer pega direto, sem estudo nem conselho
    assert not mercado.repo_devido(s) and "viraram item" in avisos[-1]
    assert r["perguntas"][0]["fontes"] == [mercado.REPOS[0]]
    from circulo import perguntas
    assert any(p.id.startswith("repo:") and p.evidencia["repositorio"] == mercado.REPOS[0] for p in perguntas._mercado(s, time.time()))
    r2 = mercado.estudar_repositorio(circle.ctx)                                        # rodízio: o próximo da lista; título repetido não duplica
    assert r2["repo"] == mercado.REPOS[1] and r2["itens"] == []
    s.set("repos_referencia", ["https://github.com/x/y"])
    assert mercado.repos(s) == ["https://github.com/x/y"]

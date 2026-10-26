"""Norte (25/10): o loop evolui em direção a resultados de produto medidos, não só a si mesmo."""
import json
import time

from circulo import mercado, norte, perguntas
from circulo.self_dev import SelfDeveloper


def _item(s, titulo, origem="loop", eixo=None, agora=None, estudo="e", ordem=10):
    agora = agora or time.time()
    iid = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
              (titulo, "d", origem, "pendente", "", ordem, estudo, agora, agora))
    if eixo:
        s.x("INSERT INTO perguntas(chave,persona,texto,relevancia,score,evidencia,status,cerebro,eixo,item_id,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (f"k{iid}", "pm", titulo, 1, 1, "{}", "virou_item", "loop", eixo, iid, agora, agora))
    return iid


def _pr(s, item_id, quando, arquivos=("circulo/x.py",), consertos=0, n=None):
    n = n or int(quando) % 100000
    s.x("INSERT INTO prs(number,titulo,branch,status,item_id,arquivos,consertos,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (n, "t", "b", "mergeado", item_id, json.dumps(list(arquivos)), consertos, quando - 7200, quando))


def test_norte_mede_cada_resultado_com_meta_e_distancia(circle):
    s = circle.store
    agora = time.time()
    s.x("UPDATE roadmap SET status='feito'")
    manut = _item(s, "Vigia: lição aberta", agora=agora - 10 * 3600)
    prod = _item(s, "Console: motivo da recusa do gate em 10 s", eixo="produto", agora=agora - 30 * 3600)
    _pr(s, manut, agora - 3600, n=1)
    _pr(s, prod, agora - 1800, arquivos=("circulo/painel.html",), consertos=1, n=2)
    m = norte.medir(s, agora)
    assert m["prs_produto_semana"]["valor"] == 1 and m["fracao_produto"]["valor"] == 0.5 and m["fracao_produto"]["distancia"] == 0
    assert m["console_semana"]["valor"] == 1 and m["merge_sem_conserto"]["valor"] == 0.5 and m["merge_sem_conserto"]["distancia"] > 0
    assert m["lead_time_h"]["valor"] > 0 and m["prs_produto_semana"]["distancia"] > 0 and m["repositorios"]["valor"] == 1
    r = norte.resumo(s)
    assert len(r["resultados"]) == 6 and r["prs_7d"] == 2 and r["fracao_24h"] == 0.5


def test_cota_poe_produto_antes_da_manutencao_quando_a_entrega_e_saudavel(circle, tmp_path):
    s = circle.store
    agora = time.time()
    s.x("UPDATE roadmap SET status='feito'")
    erro = _item(s, "Lição #9: falha", origem="erro", ordem=1)
    manut = _item(s, "Vigia: lição aberta", ordem=2)
    prod = _item(s, "PR com descrição de impacto", eixo="produto", ordem=50)
    dev = SelfDeveloper.__new__(SelfDeveloper)
    dev.s = s
    assert norte.prefere_produto(s)                              # sem PR recente: produto primeiro
    assert dev.pick()["id"] == prod
    s.set("entrega_parada", {"desde": agora})                    # entrega parada: a cota desliga, a correção vem antes
    assert not norte.prefere_produto(s) and dev.pick()["id"] == erro
    s.set("entrega_parada", None)
    _pr(s, prod, agora - 600, n=1)                               # 100 % produto nas últimas 24 h: manutenção volta à frente
    s.x("UPDATE roadmap SET status='feito' WHERE id=?", (prod,))
    assert not norte.prefere_produto(s) and dev.pick()["id"] == erro
    urg = _item(s, "Urgente: meta caindo", origem="erro", ordem=99)
    prod2 = _item(s, "Outro de produto", eixo="missao", ordem=60)
    _pr(s, manut, agora - 300, n=2)                              # 50 %: a cota está satisfeita; o Urgente passa na frente de tudo
    assert dev.pick()["id"] == urg
    s.x("UPDATE roadmap SET status='feito' WHERE id=?", (urg,))
    assert dev.pick()["id"] == erro                              # cota ok: ordem normal (erro primeiro)
    _pr(s, manut, agora - 200, n=3)                              # 1 de 3 é produto: abaixo da cota, produto de novo
    assert norte.prefere_produto(s) and dev.pick()["id"] == prod2


def test_tech_lead_pm_e_mercado_perguntam_contra_o_norte(circle):
    s = circle.store
    agora = time.time()
    ps = perguntas._norte(s, agora)
    chaves = {p.id for p in ps}
    assert {"tech_lead:lead_time", "pm:fracao_produto", "tech_lead:console"} <= chaves
    assert all(p.persona in ("tech_lead", "pm") and p.evidencia.get("norte") for p in ps)
    assert "tech_lead" in perguntas.PERSONAS and "mercado" in perguntas.PERSONAS
    s.set("mercado_pesquisa", {"em": agora, "perguntas": [{"texto": "Como tech lead, por que o PR não traz um resumo de impacto?",
                                                           "pratica": "Copilot coding agent escreve o resumo", "fontes": ["https://x"], "relevancia": 0.8}]})
    m = perguntas._mercado(s, agora)
    assert len(m) == 1 and m[0].persona == "mercado" and m[0].evidencia["fontes"] == ["https://x"] and m[0].relevancia == 0.8
    todas = {p.id for f in perguntas.SINAIS for p in f(s, agora)}
    assert "tech_lead:lead_time" in todas and any(k.startswith("mercado:") for k in todas)


class LLM:
    busca_web = True

    def __init__(self, texto):
        self.texto, self.prompts = texto, []

    def generate(self, *, system, prompt, model, max_tokens, web_search=0):
        from circulo.llm import LLMResult
        self.prompts.append((prompt, web_search))
        return LLMResult(self.texto, 0, model, [{"url": "https://cit.example", "title": "", "cited_text": ""}], entrada=10, saida=5)


def test_pesquisa_de_mercado_guarda_perguntas_com_fontes_uma_vez_por_semana(circle):
    s = circle.store
    resposta = json.dumps({"perguntas": [
        {"texto": "Como tech lead, por que o PR não vem com resumo de impacto e risco?", "pratica": "agentes do mercado escrevem o resumo", "fontes": ["https://a"], "relevancia": 0.9},
        {"texto": "Como PM, como peço uma feature pelo console sem escrever um item do roteiro?", "pratica": "entrada em linguagem natural", "fontes": [], "relevancia": 0.7},
        {"texto": "Como tech lead, como vejo o diff antes do PR abrir?", "pratica": "revisão prévia", "fontes": ["https://b"], "relevancia": 0.5}]})
    circle.ctx.dl.llm = LLM(resposta)
    avisos = []
    circle.ctx.reply = lambda m, k="": avisos.append(m)
    assert mercado.devida(s)
    r = mercado.pesquisar(circle.ctx)
    assert len(r["perguntas"]) == 3 and r["perguntas"][1]["fontes"] == ["https://cit.example"]      # sem fonte própria: a citação da busca
    assert "https://a" in r["fontes"] and avisos and circle.ctx.dl.llm.prompts[0][1] == 4
    assert "Norte medido hoje" in circle.ctx.dl.llm.prompts[0][0]
    assert not mercado.devida(s) and mercado.resumo(s)["proxima_em"] > time.time()
    assert s.one("SELECT COUNT(*) n FROM llm_calls WHERE papel='mercado' AND ok=1")["n"] == 1


def test_pesquisa_sem_json_registra_e_nao_derruba(circle):
    circle.ctx.dl.llm = LLM("não consegui")
    circle.ctx.reply = lambda m, k="": None
    assert mercado.pesquisar(circle.ctx) is None
    assert circle.store.get("mercado_pesquisa")["erro"] and not mercado.devida(circle.store)

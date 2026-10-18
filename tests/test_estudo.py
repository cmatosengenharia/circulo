"""Pedido é hipótese: o loop estuda em fontes confiáveis antes de executar, e só desobedece com evidência."""
import json

from circulo.estudo import Estudo
from circulo.llm import LLMResult


class Pesquisa:
    def __init__(self, resposta: dict | str, citacoes=()):
        self.resposta = resposta
        self.citacoes = [{"url": u, "title": u, "cited_text": "x"} for u in citacoes]
        self.chamadas = []

    def complete(self, system, prompt, max_tokens):
        return "{}", 1

    def generate(self, *, system, prompt, model, max_tokens, web_search=0):
        self.chamadas.append({"prompt": prompt, "web_search": web_search})
        texto = self.resposta if isinstance(self.resposta, str) else json.dumps(self.resposta, ensure_ascii=False)
        return LLMResult(texto, 800, model, self.citacoes)


def pedido(circle, titulo="Usar cache em todas as decisões do Jev"):
    circle.store.x("UPDATE roadmap SET status='feito'")
    return circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                          "VALUES(?,?,'pedido_cassio','pendente','pedido pelo painel',500,0,0)", (titulo, titulo))


def resposta(veredito, urls=("https://a.org/x", "https://b.org/y")):
    return {"veredito": veredito, "justificativa": "porque as referências mostram outro caminho",
            "achados": [{"ideia": f"ideia {i}", "fonte": f"ref{i}", "url": u} for i, u in enumerate(urls)],
            "item": {"titulo": "Cache só nas decisões determinísticas", "detalhe": "aplicar cache onde a entrada se repete",
                     "sucesso": "50% menos chamadas ao Jev"}}


def item(circle, iid):
    return circle.store.one("SELECT * FROM roadmap WHERE id=?", (iid,))


def test_adaptar_com_evidencia_reescreve_o_item_e_avisa(circle):
    iid = pedido(circle)
    circle.ctx.dl.llm = llm = Pesquisa(resposta("adaptar"), citacoes=["https://c.org/z"])
    r = Estudo(circle.ctx).run()
    assert r["veredito"] == "adaptar" and len(r["fontes"]) == 3
    assert llm.chamadas[0]["web_search"] > 0 and "hipótese" in llm.chamadas[0]["prompt"]
    it = item(circle, iid)
    assert it["titulo"] == "Cache só nas decisões determinísticas" and "Pedido original" in it["detalhe"]
    assert "https://a.org/x" in it["detalhe"] and it["status"] == "pendente"
    assert circle.store.one("SELECT 1 FROM alerts WHERE message LIKE 'Estudei o item%adaptei%'")
    assert circle.store.one("SELECT papel FROM llm_calls ORDER BY id DESC LIMIT 1")["papel"] == "estudo"


def test_contestar_com_evidencia_nao_executa_ate_voce_reafirmar(circle, tmp_path):
    from circulo.self_dev import SelfDeveloper
    iid = pedido(circle)
    circle.ctx.dl.llm = Pesquisa(resposta("contestar", urls=("https://a.org/1", "https://b.org/2", "https://c.org/3")),
                                 citacoes=["https://a.org/1"])
    Estudo(circle.ctx).run()
    assert item(circle, iid)["status"] == "contestado"
    dev = SelfDeveloper(circle.ctx, tmp_path, agent=None, github=None)
    assert dev.pick() is None                                           # o Developer não executa o contestado
    assert Estudo(circle.ctx).reafirmar(iid)
    assert dev.pick()["id"] == iid
    assert "reafirmado_pelo_humano" in json.loads(item(circle, iid)["estudo"])


def test_sem_fontes_o_loop_nao_desobedece(circle):
    iid = pedido(circle)
    circle.ctx.dl.llm = Pesquisa(resposta("contestar", urls=("https://a.org/so-uma",)))
    r = Estudo(circle.ctx).run()
    assert r["veredito"] == "adotar" and "sem 2 fontes" in r["rebaixado"]
    assert item(circle, iid)["status"] == "pendente"
    v = circle.store.one("SELECT ok FROM verificacoes WHERE ponto='estudo:pedido'")
    assert v["ok"] == 0                                                 # monitorado: estudo sem evidência suficiente


def test_adotar_anexa_o_estudo_para_o_developer(circle):
    iid = pedido(circle)
    circle.ctx.dl.llm = Pesquisa(resposta("adotar"))
    Estudo(circle.ctx).run()
    it = item(circle, iid)
    assert it["estudo"] and "Estudo (adotar)" in it["detalhe"] and "ideia 0" in it["detalhe"]


def test_resposta_invalida_vira_licao_e_nao_estuda(circle):
    iid = pedido(circle)
    circle.ctx.dl.llm = Pesquisa('{"veredito": "adotar", "justificativa": "cort')
    assert Estudo(circle.ctx).run() is None
    assert item(circle, iid)["estudo"] is None
    assert circle.store.one("SELECT assinatura FROM licoes")["assinatura"] == "estudo:saida_invalida"


def test_erro_do_loop_nao_passa_pelo_estudo(circle):
    circle.store.x("UPDATE roadmap SET status='feito'")
    circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                   "VALUES('Corrigir erro','x','erro','pendente','',1,0,0)")
    assert Estudo(circle.ctx).pendente() is None


def test_loop_estuda_antes_do_developer(circle):
    pedido(circle)
    circle.ctx.dl.llm = Pesquisa(resposta("adotar"))

    class Dev:
        def busy(self):
            return False

        def em_espera(self):
            return False

        def pick(self):
            return None

        def tem_trabalho(self):
            return False

        def alvo(self):
            return None
    circle.self_dev = Dev()
    assert circle.trabalho_pendente()
    for _ in range(6):
        if circle.tick().idle_task == "estudar_pedido":
            break
    assert circle.store.one("SELECT COUNT(*) n FROM roadmap WHERE estudo IS NOT NULL")["n"] >= 1

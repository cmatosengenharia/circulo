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


def test_resposta_cortada_no_item_aproveita_o_veredito_e_os_achados(circle):
    """Lição #22: o limite de tokens cortou a resposta dentro de "item" (depois de veredito, justificativa e achados
    completos) e o estudo inteiro foi descartado como "resposta sem JSON válido". O que chegou inteiro vale."""
    iid = pedido(circle)
    inteiro = json.dumps(resposta("adotar"), ensure_ascii=False)
    circle.ctx.dl.llm = Pesquisa(inteiro[:inteiro.index('"detalhe"') + len('"detalhe')])
    r = Estudo(circle.ctx).run()
    assert r is not None and r["veredito"] == "adotar" and r["cortado"]
    assert r["fontes"] == ["https://a.org/x", "https://b.org/y"]
    assert item(circle, iid)["estudo"] is not None
    assert circle.store.one("SELECT COUNT(*) n FROM licoes WHERE assinatura='estudo:saida_invalida'")["n"] == 0


def test_cortada_depois_da_justificativa_inteira_estuda_e_sem_ela_grava_o_motivo_tipado(circle):
    """Lição #22: cortada logo depois do último valor inteiro, a resposta vale; cortada dentro da justificativa, a
    verificação grava qual chave obrigatória faltou, e não um "sem JSON válido" genérico."""
    pedido(circle)
    circle.ctx.dl.llm = Pesquisa('{"veredito": "adotar", "justificativa": "segue o pedido"')
    r = Estudo(circle.ctx).run()
    assert r is not None and r["veredito"] == "adotar" and r["justificativa"] == "segue o pedido"
    pedido(circle, "Outro pedido")
    circle.ctx.dl.llm = Pesquisa('{"veredito": "adaptar", "achados": ["x"], "justificativa": "A fonte oficial mostra')
    assert Estudo(circle.ctx).run() is None
    v = circle.store.one("SELECT motivo FROM verificacoes WHERE ponto='estudo:pedido' AND ok=0 ORDER BY id DESC LIMIT 1")
    assert "falta_chave: justificativa" in v["motivo"]


def test_adaptar_cortado_sem_o_item_novo_e_adotado_como_pedido(circle):
    """Lição #22: adaptar sem o item reescrito completo não reescreve nada: segue o pedido como está."""
    iid = pedido(circle)
    inteiro = json.dumps(resposta("adaptar"), ensure_ascii=False)
    circle.ctx.dl.llm = Pesquisa(inteiro[:inteiro.index('"detalhe"') + 3])
    r = Estudo(circle.ctx).run()
    assert r["veredito"] == "adotar" and "cortad" in r["rebaixado"]
    assert item(circle, iid)["titulo"] == "Usar cache em todas as decisões do Jev"


def test_narracao_com_chave_antes_do_json_nao_descarta_o_estudo(circle):
    """Lição #22 (reincidente): com busca na web a LLM narra antes do JSON; um `{` na narração fazia o estudo inteiro,
    completo ou cortado no "item", virar "resposta sem JSON válido"."""
    narra = "Vou pesquisar o veto {constituição} no planejador e a causa de cada falha de abrir_pr.\n\n"
    inteiro = json.dumps(resposta("adotar"), ensure_ascii=False)
    for texto in (narra + inteiro, narra + inteiro[:inteiro.index('"detalhe"') + len('"detalhe')]):
        iid = pedido(circle)
        circle.ctx.dl.llm = Pesquisa(texto)
        r = Estudo(circle.ctx).run()
        assert r is not None and r["veredito"] == "adotar"
        assert r["fontes"] == ["https://a.org/x", "https://b.org/y"]
        assert item(circle, iid)["estudo"] is not None
    assert circle.store.one("SELECT COUNT(*) n FROM licoes WHERE assinatura='estudo:saida_invalida'")["n"] == 0


def test_rascunho_ou_eco_do_formato_antes_da_resposta_nao_descarta_o_estudo(circle):
    """Lição #22 (reincidiu 2x): o extrator devolvia o primeiro objeto com "veredito" e o papel só validava depois; um
    rascunho largado antes de mais uma busca, ou o formato ecoado ("adotar|adaptar"), escondia a resposta cortada no
    "item" e o estudo virava "resposta sem JSON válido"."""
    inteiro = json.dumps(resposta("adotar"), ensure_ascii=False)
    cortado = inteiro[:inteiro.index('"detalhe"') + len('"detalhe')]
    antes = ('{"veredito": "adaptar", "justificativa": "Preciso conferir mais uma fonte',
             'O formato pedido é {"veredito": "adotar|adaptar|contestar"}. ')
    for texto in (a + "\n\nVou buscar mais uma fonte.\n\n" + r for a in antes for r in (inteiro, cortado)):
        iid = pedido(circle)
        circle.ctx.dl.llm = Pesquisa(texto)
        r = Estudo(circle.ctx).run()
        assert r is not None and r["veredito"] == "adotar"
        assert r["justificativa"] == "porque as referências mostram outro caminho"
        assert item(circle, iid)["estudo"] is not None
    assert circle.store.one("SELECT COUNT(*) n FROM licoes WHERE assinatura='estudo:saida_invalida'")["n"] == 0


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

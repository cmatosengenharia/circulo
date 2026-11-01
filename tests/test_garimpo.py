"""31/10: camada que varre o GitHub pelo que o loop precisa agora e alimenta o estudo de repositórios."""
import json
import time

from circulo import garimpo, mercado


def _item(s, titulo, origem="pedido_cassio"):
    agora = time.time()
    return s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
               (titulo, "d", origem, "pendente", "", 10, "e", agora, agora))


def test_necessidades_viram_consultas_e_o_filtro_segura_o_lixo(circle):
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    _item(s, "Meu trabalho: importar o CSV do Cursor pela tela e ver o gasto por assunto")
    s.x("INSERT INTO licoes(assinatura,ponto,descricao,classe,status,ocorrencias,reincidencias,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        ("a:b", "a", "worktree do Developer fica com cache de testes", "estrutural", "reincidente", 4, 2, time.time(), time.time()))
    ns = garimpo.necessidades(s)
    assert ns[0][0].startswith("item pendente") and "csv" in ns[0][1] and "cursor" in ns[0][1] and "meu" not in ns[0][1]
    assert any(m.startswith("lição estrutural") and "worktree" in c for m, c in ns)
    assert any("engenharia reversa" in m for m, _ in ns) and len(ns) <= garimpo.MAX_CONSULTAS
    agora = time.time()
    recente = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(agora - 30 * 86400))
    velho = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(agora - 500 * 86400))
    chamadas = []

    def buscar(c):
        chamadas.append(c)
        return [{"url": "https://github.com/a/bom", "estrelas": 900, "pushed_at": recente, "licenca": "MIT", "descricao": "x"},
                {"url": "https://github.com/a/parado", "estrelas": 900, "pushed_at": velho, "licenca": "MIT"},
                {"url": "https://github.com/a/fraco", "estrelas": 3, "pushed_at": recente, "licenca": "MIT"},
                {"url": mercado.REPOS[0], "estrelas": 9000, "pushed_at": recente, "licenca": "MIT"},
                {"url": "https://github.com/a/gpl", "estrelas": 300, "pushed_at": recente, "licenca": "GPL-3.0"},
                {"url": "https://github.com/a/terceiro", "estrelas": 100, "pushed_at": recente, "licenca": "MIT"}]
    avisos = []
    r = garimpo.garimpar(s, agora, buscar=buscar, reply=lambda m, k: avisos.append(m))
    assert chamadas == [c for _, c in ns] and r["erros"] == 0
    fila = s.get(garimpo.KV)["fila"]
    urls = [f["url"] for f in fila]
    assert urls == ["https://github.com/a/bom", "https://github.com/a/gpl", "https://github.com/a/terceiro"]   # 2 por consulta; sem o parado, o fraco e o já conhecido; sem repetir
    assert fila[1]["permissiva"] is False and fila[0]["permissiva"] is True and fila[0]["motivo"].startswith("item pendente")
    assert avisos and "Garimpo" in avisos[0] and not garimpo.devido(s, agora) and garimpo.devido(s, agora + garimpo.A_CADA + 1)
    r2 = garimpo.garimpar(s, agora + 1, buscar=lambda c: (_ for _ in ()).throw(OSError("rate limit")))
    assert r2["erros"] == len(ns) and r2["novos"] == [] and [f["url"] for f in s.get(garimpo.KV)["fila"]] == urls     # erro não derruba nem apaga


class _LLM:
    busca_web = True

    def __init__(self, texto):
        self.texto, self.prompts = texto, []

    def generate(self, *, system, prompt, model, max_tokens, web_search=0):
        from circulo.llm import LLMResult
        self.prompts.append(prompt)
        return LLMResult(self.texto, 0, model, [], entrada=10, saida=5)


def test_estudo_consome_a_fila_do_garimpo_antes_da_lista_fixa_e_avisa_a_licenca(circle):
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    agora = time.time()
    s.set(garimpo.KV, {"em": agora, "fila": [{"url": "https://github.com/a/gpl", "motivo": "tema fixo: engenharia reversa", "estrelas": 300,
                                              "licenca": "GPL-3.0", "permissiva": False, "achado_em": agora}], "vistos": []})
    resposta = json.dumps({"perguntas": [], "itens": [{"titulo": "Portar o mapa de chamadas de a/gpl: estudo.py lista funções tocadas pelo item",
                                                      "detalhe": "reimplementar: ast + grafo", "sucesso": "teste", "fontes": ["https://github.com/a/gpl"]}]})
    circle.ctx.dl.llm = _LLM(resposta)
    circle.ctx.reply = lambda m, k="": None
    r = mercado.estudar_repositorio(circle.ctx)
    assert r["repo"] == "https://github.com/a/gpl" and r["garimpo"] and len(r["itens"]) == 1
    assert "NÃO permissiva" in circle.ctx.dl.llm.prompts[0] and "engenharia reversa" in circle.ctx.dl.llm.prompts[0]
    assert garimpo.proximo(s) is None and "https://github.com/a/gpl" in s.get(garimpo.KV)["vistos"]
    r2 = mercado.estudar_repositorio(circle.ctx)                                                 # fila vazia: volta à lista fixa
    assert r2["repo"] == mercado.REPOS[0] and not r2["garimpo"]

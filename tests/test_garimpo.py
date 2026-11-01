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
    assert urls == ["https://github.com/a/bom", "https://github.com/a/terceiro", "https://github.com/a/gpl"]   # 2 por consulta; sem o parado, o fraco e o já conhecido; sem repetir; ordenada pela triagem
    assert fila[2]["permissiva"] is False and fila[0]["permissiva"] is True and fila[0]["motivo"].startswith("item pendente")
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


class _DL:
    """Jev de mentira: aderência fixa por url; fonte 'local' é o que a cascata devolve com o Jev fora do ar ou em dúvida."""

    def __init__(self, notas, fonte="jev"):
        self.notas, self.fonte, self.perguntas = notas, fonte, []

    def ask(self, name, q, state):
        from circulo.decision import Decision
        self.perguntas.append((name, state))
        p = self.notas.get(state["url"], 0.5)
        return Decision(name, "noul", p, abs(2 * p - 1), self.fonte)


def _dia(agora, n):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(agora - n * 86400))


def _cinco(agora):
    return [{"url": "https://github.com/a/popular-sem-licenca", "estrelas": 40000, "pushed_at": _dia(agora, 2), "licenca": "desconhecida"},
            {"url": "https://github.com/a/arquivado", "estrelas": 20000, "pushed_at": _dia(agora, 5), "licenca": "MIT", "arquivado": True},
            {"url": "https://github.com/a/mit-ativo", "estrelas": 120, "pushed_at": _dia(agora, 3), "licenca": "MIT"},
            {"url": "https://github.com/a/apache-morno", "estrelas": 5000, "pushed_at": _dia(agora, 200), "licenca": "Apache-2.0"},
            {"url": "https://github.com/a/gpl-ativo", "estrelas": 800, "pushed_at": _dia(agora, 10), "licenca": "GPL-3.0"}]


def _fila_com(circle, achados, dl, agora, rnd):
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    s.set(garimpo.KV, {})
    chegada = rnd.sample(achados, len(achados))                     # a ordem de chegada da busca não pode mudar a fila
    garimpo.garimpar(s, agora, buscar=lambda c: chegada, dl=dl)
    return [f["url"].rsplit("/", 1)[1] for f in s.get(garimpo.KV)["fila"]]


def test_triagem_por_pontos_ordena_a_fila_e_o_jev_so_soma_a_aderencia(circle):
    import random
    rnd, agora = random.Random(351), time.time()
    achados = _cinco(agora)
    aderencia = {"https://github.com/a/gpl-ativo": 0.95, "https://github.com/a/apache-morno": 0.9, "https://github.com/a/mit-ativo": 0.2}
    for _ in range(20):                                              # a mesma ordem em 100% das execuções
        dl = _DL(aderencia)
        assert _fila_com(circle, achados, dl, agora, rnd) == ["gpl-ativo", "apache-morno", "mit-ativo", "arquivado", "popular-sem-licenca"]
    assert {n for n, _ in dl.perguntas} == {"garimpo_vale"} and all(set(st) == {"url", "descricao", "necessidade"} for _, st in dl.perguntas)
    f = circle.store.get(garimpo.KV)["fila"][0]
    assert f["pontos"]["aderencia"] > 0 and f["aderencia_fonte"] == "jev" and f["total"] == round(sum(f["pontos"].values()), 3)
    # Jev fora do ar ou em dúvida: só a regra local; estrelas pesam pouco (o MIT recente de 120 vence o Apache morno de 5 mil)
    local = ["mit-ativo", "gpl-ativo", "apache-morno", "arquivado", "popular-sem-licenca"]
    assert _fila_com(circle, achados, _DL(aderencia, fonte="local"), agora, rnd) == local
    f = circle.store.get(garimpo.KV)["fila"][0]
    assert f["pontos"]["aderencia"] == 0 and f["aderencia_fonte"] == "local"
    assert _fila_com(circle, achados, None, agora, rnd) == local                 # sem Jev nenhum: a regra local basta
    assert garimpo.proximo(circle.store)["url"].endswith("mit-ativo")            # o estudo pega o de maior pontuação


def test_sem_licenca_ou_arquivado_nunca_fica_a_frente_de_um_ativo_e_licenciado(circle):
    import random
    rnd, agora = random.Random(7), time.time()
    achados = _cinco(agora)
    problemas = {"popular-sem-licenca", "arquivado"}
    dl = _DL({a["url"]: (1.0 if a["url"].rsplit("/", 1)[1] in problemas else 0.0) for a in achados})   # o pior caso para a regra
    for _ in range(20):
        fila = _fila_com(circle, achados, dl, agora, rnd)
        ruins = [i for i, n in enumerate(fila) if n in problemas]
        bons = [i for i, n in enumerate(fila) if n not in problemas]
        assert bons and (not ruins or max(bons) < min(ruins)), fila


def test_abaixo_do_limiar_nao_entra_na_fila(circle):
    import random
    agora = time.time()
    lixo = {"url": "https://github.com/a/lixo", "estrelas": 60, "pushed_at": _dia(agora, 360), "licenca": "desconhecida", "arquivado": True}
    assert garimpo.pontuar(lixo, agora)["total"] < garimpo.LIMIAR
    fila = _fila_com(circle, [lixo, *_cinco(agora)], _DL({"https://github.com/a/lixo": 1.0}), agora, random.Random(1))
    assert "lixo" not in fila and len(fila) == 5

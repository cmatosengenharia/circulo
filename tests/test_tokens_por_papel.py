"""Pergunta #828 (estudo: adaptar): tokens por papel e por PR mergeado, série semanal com meta sobre a média móvel de
4 semanas e experimento de uma alavanca por vez que só vira padrão com a qualidade dentro do ruído da linha de base."""
import time

from circulo import alavancas
from circulo.custo import PAPEIS, serie_semanal, tendencia, tokens_por_papel
from circulo.state import Store

SEMANA = 7 * 86400
ITENS = [{"titulo": "Item entregue", "status": "feito"}, {"titulo": "Item na fila", "status": "em_andamento"}]


def _c(papel, ent, sai, cache, entrada="Item entregue", em=0.0):
    return {"papel": papel, "tokens_entrada": ent, "tokens_saida": sai, "cache_lido": cache, "tokens": ent + sai,
            "entrada": entrada, "created_at": em}


def test_tokens_por_papel_separa_entrada_saida_e_cache_e_divide_pelos_prs_mergeados():
    chamadas = [_c("planejador", 1000, 200, 800), _c("developer", 5000, 3000, 4000),
                _c("developer", 1000, 1000, 0, entrada="reparo: Item entregue"),
                _c("validador", 400, 100, 0, entrada="Item na fila"), _c("estudo_duvida", 300, 50, 100),
                _c("mercado", 9999, 1, 0)]                                # papel fora dos quatro: não entra
    r = tokens_por_papel(chamadas, ITENS, prs_mergeados=2)
    assert set(r["por_papel"]) == set(PAPEIS)
    dev = r["por_papel"]["developer"]
    assert (dev["entrada"], dev["saida"], dev["cache_lido"], dev["tokens"], dev["por_pr"]) == (6000, 4000, 4000, 10000, 5000)
    assert r["por_papel"]["estudo"]["tokens"] == 350                    # estudo_duvida é o papel estudo
    assert r["por_item"]["Item entregue"] == {"planejador": 1200, "developer": 10000, "estudo": 350}
    assert r["por_item"]["Item na fila"] == {"validador": 500}
    assert r["tokens_por_pr"] == (1200 + 10000 + 500 + 350) // 2
    assert tokens_por_papel([], ITENS, 0)["tokens_por_pr"] is None


def test_serie_semanal_e_meta_sobre_a_media_movel_de_4_semanas():
    agora = 100 * SEMANA
    chamadas, merges = [], []
    for s, custo in enumerate([1000, 1000, 1000, 1000, 850]):          # 4 semanas a 1000, a última a 850
        inicio = agora - (5 - s) * SEMANA
        merges += [inicio + 10, inicio + 20]
        chamadas.append(_c("developer", custo * 2, 0, 0, em=inicio + 5))
    serie = serie_semanal(chamadas, merges, agora, semanas=5)
    assert [p["custo_por_pr"] for p in serie] == [1000, 1000, 1000, 1000, 850]
    assert serie[-1]["por_papel"]["developer"] == 850
    t = tendencia(serie)
    assert t == {"atual": 850, "media_4s": 1000, "queda_pct": 15.0, "em_queda": True, "meta_10pct": True}
    assert tendencia(serie[:3])["em_queda"] is None                    # menos de 4 semanas de base: sem veredito


def test_guarda_de_qualidade_so_adota_dentro_do_ruido_com_n_minimo():
    base = {"abertos": 40, "mergeados": 30, "falhas_ci": 6, "tokens_por_pr": 10000}
    assert alavancas.julgar(base, {**base, "abertos": alavancas.N_MIN - 1})["veredito"] == "sem_dados"
    igual = alavancas.julgar(base, {"abertos": 40, "mergeados": 29, "falhas_ci": 7, "tokens_por_pr": 8000})
    assert igual["veredito"] == "adotar"                                # 1 merge a menos é ruído
    pior = alavancas.julgar(base, {"abertos": 40, "mergeados": 18, "falhas_ci": 6, "tokens_por_pr": 6000})
    assert pior["veredito"] == "rejeitar" and "merge" in pior["motivo"]
    ci = alavancas.julgar(base, {"abertos": 40, "mergeados": 30, "falhas_ci": 18, "tokens_por_pr": 6000})
    assert ci["veredito"] == "rejeitar" and "checks" in ci["motivo"]
    caro = alavancas.julgar(base, {"abertos": 40, "mergeados": 30, "falhas_ci": 6, "tokens_por_pr": 10500})
    assert caro["veredito"] == "rejeitar" and "custo" in caro["motivo"]


def _pr(st, n, criado, merge=True):
    st.x("INSERT INTO prs(number,titulo,status,created_at,updated_at) VALUES(?,?,?,?,?)",
         (n, f"pr {n}", "mergeado" if merge else "fechado", criado, criado + 60))
    if merge:
        st.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,'s',1,'ok','{}',?)", (n, criado + 60))


def test_loop_testa_uma_alavanca_por_vez_e_registra_o_veredito(tmp_path):
    st = Store(tmp_path / "s.db")
    agora = time.time()
    inicio = agora - 3 * 86400
    for i in range(alavancas.N_MIN):                                    # linha de base: N_MIN PRs, 3/4 mergeados
        _pr(st, 100 + i, inicio - 86400 - i * 60, merge=i % 4 != 0)
    st.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,ok,created_at) VALUES(1,'developer','m','fixo',?,1,?)",
         (900_000, inicio - 3600))
    ativa = alavancas.girar(st, agora=inicio)
    assert ativa["alavanca"] == alavancas.ALAVANCAS[0] and alavancas.ativa(st) == alavancas.ALAVANCAS[0]
    assert alavancas.girar(st, agora=inicio + 60)["alavanca"] == ativa["alavanca"]   # uma por vez: não troca
    for i in range(alavancas.N_MIN):
        _pr(st, 200 + i, inicio + 60 + i * 60, merge=i % 4 != 0)
    st.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,ok,created_at) VALUES(1,'developer','m','fixo',?,1,?)",
         (600_000, inicio + 3600))
    avisos = []
    fechado = alavancas.girar(st, lambda m, *_: avisos.append(m), agora=agora)
    assert fechado["veredito"] == "adotar" and fechado["alavanca"] == alavancas.ALAVANCAS[0]
    assert alavancas.padrao(st) == [alavancas.ALAVANCAS[0]] and alavancas.ALAVANCAS[0] in avisos[0]
    assert alavancas.ativa(st) is None
    assert alavancas.girar(st, agora=agora + 1)["alavanca"] == alavancas.ALAVANCAS[1]   # próxima alavanca


def test_semana_sem_n_minimo_fecha_inconclusivo_e_passa_a_proxima(tmp_path):
    st = Store(tmp_path / "s.db")
    t0 = time.time() - 10 * 86400
    alavancas.girar(st, agora=t0)
    r = alavancas.girar(st, agora=t0 + alavancas.JANELA_MAX + 1)
    assert r["veredito"] == "sem_dados" and alavancas.padrao(st) == []
    assert alavancas.historico(st)[-1]["veredito"] == "sem_dados"


def test_card_no_painel_mostra_tokens_por_pr_por_papel_e_o_experimento_ativo(tmp_path):
    from circulo.painel import pagina_saude, saude
    st = Store(tmp_path / "s.db")
    agora = time.time()
    _pr(st, 1, agora - 86400)
    st.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,tokens_entrada,tokens_saida,cache_lido,ok,created_at) "
         "VALUES(1,'planejador','m','fixo',1500,1000,500,700,1,?)", (agora - 3600,))
    alavancas.girar(st, agora=agora - 60)
    h = saude(st.db)
    card = pagina_saude(h).decode().split('aria-label="Tokens por PR mergeado"', 1)[1].split("</section>", 1)[0]
    assert "planejador" in card and "1500" in card and alavancas.ALAVANCAS[0] in card


def test_card_mostra_o_ultimo_experimento_concluido_com_a_taxa_de_merge(tmp_path):
    from circulo.painel import pagina_saude, saude
    st = Store(tmp_path / "s.db")
    st.set(alavancas.HISTORICO, [{"alavanca": "teto_saida", "veredito": "rejeitar", "motivo": "taxa de merge caiu",
                                  "base": {"abertos": 40, "mergeados": 30}, "exp": {"abertos": 40, "mergeados": 18}}])
    card = pagina_saude(saude(st.db)).decode().split('aria-label="Tokens por PR mergeado"', 1)[1].split("</section>", 1)[0]
    assert "teto_saida: rejeitar" in card and "merge 75% → 45%" in card


def test_base_sem_pr_mergeado_nao_adota_sem_comparar_custo():
    """Base sem PR mergeado não tem custo por PR: adotar seria sem evidência de economia."""
    base = {"abertos": 40, "mergeados": 0, "falhas_ci": 0, "tokens_por_pr": None}
    exp = {"abertos": 40, "mergeados": 0, "falhas_ci": 0, "tokens_por_pr": None}
    assert alavancas.julgar(base, exp)["veredito"] == "sem_dados"
    assert alavancas.julgar(base, {**exp, "mergeados": 30, "tokens_por_pr": 100})["veredito"] == "sem_dados"


def test_alavanca_ativa_ou_adotada_muda_a_chamada_de_llm(tmp_path):
    from circulo.llm import PORTE_ANTHROPIC
    pequeno = next(m for m, p in PORTE_ANTHROPIC.items() if p == "pequena")
    st = Store(tmp_path / "s.db")
    assert alavancas.aplicar(st, "planejador", "claude-sonnet-5-5", 4000) == ("claude-sonnet-5-5", 4000)
    st.set(alavancas.ATIVA, {"alavanca": "modelo_menor", "inicio": 0, "base": {}})
    assert alavancas.aplicar(st, "planejador", "claude-sonnet-5-5", 4000) == (pequeno, 4000)
    assert alavancas.aplicar(st, "estudo", "claude-sonnet-5-5", 4000) == ("claude-sonnet-5-5", 4000)  # saída longa
    st.set(alavancas.ATIVA, {"alavanca": "teto_saida", "inicio": 0, "base": {}})
    assert alavancas.aplicar(st, "estudo", "claude-sonnet-5-5", 4000) == ("claude-sonnet-5-5", 3000)
    st.set(alavancas.ATIVA, None)
    st.set(alavancas.PADRAO, ["modelo_menor", "teto_saida"])                # adotadas valem sempre
    assert alavancas.aplicar(st, "validador", "claude-sonnet-5-5", 4000) == (pequeno, 3000)
    assert set(alavancas.ALAVANCAS) == set(alavancas.EFEITO)               # nenhuma alavanca sem efeito na chamada


def test_validador_chama_a_llm_com_a_alavanca_aplicada(tmp_path):
    from types import SimpleNamespace

    from circulo.llm import LLMResult
    from circulo.validador import MAX_TOKENS, _chamar_llm
    st = Store(tmp_path / "s.db")
    st.set(alavancas.ATIVA, {"alavanca": "teto_saida", "inicio": 0, "base": {}})
    pedidos = []

    def generate(**kw):
        pedidos.append(kw)
        return LLMResult("ok", 10, kw["model"])
    dl = SimpleNamespace(llm=SimpleNamespace(generate=generate), project_id=None,
                         pick_model_detalhe=lambda papel, ctx: {"modelo": "claude-sonnet-5-5"})
    ctx = SimpleNamespace(dl=dl, store=st, budget=SimpleNamespace(charge=lambda *a: None))
    assert _chamar_llm(ctx, {"titulo": "x"})("s", "p") == "ok"
    assert 0 < pedidos[0]["max_tokens"] < MAX_TOKENS


def test_planejador_e_estudo_passam_pela_alavanca():
    import inspect

    from circulo import estudo, planejador
    assert "alavancas.aplicar(" in inspect.getsource(planejador.Planejador._llm)
    assert inspect.getsource(estudo).count("alavancas.aplicar(") == 1


def test_semana_do_merge_vem_do_instante_do_merge_e_nao_do_updated_at(tmp_path):
    st = Store(tmp_path / "s.db")
    agora = time.time()
    st.x("INSERT INTO prs(number,titulo,status,created_at,updated_at) VALUES(7,'pr','mergeado',?,?)",
         (agora - 10 * 86400, agora - 60))                                  # atualizado ontem (comentário, rótulo)
    st.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(7,'s',1,'ok','{}',?)", (agora - 9 * 86400,))
    st.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,ok,created_at) VALUES(1,'developer','m','fixo',500,1,?)",
         (agora - 9 * 86400 - 60,))
    d = alavancas.painel(st.db, agora)
    assert [p["prs"] for p in d["serie"]][-2:] == [1, 0]                   # o merge fica na semana em que aconteceu
    assert d["tokens_por_pr"] is None                                      # nenhum merge nos últimos 7 dias

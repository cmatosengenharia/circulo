import json
import threading
import urllib.error
import urllib.request

import pytest

from circulo.painel import estado, serve
from circulo.projects import kit_project_id
from conftest import say


@pytest.fixture
def painel(circle):
    srv = serve(circle.store.path, port=0, background=True)
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_estado_reflete_o_loop(circle):
    say(circle, "38,90 ifood almoço")
    s = estado(circle.store)
    assert s["loop"]["tick"] == 1 and s["loop"]["etapa"]["nome"] == "descanso"
    assert s["saude"]["invariantes"] == [] and s["saude"]["decisoes_24h"] >= 2
    assert s["projetos"][0]["lancamentos"] == 1 and s["ultima_decisao"] >= 2


def test_pagina_e_api(painel):
    with urllib.request.urlopen(painel + "/", timeout=5) as r:
        assert b"<title>" in r.read()
    with urllib.request.urlopen(painel + "/api/estado", timeout=5) as r:
        assert json.loads(r.read())["loop"]["status"] in ("parado", "rodando")


def test_controles_exigem_cabecalho_e_origem_local(painel):
    assert post(painel + "/api/controle", {"acao": "pausar"})[0] == 403
    assert post(painel + "/api/controle", {"acao": "pausar"}, {"X-Circulo": "1", "Origin": "https://evil.example"})[0] == 403
    code, body = post(painel + "/api/controle", {"acao": "pausar"}, {"X-Circulo": "1"})
    assert code == 200 and body["controle"]["pausado"] is True


def test_pausa_pelo_painel_para_o_loop(circle, painel):
    post(painel + "/api/controle", {"acao": "pausar"}, {"X-Circulo": "1"})
    r = circle.tick()
    assert r.paused and r.pause_reason == "humano" and circle.store.get("loop_status") == "pausado_humano"
    post(painel + "/api/controle", {"acao": "retomar"}, {"X-Circulo": "1"})
    assert not circle.tick().paused


def test_modo_seguro_congela_evolucao(circle):
    circle.set_control(modo_seguro=True)
    for i in range(3):
        say(circle, f"{50 + i} sacolão")
        say(circle, f"corrige {i + 1} mercado")
    assert circle.ctx.policies.active()[0] == 1            # nada aprendido em modo seguro
    tasks = {circle.tick().idle_task for _ in range(10)}
    assert tasks <= {"analisar_padroes", "rodar_regressao", "resumo", None}
    circle.set_control(modo_seguro=False)
    circle.tick()
    assert circle.ctx.policies.active()[0] == 2            # ao sair, aprende com o que acumulou


def test_pedido_pelo_painel_entra_na_fila(circle, painel):
    code, body = post(painel + "/api/pedido", {"texto": "19,90 netflix"}, {"X-Circulo": "1"})
    assert code == 200
    assert circle.tick().handled_event == body["evento"]


def test_feed_ao_vivo_sse(circle, painel):
    say(circle, "38,90 ifood almoço")
    got = []

    def read():
        with urllib.request.urlopen(painel + "/api/eventos?desde=0", timeout=5) as r:
            for line in r:
                if line.startswith(b"event: decisao"):
                    got.append(line)
                if len(got) >= 2:
                    return

    t = threading.Thread(target=read, daemon=True)
    t.start()
    t.join(5)
    assert len(got) >= 2


def test_home_e_cards(circle, painel):
    with urllib.request.urlopen(painel + "/", timeout=5) as r:
        assert "Nova missão" in r.read().decode()
    for rota in ("/projeto/1", "/missao/1"):
        with urllib.request.urlopen(painel + rota, timeout=5) as r:
            assert 'id="navTopo"' in r.read().decode()          # o menu de cima leva às missões
    code, body = post(painel + "/api/projeto", {"pedido": "Crie um portal admin para fotógrafos"}, {"X-Circulo": "1"})
    assert code == 200
    circle.tick()
    with urllib.request.urlopen(painel + "/api/projetos", timeout=5) as r:
        data = json.loads(r.read())
    assert {p["tipo"] for p in data["projetos"]} == {"circulo", "financas", "produto_software"}
    assert data["projetos"][0]["kit"] == "circulo"             # o próprio círculo fica fixado no topo


def test_pedido_curto_demais_e_recusado(painel):
    assert post(painel + "/api/projeto", {"pedido": "oi"}, {"X-Circulo": "1"})[0] == 400


def test_estado_filtrado_por_projeto(circle):
    say(circle, "38,90 ifood almoço")
    circle.submit_project("Crie uma landing page para captar leads do Instagram")
    circle.tick()
    lp = circle.store.one("SELECT id FROM projects WHERE tipo='landing_page'")["id"]
    s = estado(circle.store, lp)
    assert s["projeto"]["status"] == "ativo" and s["projeto"]["kit"] == "geral" and s["projetos"] == [] and s["aguardando"] == []
    assert estado(circle.store, 1)["projeto"]["decisoes"] >= 2


def test_painel_sobe_antes_do_loop_e_mostra_desligado(tmp_path):
    srv = serve(tmp_path / "novo.db", port=0, background=True)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/projetos", timeout=5) as r:
            data = json.loads(r.read())
        assert data["loop"]["vivo"]["estado"] == "desligado" and data["projetos"][0]["kit"] == "circulo"
    finally:
        srv.shutdown()


def test_desativar_item_do_roteiro_tira_da_fila_do_developer(circle, painel):
    from circulo.self_dev import SelfDeveloper
    dev = SelfDeveloper(circle.ctx, circle.data_dir, agent=None, github=None)
    circle.store.x("UPDATE roadmap SET estudo='{}'")                 # já estudados (o estudo tem teste próprio)
    primeiro = dev.pick()
    assert primeiro is not None
    code, _ = post(painel + "/api/roteiro", {"id": primeiro["id"], "ativo": False}, {"X-Circulo": "1"})
    assert code == 200
    assert dev.pick()["id"] != primeiro["id"]                       # o Developer pula o item desativado
    item = next(r for r in estado(circle.store, kit_project_id(circle.store, "circulo"))["roteiro"] if r["id"] == primeiro["id"])
    assert item["desativado"] == 1
    assert post(painel + "/api/roteiro", {"id": primeiro["id"], "ativo": True}, {"X-Circulo": "1"})[0] == 200
    assert dev.pick()["id"] == primeiro["id"]                       # reativado: volta ao lugar dele
    assert post(painel + "/api/roteiro", {"id": primeiro["id"], "ativo": False})[0] == 403    # sem o cabeçalho do painel


def test_conversa_liga_cada_resposta_a_sua_mensagem(circle, painel):
    zero = kit_project_id(circle.store, "circulo")
    post(painel + "/api/pedido", {"texto": "Priorize corrigir erros", "projeto": str(zero)}, {"X-Circulo": "1"})
    circle.tick()
    c = estado(circle.store, zero)["conversa"]
    assert c[-1]["texto"] == "Priorize corrigir erros" and c[-1]["status"] == "done"
    assert "item #" in c[-1]["respostas"][0]["message"]


def test_aba_fechada_no_meio_da_resposta_nao_vira_traceback(capsys):
    """No Mac o loop.err enchia de BrokenPipeError do painel quando o navegador fechava a aba."""
    import socket
    from circulo.painel import _Servidor
    srv = _Servidor.__new__(_Servidor)
    try:
        raise BrokenPipeError(32, "Broken pipe")
    except BrokenPipeError:
        srv.handle_error(None, ("127.0.0.1", 1))
    try:
        raise ValueError("outro erro")
    except ValueError:
        srv.handle_error(socket.socket(), ("127.0.0.1", 1))
    err = capsys.readouterr().err
    assert "BrokenPipeError" not in err and "ValueError" in err


def test_faixa_de_saude_com_incidente_aberto_nao_fica_verde_e_aparece_no_painel(tmp_path):
    """Pergunta #58: a faixa de saúde lê só o SQLite e serve /painel sem Grafana; um incidente aberto pinta o semáforo
    e aparece na linha de causa."""
    import time

    from circulo.painel import saude
    from circulo.state import Store
    st = Store(tmp_path / "s.db")
    agora = time.time()
    st.x("INSERT INTO incidents(fingerprint,stage,kind,message,count,first_seen,last_seen,first_tick,last_tick,status) "
         "VALUES('fp','meta','JSONDecodeError','Expecting value <b>',8,?,?,1,3,'aberto')", (agora, agora))
    h = saude(st.db)
    assert h["semaforo"] in ("amarelo", "vermelho") and h["incidentes_abertos"] == 1
    assert set(h) >= {"giros", "jev_duvida_pct", "incidentes_abertos", "llm_falhas_7d_pct", "gate"} and h["causa"]
    srv = serve(st.path, port=0, background=True)
    try:
        t0 = time.monotonic()
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/painel", timeout=5) as r:
            pagina = r.read().decode()
            assert r.status == 200 and r.headers["Content-Type"].startswith("text/html")
        assert time.monotonic() - t0 < 0.5
    finally:
        srv.shutdown()
    assert "JSONDecodeError" in pagina and "&lt;b&gt;" in pagina and "<script src" not in pagina
    for campo in ("Giros", "Jev em dúvida", "Incidentes abertos", "Falhas de LLM", "Gate"):
        assert campo in pagina


def test_faixa_de_saude_verde_sem_sinal_ruim(tmp_path):
    from circulo.painel import saude
    from circulo.state import Store
    h = saude(Store(tmp_path / "s.db").db)
    assert h["semaforo"] == "verde" and h["causa"] is None and h["gate"] is None


def test_falhas_do_painel_agrupadas_por_causa_somam_o_total_e_aparecem_no_topo(tmp_path):
    """Pergunta #302: as falhas painel:% das últimas 24 h viram top 5 causas + 'outras', sem falha sem causa."""
    import time

    from circulo.painel import falhas_por_causa, pagina_saude, saude
    from circulo.state import Store
    linhas = ([("painel:frescor", "painel:frescor_atrasado", None)] * 150 + [("painel:sse", None, "timeout")] * 30
              + [("painel:api", "painel:api_500", None)] * 12 + [("painel:x", None, None)] * 6
              + [(f"painel:p{i}", f"sig{i}", None) for i in range(7)])
    g = falhas_por_causa(linhas)
    assert g["total"] == 205 and len(g["causas"]) == 5
    assert sum(c["n"] for c in g["causas"]) + g["outras"] == g["total"]
    assert g["causas"][0] == {"causa": "painel:frescor_atrasado", "n": 150}
    assert {"timeout", "painel:x"} <= {c["causa"] for c in g["causas"]} and g["outras"] / g["total"] < 0.1
    assert falhas_por_causa([]) == {"total": 0, "causas": [], "outras": 0}

    st = Store(tmp_path / "s.db")
    agora = time.time()
    for ponto, sig, ts in (("painel:frescor", "painel:frescor_atrasado", agora),
                           ("painel:frescor", "painel:frescor_atrasado", agora),
                           ("painel:frescor", "painel:frescor_atrasado", agora - 2 * 86400),
                           ("gate:ci", "gate:ci:x", agora)):
        st.x("INSERT INTO verificacoes(tick,ponto,ok,assinatura,created_at) VALUES(1,?,0,?,?)", (ponto, sig, ts))
    h = saude(st.db)
    assert h["falhas_24h"] == {"total": 2, "causas": [{"causa": "painel:frescor_atrasado", "n": 2}], "outras": 0}
    pagina = pagina_saude(h).decode()
    assert pagina.index("Falhas do painel (24 h)") < pagina.index("Semáforo") and "painel:frescor_atrasado" in pagina


def test_falhas_do_painel_por_componente_com_variacao_ordenadas_do_mais_afetado(tmp_path):
    """Pergunta #307: toda falha painel:% das últimas 24 h cai num componente (o ponto), com a variação contra as 24 h
    anteriores, do mais afetado para o menos; janela vazia é lista vazia."""
    import time

    from circulo.painel import falhas_por_componente, pagina_saude, saude
    from circulo.state import Store
    agora = 1_000_000.0
    linhas = ([("painel:frescor", agora - 60)] * 150 + [("painel:sse", agora - 3600)] * 30
              + [("painel:api", agora - 10)] * 25 + [("painel:frescor", agora - 86400 - 60)] * 100
              + [("painel:sse", agora - 86400 - 5)] * 40 + [("painel:velho", agora - 86400 - 1)] * 9)
    g = falhas_por_componente(linhas, agora)
    assert [c["componente"] for c in g] == ["painel:frescor", "painel:sse", "painel:api"]
    assert sum(c["n"] for c in g) == 205
    assert g[0] == {"componente": "painel:frescor", "n": 150, "anterior": 100, "variacao": 50}
    assert g[1]["variacao"] == -10 and g[2] == {"componente": "painel:api", "n": 25, "anterior": 0, "variacao": 25}
    assert falhas_por_componente([], agora) == []
    assert falhas_por_componente([("painel:x", agora - 86400 - 5)], agora) == []

    st = Store(tmp_path / "s.db")
    t = time.time()
    for ponto, ts in (("painel:frescor", t), ("painel:sse", t), ("painel:sse", t), ("painel:sse", t - 86400 - 60),
                      ("painel:sse", t - 3 * 86400), ("gate:ci", t)):
        st.x("INSERT INTO verificacoes(tick,ponto,ok,created_at) VALUES(1,?,0,?)", (ponto, ts))
    h = saude(st.db)
    assert h["componentes_24h"] == [{"componente": "painel:sse", "n": 2, "anterior": 1, "variacao": 1},
                                    {"componente": "painel:frescor", "n": 1, "anterior": 0, "variacao": 1}]
    pagina = pagina_saude(h).decode()
    assert pagina.index("Falhas por componente (24 h)") < pagina.index("Semáforo")
    assert pagina.index("painel:sse") < pagina.index("painel:frescor") and "▲ +1" in pagina


def test_variacao_das_falhas_contra_as_24h_anteriores_com_cor_invertida_e_sem_base(tmp_path):
    """Item #230: alta de falhas é ruim (▲ vermelho), queda é boa (▼ verde), igual é '● 0', sem base é 'novo' ou '—',
    sem dividir por zero; os dois cards de falhas (causa e componente) mostram o delta."""
    import time

    from circulo.painel import pagina_saude, saude, variacao
    from circulo.state import Store
    assert variacao(150, 100) == {"seta": "▲", "delta": 50, "texto": "▲ +50 (+50%)", "classe": "ruim"}
    assert variacao(30, 40) == {"seta": "▼", "delta": -10, "texto": "▼ −10 (−25%)", "classe": "bom"}
    assert variacao(0, 9)["texto"] == "▼ −9 (−100%)"
    assert variacao(7, 7) == {"seta": "●", "delta": 0, "texto": "● 0", "classe": "neutro"}
    assert variacao(25, 0) == {"seta": "▲", "delta": 25, "texto": "▲ +25 novo", "classe": "ruim"}
    assert variacao(0, 0) == {"seta": "", "delta": 0, "texto": "—", "classe": "neutro"}

    st = Store(tmp_path / "s.db")
    t = time.time()
    for ponto, sig, ts in (("painel:sse", "painel:sse_timeout", t), ("painel:sse", "painel:sse_timeout", t),
                           ("painel:sse", "painel:sse_timeout", t - 86400 - 60), ("painel:api", "painel:api_500", t),
                           ("painel:frescor", "painel:frescor_atrasado", t - 86400 - 60)):
        st.x("INSERT INTO verificacoes(tick,ponto,ok,assinatura,created_at) VALUES(1,?,0,?,?)", (ponto, sig, ts))
    h = saude(st.db)
    assert h["falhas_antes"] == {"total": 2, "por_causa": {"painel:sse_timeout": 1, "painel:frescor_atrasado": 1}}
    pagina = pagina_saude(h).decode()
    inicio_causa = pagina.index('aria-label="Falhas do painel por causa"')
    componente = pagina[pagina.index('aria-label="Falhas do painel por componente"'):inicio_causa]
    causa = pagina[inicio_causa:]
    assert '<em class="delta ruim">▲ +1 (+50%)</em>' in causa                      # total 3 vs 2
    assert '<em class="delta ruim">▲ +1 (+100%)</em>' in causa and "▲ +1 novo" in causa
    assert '<em class="delta ruim">▲ +1 (+100%)</em>' in componente and "▲ +1 novo" in componente
    assert ".delta.ruim{color:var(--bad)}" in pagina and ".delta.bom{color:var(--ok)}" in pagina
    vazia = pagina_saude(saude(Store(tmp_path / "v.db").db)).decode()
    assert '<em class="delta neutro">—</em>' in vazia


def test_cada_causa_do_card_mostra_as_24h_anteriores_e_o_delta_nova_subiu_caiu(tmp_path):
    """Pergunta #326 (item #234): toda causa do card de falhas traz a contagem das 24 h anteriores e o delta; a causa
    que sumiu aparece com ×0 e ▼ em vez de se esconder em 'outras'; n e anterior somam os totais das duas janelas."""
    import time

    from circulo.painel import causas_vs_antes, pagina_saude, saude
    from circulo.state import Store
    atual = {"total": 13, "causas": [{"causa": "sse", "n": 8}, {"causa": "api", "n": 3}], "outras": 2}
    antes = {"total": 17, "por_causa": {"sse": 5, "frescor": 7, "api": 2, "x": 3}}
    g = causas_vs_antes(atual, antes, top=2)
    assert g == [{"causa": "sse", "n": 8, "anterior": 5}, {"causa": "api", "n": 3, "anterior": 2},
                 {"causa": "frescor", "n": 0, "anterior": 7}, {"causa": "outras", "n": 2, "anterior": 3}]
    assert sum(c["n"] for c in g) == atual["total"] and sum(c["anterior"] for c in g) == antes["total"]
    assert causas_vs_antes({"total": 0, "causas": [], "outras": 0}, {"total": 0, "por_causa": {}}) == []

    st = Store(tmp_path / "s.db")
    t = time.time()
    for sig, n, ts in (("painel:nova", 2, t), ("painel:subiu", 3, t), ("painel:subiu", 1, t - 86400 - 60),
                       ("painel:caiu", 1, t), ("painel:caiu", 4, t - 86400 - 60), ("painel:sumiu", 2, t - 86400 - 60)):
        for _ in range(n):
            st.x("INSERT INTO verificacoes(tick,ponto,ok,assinatura,created_at) VALUES(1,'painel:x',0,?,?)", (sig, ts))
    pagina = pagina_saude(saude(st.db)).decode()
    causa = pagina[pagina.index('aria-label="Falhas do painel por causa"'):]
    lista = causa[causa.index("<ol><li>") + 8:causa.index("</li></ol>")].split("</li><li>")
    itens = {li.split(" <b>")[0]: li for li in lista}
    assert set(itens) == {"painel:nova", "painel:subiu", "painel:caiu", "painel:sumiu"}
    assert '×2</b> <small>antes 0</small> <em class="delta ruim">▲ +2 novo</em>' in itens["painel:nova"]
    assert '×3</b> <small>antes 1</small> <em class="delta ruim">▲ +2 (+200%)</em>' in itens["painel:subiu"]
    assert '×1</b> <small>antes 4</small> <em class="delta bom">▼ −3 (−75%)</em>' in itens["painel:caiu"]
    assert '×0</b> <small>antes 2</small> <em class="delta bom">▼ −2 (−100%)</em>' in itens["painel:sumiu"]


def test_falhas_agrupadas_por_causa_normalizada_com_fracao_e_dominante_no_topo(tmp_path):
    """Pergunta #330: as 205 falhas painel:% das 24 h caem em causas normalizadas (números e ids não separam a mesma
    causa), com n e fração somando o total, ordem estável (empate pelo nome) e 'outras' abaixo de 20%; o card mostra
    a causa dominante e o total no topo."""
    import random
    import time

    from circulo.painel import agrupar_por_causa, falhas_por_causa, pagina_saude, saude
    from circulo.state import Store
    linhas = ([("painel:frescor", "painel:frescor_atrasado", None)] * 120
              + [("painel:sse", None, f"timeout após {3000 + i} ms") for i in range(40)]
              + [("painel:api", None, f"HTTP 500 no pedido {i}") for i in range(30)]
              + [("painel:z", "painel:z_b", None)] * 5 + [("painel:z", "painel:z_a", None)] * 5
              + [(f"painel:p{i}", f"sig{i}", None) for i in range(5)])
    g = agrupar_por_causa(linhas)
    assert sum(c["n"] for c in g) == 205 and abs(sum(c["fracao"] for c in g) - 1) < 1e-9
    assert g[0] == {"causa": "painel:frescor_atrasado", "n": 120, "fracao": 120 / 205}
    assert [c["causa"] for c in g[1:3]] == ["timeout após n ms", "http n no pedido n"]
    assert [c["causa"] for c in g[3:5]] == ["painel:z_a", "painel:z_b"]               # empate: pelo nome
    embaralhadas = linhas[:]
    random.Random(7).shuffle(embaralhadas)
    assert agrupar_por_causa(embaralhadas) == g and falhas_por_causa(embaralhadas) == falhas_por_causa(linhas)
    f = falhas_por_causa(linhas)
    assert f["total"] == 205 and f["outras"] / f["total"] < 0.2
    assert agrupar_por_causa([]) == []

    st = Store(tmp_path / "s.db")
    t = time.time()
    for sig, n in (("painel:sse_timeout", 3), ("painel:api_500", 1)):
        for _ in range(n):
            st.x("INSERT INTO verificacoes(tick,ponto,ok,assinatura,created_at) VALUES(1,'painel:x',0,?,?)", (sig, t))
    h = saude(st.db)
    assert h["falhas_dominante"] == {"causa": "painel:sse_timeout", "n": 3, "fracao": 0.75}
    pagina = pagina_saude(h).decode()
    card = pagina[pagina.index('aria-label="Falhas do painel por causa"'):]
    assert card.index("Dominante: <strong>painel:sse_timeout</strong> ×3 (75% de 4)") < card.index("<ol>")
    vazia = Store(tmp_path / "v.db").db
    assert saude(vazia)["falhas_dominante"] is None and "Dominante" not in pagina_saude(saude(vazia)).decode()


def test_painel_lista_entregas_sem_uso_apos_7_dias(tmp_path):
    """Pergunta #338: o painel lê entrega_uso_esperado e lista cada entrega mergeada há 7+ dias sem evento de uso
    depois do merge; a usada e a de menos de 7 dias ficam de fora, e a contagem aparece no card."""
    import time

    from circulo.painel import pagina_saude, saude
    from circulo.state import Store
    from circulo.uso_entregas import registrar_esperado
    st = Store(tmp_path / "s.db")
    t = time.time()
    registrar_esperado(st.db, 11, "comando:circulo_assunto", t - 8 * 86400)
    registrar_esperado(st.db, 12, "tela:painel_saude", t - 9 * 86400)
    registrar_esperado(st.db, 13, "endpoint:api_uso", t - 2 * 86400)
    st.x("INSERT INTO events(kind,payload,created_at) VALUES('comando:circulo_assunto','{}',?)", (t - 86400,))
    h = saude(st.db)
    assert [e["number"] for e in h["entregas_sem_uso"]] == [12]
    pagina = pagina_saude(h).decode()
    card = pagina[pagina.index('aria-label="Entregas sem uso após 7 dias"'):]
    assert "<b>1</b>" in card[:card.index("</section>")] and "PR #12" in card and "tela:painel_saude" in card
    assert "PR #11" not in pagina and "PR #13" not in pagina
    vazia = saude(Store(tmp_path / "v.db").db)
    assert vazia["entregas_sem_uso"] == [] and "<b>0</b>" in pagina_saude(vazia).decode()


def test_chamar_endpoint_do_painel_grava_uso_e_a_entrega_sai_de_sem_uso(circle, painel):
    """Pergunta #351: a rota do painel chamada grava o uso real (nome, instante) casado com o evento esperado; a
    entrega com evento esperado X sai de 'sem uso' depois de um uso X posterior ao merge, e a que não foi usada fica."""
    import time

    from circulo.painel import saude
    from circulo.uso_entregas import nome_uso, registrar_esperado
    st = circle.store
    oito_dias = time.time() - 8 * 86400
    registrar_esperado(st.db, 21, nome_uso("/api/norte"), oito_dias)
    registrar_esperado(st.db, 22, nome_uso("/painel"), oito_dias)
    registrar_esperado(st.db, 23, "endpoint:/api/nunca_chamado", oito_dias)
    assert [e["number"] for e in saude(st.db)["entregas_sem_uso"]] == [21, 22, 23]
    for caminho in ("/api/norte", "/painel", "/api/estado"):
        with urllib.request.urlopen(painel + caminho, timeout=5) as r:
            r.read()
    assert [e["number"] for e in saude(st.db)["entregas_sem_uso"]] == [23]
    usos = [n for (n,) in st.db.execute("SELECT nome FROM entrega_uso ORDER BY nome")]
    assert usos == ["endpoint:/api/norte", "tela:/painel"]          # só o que alguma entrega espera é gravado


def test_painel_expoe_entregas_sem_uso_7d_com_toda_entrega_madura_classificada(tmp_path):
    """Pergunta #364: saude() expõe entregas_sem_uso_7d; cada entrega mergeada há 7+ dias cai em 'com uso' ou
    'sem uso' (0 sem classificação), a de menos de 7 dias fica de fora, e o cálculo cabe na meta de frescor (3000 ms)."""
    import time

    from circulo.painel import pagina_saude, saude
    from circulo.state import Store
    from circulo.uso_entregas import registrar_esperado
    st = Store(tmp_path / "s.db")
    t = time.time()
    registrar_esperado(st.db, 31, "comando:circulo_assunto", t - 8 * 86400)
    registrar_esperado(st.db, 32, "tela:painel_saude", t - 9 * 86400)
    registrar_esperado(st.db, 33, "endpoint:api_uso", t - 2 * 86400)
    st.x("INSERT INTO events(kind,payload,created_at) VALUES('comando:circulo_assunto','{}',?)", (t - 86400,))
    r = saude(st.db)["entregas_sem_uso_7d"]
    assert r["com_uso"] == [31] and r["sem_uso"] == [32] and r["maduras"] == 2
    assert "Com uso: <b>1</b> de 2" in pagina_saude(saude(st.db)).decode()
    for pr in range(1000, 3000):
        registrar_esperado(st.db, pr, f"tela:x{pr % 50}", t - 10 * 86400)
    inicio = time.perf_counter()
    r = saude(st.db)["entregas_sem_uso_7d"]
    assert (time.perf_counter() - inicio) * 1000 < 3000
    assert sorted(r["com_uso"] + r["sem_uso"]) == [31, 32, *range(1000, 3000)]    # 0 maduras sem classificação


def test_cada_pedido_contestado_aparece_com_motivo_e_fontes_e_sem_fonte_vira_aviso(tmp_path):
    """Pergunta #429: o painel lista todo pedido contestado com o motivo e os links das fontes; a contestação sem fonte
    registrada aparece com o aviso 'contestação sem fonte' em vez de sumir."""
    import time

    from circulo.painel import pagina_saude, saude
    from circulo.state import Store
    st = Store(tmp_path / "s.db")
    agora = time.time()
    estudo = json.dumps({"veredito": "contestar", "justificativa": "O banco atual já aguenta a carga medida.",
                         "fontes": ["https://sqlite.org/whentouse.html", "https://www.sqlite.org/wal.html"]})
    for titulo, est in (("Trocar o banco", estudo), ("Reescrever em Rust", None)):
        st.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,estudo) "
             "VALUES(?,'d','pedido_cassio','contestado','contestado pelo estudo',1,?,?,?)", (titulo, agora, agora, est))
    st.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
         "VALUES('Item comum','d','loop','pendente','e',2,?,?)", (agora, agora))
    h = saude(st.db)
    por_titulo = {c["titulo"]: c for c in h["contestados"]}
    assert set(por_titulo) == {"Trocar o banco", "Reescrever em Rust"}
    assert por_titulo["Trocar o banco"]["motivo"] == "O banco atual já aguenta a carga medida."
    assert por_titulo["Trocar o banco"]["fontes"] == ["https://sqlite.org/whentouse.html", "https://www.sqlite.org/wal.html"]
    assert por_titulo["Reescrever em Rust"]["fontes"] == [] and por_titulo["Reescrever em Rust"]["motivo"]
    assert h["contestados_sem_fonte"] == 1
    pagina = pagina_saude(h).decode()
    assert "Pedidos contestados" in pagina and "O banco atual já aguenta a carga medida." in pagina
    assert '<a href="https://sqlite.org/whentouse.html"' in pagina
    assert pagina.count("contestação sem fonte") == 1 and "Reescrever em Rust" in pagina


def test_planos_antes_do_commit_fracoes_puras_com_plano_posterior_ausente_e_lista_vazia():
    """Item #276: só conta o plano gravado até o primeiro commit do PR; plano depois do commit e plano ausente entram
    na lista de pedidos sem plano; a fração humana conta aprovado ou corrigido por humano, não o prazo vencido."""
    from circulo.planos import fracoes
    prs = [{"item_id": i, "pr": 9 + i, "commit_em": 100.0} for i in range(1, 6)]
    planos = {1: {"estado": "aprovado_humano", "em": 50.0}, 2: {"estado": "corrigido_humano", "em": 100.0},
              3: {"estado": "auto_prosseguiu", "em": 90.0}, 4: {"estado": "aprovado_humano", "em": 101.0}}
    r = fracoes(prs, planos)
    assert r["total"] == 5 and r["registrado_pct"] == 60.0 and r["humano_pct"] == 40.0
    assert r["estados"] == {"aprovado_humano": 1, "corrigido_humano": 1, "auto_prosseguiu": 1, "ausente": 2}
    assert r["sem_plano"] == [{"item_id": 4, "pr": 13, "motivo": "plano depois do commit"},
                              {"item_id": 5, "pr": 14, "motivo": "sem plano"}]
    vazio = fracoes([], planos)
    assert vazio["total"] == 0 and vazio["registrado_pct"] is None and vazio["humano_pct"] is None
    assert vazio["sem_plano"] == []


def test_planos_aprovados_antes_do_commit_aparecem_no_painel(tmp_path):
    """Item #276: o plano gravado por item e o PR do Developer viram a seção 'Planos aprovados antes do commit'."""
    import sqlite3
    import time

    from circulo.painel import pagina_saude, saude
    from circulo.planos import gravar
    from circulo.state import Store
    st = Store(tmp_path / "s.db")
    agora = time.time()
    gravar(st.db, 7, ["ler painel.py", "criar seção"], ["circulo/painel.py"], ["prs.created_at é o commit"],
           "aprovado_humano", em=agora - 60)
    with pytest.raises(sqlite3.IntegrityError):
        gravar(st.db, 8, [], [], [], "talvez", em=agora)
    for n, item in ((40, 7), (41, 9)):
        st.x("INSERT INTO prs(number,titulo,branch,status,item_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
             (n, f"item {item}", f"circulo/fix-{item}-1", "aberto", item, agora, agora))
    h = saude(st.db)
    assert h["planos"]["registrado_pct"] == 50.0 and h["planos"]["humano_pct"] == 50.0
    pagina = pagina_saude(h).decode()
    assert "Planos aprovados antes do commit" in pagina and "PR #41" in pagina and "sem plano" in pagina


def test_estado_do_pedido_e_puro_e_segue_a_ordem_das_regras():
    """Pergunta #472: entregue > bloqueado > andamento (com o PR) > recebido; idade desde a última transição."""
    from circulo.pedido_estado import estado_pedido

    def c(feitas, motivo="", o_que="o estudo do item"):
        etapas = [{"etapa": e, "titulo": t, "em": em, "feita": True} for e, t, em in feitas]
        return {"etapas": etapas, "esperando": {"o_que": o_que, "motivo": motivo}}
    ev = {"status": "done", "error": None, "created_at": 100.0, "processed_at": 110.0}
    item = [("pedido", "Pedido", 100.0), ("item", "virou item #5", 120.0)]
    pr = item + [("pr", "PR #9 aberto", 200.0)]
    assert estado_pedido(ev, c(item), {"status": "pendente"}, 300.0) == {
        "estado": "recebido", "detalhe": "esperando o estudo do item", "pr": None, "desde": 120.0, "idade_s": 180}
    r = estado_pedido(ev, c(pr, "checks em andamento: test"), {"status": "em_andamento"}, 300.0)
    assert (r["estado"], r["pr"], r["idade_s"]) == ("andamento", 9, 100)
    r = estado_pedido(ev, c(pr + [("ci", "CI: vermelho", 250.0)], "CI vermelho: test_x"), {"status": "em_andamento"}, 300.0)
    assert (r["estado"], r["detalhe"], r["pr"], r["desde"]) == ("bloqueado", "CI vermelho: test_x", 9, 250.0)
    r = estado_pedido(ev, c(pr + [("merge", "PR #9 mergeado", 280.0)]), {"status": "feito"}, 300.0)
    assert (r["estado"], r["detalhe"], r["idade_s"]) == ("entregue", "PR #9 mergeado", 20)
    r = estado_pedido(ev, c([("pedido", "Pedido", 100.0)]), None, 300.0)
    assert (r["estado"], r["desde"]) == ("entregue", 110.0)                      # respondido sem virar item
    falhou = {**ev, "status": "failed", "error": "boom", "processed_at": None}
    r = estado_pedido(falhou, c([("pedido", "Pedido", 100.0)], "o pedido falhou ao virar item: boom"), None, 300.0)
    assert (r["estado"], r["idade_s"]) == ("bloqueado", 200) and "boom" in r["detalhe"]
    r = estado_pedido({**ev, "status": "pending", "processed_at": None}, c([("pedido", "Pedido", 100.0)]), None, 300.0)
    assert r["estado"] == "recebido"


def test_cada_pedido_dos_7_dias_tem_exatamente_um_estado_com_idade_no_painel(tmp_path):
    """Pergunta #472: os 10 pedidos do humano em 7 dias, um em cada caminho já gravado (evento, item, PR, CI, gate),
    saem com exatamente 1 estado e a idade nele; nenhum fica sem estado, nem na lista nem na página."""
    import time

    from circulo.painel import pagina_saude, pedidos, saude
    from circulo.pedido_estado import ESTADOS_PEDIDO
    from circulo.rastro import elo
    from circulo.state import Store
    st = Store(tmp_path / "s.db")
    agora = time.time()

    def ev(kind, status, horas, error=None, origem="painel"):
        em = agora - horas * 3600
        return st.x("INSERT INTO events(kind,payload,status,error,created_at,processed_at) VALUES(?,?,?,?,?,?)",
                    (kind, json.dumps({"text": f"pedido de {horas} h", "origem": origem}), status, error, em,
                     em + 1 if status == "done" else None))

    def item(e, status="pendente", pr=None, merges=()):
        i = st.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                 "VALUES(?,?,'pedido_cassio',?,'pedido pelo painel',1,?,?)", (f"item do ev {e}", "d", status, agora, agora))
        elo(st, f"pedido:{e}", f"item:{i}", "virou_item")
        if pr:
            st.x("INSERT INTO prs(number,titulo,branch,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                 (pr, "t", f"circulo/fix-{i}-1", "aberto", agora - 600, agora - 600))
        for merged, motivo in merges:
            st.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,'a',?,?,'{}',?)",
                 (pr, merged, motivo, agora - 300))

    ev("mensagem", "pending", 1)
    ev("novo_projeto", "processing", 2)
    ev("mensagem", "failed", 3, error="boom")
    ev("novo_projeto", "done", 4)
    item(ev("mensagem", "done", 5))
    item(ev("mensagem", "done", 6), "em_andamento", 101)
    item(ev("mensagem", "done", 7), "em_andamento", 102, [(0, "checks em andamento: test")])
    item(ev("mensagem", "done", 8), "em_andamento", 103, [(0, "CI vermelho: test_x")])
    item(ev("mensagem", "done", 9), "feito", 104, [(1, "checks verdes")])
    item(ev("mensagem", "done", 10), "contestado")
    ev("mensagem", "done", 11, origem="demo")                                    # não é pedido do humano
    ev("mensagem", "done", 8 * 24)                                               # fora da janela de 7 dias

    ps = pedidos(st, agora)
    assert len(ps) == 10
    assert all(p["estado"] in ESTADOS_PEDIDO and p["idade_s"] >= 0 for p in ps)
    assert [p["estado"] for p in ps] == ["recebido", "recebido", "bloqueado", "entregue", "recebido",
                                         "andamento", "andamento", "bloqueado", "entregue", "bloqueado"]
    assert [p["pr"] for p in ps][5:9] == [101, 102, 103, 104] and "CI vermelho" in ps[7]["detalhe"]

    pagina = pagina_saude({**saude(st.db), "pedidos": ps}).decode()
    linhas = pagina.split('aria-label="Estado de cada pedido seu"', 1)[1].split("</ol>", 1)[0].count("<li")
    assert linhas == 10 and "PR #104 mergeado" in pagina and "boom" in pagina

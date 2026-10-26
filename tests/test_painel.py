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

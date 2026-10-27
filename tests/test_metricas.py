import json
import threading
import time
import urllib.request

from circulo.projects import cards, kit_project_id
from circulo.painel import serve
from conftest import say


def card(circle, kit):
    return next(c for c in cards(circle.store) if c["kit"] == kit)


def test_metricas_do_loop(circle):
    for _ in range(3):
        circle.tick()
    circle.store.x("INSERT INTO prs(number,project_id,titulo,status,created_at,updated_at) VALUES(7,?, 'fix', 'mergeado', 0, 0)",
                   (kit_project_id(circle.store, "circulo"),))
    m = card(circle, "circulo")["metricas"]
    assert m["ciclos"] == 3 and m["versao"] == "política v1" and m["prs"] == {"abertos": 0, "mergeados": 1}
    assert "Jev local" in m["modelos"] and "Claude Code" in m["modelos"]
    assert m["principal"]["rotulo"] == "Roteiro concluído" and 0 < m["principal"]["valor"] < 1
    assert card(circle, "circulo")["nome"] == "O Loop"


def test_metricas_de_financas(circle):
    for i in range(3):
        say(circle, f"{50 + i} sacolão")
        say(circle, f"corrige {i + 1} mercado")
    say(circle, "20 netflix")
    m = card(circle, "financas")["metricas"]
    assert m["versao"] == "regras v2" and m["evolucoes"] == 1 and m["lancamentos"] == 4
    assert m["principal"]["valor"] == 0.25          # só a netflix foi categorizada sozinha e certa


def test_metricas_do_motor(tmp_path, clock):
    from test_engine import FakeGen
    from circulo.decision import LocalJev
    from circulo.loop import Circle
    c = Circle(tmp_path, jev=LocalJev(), llm=FakeGen(), now=clock)
    c.submit_project("Crie uma landing page para captar leads do Instagram")
    c.tick()
    pid = c.store.one("SELECT id FROM projects WHERE tipo='landing_page'")["id"]
    for _ in range(3):
        c.engine.cycle(pid)
    m = next(x for x in cards(c.store) if x["id"] == pid)["metricas"]
    assert m["versao"] == "v2" and m["evolucoes"] == 1 and m["aceitacao"] == 1.0
    assert len(m["principal"]["historico"]) == 2 and m["principal"]["historico"][1] > m["principal"]["historico"][0]
    assert any(x.startswith("Sonnet") for x in m["modelos"]) and m["tokens"] > 0 and m["tokens_por_ponto"]


def test_trilha_de_etapas_no_sse(circle):
    srv = serve(circle.store.path, port=0, background=True)
    got = []

    def read():
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/eventos?desde=0", timeout=8) as r:
            for line in r:
                if line.startswith(b"data:") and b'"etapa"' in line and b'"seq"' in line:
                    got.append(json.loads(line[5:]))
                if len(got) >= 4:
                    return

    th = threading.Thread(target=read, daemon=True)
    th.start()
    import time
    time.sleep(0.8)
    circle.tick()
    th.join(6)
    srv.shutdown()
    assert [g["etapa"] for g in got][:2] == ["orquestrador", "idle"]


def test_falar_com_o_loop_vira_pedido_no_roteiro(circle):
    pid = kit_project_id(circle.store, "circulo")
    circle.store.enqueue("mensagem", {"text": "Priorize pesquisar antes de construir", "projeto": pid})
    circle.tick()
    r = circle.store.one("SELECT * FROM roadmap ORDER BY id DESC LIMIT 1")
    assert r["titulo"] == "Priorize pesquisar antes de construir" and r["origem"] == "pedido_cassio" and r["status"] == "pendente"
    assert circle.store.one("SELECT COUNT(*) n FROM ledger")["n"] == 0


def test_tokens_por_pr_fecha_com_tokens_24h_atribuindo_o_sem_pr_a_papel_e_desfecho(circle):
    """Pergunta #352: 79% de tokens_24h não estavam em PR nenhum. Os tokens que chegaram a PR (por veredito) mais
    'sem_pr' (por papel e por desfecho do item) somam exatamente tokens_24h."""
    from circulo.pedido_claro import registrar
    from circulo.perguntas import METRICAS
    s, agora = circle.store, time.time()
    for titulo, detalhe, status in (("Entregue", "Mudar circulo/loop.py; teste de regressão.\nSucesso: giro", "feito"),
                                    ("Vago entregue", "melhorar", "feito"), ("Jogado fora", "", "descartado"),
                                    ("Travado", "", "bloqueado"), ("Em curso", "", "pendente")):
        s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
            "VALUES(?,?,'erro',?,'',1,?,?)", (titulo, detalhe, status, agora, agora))
        registrar(s, dict(s.one("SELECT * FROM roadmap WHERE titulo=?", (titulo,))), agora=agora)
    s.x("DELETE FROM llm_calls")
    for papel, entrada, tokens, ok, quando in (
            ("developer", "Entregue", 30_000, 1, agora), ("developer", "reparo: Entregue", 10_000, 1, agora),
            ("estudo", "[rapido] Entregue", 4_000, 1, agora), ("developer", "Vago entregue", 20_000, 1, agora),
            ("developer", "Jogado fora", 50_000, 1, agora), ("planejador", "Jogado fora", 3_000, 1, agora),
            ("developer", "Travado", 40_000, 1, agora), ("developer", "Em curso", 7_000, 0, agora),
            ("developer", "Em curso", 9_000, 1, agora), ("planejador", "evidência do loop", 2_000, 1, agora),
            ("estudo", "[profundo] Em curso", 6_000, 1, agora), ("developer", "Entregue", 999_999, 1, agora - 2 * 86400)):
        s.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,ok,entrada,created_at) "
            "VALUES(1,?,'m','fixo',?,?,?,?)", (papel, tokens, ok, entrada, quando))
    _, ctx = METRICAS["tokens_por_pr"][1](s, agora)
    assert ctx["com_pr_por_veredito"] == {"completo": 44_000, "incompleto": 20_000}
    assert ctx["sem_pr"] == {"tokens": 117_000,
                             "por_papel": {"developer": 106_000, "planejador": 5_000, "estudo": 6_000},
                             "por_desfecho": {"descartado": 53_000, "falha": 47_000, "pendente": 17_000}}
    assert sum(ctx["com_pr_por_veredito"].values()) + ctx["sem_pr"]["tokens"] == ctx["tokens_24h"] == 181_000

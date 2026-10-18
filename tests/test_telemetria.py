"""Trilha de eventos tipados do loop (OTel GenAI) e o painel de timeline + grafo gerado dela."""
import json
import time
import urllib.request

from circulo import telemetria
from circulo.painel import serve
from conftest import say


def _spans(circle):
    return [json.loads(x) for x in (circle.data_dir / "telemetria" / "spans.jsonl").read_text().splitlines()]


def _op(s):
    return s["attributes"]["gen_ai.operation.name"]


def test_todo_giro_deixa_traco_completo_e_o_painel(circle):
    say(circle, "38,90 ifood almoço")               # giro com pedido
    circle.tick()                                   # giro de evolução natural
    spans = _spans(circle)
    runs = {s["attributes"]["circulo.run_id"] for s in spans}
    assert len(runs) == 2
    for run in runs:
        dele = [s for s in spans if s["attributes"]["circulo.run_id"] == run]
        w = [s for s in dele if _op(s) == "invoke_workflow"]
        assert len(w) == 1 and w[0]["parent_span_id"] is None and len({s["trace_id"] for s in dele}) == 1
        assert w[0]["attributes"]["gen_ai.agent.version"]
        agentes = [s for s in dele if _op(s) == "invoke_agent"]
        assert agentes and all(s["parent_span_id"] == w[0]["span_id"] for s in agentes)
        assert "orquestrador" in {s["attributes"]["gen_ai.agent.name"] for s in agentes}
        dec = [s for s in dele if _op(s) == "jev_decision"]
        assert dec and all(s["attributes"]["circulo.decision.by"] and "circulo.decision.reason" in s["attributes"] for s in dec)
    pedido = [s for s in spans if _op(s) == "jev_decision" and s["attributes"]["circulo.decision.value"] == "pedido:mensagem"]
    assert pedido and pedido[0]["attributes"]["circulo.decision.by"] == "regra"
    pag = (circle.data_dir / "telemetria" / "index.html").read_text()
    assert "vis-timeline" in pag and "flowchart LR" in pag and all(r in pag for r in runs)


def test_giro_falho_aparece_no_painel_com_incidente(circle, monkeypatch):
    def quebra(payload, event_id):
        raise RuntimeError("falha de teste")
    monkeypatch.setattr(circle, "handle", quebra)
    _, (r,) = say(circle, "38,90 ifood almoço")
    w = next(s for s in _spans(circle) if _op(s) == "invoke_workflow")
    assert w["status"]["code"] == "ERROR" and "falha de teste" in w["status"]["message"]
    inc = circle.store.one("SELECT id FROM incidents")["id"]
    assert w["attributes"]["circulo.incident_ids"] == [inc]
    assert w["events"][0]["attributes"]["circulo.incident_id"] == inc
    pag = (circle.data_dir / "telemetria" / "index.html").read_text()
    falhos = pag.split("<h2>Giros com falha</h2>")[1].split("<h2>")[0]
    assert r.run_id in falhos and f"incidente #{inc}" in falhos and "falha de teste" in falhos


def test_falha_da_telemetria_nunca_derruba_o_loop(circle, monkeypatch):
    def quebra(*a, **k):
        raise OSError("disco cheio")
    monkeypatch.setattr(telemetria, "spans_do_ciclo", quebra)
    r = circle.tick()
    assert r.errors == [] and circle.store.get("telemetria_falhas")["n"] == 1
    assert circle.tick().tick == 2


def test_prompt_nao_e_gravado_por_padrao_e_ferramentas_levam_pr(circle, monkeypatch):
    s, t0 = circle.store, time.time()
    s.x("INSERT INTO trail(tick,etapa,project_id,em,run_id,tarefa) VALUES(1,'idle',NULL,?,'r1','revisar_prs')", (t0,))
    s.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,duracao_ms,ok,entrada,saida,created_at) "
        "VALUES(1,'developer','claude-x','jev',1234,500,1,'SEGREDO do prompt','resposta',?)", (t0 + 1,))
    s.x("INSERT INTO verificacoes(tick,ponto,sujeito,ok,motivo,created_at) VALUES(1,'gate:ci','PR #12',0,'testes falharam',?)", (t0 + 2,))
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(12,'abc',1,'ok','{}',?)", (t0 + 3,))
    spans = telemetria.spans_do_ciclo(s, "r1", 1, t0 - 1, t0 + 5)
    assert "SEGREDO" not in json.dumps(spans)
    w = spans[0]
    assert w["attributes"]["gen_ai.usage.total_tokens"] == 1234 and w["attributes"]["circulo.prs"] == [12]
    ci = next(x for x in spans if x["attributes"].get("gen_ai.tool.name") == "github_ci")
    agente = next(x for x in spans if _op(x) == "invoke_agent")
    assert ci["status"]["code"] == "ERROR" and ci["attributes"]["circulo.pr"] == 12 and ci["parent_span_id"] == agente["span_id"]
    monkeypatch.setenv("CIRCULO_TELEMETRIA_CONTEUDO", "1")       # opt-in explícito
    assert "SEGREDO" in json.dumps(telemetria.spans_do_ciclo(s, "r1", 1, t0 - 1, t0 + 5))


def test_grafo_conta_repeticoes_e_retry():
    def ag(trace, nome, t, ok=True):
        return {"trace_id": trace, "span_id": f"{trace}{t}", "start_time_unix_nano": t, "end_time_unix_nano": t,
                "status": {"code": "OK" if ok else "ERROR", "message": ""},
                "attributes": {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": nome}}
    spans = [ag("a", "orquestrador", 1), ag("a", "developer", 2, ok=False),
             ag("b", "orquestrador", 3), ag("b", "developer", 4), ag("b", "saude", 5)]
    g = telemetria.grafo(spans)
    assert g["nos"] == {"orquestrador": 2, "developer": 2, "saude": 1}
    assert g["falhas"] == {"developer": 1} and g["retries"] == {"developer": 1}
    assert {"de": "orquestrador", "para": "developer", "n": 2} in g["arestas"]
    m = telemetria.mermaid(g)
    assert "a_developer -.->|retry 1| a_developer" in m and "class a_developer falha" in m


def test_painel_abre_rapido_com_200_giros(circle):
    for _ in range(10):
        circle.tick()
    pasta = circle.data_dir / "telemetria"
    base = _spans(circle)
    with (pasta / "spans.jsonl").open("w") as f:      # 200 giros distintos no log
        for k in range(20):
            for s in base:
                f.write(json.dumps({**s, "trace_id": f"{k:02d}{s['trace_id'][2:]}"}) + "\n")
    t0 = time.time()
    spans = telemetria.ler(pasta)
    html = telemetria.pagina(spans)
    assert time.time() - t0 < 2 and "Trilha do loop" in html
    assert len({s["trace_id"] for s in spans}) == 200
    srv = serve(circle.store.path, port=0, background=True)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/telemetria", timeout=5) as r:
            assert b"Trilha do loop" in r.read()
    finally:
        srv.shutdown()

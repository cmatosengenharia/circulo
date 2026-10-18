"""Observabilidade: sinais de ouro, SLOs com orçamento de erro, /metrics (Prometheus) e exportação OTLP/HTTP."""
import json
import re
import time
import urllib.request

from circulo import observabilidade as ob
from circulo.telemetria import gravar

from test_painel import painel  # noqa: F401 — fixture do servidor do painel


def _giro(s, tick, ms, erros=0, tarefa=None, em=None):
    s.x("INSERT OR REPLACE INTO metrics(tick,body,created_at) VALUES(?,?,?)",
        (tick, json.dumps({"run_id": f"{tick:012x}", "duracao_ms": ms, "errors": ["x"] * erros, "idle": tarefa,
                           "budget": {"tokens": 50_000, "limite": 200_000}}), em or time.time() - 60))


def _base(s, n=100, erros=1):
    s.x("DELETE FROM metrics")
    for t in range(1, n + 1):
        _giro(s, t, 300, erros=1 if t <= erros else 0)
    _giro(s, n + 1, 600_000, tarefa="corrigir_codigo")      # Developer: pesado, fora da latência do giro leve


def test_sinais_de_ouro(circle):
    s = circle.store
    _base(s)
    g = ob.sinais(s)
    assert g["trafego"]["giros"] == 101 and g["trafego"]["pesados"] == 1
    assert g["latencia"]["leve_p95_ms"] == 300 and g["latencia"]["max_ms"] == 600_000
    assert g["erros"]["giros_com_erro"] == 1
    assert g["saturacao"]["orcamento_usado"] == 0.25


def test_slo_com_orcamento_de_erro(circle):
    s = circle.store
    _base(s, n=200, erros=1)        # 1 ruim em 201, alvo 99%: permitido ~2, gastou metade
    slo = {x["id"]: x for x in ob.slos(s)}
    g = slo["giros_ok"]
    assert g["estado"] == "ok" and 0.4 < g["orcamento_restante"] < 0.6
    assert slo["latencia_giro"]["ruins"] == 0                 # o giro do Developer não conta como giro leve lento
    _base(s, n=100, erros=5)
    g = {x["id"]: x for x in ob.slos(s)}["giros_ok"]
    assert g["estado"] == "violado" and g["orcamento_restante"] < 0
    assert {x["id"]: x for x in ob.slos(s)}["rastreabilidade"]["estado"] == "sem_dados"


def test_metrics_no_formato_do_prometheus(circle):
    s = circle.store
    _base(s)
    txt = ob.prometheus(s)
    amostra = re.compile(r'^[a-zA-Z_:][a-zA-Z0-9_:]*(\{([a-zA-Z_][a-zA-Z0-9_]*="([^"\\]|\\.)*",?)*\})? -?[0-9.eE+-]+$')
    tipos = set()
    for linha in txt.strip().splitlines():
        if linha.startswith("# TYPE"):
            nome = linha.split()[2]
            assert nome not in tipos, nome                    # HELP/TYPE uma vez por métrica
            tipos.add(nome)
        elif not linha.startswith("#"):
            assert amostra.match(linha), linha
    assert 'circulo_info{versao="' in txt and "circulo_giros_total 101" in txt
    assert 'circulo_slo_orcamento_restante_ratio{slo="giros_ok"}' in txt


def test_span_otlp_oficial():
    s = {"trace_id": "a" * 32, "span_id": "b" * 16, "parent_span_id": None, "name": "invoke_workflow circulo", "kind": "CLIENT",
         "start_time_unix_nano": 1, "end_time_unix_nano": 2, "status": {"code": "ERROR", "message": "x"},
         "attributes": {"n": 3, "f": 0.5, "b": True, "l": [1, 2], "s": "t"},
         "links": [{"trace_id": "c" * 32, "span_id": "d" * 16, "attributes": {"circulo.no": "item:1"}}]}
    lote = ob.lote_otlp([s])
    sp = lote["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert sp["kind"] == 3 and sp["status"]["code"] == 2 and sp["startTimeUnixNano"] == "1" and "parentSpanId" not in sp
    vals = {a["key"]: a["value"] for a in sp["attributes"]}
    assert vals["n"] == {"intValue": "3"} and vals["f"] == {"doubleValue": 0.5} and vals["b"] == {"boolValue": True}
    assert vals["l"]["arrayValue"]["values"][0] == {"intValue": "1"}
    assert sp["links"][0]["traceId"] == "c" * 32
    res = {a["key"]: a["value"]["stringValue"] for a in lote["resourceSpans"][0]["resource"]["attributes"]}
    assert res["service.name"] == "circulo"


def test_exportacao_otlp_so_avanca_depois_do_2xx(circle, tmp_path):
    s = circle.store
    pasta = tmp_path / "dados"
    span = {"trace_id": "a" * 32, "span_id": "b" * 16, "name": "x", "start_time_unix_nano": 1, "end_time_unix_nano": 2,
            "status": {"code": "OK"}, "attributes": {}}
    gravar(pasta / "telemetria", [span, {**span, "span_id": "c" * 16}])
    enviados = []

    def falha(url, corpo, cab):
        raise OSError("coletor fora do ar")
    st = ob.exportar_otlp(s, pasta, endpoint="https://otlp.exemplo:4318", enviar=falha)
    assert st["ok"] is False and s.get("otlp_cursor") is None          # nada se perde

    def ok(url, corpo, cab):
        enviados.append((url, json.loads(corpo), cab))
        return 200
    st = ob.exportar_otlp(s, pasta, endpoint="https://otlp.exemplo:4318", cabecalhos="Authorization=Basic%20abc,x-org=1", enviar=ok)
    assert st["ok"] and st["enviados"] == 2
    url, corpo, cab = enviados[0]
    assert url == "https://otlp.exemplo:4318/v1/traces" and cab == {"Authorization": "Basic abc", "x-org": "1"}
    assert len(corpo["resourceSpans"][0]["scopeSpans"][0]["spans"]) == 2
    assert ob.exportar_otlp(s, pasta, endpoint="https://otlp.exemplo:4318", enviar=ok)["enviados"] == 0   # nada repetido
    gravar(pasta / "telemetria", [{**span, "span_id": "d" * 16}])
    assert ob.exportar_otlp(s, pasta, endpoint="https://otlp.exemplo:4318", enviar=ok)["enviados"] == 1
    assert s.get("otlp_estado")["enviados_total"] == 3
    assert ob.exportar_otlp(s, pasta) is None                          # sem endpoint configurado: desligado


def test_painel_expoe_metrics_observabilidade_e_rastros(circle, painel):  # noqa: F811
    circle.tick()
    with urllib.request.urlopen(painel + "/metrics", timeout=5) as r:
        assert r.headers["Content-Type"].startswith("text/plain; version=0.0.4")
        assert b"circulo_giros_total" in r.read()
    with urllib.request.urlopen(painel + "/api/observabilidade", timeout=5) as r:
        d = json.loads(r.read())
    assert {"sinais", "slos", "red", "rastros", "completude", "exportacao"} <= set(d)
    with urllib.request.urlopen(painel + "/rastros", timeout=5) as r:
        assert "Seguir o fio" in r.read().decode()
    try:
        urllib.request.urlopen(painel + "/api/rastro?q=item%209999", timeout=5)
        raise AssertionError("deveria ser 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_central_de_confianca_mostra_slos(circle):
    from circulo.confianca import confianca
    _base(circle.store, n=100, erros=5)
    c = {x["id"]: x for x in confianca(circle.store)["checks"]}
    assert c["slos"]["estado"] == "atencao" and "giros sem erro" in c["slos"]["porque"]


def test_limite_da_conta_nao_conta_como_erro_de_llm(circle):
    from circulo.registro import registrar
    s = circle.store
    registrar(s, tick=1, project_id=None, papel="developer", modelo="x", ok=False, erro="You've hit your session limit · resets 4am")
    registrar(s, tick=1, project_id=None, papel="planejador", modelo="x", ok=False, erro="resposta sem JSON válido")
    for _ in range(8):
        registrar(s, tick=1, project_id=None, papel="planejador", modelo="x", ok=True)
    llm = {x["id"]: x for x in ob.slos(s)}["llm_ok"]
    assert llm["n"] == 9 and llm["ruins"] == 1

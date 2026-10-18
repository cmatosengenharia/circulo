"""/metrics do loop via prometheus_client: registry isolado por teste, servidor desligado por padrão.

Regressão: antes não existia telemetria do loop no padrão do prometheus_client (decisões do Jev, PRs por estado,
duração das etapas, último ciclo); o Grafana não tinha o que raspar além do texto montado à mão no painel.
"""
import json
import socket
import statistics
import time
import urllib.request
from pathlib import Path

import pytest

from circulo import metrics
from circulo.decision import Decision, LocalJev, Question
from circulo.loop import Circle
from circulo.metrics import Metricas

# prometheus_client é opcional (circulo[metricas]): sem ele, só rodam os testes do no-op, da porta e do dashboard
com_prometheus = pytest.mark.skipif(not metrics.DISPONIVEL, reason="prometheus_client não instalado")

SERIES = ("circulo_loop_decisoes_jev_total", "circulo_loop_prs_total",
          "circulo_loop_etapa_duracao_seconds_bucket", "circulo_loop_ultimo_ciclo_timestamp_seconds")


@pytest.fixture
def m():
    from prometheus_client import CollectorRegistry
    return Metricas(CollectorRegistry())        # isolado: nada vaza para o registry global nem entre testes


@pytest.fixture
def loop(tmp_path, clock, m):
    return Circle(tmp_path, jev=LocalJev(), now=clock, metricas=m)


def _pr(s, n, status):
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
        (n, None, f"pr {n}", f"b{n}", status, time.time(), time.time()))


def _porta_livre() -> int:
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]


@com_prometheus
def test_metrics_responde_200_com_as_series_do_loop_em_ate_1s(loop, m):
    _pr(loop.store, 1, "aberto")
    _pr(loop.store, 2, "mergeado")
    _pr(loop.store, 3, "fechado")
    loop.tick()
    loop.tick()
    porta = _porta_livre()
    srv = m.servir(porta)
    try:
        t0 = time.perf_counter()
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/metrics", timeout=1) as r:
            status, txt = r.status, r.read().decode()
        assert time.perf_counter() - t0 <= 1.0
    finally:
        if isinstance(srv, tuple):              # prometheus_client recente devolve (servidor, thread)
            srv[0].shutdown()
    assert status == 200
    linhas = [x for x in txt.splitlines() if x and not x.startswith("#")]
    achadas = [any(x.startswith(nome) for x in linhas) for nome in SERIES]
    for nome, ok in zip(SERIES, achadas, strict=True):
        assert ok, f"série {nome} ausente no /metrics"
    assert 'circulo_loop_prs_total{estado="aberto"} 3.0' in txt       # todo PR registrado foi aberto
    assert 'circulo_loop_prs_total{estado="mergeado"} 1.0' in txt
    assert 'circulo_loop_prs_total{estado="falhou"} 1.0' in txt
    assert 'circulo_loop_etapa_duracao_seconds_count{etapa="orquestrador"} 2.0' in txt


class _Jev:
    source = "jev"

    def __init__(self, confianca=None):
        self.confianca = confianca

    def ask_many(self, state, questions):
        if self.confianca is None:
            raise OSError("Jev fora do ar")
        return {k: Decision(k, "noul", 0.9, self.confianca, "jev") for k in questions}, 1000


@com_prometheus
@pytest.mark.parametrize("jev,fonte,resultado", [(_Jev(0.8), "jev", "confiante"), (_Jev(0.05), "local", "incerto"),
                                                 (_Jev(None), "local", "indisponivel")])
def test_decisoes_do_jev_contadas_por_fonte_e_resultado(tmp_path, clock, m, jev, fonte, resultado):
    c = Circle(tmp_path, jev=jev, now=clock, metricas=m)
    rotulos = {"fonte": fonte, "resultado": resultado}
    antes = m.registry.get_sample_value("circulo_loop_decisoes_jev_total", rotulos) or 0
    c.ctx.dl.ask("teste_metrica", Question("noul", "Vale?"), {"x": 1})
    assert m.registry.get_sample_value("circulo_loop_decisoes_jev_total", rotulos) == antes + 1


@com_prometheus
def test_duracao_das_etapas_sem_contar_o_descanso(m):
    for nome, t in (("orquestrador", 0.0), ("pedido", 0.5), ("descanso", 2.0), ("orquestrador", 300.0)):
        m.etapa(nome, agora=t)
    assert m.registry.get_sample_value("circulo_loop_etapa_duracao_seconds_sum", {"etapa": "orquestrador"}) == 0.5
    assert m.registry.get_sample_value("circulo_loop_etapa_duracao_seconds_sum", {"etapa": "pedido"}) == 1.5
    assert m.registry.get_sample_value("circulo_loop_etapa_duracao_seconds_count", {"etapa": "descanso"}) is None


@com_prometheus
def test_prs_so_sobem_e_contam_o_delta(loop, m):
    s = loop.store
    _pr(s, 10, "aberto")
    m.ciclo_concluido(s, em=123.0)
    s.x("UPDATE prs SET status='mergeado' WHERE number=10")
    _pr(s, 11, "aberto")
    m.ciclo_concluido(s, em=456.0)
    v = lambda e: m.registry.get_sample_value("circulo_loop_prs_total", {"estado": e})  # noqa: E731
    assert (v("aberto"), v("mergeado"), v("falhou")) == (2.0, 1.0, 0.0)
    s.x("DELETE FROM prs")                       # banco restaurado para trás: counter não desce
    m.ciclo_concluido(s)
    assert v("aberto") == 2.0
    assert m.registry.get_sample_value("circulo_loop_ultimo_ciclo_timestamp_seconds") > 456.0


@com_prometheus
def test_registry_isolado(loop):
    from prometheus_client import REGISTRY
    loop.tick()
    assert REGISTRY.get_sample_value("circulo_loop_ultimo_ciclo_timestamp_seconds") is None


def test_servidor_desligado_por_padrao(monkeypatch):
    monkeypatch.delenv("CIRCULO_METRICS_PORT", raising=False)
    assert metrics.porta_configurada(None) is None
    monkeypatch.setenv("CIRCULO_METRICS_PORT", "9464")
    assert metrics.porta_configurada(None) == 9464
    assert metrics.porta_configurada(9500) == 9500   # a flag vence o ambiente


@com_prometheus
def test_medir_custa_menos_de_1_por_cento_do_ciclo(loop, m):
    loop.tick()
    ciclos, medicao = [], []
    for _ in range(5):
        t0 = time.perf_counter()
        loop.tick()
        ciclos.append(time.perf_counter() - t0)
    etapas = loop.store.one("SELECT COUNT(DISTINCT etapa) n FROM trail")["n"] or 10
    for _ in range(5):
        t0 = time.perf_counter()
        for i in range(etapas):                  # o que o loop chama por ciclo: uma marca por etapa,
            m.etapa(f"e{i % 8}")
        m.decisao("jev", "confiante")            # algumas decisões
        m.ciclo_concluido(loop.store)            # e a sincronização dos PRs
        medicao.append(time.perf_counter() - t0)
    assert statistics.median(medicao) < 0.01 * statistics.median(ciclos)


def test_sem_prometheus_client_tudo_vira_no_op_e_o_loop_segue(tmp_path, clock, monkeypatch):
    monkeypatch.setattr(metrics, "DISPONIVEL", False)
    m = Metricas()
    assert not m.ativo and m.registry is None
    c = Circle(tmp_path, jev=LocalJev(), now=clock, metricas=m)
    c.tick()
    m.decisao("jev", "confiante")
    m.etapa("orquestrador")
    m.ciclo_concluido(c.store)
    with pytest.raises(RuntimeError, match="prometheus_client"):
        m.servir(_porta_livre())


def test_dashboard_grafana_versionado_usa_as_series_do_loop():
    painel = json.loads((Path(__file__).parent.parent / "ops" / "grafana" / "circulo-loop.json").read_text(encoding="utf-8"))
    exprs = " ".join(t["expr"] for p in painel["panels"] for t in p["targets"])
    for nome in SERIES:
        assert nome in exprs

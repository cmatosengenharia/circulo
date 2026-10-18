"""Métricas do loop no padrão Prometheus, via prometheus_client, num registry próprio (não no global do processo).

O que mede (o Grafana só exibe; a telemetria nasce aqui):
- decisões do Jev por fonte e resultado (confiante, incerto → regra, aprendido, indisponível → regra);
- PRs por estado (aberto, mergeado, falhou), sincronizados da tabela `prs` a cada ciclo: quem muda o estado é a
  constituição (merge_gate/self_dev), que não é tocada; aqui só se conta;
- duração de cada etapa do ciclo (Histogram: p50/p95/p99 no Grafana com histogram_quantile);
- timestamp do último ciclo concluído (alerta de loop parado: time() - isso > N).

Servidor desligado por padrão: `circulo run --metricas-porta 9464` ou CIRCULO_METRICS_PORT=9464.
Sem o pacote instalado (`pip install circulo[metricas]`), tudo vira no-op e o loop segue igual.
Medir nunca derruba um giro.
"""
from __future__ import annotations

import os
import time

try:
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server
    DISPONIVEL = True
except ImportError:  # dependência opcional: o loop não depende dela
    DISPONIVEL = False

# etapas pesadas (Developer, estudo) passam de minutos; os buckets padrão param em 10 s
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1800)
ESTADOS_PR = {"aberto": "SELECT COUNT(*) n FROM prs",                       # todo PR registrado foi aberto um dia
              "mergeado": "SELECT COUNT(*) n FROM prs WHERE status='mergeado'",
              "falhou": "SELECT COUNT(*) n FROM prs WHERE status='fechado'"}   # fechado sem merge
SEM_DURACAO = ("descanso", "pausado")   # o intervalo depois delas é espera entre giros, não trabalho


class Metricas:
    def __init__(self, registry=None):
        self.ativo = DISPONIVEL
        self._prs_vistos: dict[str, int] = {}
        self._etapa: tuple[str, float] | None = None
        if not self.ativo:
            self.registry = None
            return
        self.registry = registry if registry is not None else CollectorRegistry()
        r = self.registry
        self.decisoes = Counter("circulo_loop_decisoes_jev", "Decisões da camada do Jev por fonte e resultado.",
                                ("fonte", "resultado"), registry=r)
        self.prs = Counter("circulo_loop_prs", "PRs do Developer por estado.", ("estado",), registry=r)
        self.etapa_duracao = Histogram("circulo_loop_etapa_duracao_seconds", "Duração de cada etapa do ciclo.",
                                       ("etapa",), buckets=BUCKETS, registry=r)
        self.ultimo_ciclo = Gauge("circulo_loop_ultimo_ciclo_timestamp_seconds", "Quando o último ciclo terminou.",
                                  registry=r)
        for estado in ESTADOS_PR:          # as três séries existem desde o início, mesmo zeradas
            self.prs.labels(estado)

    def decisao(self, fonte: str, resultado: str) -> None:
        if self.ativo:
            self.decisoes.labels(fonte, resultado).inc()

    def etapa(self, nome: str, agora: float | None = None) -> None:
        """Marca o início de uma etapa; a anterior termina aqui e entra no histograma."""
        if not self.ativo:
            return
        agora = time.perf_counter() if agora is None else agora
        if self._etapa is not None and self._etapa[0] not in SEM_DURACAO:
            self.etapa_duracao.labels(self._etapa[0]).observe(max(0.0, agora - self._etapa[1]))
        self._etapa = (nome, agora)

    def ciclo_concluido(self, store, em: float | None = None) -> None:
        if not self.ativo:
            return
        self.ultimo_ciclo.set(time.time() if em is None else em)
        for estado, sql in ESTADOS_PR.items():
            n = store.one(sql)["n"] or 0
            visto = self._prs_vistos.get(estado, 0)
            if n > visto:                  # counter só sobe; se o banco foi restaurado para trás, espera alcançar
                self.prs.labels(estado).inc(n - visto)
                self._prs_vistos[estado] = n

    def servir(self, porta: int, endereco: str = "127.0.0.1"):
        if not self.ativo:
            raise RuntimeError("prometheus_client não instalado: pip install 'circulo[metricas]'")
        return start_http_server(porta, addr=endereco, registry=self.registry)


METRICAS = Metricas()


def porta_configurada(flag: int | None = None) -> int | None:
    """Porta do /metrics: a flag vence o ambiente; nenhuma das duas = desligado."""
    if flag:
        return flag
    v = os.environ.get("CIRCULO_METRICS_PORT", "").strip()
    return int(v) if v.isdigit() and int(v) > 0 else None


def seguro(fn, *args, **kw) -> None:
    try:
        fn(*args, **kw)
    except Exception:  # noqa: BLE001 — medir nunca derruba o giro
        pass

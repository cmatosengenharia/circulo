"""Observabilidade do loop: sinais de ouro, SLOs com orçamento de erro, métricas no padrão Prometheus e exportação OTLP.

Baseado no que é consolidado no mercado:
- Google SRE (sinais de ouro): tráfego, latência, erros e saturação; SLO com orçamento de erro (quanto ainda dá
  para errar na janela antes de violar o objetivo);
- RED por operação (taxa, erros, duração) para cada ponto de verificação e cada papel de LLM;
- Prometheus (formato de exposição em texto, `/metrics`): o que o Grafana e quase toda ferramenta de monitoramento lê;
- OpenTelemetry OTLP/HTTP (JSON): os traços dos giros (telemetria/spans.jsonl) vão para qualquer coletor (Grafana
  Tempo, Jaeger, Honeycomb, Datadog, Langfuse…) quando OTEL_EXPORTER_OTLP_ENDPOINT estiver configurado.

Os alvos dos SLOs foram calibrados nos dados reais do loop (24 h com ~2 mil giros: p95 do giro leve ~0,5 s,
0,2% de giros com erro, ~90% das chamadas de LLM sem falha) com folga, para alertar desvio e não ruído.
Só leitura do banco; a exportação roda em segundo plano e nunca segura nem derruba um giro.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__
from .state import Store

PESADAS = ("corrigir_codigo", "atualizar_corpo", "planejar_roteiro", "estudar_pedido", "evoluir_projeto")
HORA, DIA = 3600, 86400

# id, nome, alvo, janela (s), como medir
SLOS = (
    ("giros_ok", "Giros sem erro", 0.99, DIA, "fração dos giros sem nenhum erro"),
    ("latencia_giro", "Giro leve no tempo", 0.95, DIA, "giros sem tarefa pesada: ≤ 3 s (≤ 15 s quando falam com o GitHub)"),
    ("llm_ok", "Chamadas de LLM sem falha", 0.90, 7 * DIA, "inclui o Claude Code; limite de uso e rede fora do ar contam como saturação, não como erro"),
    ("painel_frescor", "Painel em tempo real (≤ 3 s)", 0.99, DIA, "atraso entre o dado e a tela medido pelo próprio painel"),
    ("rastreabilidade", "Entregas com o fio completo", 0.95, 30 * DIA, "do pedido/pergunta/lição até a evidência no código rodando"),
)
LIMITE_GIRO_LEVE_MS = 3000          # local: o máximo observado em 2 dias foi 1,9 s
LIMITE_POR_TAREFA_MS = {"revisar_prs": 15_000}   # fala com a API do GitHub: p50 2,7 s, máx. 8,3 s observados
LIMITE_FRESCOR_MS = 3000


def _pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    i = int(k)
    return xs[i] if i + 1 >= len(xs) else xs[i] + (xs[i + 1] - xs[i]) * (k - i)


def _giros(store: Store, ini: float) -> list[dict]:
    out = []
    for r in store.q("SELECT tick, body, created_at FROM metrics WHERE created_at>=? ORDER BY tick", (ini,)):
        try:
            b = json.loads(r["body"])
        except ValueError:
            continue
        out.append({"tick": r["tick"], "em": r["created_at"], "ms": b.get("duracao_ms"), "erros": len(b.get("errors") or []),
                    "tarefa": b.get("idle"), "run_id": b.get("run_id"), "budget": b.get("budget") or {}})
    return out


# ------------------------------------------------------------------ sinais de ouro
def sinais(store: Store, janela_s: int = DIA, now: float | None = None) -> dict:
    now = now or time.time()
    ini = now - janela_s
    g = _giros(store, ini)
    ms = [x["ms"] for x in g if x["ms"] is not None]
    leves = [x["ms"] for x in g if x["ms"] is not None and x["tarefa"] not in PESADAS]
    com_erro = [x for x in g if x["erros"]]
    llm = store.one("SELECT COUNT(*) n, SUM(ok=0) f, SUM(tokens) t FROM llm_calls WHERE created_at>=?", (ini,))
    ver = store.one("SELECT COUNT(*) n, SUM(ok=0) f FROM verificacoes WHERE created_at>=?", (ini,))
    gate = store.one("SELECT COUNT(*) n, SUM(merged=0) f FROM merges WHERE created_at>=?", (ini,))
    ult = g[-1]["budget"] if g else {}
    limite = ult.get("limite") or 0
    fila = store.one("SELECT COUNT(*) n FROM events WHERE status IN ('pending','processing')")["n"]
    roteiro = store.one("SELECT COUNT(*) n FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0")["n"]
    horas = max(janela_s / HORA, 1e-9)
    return {
        "janela_s": janela_s,
        "trafego": {"giros": len(g), "giros_por_hora": round(len(g) / horas, 1),
                    "pesados": sum(x["tarefa"] in PESADAS for x in g),
                    "chamadas_llm": llm["n"] or 0, "verificacoes": ver["n"] or 0},
        "latencia": {"p50_ms": _r(_pct(ms, .5)), "p95_ms": _r(_pct(ms, .95)), "p99_ms": _r(_pct(ms, .99)),
                     "leve_p95_ms": _r(_pct(leves, .95)), "max_ms": max(ms) if ms else None},
        "erros": {"giros_com_erro": len(com_erro), "taxa_giros": round(len(com_erro) / len(g), 4) if g else None,
                  "llm_falhas": llm["f"] or 0, "verificacoes_reprovadas": ver["f"] or 0, "gate_recusas": gate["f"] or 0,
                  "ultimo": max((x["em"] for x in com_erro), default=None)},
        "saturacao": {"orcamento_usado": round((ult.get("tokens") or 0) / limite, 3) if limite else None,
                      "tokens_hoje": ult.get("tokens"), "limite": limite or None, "fila_pedidos": fila, "roteiro_pendente": roteiro,
                      "tokens_llm_janela": llm["t"] or 0},
    }


def _r(x):
    return None if x is None else round(x)


# ------------------------------------------------------------------ RED por operação
def red(store: Store, janela_s: int = DIA, now: float | None = None, limite: int = 20) -> dict:
    now = now or time.time()
    ini = now - janela_s
    pontos = [{"operacao": r["ponto"], "n": r["n"], "falhas": r["f"] or 0, "taxa_erro": round((r["f"] or 0) / r["n"], 3)}
              for r in store.q("SELECT ponto, COUNT(*) n, SUM(ok=0) f FROM verificacoes WHERE created_at>=? GROUP BY ponto "
                               "ORDER BY SUM(ok=0) DESC, COUNT(*) DESC LIMIT ?", (ini, limite))]
    papeis = []
    for r in store.q("SELECT papel, COUNT(*) n, SUM(ok=0) f, SUM(tokens) t FROM llm_calls WHERE created_at>=? GROUP BY papel "
                     "ORDER BY COUNT(*) DESC", (ini,)):
        dur = [x["duracao_ms"] for x in store.q("SELECT duracao_ms FROM llm_calls WHERE created_at>=? AND papel=? AND duracao_ms IS NOT NULL",
                                                (ini, r["papel"]))]
        papeis.append({"operacao": r["papel"], "n": r["n"], "falhas": r["f"] or 0, "taxa_erro": round((r["f"] or 0) / r["n"], 3),
                       "p50_ms": _r(_pct(dur, .5)), "p95_ms": _r(_pct(dur, .95)), "tokens": r["t"] or 0})
    return {"verificacoes": pontos, "llm": papeis}


# ------------------------------------------------------------------ SLOs com orçamento de erro
def _slo(id_, nome, alvo, janela, como, bons, n) -> dict:
    ruins = n - bons
    permitido = (1 - alvo) * n
    atual = bons / n if n else None
    restante = None if not n else (1 - ruins / permitido if permitido > 0 else (1.0 if ruins == 0 else -1.0))
    estado = "sem_dados" if not n else "ok" if atual >= alvo else "violado"
    if estado == "ok" and restante is not None and restante < 0.25:
        estado = "em_risco"
    return {"id": id_, "nome": nome, "alvo": alvo, "janela_s": janela, "como": como, "n": n, "ruins": ruins,
            "atual": None if atual is None else round(atual, 4), "orcamento_restante": None if restante is None else round(restante, 3),
            "estado": estado}


def slos(store: Store, now: float | None = None) -> list[dict]:
    now = now or time.time()
    out = []
    for id_, nome, alvo, janela, como in SLOS:
        ini = now - janela
        if id_ == "giros_ok":
            g = _giros(store, ini)
            n, bons = len(g), sum(1 for x in g if not x["erros"])
        elif id_ == "latencia_giro":
            g = [x for x in _giros(store, ini) if x["ms"] is not None and x["tarefa"] not in PESADAS]
            n, bons = len(g), sum(1 for x in g if x["ms"] <= LIMITE_POR_TAREFA_MS.get(x["tarefa"], LIMITE_GIRO_LEVE_MS))
        elif id_ == "llm_ok":
            from .licoes import AMBIENTE
            rows = store.q("SELECT ok, erro FROM llm_calls WHERE created_at>=?", (ini,))
            validas = [r for r in rows if r["ok"] or not AMBIENTE.search(r["erro"] or "")]
            n, bons = len(validas), sum(1 for r in validas if r["ok"])
        elif id_ == "painel_frescor":
            r = store.one("SELECT COUNT(*) n, SUM(atraso_ms<=?) b FROM frescor WHERE em>=?", (LIMITE_FRESCOR_MS, ini))
            n, bons = r["n"] or 0, r["b"] or 0
        else:
            from .rastro import completude
            c = completude(store, janela // DIA, now)
            n, bons = c["total"], c["completos"]
        out.append(_slo(id_, nome, alvo, janela, como, bons, n))
    return out


def visao(store: Store, now: float | None = None) -> dict:
    """Tudo o que a tela de observabilidade mostra numa chamada só."""
    now = now or time.time()
    from . import rastro
    return {"gerado_em": now, "versao": __version__, "sinais": sinais(store, DIA, now), "sinais_1h": sinais(store, HORA, now),
            "slos": slos(store, now), "red": red(store, DIA, now), "rastros": rastro.recentes(store, now=now),
            "completude": rastro.completude(store, now=now), "exportacao": estado_exportacao(store)}


# ------------------------------------------------------------------ Prometheus /metrics
def _esc(v) -> str:
    return str(v).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def prometheus(store: Store, now: float | None = None) -> str:
    """Formato de exposição em texto do Prometheus (0.0.4): o Grafana (ou o Grafana Alloy/Agent) raspa daqui."""
    now = now or time.time()
    linhas: list[str] = []

    def m(nome, tipo, ajuda, amostras):
        linhas.append(f"# HELP {nome} {ajuda}")
        linhas.append(f"# TYPE {nome} {tipo}")
        for rotulos, valor in amostras:
            if valor is None:
                continue
            lab = ",".join(f'{k}="{_esc(v)}"' for k, v in rotulos.items())
            linhas.append(f"{nome}{{{lab}}} {valor}" if lab else f"{nome} {valor}")

    m("circulo_info", "gauge", "Versão do loop rodando.", [({"versao": __version__}, 1)])
    tot = store.one("SELECT COUNT(*) n, MAX(tick) t FROM metrics")
    m("circulo_giros_total", "counter", "Giros registrados.", [({}, tot["n"])])
    m("circulo_giro_atual", "gauge", "Número do último giro.", [({}, tot["t"] or 0)])
    g = _giros(store, now - DIA)
    ms = [x["ms"] / 1000 for x in g if x["ms"] is not None]
    m("circulo_giro_duracao_segundos_24h", "gauge", "Quantis da duração dos giros nas últimas 24 h.",
      [({"quantile": q}, None if _pct(ms, q) is None else round(_pct(ms, q), 3)) for q in (0.5, 0.95, 0.99)])
    m("circulo_giros_com_erro_24h", "gauge", "Giros com erro nas últimas 24 h.", [({}, sum(1 for x in g if x["erros"]))])
    m("circulo_erros_total", "counter", "Erros registrados nos giros.", [({}, store.one("SELECT COUNT(*) n FROM run_errors")["n"])])
    m("circulo_llm_chamadas_total", "counter", "Chamadas de LLM por papel e resultado.",
      [({"papel": r["papel"], "ok": "true" if r["ok"] else "false"}, r["n"])
       for r in store.q("SELECT papel, ok, COUNT(*) n FROM llm_calls GROUP BY papel, ok")])
    m("circulo_llm_tokens_total", "counter", "Tokens de LLM por papel.",
      [({"papel": r["papel"]}, r["t"] or 0) for r in store.q("SELECT papel, SUM(tokens) t FROM llm_calls GROUP BY papel")])
    m("circulo_decisoes_total", "counter", "Decisões por quem decidiu (jev, local, llm).",
      [({"fonte": r["source"]}, r["n"]) for r in store.q("SELECT source, COUNT(*) n FROM decisions GROUP BY source")])
    m("circulo_verificacoes_24h", "gauge", "Verificações nas últimas 24 h por ponto e resultado.",
      [({"ponto": r["ponto"], "ok": "true" if r["ok"] else "false"}, r["n"])
       for r in store.q("SELECT ponto, ok, COUNT(*) n FROM verificacoes WHERE created_at>=? GROUP BY ponto, ok", (now - DIA,))])
    m("circulo_merges_total", "counter", "Decisões do gate de merge.",
      [({"resultado": "mergeado" if r["merged"] else "recusado"}, r["n"]) for r in store.q("SELECT merged, COUNT(*) n FROM merges GROUP BY merged")])
    m("circulo_licoes", "gauge", "Lições por estado.",
      [({"status": r["status"], "classe": r["classe"]}, r["n"]) for r in store.q("SELECT status, classe, COUNT(*) n FROM licoes GROUP BY status, classe")])
    m("circulo_roteiro_itens", "gauge", "Itens do roteiro por estado.",
      [({"status": r["status"]}, r["n"]) for r in store.q("SELECT status, COUNT(*) n FROM roadmap GROUP BY status")])
    s = sinais(store, DIA, now)["saturacao"]
    m("circulo_orcamento_uso_ratio", "gauge", "Fração do limite diário de tokens da API já usada.", [({}, s["orcamento_usado"])])
    m("circulo_fila_pedidos", "gauge", "Pedidos esperando na fila.", [({}, s["fila_pedidos"])])
    for x in slos(store, now):
        m("circulo_slo_atual_ratio", "gauge", "Valor atual do SLO na janela.", [({"slo": x["id"]}, x["atual"])])
        m("circulo_slo_alvo_ratio", "gauge", "Alvo do SLO.", [({"slo": x["id"]}, x["alvo"])])
        m("circulo_slo_orcamento_restante_ratio", "gauge", "Orçamento de erro restante do SLO (1 = intacto, < 0 = violado).",
          [({"slo": x["id"]}, x["orcamento_restante"])])
    from .jev_lab import VARIANTES, placar
    for qid in VARIANTES:
        p = placar(store, qid)
        if p["n"]:
            m("circulo_jev_lab_confianca_ratio", "gauge", "Confiança média do Jev por forma de perguntar (laboratório).",
              [({"pergunta": qid, "forma": "atual"}, p["conf_pt"]), ({"pergunta": qid, "forma": "variante_en"}, p["conf_en"])])
    b = store.get("batimento") or {}
    m("circulo_batimento_timestamp_segundos", "gauge", "Último batimento do processo do loop.", [({}, b.get("em"))])
    # cada métrica com HELP/TYPE uma vez só (o formato exige)
    vistos, saida = set(), []
    for linha in linhas:
        if linha.startswith("# "):
            chave = linha.split(" ", 3)[:3]
            if tuple(chave) in vistos:
                continue
            vistos.add(tuple(chave))
        saida.append(linha)
    return "\n".join(saida) + "\n"


# ------------------------------------------------------------------ exportação OTLP/HTTP (JSON)
KIND = {"INTERNAL": 1, "SERVER": 2, "CLIENT": 3, "PRODUCER": 4, "CONSUMER": 5}
STATUS = {"UNSET": 0, "OK": 1, "ERROR": 2}
LOTE_BYTES = 1024 * 1024
_lock = threading.Lock()


def _valor(v) -> dict:
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [_valor(x) for x in v]}}
    if v is None:
        return {"stringValue": ""}
    return {"stringValue": str(v)}


def _attrs(d: dict | None) -> list[dict]:
    return [{"key": k, "value": _valor(v)} for k, v in (d or {}).items()]


def span_otlp(s: dict) -> dict:
    """Um span da telemetria (dicionário OTLP-like) → span OTLP/JSON oficial (ids em hex, enums numéricos)."""
    out = {"traceId": s["trace_id"], "spanId": s["span_id"], "name": s["name"], "kind": KIND.get(s.get("kind", "INTERNAL"), 1),
           "startTimeUnixNano": str(s["start_time_unix_nano"]), "endTimeUnixNano": str(s["end_time_unix_nano"]),
           "attributes": _attrs(s.get("attributes")),
           "status": {"code": STATUS.get((s.get("status") or {}).get("code", "UNSET"), 0),
                      "message": (s.get("status") or {}).get("message", "")}}
    if s.get("parent_span_id"):
        out["parentSpanId"] = s["parent_span_id"]
    if s.get("events"):
        out["events"] = [{"name": e["name"], "timeUnixNano": str(e["time_unix_nano"]), "attributes": _attrs(e.get("attributes"))}
                         for e in s["events"]]
    if s.get("links"):
        out["links"] = [{"traceId": ln["trace_id"], "spanId": ln["span_id"], "attributes": _attrs(ln.get("attributes"))}
                        for ln in s["links"]]
    return out


def lote_otlp(spans: list[dict]) -> dict:
    return {"resourceSpans": [{
        "resource": {"attributes": _attrs({"service.name": "circulo", "service.version": __version__,
                                           "telemetry.sdk.language": "python", "telemetry.sdk.name": "circulo"})},
        "scopeSpans": [{"scope": {"name": "circulo.telemetria", "version": __version__}, "spans": [span_otlp(s) for s in spans]}]}]}


def _cabecalhos(texto: str | None) -> dict:
    """OTEL_EXPORTER_OTLP_HEADERS: 'k1=v1,k2=v2' com valores codificados em URL (especificação do OpenTelemetry)."""
    out = {}
    for par in (texto or "").split(","):
        if "=" in par:
            k, v = par.split("=", 1)
            out[k.strip()] = urllib.parse.unquote(v.strip())
    return out


def _url(endpoint: str) -> str:
    e = endpoint.rstrip("/")
    return e if e.endswith("/v1/traces") else e + "/v1/traces"


def _enviar_http(url: str, corpo: bytes, cabecalhos: dict) -> int:
    req = urllib.request.Request(url, data=corpo, method="POST",
                                 headers={"Content-Type": "application/json", **cabecalhos})
    with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 — URL configurada por você
        return r.status


def exportar_otlp(store: Store, pasta: str | Path, endpoint: str | None = None, cabecalhos: str | None = None,
                  enviar=None) -> dict | None:
    """Envia ao coletor os spans novos de telemetria/spans.jsonl (do cursor salvo em diante). Sem endpoint: nada.
    Falha de rede não perde nada: o cursor só anda depois do 2xx, e o próximo giro tenta de novo."""
    endpoint = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None
    if not _lock.acquire(blocking=False):
        return {"ok": None, "motivo": "envio anterior ainda em curso"}
    try:
        arq = Path(pasta) / "telemetria" / "spans.jsonl"
        if not arq.exists():
            return {"ok": True, "enviados": 0}
        cur = store.get("otlp_cursor") or {"pos": 0}
        tam = arq.stat().st_size
        pos = int(cur.get("pos", 0)) if int(cur.get("pos", 0)) <= tam else 0      # arquivo recriado: recomeça
        with arq.open("rb") as f:
            f.seek(pos)
            bruto = f.read(LOTE_BYTES)
        corte = bruto.rfind(b"\n")
        if corte < 0:
            return {"ok": True, "enviados": 0}
        bruto = bruto[:corte + 1]
        spans = []
        for linha in bruto.decode("utf-8", "replace").splitlines():
            try:
                spans.append(json.loads(linha))
            except ValueError:
                continue
        envio = enviar or _enviar_http
        try:
            status = envio(_url(endpoint), json.dumps(lote_otlp(spans), ensure_ascii=False).encode(),
                           _cabecalhos(cabecalhos if cabecalhos is not None else
                                       os.environ.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS") or os.environ.get("OTEL_EXPORTER_OTLP_HEADERS")))
        except Exception as exc:  # noqa: BLE001
            st = {"ok": False, "erro": str(exc)[:300], "em": time.time(), "destino": urllib.parse.urlsplit(endpoint).netloc,
                  "enviados_total": int((store.get("otlp_estado") or {}).get("enviados_total", 0))}
            store.set("otlp_estado", st)
            return st
        ok = 200 <= int(status) < 300
        anterior = store.get("otlp_estado") or {}
        st = {"ok": ok, "status": int(status), "em": time.time(), "destino": urllib.parse.urlsplit(endpoint).netloc,
              "enviados": len(spans) if ok else 0,
              "enviados_total": int(anterior.get("enviados_total", 0)) + (len(spans) if ok else 0)}
        if ok:
            store.set("otlp_cursor", {"pos": pos + len(bruto), "em": time.time()})
        else:
            st["erro"] = f"o coletor respondeu {status}"
        store.set("otlp_estado", st)
        return st
    finally:
        _lock.release()


def exportar_em_segundo_plano(store_path: str, pasta: str | Path) -> None:
    """Chamado no fim do giro: a rede nunca segura o loop."""
    if store_path == ":memory:" or not (os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")):
        return

    def _rodar():
        try:
            exportar_otlp(Store(store_path), pasta)
        except Exception:  # noqa: BLE001
            pass
    threading.Thread(target=_rodar, name="otlp", daemon=True).start()


def estado_exportacao(store: Store) -> dict:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    st = store.get("otlp_estado") or {}
    return {"otlp_configurado": bool(endpoint), "destino": urllib.parse.urlsplit(endpoint).netloc if endpoint else None,
            "ultimo": st, "prometheus": "/metrics", "trilha": "/telemetria"}

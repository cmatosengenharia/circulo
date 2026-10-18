"""Trilha de eventos tipados do loop, no vocabulário OpenTelemetry GenAI, e o painel de timeline + grafo.

A cada giro, `registrar_ciclo` monta a árvore de spans do giro a partir do que ele mesmo deixou no banco
(trilha de etapas, intenções write-ahead, decisões, chamadas de LLM, verificações, PRs, merges e erros) e a grava
em `telemetria/spans.jsonl`, só de acréscimo. Depois gera `telemetria/index.html`, estático, renderizado só desse log.

- `invoke_workflow`: o giro (raiz do traço; trace_id derivado do run_id);
- `invoke_agent`: cada etapa/agente que trabalhou no giro (orquestrador, developer, merge gate, saúde…);
- `execute_tool`: git/pytest/ruff/PR/merge/CI, a partir das verificações e das tabelas de PR;
- `chat`: cada chamada de LLM (modelo e tokens; o conteúdo do prompt só entra com CIRCULO_TELEMETRIA_CONTEUDO=1);
- `jev_decision`: o que foi decidido, o motivo e quem decidiu (regra, jev, local ou llm).

O formato de cada linha é o de um span OTLP/JSON (trace_id, span_id, parent_span_id, name, start/end em ns, status,
attributes, events), então exportar para um coletor OTLP ou para o Langfuse é só reenviar as linhas.
A telemetria nunca derruba o loop: tudo aqui roda dentro de try/except e a falha só vira um contador.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
from collections import Counter, defaultdict
from itertools import pairwise
from pathlib import Path

from . import __version__

ARQUIVO = "spans.jsonl"
PAGINA = "index.html"
CICLOS_NO_PAINEL = 200            # o painel lê só o fim do log: abre rápido mesmo com meses de histórico
BYTES_LIDOS = 4 * 1024 * 1024
SEM_AGENTE = ("descanso", "pausado")
# ponto de verificação → ferramenta executada
FERRAMENTAS = {"developer:lint": "ruff", "developer:testes": "pytest", "developer:abrir_pr": "github_pr",
               "gate:ci": "github_ci", "gate:main": "github_ci", "gate:merge": "github_merge",
               "developer:agente": "claude_code", "corpo:atualizar": "git"}


def _ns(t: float) -> int:
    return int(float(t) * 1e9)


def _id(*partes, n: int = 16) -> str:
    return hashlib.sha256("|".join(map(str, partes)).encode()).hexdigest()[:n]


def _conteudo() -> bool:
    return os.environ.get("CIRCULO_TELEMETRIA_CONTEUDO") == "1"


def _quem(regra: str) -> str:
    r = (regra or "").lower()
    if "jev" in r:
        return "jev"
    if "llm" in r:
        return "llm"
    if "humano" in r or "cassio" in r or "cássio" in r:
        return "humano"
    return "regra"


def _pr(texto) -> int | None:
    m = re.search(r"#(\d+)", str(texto or ""))
    return int(m.group(1)) if m else None


def spans_do_ciclo(store, run_id: str, tick: int, inicio: float, fim: float, erros: list[str] | None = None,
                   versao: str | None = None) -> list[dict]:
    """A árvore de spans de um giro, montada do que o giro gravou entre `inicio` e `fim`."""
    trace = _id("trace", run_id, n=32)
    raiz = _id("workflow", run_id)
    versao = versao or __version__
    sha = str((store.get("corpo") or {}).get("sha") or "")[:12]
    base = {"circulo.run_id": run_id, "circulo.tick": tick}
    out: list[dict] = []

    def span(nome, op, ini, fim_, pai, status="OK", msg="", attrs=None, chave=None, events=None):
        s = {"trace_id": trace, "span_id": _id(run_id, op, nome, ini, chave), "parent_span_id": pai, "name": nome,
             "kind": "CLIENT" if op in ("execute_tool", "chat") else "INTERNAL",
             "start_time_unix_nano": _ns(ini), "end_time_unix_nano": _ns(max(ini, fim_)),
             "status": {"code": status, "message": str(msg or "")[:300]},
             "attributes": {"gen_ai.operation.name": op, **base, **(attrs or {})}}
        if events:
            s["events"] = events
        out.append(s)
        return s

    # agentes: cada passagem na trilha de etapas do giro (passagens seguidas do mesmo agente viram uma só)
    agentes: list[dict] = []
    trilha = store.q("SELECT etapa, tarefa, em, project_id FROM trail WHERE run_id=? ORDER BY seq", (run_id,))
    for i, t in enumerate(trilha):
        nome = t["tarefa"] or t["etapa"]
        if t["etapa"] in SEM_AGENTE:
            continue
        if t["etapa"] == "developer":
            nome = "developer"
        prox = trilha[i + 1]["em"] if i + 1 < len(trilha) else fim
        if agentes and agentes[-1]["nome"] == nome:
            agentes[-1]["fim"] = prox
            continue
        agentes.append({"nome": nome, "ini": t["em"], "fim": prox, "projeto": t["project_id"]})

    def pai_em(t: float) -> str:
        dono = None
        for a in agentes:
            if a["ini"] <= t:
                dono = a
        return dono["span_id"] if dono else raiz

    contagem = Counter()
    for a in agentes:
        contagem[a["nome"]] += 1
        a["span_id"] = _id(run_id, "invoke_agent", a["nome"], a["ini"], contagem[a["nome"]])

    # erros do giro (com o incidente que abriram)
    errs = store.q("SELECT stage, kind, message, incident_id, em FROM run_errors WHERE run_id=? ORDER BY id", (run_id,))
    incidentes = sorted({e["incident_id"] for e in errs if e["incident_id"]})

    # decisões: intenções write-ahead (ação, motivo, regra) e perguntas ao decisor (jev/local/llm)
    decisoes = []
    for i in store.q("SELECT seq, acao, motivo, regra, entradas, em FROM intencoes WHERE tipo='intencao' AND em BETWEEN ? AND ? "
                     "ORDER BY seq", (inicio, fim)):
        r = store.one("SELECT motivo, entradas, em FROM intencoes WHERE tipo='resultado' AND ref=?", (i["seq"],))
        ok = r is None or r["motivo"] == "ok"
        try:
            detalhe = json.loads(r["entradas"]).get("detalhe", "") if r is not None else ""
        except (TypeError, ValueError):
            detalhe = ""
        decisoes.append(("intencao", i["seq"], i["em"], r["em"] if r is not None else i["em"], ok, detalhe,
                         {"circulo.decision.value": i["acao"], "circulo.decision.reason": i["motivo"] or "",
                          "circulo.decision.rule": i["regra"] or "", "circulo.decision.by": _quem(i["regra"])}))
    for d in store.q("SELECT id, question, value, confidence, source, created_at FROM decisions WHERE tick=? AND created_at "
                     "BETWEEN ? AND ? ORDER BY id", (tick, inicio, fim)):
        decisoes.append(("pergunta", d["id"], d["created_at"], d["created_at"], True, "",
                         {"circulo.decision.question": d["question"], "circulo.decision.value": d["value"],
                          "circulo.decision.confidence": d["confidence"], "circulo.decision.by": d["source"],
                          "circulo.decision.reason": f"pergunta '{d['question']}' respondida por {d['source']}"}))
    if not any(k == "intencao" for k, *_ in decisoes):
        # giro sem ação: a decisão de não agir também é decisão, e quem decidiu foi a regra da cascata
        decisoes.append(("nada", 0, fim, fim, True, "", {"circulo.decision.value": "nada_a_fazer",
                                                         "circulo.decision.reason": "nenhum pedido na fila e nenhuma tarefa elegível",
                                                         "circulo.decision.by": "regra"}))
    for kind, ref, ini, fim_, ok, det, attrs in decisoes:
        span(f"jev_decision {attrs['circulo.decision.value']}", "jev_decision", ini, fim_, pai_em(ini),
             "OK" if ok else "ERROR", det, attrs, chave=f"{kind}{ref}")

    # LLM: modelo e tokens (conteúdo só se pedido explicitamente)
    tokens = 0
    for c in store.q("SELECT id, papel, modelo, nivel, decidido_por, tokens, duracao_ms, ok, erro, entrada, saida, created_at, "
                     "project_id FROM llm_calls WHERE created_at BETWEEN ? AND ? ORDER BY id", (inicio, fim)):
        tokens += int(c["tokens"] or 0)
        dur = (c["duracao_ms"] or 0) / 1000
        attrs = {"gen_ai.request.model": c["modelo"], "gen_ai.agent.name": c["papel"], "gen_ai.usage.total_tokens": int(c["tokens"] or 0),
                 "circulo.model.decided_by": c["decidido_por"], "circulo.model.tier": c["nivel"] or ""}
        if _conteudo():
            attrs.update({"gen_ai.prompt": c["entrada"] or "", "gen_ai.completion": c["saida"] or ""})
        span(f"chat {c['modelo']}", "chat", c["created_at"] - dur, c["created_at"], pai_em(c["created_at"] - dur),
             "OK" if c["ok"] else "ERROR", c["erro"], attrs, chave=c["id"])

    # ferramentas: verificações (lint, testes, PR, CI, merge), PRs e merges do giro
    prs = set()
    for v in store.q("SELECT id, ponto, sujeito, ok, motivo, created_at FROM verificacoes WHERE created_at BETWEEN ? AND ? "
                     "ORDER BY id", (inicio, fim)):
        ferramenta = FERRAMENTAS.get(v["ponto"])
        if ferramenta is None:
            continue
        attrs = {"gen_ai.tool.name": ferramenta, "circulo.check": v["ponto"]}
        pr = _pr(v["sujeito"]) if ferramenta.startswith("github") else None
        if pr:
            attrs["circulo.pr"] = pr
            prs.add(pr)
        span(f"execute_tool {ferramenta}", "execute_tool", v["created_at"], v["created_at"], pai_em(v["created_at"]),
             "OK" if v["ok"] else "ERROR", "" if v["ok"] else str(v["motivo"] or "")[-300:], attrs, chave=v["id"])
    for p in store.q("SELECT number, titulo, status, updated_at FROM prs WHERE updated_at BETWEEN ? AND ?", (inicio, fim)):
        prs.add(p["number"])
        span("execute_tool github_pr", "execute_tool", p["updated_at"], p["updated_at"], pai_em(p["updated_at"]), "OK", "",
             {"gen_ai.tool.name": "github_pr", "circulo.pr": p["number"], "circulo.pr.status": p["status"],
              "circulo.pr.title": p["titulo"][:160]}, chave=f"pr{p['number']}")
    for m in store.q("SELECT id, pr, sha, merged, reason, created_at FROM merges WHERE created_at BETWEEN ? AND ?", (inicio, fim)):
        prs.add(m["pr"])
        span("execute_tool github_merge", "execute_tool", m["created_at"], m["created_at"], pai_em(m["created_at"]),
             "OK" if m["merged"] else "ERROR", "" if m["merged"] else m["reason"],
             {"gen_ai.tool.name": "github_merge", "circulo.pr": m["pr"], "circulo.sha": str(m["sha"])[:12]}, chave=f"m{m['id']}")

    # agentes por último: o status vem dos erros cuja etapa caiu dentro deles
    for a in agentes:
        dele = [e for e in errs if a["ini"] <= e["em"] <= a["fim"]]
        out.append({"trace_id": trace, "span_id": a["span_id"], "parent_span_id": raiz, "name": f"invoke_agent {a['nome']}",
                    "kind": "INTERNAL", "start_time_unix_nano": _ns(a["ini"]), "end_time_unix_nano": _ns(max(a["ini"], a["fim"])),
                    "status": {"code": "ERROR" if dele else "OK", "message": (dele[0]["message"][:300] if dele else "")},
                    "attributes": {"gen_ai.operation.name": "invoke_agent", **base, "gen_ai.agent.name": a["nome"],
                                   "gen_ai.agent.version": versao, "circulo.project_id": a["projeto"]}})

    eventos = [{"name": "exception", "time_unix_nano": _ns(e["em"]),
                "attributes": {"exception.type": e["kind"], "exception.message": e["message"][:300],
                               "circulo.stage": e["stage"], "circulo.incident_id": e["incident_id"]}} for e in errs]
    falhou = bool(erros) or bool(errs)
    msg = (erros[0] if erros else errs[0]["message"] if errs else "")
    out.insert(0, {"trace_id": trace, "span_id": raiz, "parent_span_id": None, "name": "invoke_workflow circulo",
                   "kind": "INTERNAL", "start_time_unix_nano": _ns(inicio), "end_time_unix_nano": _ns(fim),
                   "status": {"code": "ERROR" if falhou else "OK", "message": str(msg)[:300]},
                   "attributes": {"gen_ai.operation.name": "invoke_workflow", **base, "gen_ai.agent.name": "circulo",
                                  "gen_ai.agent.version": versao, "circulo.corpo.sha": sha, "gen_ai.usage.total_tokens": tokens,
                                  "circulo.prs": sorted(prs), "circulo.incident_ids": incidentes,
                                  "circulo.errors": len(erros or []) or len(errs), "circulo.duration_ms": round(1000 * (fim - inicio))},
                   **({"events": eventos} if eventos else {})})
    return out


def gravar(pasta: Path, spans: list[dict]) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / ARQUIVO
    with arq.open("a", encoding="utf-8") as f:        # só de acréscimo: nada é reescrito
        f.write("".join(json.dumps(s, ensure_ascii=False, default=str) + "\n" for s in spans))
    return arq


def ler(pasta: Path, ciclos: int = CICLOS_NO_PAINEL) -> list[dict]:
    """Os spans dos últimos `ciclos` giros, lendo só o fim do arquivo."""
    arq = pasta / ARQUIVO
    if not arq.exists():
        return []
    with arq.open("rb") as f:
        f.seek(0, 2)
        tam = f.tell()
        f.seek(max(0, tam - BYTES_LIDOS))
        bruto = f.read().decode("utf-8", "replace").splitlines()
    if tam > BYTES_LIDOS:
        bruto = bruto[1:]                              # a primeira linha pode estar cortada
    spans = []
    for linha in bruto:
        try:
            spans.append(json.loads(linha))
        except ValueError:
            continue
    traces = list(dict.fromkeys(s["trace_id"] for s in spans))[-ciclos:]
    manter = set(traces)
    return [s for s in spans if s["trace_id"] in manter]


def _op(s: dict) -> str:
    return s["attributes"].get("gen_ai.operation.name", "")


def grafo(spans: list[dict]) -> dict:
    """Grafo agregado dos agentes: nós com contagem e falhas, arestas com repetição e ciclos de retry
    (o mesmo agente voltando a rodar no mesmo giro, ou rodando de novo no giro seguinte a uma falha)."""
    por_trace: dict[str, list[dict]] = defaultdict(list)
    for s in spans:
        if _op(s) == "invoke_agent":
            por_trace[s["trace_id"]].append(s)
    nos, falhas, arestas, retries = Counter(), Counter(), Counter(), Counter()
    falhou_antes: set[str] = set()
    for trace in dict.fromkeys(s["trace_id"] for s in spans):
        seq = sorted(por_trace.get(trace, []), key=lambda s: s["start_time_unix_nano"])
        nomes = [s["attributes"]["gen_ai.agent.name"] for s in seq]
        vistos: set[str] = set()
        for s, n in zip(seq, nomes, strict=True):
            nos[n] += 1
            if s["status"]["code"] == "ERROR":
                falhas[n] += 1
            if n in vistos or n in falhou_antes:
                retries[n] += 1
            vistos.add(n)
        for a, b in pairwise(nomes):
            arestas[(a, b)] += 1
        falhou_antes = {n for s, n in zip(seq, nomes, strict=True) if s["status"]["code"] == "ERROR"}
    return {"nos": dict(nos), "falhas": dict(falhas), "retries": dict(retries),
            "arestas": [{"de": a, "para": b, "n": n} for (a, b), n in arestas.items()]}


def mermaid(g: dict) -> str:
    def nid(n):
        return "a_" + re.sub(r"\W", "_", n)

    def rot(n):
        return re.sub(r"[\"<>{}\[\]|]", "", n)
    linhas = ["flowchart LR"]
    for n, c in sorted(g["nos"].items()):
        extra = (f" · {g['falhas'][n]} falha(s)" if g["falhas"].get(n) else "") + \
                (f" · {g['retries'][n]} retry" if g["retries"].get(n) else "")
        linhas.append(f'  {nid(n)}["{rot(n)} ×{c}{extra}"]')
        if g["falhas"].get(n):
            linhas.append(f"  class {nid(n)} falha")
    for e in g["arestas"]:
        linhas.append(f"  {nid(e['de'])} -->|{e['n']}| {nid(e['para'])}")
    for n, c in sorted(g["retries"].items()):
        linhas.append(f"  {nid(n)} -.->|retry {c}| {nid(n)}")
    linhas.append("  classDef falha stroke:#c0392b,stroke-width:2px")
    return "\n".join(linhas)


def ciclos(spans: list[dict]) -> list[dict]:
    """Um resumo por giro, do mais novo para o mais antigo: o ponto de partida do diagnóstico."""
    por: dict[str, list[dict]] = defaultdict(list)
    for s in spans:
        por[s["trace_id"]].append(s)
    out = []
    for ss in por.values():
        w = next((s for s in ss if _op(s) == "invoke_workflow"), None)
        if w is None:
            continue
        a = w["attributes"]
        out.append({"run_id": a["circulo.run_id"], "tick": a["circulo.tick"], "inicio": w["start_time_unix_nano"] / 1e9,
                    "duracao_ms": a.get("circulo.duration_ms"), "status": w["status"]["code"], "erro": w["status"]["message"],
                    "versao": a.get("gen_ai.agent.version"), "tokens": a.get("gen_ai.usage.total_tokens", 0),
                    "prs": a.get("circulo.prs", []), "incidentes": a.get("circulo.incident_ids", []),
                    "agentes": [s["attributes"]["gen_ai.agent.name"] for s in sorted(ss, key=lambda s: s["start_time_unix_nano"])
                                if _op(s) == "invoke_agent"],
                    "ferramentas": [{"nome": s["attributes"].get("gen_ai.tool.name"), "status": s["status"]["code"],
                                     "msg": s["status"]["message"], "pr": s["attributes"].get("circulo.pr")}
                                    for s in ss if _op(s) == "execute_tool"],
                    "decisoes": [{"valor": s["attributes"].get("circulo.decision.value"), "por": s["attributes"].get("circulo.decision.by"),
                                  "motivo": s["attributes"].get("circulo.decision.reason"), "status": s["status"]["code"]}
                                 for s in ss if _op(s) == "jev_decision"]})
    return sorted(out, key=lambda c: c["inicio"], reverse=True)


def _json_script(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str).replace("</", "<\\/")


def pagina(spans: list[dict], repo: str | None = None) -> str:
    """HTML estático: timeline (vis-timeline), grafo agregado (mermaid) e a lista de giros com falha primeiro.
    Sem as bibliotecas (offline), a tabela de giros continua legível: o diagnóstico não depende do CDN."""
    g = grafo(spans)
    cs = ciclos(spans)
    itens = []
    for s in spans:
        op = _op(s)
        if op == "invoke_workflow":
            continue
        a = s["attributes"]
        grupo = {"invoke_agent": "agentes", "jev_decision": "decisões", "execute_tool": "ferramentas", "chat": "LLM"}.get(op, op)
        rotulo = a.get("gen_ai.agent.name") if op == "invoke_agent" else a.get("gen_ai.tool.name") if op == "execute_tool" else \
            f"{a.get('circulo.decision.value')} ({a.get('circulo.decision.by')})" if op == "jev_decision" else a.get("gen_ai.request.model")
        ini, fim = s["start_time_unix_nano"] / 1e6, s["end_time_unix_nano"] / 1e6
        item = {"id": s["span_id"] + s["trace_id"][:6], "group": grupo, "content": str(rotulo), "start": ini,
                "className": "erro" if s["status"]["code"] == "ERROR" else "ok",
                "title": f"giro {a.get('circulo.tick')} · {a.get('circulo.run_id')} · {s['name']}"
                         + (f" · {s['status']['message']}" if s["status"]["message"] else "")}
        if op == "invoke_agent" and fim > ini:
            item["end"] = fim
        else:
            item["type"] = "point"
        itens.append(item)
    falhos = [c for c in cs if c["status"] == "ERROR"]
    pr_url = (lambda n: f"https://github.com/{repo}/pull/{n}") if repo else (lambda n: "#")
    e = html.escape

    def linha(c):
        prs = " ".join(f'<a href="{e(pr_url(n))}">PR #{n}</a>' for n in c["prs"]) or "—"
        inc = " ".join(f'<a href="/api/execucao/{e(c["run_id"])}">incidente #{i}</a>' for i in c["incidentes"]) or "—"
        dec = "; ".join(f"{e(str(d['valor']))} <small>por {e(str(d['por']))}</small>" for d in c["decisoes"])
        ferr = " ".join(f'<span class="{"erro" if f["status"] == "ERROR" else "ok"}" title="{e(f["msg"] or "")}">{e(str(f["nome"]))}</span>'
                        for f in c["ferramentas"]) or "—"
        quando = time.strftime("%d/%m %H:%M:%S", time.localtime(c["inicio"]))
        return (f'<tr class="{"erro" if c["status"] == "ERROR" else ""}"><td>{c["tick"]}</td>'
                f'<td><a href="/api/execucao/{e(c["run_id"])}"><code>{e(c["run_id"])}</code></a></td><td>{quando}</td>'
                f'<td>{c["duracao_ms"]} ms</td><td>{e(" → ".join(c["agentes"]))}</td><td>{dec}</td><td>{ferr}</td>'
                f'<td>{prs}</td><td>{inc}</td><td>{e(c["erro"])}</td></tr>')
    cab = "<tr><th>giro</th><th>run_id</th><th>quando</th><th>duração</th><th>agentes</th><th>decisão (quem)</th>" \
          "<th>ferramentas</th><th>PR</th><th>incidente</th><th>erro</th></tr>"
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Círculo · trilha do loop</title>
<link rel="stylesheet" href="https://unpkg.com/vis-timeline@7.7.3/styles/vis-timeline-graph2d.min.css">
<style>body{{font:14px system-ui,sans-serif;margin:20px;color:#222}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #ddd;padding:4px 6px;text-align:left;vertical-align:top}}tr.erro td{{background:#fdecea}}
.erro{{color:#c0392b}} .vis-item.erro{{background:#f5b7b1;border-color:#c0392b}} .vis-item.ok{{background:#d5f5e3;border-color:#27ae60}}
span.ok,span.erro{{margin-right:4px}} #timeline{{margin:12px 0}}</style></head><body>
<h1>Trilha do loop</h1>
<p>{len(cs)} giros · {len(falhos)} com falha · {len(spans)} spans · versão {e(__version__)} · gerado {time.strftime("%d/%m %H:%M:%S")}</p>
<h2>Giros com falha</h2><table>{cab}{"".join(linha(c) for c in falhos) or '<tr><td colspan="10">nenhum</td></tr>'}</table>
<h2>Linha do tempo</h2><div id="timeline"></div>
<h2>Grafo dos agentes</h2><pre class="mermaid">{e(mermaid(g))}</pre>
<h2>Todos os giros</h2><table>{cab}{"".join(linha(c) for c in cs[:CICLOS_NO_PAINEL])}</table>
<script id="dados" type="application/json">{_json_script(itens)}</script>
<script src="https://unpkg.com/vis-timeline@7.7.3/standalone/umd/vis-timeline-graph2d.min.js"></script>
<script type="module">
try {{
  const itens = JSON.parse(document.getElementById("dados").textContent);
  const grupos = ["agentes", "decisões", "ferramentas", "LLM"].map(g => ({{id: g, content: g}}));
  if (window.vis) new vis.Timeline(document.getElementById("timeline"), new vis.DataSet(itens), new vis.DataSet(grupos),
                                   {{stack: true, maxHeight: 480, zoomMin: 50}});
}} catch (e) {{ console.error(e); }}
try {{
  const m = (await import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs")).default;
  m.initialize({{startOnLoad: false}}); await m.run();
}} catch (e) {{ console.error(e); }}
</script></body></html>"""


def registrar_ciclo(store, pasta: str | Path, run_id: str | None, tick: int, inicio: float, fim: float | None = None,
                    erros: list[str] | None = None) -> bool:
    """Grava o traço do giro e regenera o painel. Nunca levanta: falha de telemetria não derruba o loop."""
    if not run_id:
        return False
    try:
        pasta = Path(pasta) / "telemetria"
        gravar(pasta, spans_do_ciclo(store, run_id, tick, inicio, fim or time.time(), erros))
        tmp = pasta / (PAGINA + ".tmp")
        tmp.write_text(pagina(ler(pasta), os.environ.get("CIRCULO_REPO")), encoding="utf-8")
        tmp.replace(pasta / PAGINA)                    # troca atômica: o painel nunca abre página pela metade
        return True
    except Exception as exc:  # noqa: BLE001 — telemetria nunca derruba o loop
        try:
            st = store.get("telemetria_falhas") or {"n": 0}
            store.set("telemetria_falhas", {"n": int(st.get("n", 0)) + 1, "ultima": repr(exc)[:300], "em": time.time()})
        except Exception:  # noqa: BLE001
            pass
        return False

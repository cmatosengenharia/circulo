"""Painel local do círculo: estado, feed ao vivo (SSE) e controles do humano.

Só escuta em 127.0.0.1. Lê o mesmo SQLite do loop (WAL permite leitura concorrente).
Escritas permitidas: pausar/retomar, modo seguro e enfileirar pedido — nada além disso.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, finance
from . import atividade as atv
from . import registro, repo_stats
from .money import fmt_brl
from .projects import cards, incidentes, novos_na_fila, roteiro
from .status import loop_status
from .state import Store

HOST = "127.0.0.1"


def _rows(rows):
    return [dict(r) for r in rows]


def estado(store: Store, projeto: int | None = None) -> dict:
    s = store
    now = time.time()
    tick = s.tick
    controle = s.get("controle", {}) or {}
    pol = s.one("SELECT version, body FROM policy_versions WHERE status='active' ORDER BY version DESC LIMIT 1")
    policy = json.loads(pol["body"])
    shadow = s.one("SELECT version, reason FROM policy_versions WHERE status='shadow' ORDER BY version DESC LIMIT 1")
    day = time.strftime("%Y-%m-%d", time.localtime())
    budget = s.one("SELECT * FROM budget ORDER BY day DESC LIMIT 1")

    pf = " AND project_id=?" if projeto else ""
    pa = (projeto,) if projeto else ()
    dec = s.one(f"""SELECT COUNT(*) n, SUM(source!='llm') sem_llm, SUM(source='jev') jev, SUM(source='local') local
                   FROM decisions WHERE created_at > ?{pf}""", (now - 86400, *pa))
    n = dec["n"] or 0
    last = s.q("SELECT tick, body FROM metrics ORDER BY tick DESC LIMIT 100")
    bodies = [json.loads(r["body"]) for r in last]
    ticks = [r["tick"] for r in last]
    errors = sum(len(b.get("errors", [])) for b in bodies)
    health = bodies[0].get("health", {}) if bodies else {}
    violations = finance.check_invariants(s)

    snap = finance.snapshot(s)
    kit = s.one("SELECT kit FROM projects WHERE id=?", (projeto,))["kit"] if projeto else "financas"
    projetos = [] if kit != "financas" else [{
        "nome": "Finanças da família",
        "kit": "financas",
        "linha": (f"Patrimônio {fmt_brl(snap.patrimonio_liquido_cents)} · casa {snap.progresso_bp / 100:.1f}% · "
                  f"sobra do mês {fmt_brl(snap.sobra_mes_cents)}"),
        "progresso": min(1.0, snap.progresso_bp / 10_000),
        "lancamentos": s.one("SELECT COUNT(*) c FROM ledger")["c"],
    }]

    aguardando = []
    for r in ([] if kit != "financas" else s.q("SELECT id, description, amount_cents, category FROM ledger WHERE status='open' AND auto_accepted=0 ORDER BY id DESC LIMIT 8")):
        aguardando.append({"tipo": "revisao", "texto": f"#{r['id']} {fmt_brl(r['amount_cents'])} {r['description']} → {r['category']}?",
                           "acao": f"ok {r['id']}"})
    for r in s.q("SELECT message FROM alerts WHERE kind IN ('merge','saude') AND delivered=0 ORDER BY id DESC LIMIT 8"):
        aguardando.append({"tipo": "aviso", "texto": r["message"]})

    serie = [{"tick": t, "tokens": b.get("budget", {}).get("tokens", 0), "erros": len(b.get("errors", [])),
              "pedido": bool(b.get("handled")), "idle": b.get("idle")}
             for t, b in zip(ticks, bodies, strict=True)][::-1]

    zero = kit == "circulo"
    return {
        "agora": now,
        "trabalho_agora": atv.agora(s),
        "linha_do_tempo": atv.linha_do_tempo(s, projeto, zero=zero),
        "giros": atv.giros(s, None if zero else projeto),
        "ritmo": atv.ritmo(s, None if zero else projeto),
        "llm": {"recentes": registro.recentes(s, None if zero else projeto, 15), "resumo": registro.resumo(s, None if zero else projeto)},
        **({"repo": repo_stats.stats()} if zero or projeto is None else {}),
        "repo_url": f"https://github.com/{os.environ['CIRCULO_REPO']}" if re.fullmatch(r"[\w.-]+/[\w.-]+", os.environ.get("CIRCULO_REPO", "")) else None,
        "developer": s.get("self_dev_aberto"),
        "nomes": {r["id"]: r["nome"] for r in s.q("SELECT id, nome FROM projects")},
        "ultima_decisao": s.one(f"SELECT COALESCE(MAX(id),0) m FROM decisions WHERE 1=1{pf}", pa)["m"],
        "loop": {
            "tick": tick, "status": s.get("loop_status", "parado"), "etapa": s.get("etapa"),
            "controle": {"pausado": bool(controle.get("pausado")), "modo_seguro": bool(controle.get("modo_seguro"))},
            "pendentes": s.pending_count(), "politica": pol["version"], "trabalho_pendente": s.get("trabalho_pendente"),
            "shadow": dict(shadow) if shadow else None, "jev_erro": s.get("jev_last_error"),
            "vivo": loop_status(s, now),
        },
        "orcamento": {"dia": budget["day"] if budget else day, "tokens": budget["tokens"] if budget else 0,
                      "limite": policy["budget"]["daily_token_limit"],
                      "jev": budget["jev_calls"] if budget else 0, "llm": budget["llm_calls"] if budget else 0},
        "saude": {
            "invariantes": violations,
            "correcao": health.get("correction_rate", 0.0), "correcao_limite": policy["rollback"]["max_correction_rate"],
            "amostras": health.get("samples", 0),
            "sem_llm": (dec["sem_llm"] or 0) / n if n else 1.0, "decisoes_24h": n,
            "erros_100": errors, "giros_100": len(bodies),
        },
        "evolucoes": _rows(s.q(f"SELECT id, level, kind, description, status, notes, updated_at FROM proposals WHERE 1=1{pf} ORDER BY updated_at DESC LIMIT 20", pa)),
        "versoes": _rows(s.q("SELECT version, status, reason, created_at FROM policy_versions ORDER BY version DESC LIMIT 12")),
        "merges": _rows(s.q("SELECT pr, merged, reason, created_at FROM merges ORDER BY id DESC LIMIT 10")),
        "aguardando": aguardando,
        "autonomia": autonomia(s),
        **({"conexoes": conexoes(s, projeto), "evidencias": _rows(s.q(
            "SELECT tick, fase, versao, antes, depois, oculta_antes, oculta_depois, jev_avanca, jev_contraprova, decisao, motivo, created_at "
            "FROM evidence WHERE project_id=? ORDER BY id DESC LIMIT 15", (projeto,)))} if projeto else {}),
        "projetos": projetos,
        "serie": serie,
        "respostas": _rows(s.q(f"SELECT id, message, created_at FROM alerts WHERE kind='resposta'{pf} ORDER BY id DESC LIMIT 6", pa)),
        "projeto": (next((c for c in cards(s) if c["id"] == projeto), None) if projeto else None),
        **({"motor": motor(s, projeto)} if kit == "geral" else {}),
        **({"roteiro": roteiro(s), "incidentes": incidentes(s), "quarentena": {
            k: v for k, v in (s.get("quarentena", {}) or {}).items() if v["ate_tick"] > s.tick}} if kit == "circulo" else {}),
    }


def autonomia(s: Store) -> dict:
    """Quanto o loop dependeu de você — a meta é zero intervenção."""
    semana = time.time() - 7 * 86400
    hum = "COALESCE(json_extract(payload,'$.origem'),'') != 'demo'"
    return {
        "intervencoes_7d": s.one(f"SELECT COUNT(*) n FROM events WHERE kind='mensagem' AND created_at>? AND {hum}", (semana,))["n"],
        "pedidos_7d": s.one(f"SELECT COUNT(*) n FROM events WHERE kind='novo_projeto' AND created_at>? AND {hum}", (semana,))["n"],
        "decisoes_7d": s.one("SELECT COUNT(*) n FROM decisions WHERE created_at>?", (semana,))["n"],
        "evolucoes_7d": s.one("SELECT COUNT(*) n FROM evidence WHERE created_at>? AND decisao IN ('avancar','base','cumprida')", (semana,))["n"],
        "fora_do_alcance": _rows(s.q("SELECT message, created_at FROM alerts WHERE kind='fora_alcance' ORDER BY id DESC LIMIT 6")),
        "configuracao": ([{"titulo": f"{x['nome']}: parado" if x["estado"] == "parado" else x["nome"], "detalhe": f"{x['detalhe']}. {x['como_ligar']}".strip()}
                          for x in (s.get("configuracao") or {}).get("pecas", []) if x["estado"] != "ligado"]
                         if s.get("configuracao") else
                         _rows(s.q("SELECT titulo, detalhe FROM roadmap WHERE status!='feito' AND evidencia LIKE '%depende de você%' ORDER BY ordem"))),
        "paralelo": int((json.loads(s.one("SELECT body FROM policy_versions WHERE status='active' ORDER BY version DESC LIMIT 1")["body"])
                         .get("portfolio", {}) or {}).get("parallel", 1)),
    }


def conexoes(s: Store, pid: int) -> list[dict]:
    rows = s.q("""SELECT pr.id, pr.nome, pr.tipo, l.relacao, l.forca, l.evidencia FROM links l
                  JOIN projects pr ON pr.id = CASE WHEN l.a=? THEN l.b ELSE l.a END
                  WHERE (l.a=? OR l.b=?) AND l.relacao!='nenhuma' ORDER BY l.forca DESC""", (pid, pid, pid))
    out = []
    for r in rows:
        d = dict(r)
        d["licoes_trocadas"] = s.one("SELECT COUNT(*) n FROM transfers WHERE (de=? AND para=?) OR (de=? AND para=?)",
                                     (pid, r["id"], r["id"], pid))["n"]
        out.append(d)
    return out


def motor(s: Store, pid: int) -> dict:
    """Tudo o que o motor genérico sabe sobre o projeto: régua, entrega, ciclos, pesquisa e playbook."""
    tipo = s.one("SELECT tipo FROM projects WHERE id=?", (pid,))["tipo"]
    rub = s.one("SELECT version, criteria FROM rubrics WHERE project_id=? ORDER BY version DESC LIMIT 1", (pid,))
    cur = s.one("SELECT version, formato, nota, nota_oculta, notas, created_at FROM deliverables WHERE project_id=? AND status='atual' "
                "ORDER BY version DESC LIMIT 1", (pid,))
    notas = json.loads(cur["notas"] or "{}") if cur else {}
    regua = [{**c, "nota": notas.get(c["id"])} for c in (json.loads(rub["criteria"]) if rub else [])]
    return {
        "pronto": bool(s.get("motor_pronto")), "regua_versao": rub["version"] if rub else None, "regua": regua,
        "entrega": ({k: cur[k] for k in ("version", "formato", "nota", "nota_oculta", "created_at")} | {"url": f"/projeto/{pid}/entrega"}) if cur else None,
        "versoes": _rows(s.q("SELECT version, nota, nota_oculta, status, created_at FROM deliverables WHERE project_id=? ORDER BY version DESC LIMIT 12", (pid,))),
        "ciclos": _rows(s.q("SELECT tick, fase, nota_antes, nota_depois, ganho, aceita, tokens, resultado, braco, created_at FROM cycles "
                             "WHERE project_id=? ORDER BY id DESC LIMIT 15", (pid,))),
        "achados": _rows(s.q("SELECT text, source, trust, created_at FROM memory WHERE kind='achado' AND project_id=? ORDER BY id DESC LIMIT 12", (pid,))),
        "licoes": _rows(s.q("SELECT text, status, meta FROM memory WHERE kind='licao' AND tipo=? AND status!='aposentada' ORDER BY id DESC LIMIT 8", (tipo,))),
        "feedback": _rows(s.q("SELECT text, created_at FROM memory WHERE kind='feedback' AND project_id=? ORDER BY id DESC LIMIT 5", (pid,))),
    }


def novidades(store: Store, desde: int, projeto: int | None = None) -> list[dict]:
    pf, pa = (" AND project_id=?", (projeto,)) if projeto else ("", ())
    rows = store.q(f"SELECT id, tick, question, value, confidence, source, created_at, project_id FROM decisions WHERE id > ?{pf} ORDER BY id LIMIT 60",
                   (desde, *pa))
    return [{**dict(r), "value": json.loads(r["value"])} for r in rows]


def _page(name: str = "painel.html") -> bytes:
    return resources.files("circulo").joinpath(name).read_bytes()


def make_handler(db_path: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "circulo-painel"

        def log_message(self, *args):  # silencioso
            pass

        def _store(self) -> Store:
            return Store(db_path)

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            projeto = int(q["projeto"][0]) if q.get("projeto", [""])[0].isdigit() else None
            m = re.fullmatch(r"/(?:projeto|missao)/(\d+)/entrega", u.path)
            if m:
                return self._entrega(int(m.group(1)), q.get("v", [None])[0])
            if u.path == "/" or u.path.startswith(("/projeto/", "/missao/")):
                body = _page("home.html" if u.path == "/" else "painel.html")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif u.path == "/api/estado":
                self._json(estado(self._store(), projeto))
            elif u.path == "/api/projetos":
                st = self._store()
                e = estado(st)
                self._json({"projetos": cards(st), "loop": e["loop"], "orcamento": e["orcamento"], "demo": bool(st.get("demo")), "versao": __version__,
                            "autonomia": e["autonomia"],
                            "saude": e["saude"], "novos_na_fila": novos_na_fila(st)})
            elif u.path == "/api/eventos":
                self._sse(int(q.get("desde", ["0"])[0] or 0), projeto, so_status=q.get("tipo", [""])[0] == "status")
            else:
                self._json({"erro": "não encontrado"}, 404)

        def _entrega(self, pid: int, v: str | None):
            st = self._store()
            if v and v.isdigit():
                row = st.one("SELECT formato, content FROM deliverables WHERE project_id=? AND version=?", (pid, int(v)))
            else:
                row = st.one("SELECT formato, content FROM deliverables WHERE project_id=? AND status='atual' ORDER BY version DESC LIMIT 1", (pid,))
            if not row:
                return self._json({"erro": "este projeto ainda não tem entrega"}, 404)
            body = row["content"].encode()
            self.send_response(200)
            if row["formato"] == "html":
                self.send_header("Content-Type", "text/html; charset=utf-8")
                # entrega gerada por LLM: sem scripts, sem rede, isolada do painel
                self.send_header("Content-Security-Policy", "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:")
            else:
                self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _sse(self, desde: int, projeto: int | None = None, so_status: bool = False):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            store = self._store()
            last_stage = None
            last_status, last_sent = None, 0.0
            # trilha: cada passagem de etapa, para o círculo animar o giro inteiro (mesmo os de milissegundos)
            seq = store.one("SELECT COALESCE(MAX(seq),0) m FROM trail")["m"]
            try:
                while True:
                    st = loop_status(store)
                    key = (st["estado"], st["titulo"], st["detalhe"], st["pendentes"], st["tick"], st.get("etapa"))
                    if key != last_status or time.time() - last_sent > 5:
                        last_status, last_sent = key, time.time()
                        self.wfile.write(f"event: status\ndata: {json.dumps(st, ensure_ascii=False)}\n\n".encode())
                    if so_status:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        time.sleep(0.5)
                        continue
                    for t in store.q("SELECT seq, tick, etapa, project_id, em, detalhe FROM trail WHERE seq > ? ORDER BY seq LIMIT 120", (seq,)):
                        seq = t["seq"]
                        self.wfile.write(f"event: trilha\ndata: {json.dumps(dict(t), ensure_ascii=False)}\n\n".encode())
                    for d in novidades(store, desde, projeto):
                        desde = d["id"]
                        self.wfile.write(f"event: decisao\ndata: {json.dumps(d, ensure_ascii=False)}\n\n".encode())
                    etapa = store.get("etapa")
                    if etapa != last_stage:
                        last_stage = etapa
                        self.wfile.write(f"event: etapa\ndata: {json.dumps(etapa, ensure_ascii=False)}\n\n".encode())
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    time.sleep(0.4)
            except (BrokenPipeError, ConnectionResetError):
                return

        def do_POST(self):
            # Proteção contra outro site no seu navegador mandando comandos: exige cabeçalho próprio
            # (força preflight CORS, que este servidor nunca aprova) e origem local.
            origin = self.headers.get("Origin", "")
            if self.headers.get("X-Circulo") != "1" or (origin and not origin.startswith(("http://127.0.0.1", "http://localhost"))):
                return self._json({"erro": "proibido"}, 403)
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
            except json.JSONDecodeError:
                return self._json({"erro": "json inválido"}, 400)
            store = self._store()
            u = urlparse(self.path)
            if u.path == "/api/controle":
                c = store.get("controle", {}) or {}
                acao = data.get("acao")
                if acao == "pausar":
                    c["pausado"] = True
                elif acao == "retomar":
                    c["pausado"] = False
                elif acao == "modo_seguro":
                    c["modo_seguro"] = bool(data.get("ligado"))
                else:
                    return self._json({"erro": "ação desconhecida"}, 400)
                store.set("controle", {"pausado": bool(c.get("pausado")), "modo_seguro": bool(c.get("modo_seguro"))})
                return self._json({"ok": True, "controle": store.get("controle")})
            if u.path == "/api/pedido":
                texto = str(data.get("texto", "")).strip()[:500]
                if not texto:
                    return self._json({"erro": "pedido vazio"}, 400)
                payload = {"text": texto, "at": time.time(), "origem": "painel"}
                if str(data.get("projeto", "")).isdigit():
                    payload["projeto"] = int(data["projeto"])
                eid = store.enqueue("mensagem", payload)
                return self._json({"ok": True, "evento": eid})
            if u.path == "/api/projeto":
                pedido = str(data.get("pedido", "")).strip()[:2000]
                if len(pedido) < 8:
                    return self._json({"erro": "descreva o pedido em pelo menos uma frase"}, 400)
                eid = store.enqueue("novo_projeto", {"pedido": pedido, "at": time.time(), "origem": "painel"})
                return self._json({"ok": True, "evento": eid})
            return self._json({"erro": "não encontrado"}, 404)

    return Handler


def serve(db_path: str | Path, port: int = 8765, background: bool = False) -> ThreadingHTTPServer:
    # O painel pode subir antes do loop: prepara o banco do mesmo jeito que o loop faria.
    from .policy import PolicyStore
    from .projects import ensure_seed
    st = Store(db_path)
    PolicyStore(st)
    ensure_seed(st)
    finance.base(st)
    srv = ThreadingHTTPServer((HOST, port), make_handler(str(db_path)))
    srv.daemon_threads = True
    if background:
        threading.Thread(target=srv.serve_forever, daemon=True, name="painel").start()
    else:
        srv.serve_forever()
    return srv

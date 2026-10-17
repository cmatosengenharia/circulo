"""Painel local do círculo: estado, feed ao vivo (SSE) e controles do humano.

Só escuta em 127.0.0.1. Lê o mesmo SQLite do loop (WAL permite leitura concorrente).
Escritas permitidas: pausar/retomar, modo seguro e enfileirar pedido — nada além disso.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import finance
from .money import fmt_brl
from .projects import cards
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

    return {
        "agora": now,
        "ultima_decisao": s.one(f"SELECT COALESCE(MAX(id),0) m FROM decisions WHERE 1=1{pf}", pa)["m"],
        "loop": {
            "tick": tick, "status": s.get("loop_status", "parado"), "etapa": s.get("etapa"),
            "controle": {"pausado": bool(controle.get("pausado")), "modo_seguro": bool(controle.get("modo_seguro"))},
            "pendentes": s.pending_count(), "politica": pol["version"],
            "shadow": dict(shadow) if shadow else None, "jev_erro": s.get("jev_last_error"),
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
        "projetos": projetos,
        "serie": serie,
        "respostas": _rows(s.q(f"SELECT id, message, created_at FROM alerts WHERE kind='resposta'{pf} ORDER BY id DESC LIMIT 6", pa)),
        "projeto": (next((c for c in cards(s) if c["id"] == projeto), None) if projeto else None),
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
            if u.path == "/" or u.path.startswith("/projeto/"):
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
                self._json({"projetos": cards(st), "loop": estado(st)["loop"]})
            elif u.path == "/api/eventos":
                self._sse(int(q.get("desde", ["0"])[0] or 0), projeto)
            else:
                self._json({"erro": "não encontrado"}, 404)

        def _sse(self, desde: int, projeto: int | None = None):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            store = self._store()
            last_stage = None
            try:
                while True:
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
    Store(db_path)  # garante o schema
    srv = ThreadingHTTPServer((HOST, port), make_handler(str(db_path)))
    srv.daemon_threads = True
    if background:
        threading.Thread(target=srv.serve_forever, daemon=True, name="painel").start()
    else:
        srv.serve_forever()
    return srv

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
from .projects import cards, incidentes, kit_project_id, novos_na_fila, roteiro
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
                      "limite": _limite(s, policy), "limite_padrao": policy["budget"]["daily_token_limit"],
                      "customizado": bool((s.get("orcamento_limite") or {}).get("limite")),
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
        **({"conexoes": conexoes(s, projeto), "outras_missoes": _rows(s.q(
            "SELECT id, nome FROM projects WHERE id!=? AND kit NOT IN ('circulo') AND status!='arquivado' ORDER BY nome", (projeto,))),
            "evidencias": _rows(s.q(
            "SELECT tick, fase, versao, antes, depois, oculta_antes, oculta_depois, jev_avanca, jev_contraprova, decisao, motivo, created_at "
            "FROM evidence WHERE project_id=? ORDER BY id DESC LIMIT 15", (projeto,)))} if projeto else {}),
        "projetos": projetos,
        "serie": serie,
        "respostas": _rows(s.q(f"SELECT id, message, created_at FROM alerts WHERE kind='resposta'{pf} ORDER BY id DESC LIMIT 6", pa)),
        "conversa": conversa(s, projeto),
        "projeto": (next((c for c in cards(s) if c["id"] == projeto), None) if projeto else None),
        **({"motor": motor(s, projeto)} if kit == "geral" else {}),
        **({"roteiro": roteiro(s), "incidentes": incidentes(s), "licoes": _licoes(s), "cerebros": _cerebros(s), "quarentena": {
            k: v for k, v in (s.get("quarentena", {}) or {}).items() if v["ate_tick"] > s.tick}} if kit == "circulo" else {}),
    }


def _licoes(s: Store) -> dict:
    from .licoes import Licoes
    try:
        return Licoes(s).resumo()
    except Exception:  # noqa: BLE001 — o painel nunca cai por causa de um bloco
        return {}


def _cerebros(s: Store) -> list[dict]:
    from .neuronios import cerebros
    try:
        return cerebros(s)
    except Exception:  # noqa: BLE001
        return []


def _limite(s: Store, policy: dict) -> int:
    from .budget import limite_diario
    return limite_diario(s, int(policy["budget"]["daily_token_limit"]))


def conversa(s: Store, projeto: int | None, limite: int = 25) -> list[dict]:
    """Suas mensagens para esta missão (ou para o loop) e o que o loop respondeu a cada uma, em ordem."""
    fin = kit_project_id(s, "financas")
    alvo = projeto or fin
    if alvo == fin:
        cond, args = "(json_extract(payload,'$.projeto') IS NULL OR json_extract(payload,'$.projeto')=?)", (alvo,)
    else:
        cond, args = "json_extract(payload,'$.projeto')=?", (alvo,)
    msgs = s.q(f"SELECT id, payload, status, error, created_at, processed_at FROM events WHERE kind='mensagem' AND {cond} "
               "AND COALESCE(json_extract(payload,'$.origem'),'') != 'demo' ORDER BY id DESC LIMIT ?", (*args, limite))
    out = []
    for m in reversed(msgs):
        resp = [dict(r) for r in s.q("SELECT message, created_at FROM alerts WHERE evento=? ORDER BY id", (m["id"],))]
        out.append({"id": m["id"], "texto": json.loads(m["payload"]).get("text", ""), "status": m["status"],
                    "erro": m["error"], "em": m["created_at"], "respondido_em": m["processed_at"], "respostas": resp})
    return out


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
    rows = s.q("""SELECT pr.id, pr.nome, pr.tipo, l.relacao, l.forca, l.evidencia, l.origem FROM links l
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
            if u.path in ("/", "/integracoes", "/rastros", "/fluxo") or u.path.startswith(("/projeto/", "/missao/")):
                body = _page({"/": "home.html", "/integracoes": "integracoes.html", "/rastros": "rastros.html",
                              "/fluxo": "fluxo.html"}.get(u.path, "painel.html"))
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif u.path == "/telemetria":
                pag = Path(db_path).parent / "telemetria" / "index.html"
                body = pag.read_bytes() if pag.exists() else "<p>Sem traço ainda: o painel aparece depois do primeiro giro.</p>".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif u.path == "/api/fluxo":
                from .fluxo import visao as fluxo_visao
                self._json(fluxo_visao(self._store()))
            elif u.path == "/api/fluxo/eventos":
                v = q.get("voltar", ["0"])[0]
                self._sse_fluxo(int(v) if v.isdigit() else 0)
            elif u.path == "/metrics":
                from .observabilidade import prometheus
                body = prometheus(self._store()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif u.path == "/api/observabilidade":
                from .observabilidade import visao as obs
                self._json(obs(self._store()))
            elif u.path == "/api/rastro":
                from .rastro import localizar
                c = localizar(self._store(), q.get("q", [""])[0][:120])
                self._json(c if c else {"erro": "nada encontrado com esse termo"}, 200 if c else 404)
            elif u.path == "/api/estado":
                self._json(estado(self._store(), projeto))
            elif u.path == "/api/projetos":
                st = self._store()
                e = estado(st)
                self._json({"projetos": cards(st), "loop": e["loop"], "orcamento": e["orcamento"], "demo": bool(st.get("demo")), "versao": __version__,
                            "autonomia": e["autonomia"],
                            "saude": e["saude"], "novos_na_fila": novos_na_fila(st)})
            elif u.path == "/api/chaves":
                if not self._host_local():
                    return self._json({"erro": "proibido"}, 403)
                from .cofre import Cadastro
                from .configuracao import ENV_FILE
                self._json({"chaves": Cadastro(self._store(), ENV_FILE).listar()})
            elif u.path == "/api/conselho":
                from .perguntas import Conselho
                from .agents import Ctx  # noqa: F401 — o conselho só lê o store aqui

                class _C:
                    pass
                c = _C()
                c.store = self._store()
                self._json(Conselho(c).resumo())
            elif u.path == "/api/fluxo/giro":
                from .fluxo import giro, giros_recentes
                st = self._store()
                self._json({"giro": giro(st, (q.get("run") or [None])[0]), "recentes": giros_recentes(st)})
            elif u.path == "/api/fluxo/obras":
                from .fluxo import obras
                self._json({"obras": obras(self._store()), "agora": time.time()})
            elif u.path == "/api/vigia":
                from .vigia import resumo as vig
                self._json(vig(self._store()))
            elif u.path == "/api/indagador":
                from .indagador import resumo as indag
                self._json(indag(self._store()))
            elif u.path == "/api/confianca":
                from .confianca import confianca
                self._json(confianca(self._store()))
            elif u.path == "/api/parada":
                from . import parada
                self._json(parada.estado(self._store()))
            elif u.path == "/api/loop":
                from .camadas import visao
                self._json(visao(self._store()))
            elif u.path.startswith("/api/execucao/"):
                from .camadas import execucao
                ex = execucao(self._store(), u.path.rsplit("/", 1)[1])
                self._json(ex if ex else {"erro": "execução não encontrada"}, 200 if ex else 404)
            elif u.path == "/api/eventos":
                self._sse(int(q.get("desde", ["0"])[0] or 0), projeto, so_status=q.get("tipo", [""])[0] == "status")
            else:
                self._json({"erro": "não encontrado"}, 404)

        def _host_local(self) -> bool:
            """Contra DNS rebinding: o Host precisa ser o próprio computador."""
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            return host in ("127.0.0.1", "localhost", "::1")

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

        def _sse_fluxo(self, voltar: int = 0):
            """Fluxo dos agentes ao vivo: cada evento novo (etapa, pergunta ao Jev, LLM, verificação, erro) assim que
            entra no banco, e o 'agora' do loop a cada segundo."""
            from .fluxo import agora, cursor_inicial, eventos
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            store = self._store()
            cur = cursor_inicial(store, min(voltar, 400))
            ultimo_agora = 0.0
            try:
                while True:
                    evs, cur = eventos(store, cur)
                    for e in evs:
                        self.wfile.write(f"event: fluxo\ndata: {json.dumps(e, ensure_ascii=False)}\n\n".encode())
                    if time.time() - ultimo_agora >= 1.0:
                        ultimo_agora = time.time()
                        self.wfile.write(f"event: agora\ndata: {json.dumps(agora(store), ensure_ascii=False)}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(0.4)
            except (BrokenPipeError, ConnectionResetError):
                return

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
            # sinapses: cada verificação de cada neurônio, ao vivo (as 30 últimas na conexão, depois só as novas)
            from .confianca import confianca
            sin = max(0, (store.one("SELECT COALESCE(MAX(id),0) m FROM verificacoes")["m"] or 0) - 30)
            last_conf, last_conf_em = None, 0.0
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
                    # central de confiança: empurrada quando muda e, no mínimo, a cada 2 s (o frescor é visível)
                    if time.time() - last_conf_em >= 1.0:
                        conf = confianca(store)
                        chave = json.dumps([conf["veredito"], [(c["id"], c["estado"], c["valor"], c["porque"]) for c in conf["checks"]]],
                                           ensure_ascii=False)
                        if chave != last_conf or time.time() - last_conf_em >= 2.0:
                            last_conf = chave
                            self.wfile.write(f"event: confianca\ndata: {json.dumps(conf, ensure_ascii=False)}\n\n".encode())
                        last_conf_em = time.time()
                    for v in store.q("SELECT id, tick, ponto, sujeito, ok, assinatura, substr(motivo,1,240) motivo, created_at "
                                     "FROM verificacoes WHERE id > ? ORDER BY id LIMIT 100", (sin,)):
                        sin = v["id"]
                        self.wfile.write(f"event: sinapse\ndata: {json.dumps(dict(v), ensure_ascii=False)}\n\n".encode())
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
            if u.path in ("/api/controle", "/api/parada"):
                from . import parada
                c = store.get("controle", {}) or {}
                acao = data.get("acao")
                if acao in ("pausar", "parar"):
                    # parada verificável: a intenção entra na trilha, a pausa liga e o loop confirma no próximo giro
                    parada.pedir(store)
                    return self._json({"ok": True, "controle": store.get("controle"), "parada": parada.estado(store)})
                if acao == "retomar":
                    parada.retomar(store)
                    return self._json({"ok": True, "controle": store.get("controle"), "parada": parada.estado(store)})
                if acao == "modo_seguro" and u.path == "/api/controle":
                    c["modo_seguro"] = bool(data.get("ligado"))
                else:
                    return self._json({"erro": "ação desconhecida"}, 400)
                store.set("controle", {"pausado": bool(c.get("pausado")), "modo_seguro": bool(c.get("modo_seguro"))})
                return self._json({"ok": True, "controle": store.get("controle")})
            if u.path in ("/api/chaves", "/api/chaves/migrar"):
                # chaves de integração: só do painel local; a resposta nunca traz o valor de uma chave
                if not self._host_local():
                    return self._json({"erro": "proibido"}, 403)
                from .cofre import Cadastro
                from .configuracao import ENV_FILE
                cad = Cadastro(store, ENV_FILE)
                try:
                    if u.path.endswith("/migrar"):
                        return self._json({"ok": True, **cad.migrar()})
                    return self._json({"ok": True, **cad.gravar(str(data.get("nome", "")).strip().upper(),
                                                                 data.get("valor"), str(data.get("ajuda", "")))})
                except (ValueError, RuntimeError) as exc:
                    return self._json({"erro": str(exc)}, 400)
            if u.path == "/api/missao/pausa":
                # pausar/retomar só esta missão: o loop e as outras seguem
                from . import pausa
                try:
                    pid = int(data.get("id"))
                except (TypeError, ValueError):
                    return self._json({"erro": "id é obrigatório"}, 400)
                acao = data.get("acao")
                if acao not in ("pausar", "retomar"):
                    return self._json({"erro": "acao: pausar ou retomar"}, 400)
                try:
                    st = pausa.pausar(store, pid, str(data.get("motivo") or "")) if acao == "pausar" else pausa.retomar(store, pid)
                except ValueError as exc:
                    return self._json({"erro": str(exc)}, 400)
                return self._json({"ok": True, **st})
            if u.path == "/api/missao/paralelo":
                # giros em paralelo nesta missão: variantes que disputam um torneio a cada ciclo
                from .engine import MAX_PARALELO
                try:
                    pid, n = int(data.get("id")), int(data.get("n"))
                except (TypeError, ValueError):
                    return self._json({"erro": "id e n são obrigatórios"}, 400)
                if not (1 <= n <= MAX_PARALELO) or not store.one("SELECT 1 FROM projects WHERE id=? AND kit!='circulo'", (pid,)):
                    return self._json({"erro": f"n entre 1 e {MAX_PARALELO}, numa missão"}, 400)
                store.x("UPDATE projects SET paralelo=?, updated_at=? WHERE id=?", (n, time.time(), pid))
                nome = store.one("SELECT nome FROM projects WHERE id=?", (pid,))["nome"]
                store.x("INSERT INTO alerts(kind,message,created_at,project_id) VALUES('controle',?,?,?)",
                        (f"Você definiu {n} giro(s) em paralelo para “{nome}”.", time.time(), pid))
                return self._json({"ok": True, "id": pid, "n": n})
            if u.path == "/api/ligacoes":
                # você liga ou separa missões; vale acima do Jev
                from .graph import MissionGraph

                class _C:
                    pass
                c = _C()
                c.store = store
                try:
                    r = MissionGraph(c, None).ligar(int(data.get("a")), int(data.get("b")), str(data.get("relacao", "")))
                except (TypeError, ValueError) as exc:
                    return self._json({"erro": str(exc)}, 400)
                store.x("INSERT INTO alerts(kind,message,created_at,project_id) VALUES('controle',?,?,?)",
                        (f"Você {'separou' if r['relacao'] == 'nenhuma' else 'ligou'} as missões #{r['a']} e #{r['b']}"
                         + ("" if r["relacao"] == "nenhuma" else f" ({r['relacao'].replace('_', ' ')})") + ".", time.time(), r["a"]))
                return self._json({"ok": True, **r})
            if u.path == "/api/orcamento":
                # você decide quanto a API pode gastar por dia; vale na hora, para todo o loop
                from .budget import definir_limite
                pol = store.one("SELECT body FROM policy_versions WHERE status='active' ORDER BY version DESC LIMIT 1")
                padrao = int(json.loads(pol["body"])["budget"]["daily_token_limit"])
                bruto = data.get("limite")
                try:
                    r = definir_limite(store, None if bruto in (None, "", "padrao") else int(bruto), padrao)
                except (ValueError, TypeError) as exc:
                    return self._json({"erro": str(exc)}, 400)
                def fmt(n):
                    return f"{n:,}".replace(",", ".")
                store.x("INSERT INTO alerts(kind,message,created_at,project_id) VALUES(?,?,?,?)",
                        ("controle", f"Você mudou o limite diário da API: {fmt(r['antes'])} → {fmt(r['depois'])} tokens"
                         + ("" if r["customizado"] else " (padrão da política)"), time.time(), kit_project_id(store, "circulo")))
                return self._json({"ok": True, **r})
            if u.path == "/api/frescor":
                # o painel mede o próprio atraso (dado → tela) e o loop monitora como qualquer neurônio
                from .confianca import registrar_frescor
                try:
                    atraso = float(data.get("atraso_ms"))
                except (TypeError, ValueError):
                    return self._json({"erro": "atraso_ms inválido"}, 400)
                return self._json({"ok": True, "registrado": registrar_frescor(store, atraso)})
            if u.path == "/api/pedido":
                texto = str(data.get("texto", "")).strip()[:500]
                if not texto:
                    return self._json({"erro": "pedido vazio"}, 400)
                payload = {"text": texto, "at": time.time(), "origem": "painel"}
                if str(data.get("projeto", "")).isdigit():
                    payload["projeto"] = int(data["projeto"])
                eid = store.enqueue("mensagem", payload)
                return self._json({"ok": True, "evento": eid})
            if u.path == "/api/roteiro":
                # você decide o que o loop NÃO deve evoluir: item desativado sai da fila do Developer (e volta quando reativar)
                item = data.get("id")
                if not isinstance(item, int) or not store.one("SELECT 1 FROM roadmap WHERE id=?", (item,)):
                    return self._json({"erro": "item não encontrado"}, 404)
                ativo = bool(data.get("ativo"))
                store.x("UPDATE roadmap SET desativado=?, updated_at=? WHERE id=?", (0 if ativo else 1, time.time(), item))
                if ativo and store.one("SELECT 1 FROM roadmap WHERE id=? AND status='contestado'", (item,)):
                    # você reafirmou um item que o estudo contestou: segue como pedido, decisão registrada
                    store.x("UPDATE roadmap SET status='pendente', evidencia='contestado pelo estudo; você reafirmou', "
                            "estudo=json_set(COALESCE(estudo,'{}'),'$.reafirmado_pelo_humano',?), updated_at=? WHERE id=?",
                            (time.time(), time.time(), item))
                titulo = store.one("SELECT titulo FROM roadmap WHERE id=?", (item,))["titulo"]
                store.x("INSERT INTO alerts(kind,message,created_at,project_id) VALUES(?,?,?,?)",
                        ("controle", f"Você {'reativou' if ativo else 'desativou'} o item #{item} do roteiro: {titulo}", time.time(),
                         kit_project_id(store, "circulo")))
                return self._json({"ok": True, "id": item, "ativo": ativo})
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

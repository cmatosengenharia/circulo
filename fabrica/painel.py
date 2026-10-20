"""O painel da fábrica: um servidor HTTP da biblioteca padrão que mostra o chão de fábrica ao vivo.

Rotas: `/` (a página), `/api/estado` (equipe, cartões, achados, últimos eventos), `/api/eventos` (SSE: cada evento novo
assim que entra no banco), `/api/pedido` (POST: pedido novo), `/api/pausa` (POST: pausar/retomar).
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from .estado import Estado
from .modelo import ESTADOS, ORDEM, PAPEIS


def retrato(estado: Estado) -> dict:
    agora = time.time()
    em_voo = estado.em_andamento()
    ativo = ESTADOS.get(em_voo["estado"]) if em_voo else None
    bat = estado.get("batimento") or {}
    rodando = bool(bat.get("em")) and agora - float(bat.get("em") or 0) < 120
    cartoes = []
    for r in estado.q("SELECT * FROM cartoes ORDER BY CASE estado WHEN 'concluido' THEN 1 WHEN 'cancelado' THEN 2 ELSE 0 END, atualizado_em DESC LIMIT 40"):
        d = dict(r)
        d["dados"] = json.loads(d["dados"] or "{}")
        d["papel"] = ESTADOS.get(d["estado"], "")
        d["passos"] = estado.passos(d["id"])[-8:] if d["id"] == (em_voo or {}).get("id") else []
        cartoes.append(d)
    ultimos = estado.q("SELECT * FROM eventos ORDER BY id DESC LIMIT 60")
    eventos = []
    for r in reversed(ultimos):
        d = dict(r)
        d["dados"] = json.loads(d["dados"] or "{}")
        eventos.append(d)
    dia = agora - 86400
    numeros = {"concluidos_24h": estado.um("SELECT COUNT(*) n FROM cartoes WHERE estado='concluido' AND atualizado_em>=?", (dia,))["n"],
               "devolucoes_24h": estado.um("SELECT COUNT(*) n FROM passos WHERE em>=? AND de_estado!=para_estado AND para_estado NOT IN ('concluido','bloqueado','cancelado') "
                                           "AND para_estado IN ('novo','planejado','em_desenvolvimento') AND de_estado IN ('verificando','em_revisao','liberando')", (dia,))["n"],
               "bloqueados": estado.um("SELECT COUNT(*) n FROM cartoes WHERE estado='bloqueado'")["n"],
               "na_fila": estado.um("SELECT COUNT(*) n FROM cartoes WHERE estado='novo'")["n"],
               "achados": len(estado.achados_abertos())}
    equipe = []
    for k in ORDEM:
        ult = estado.um("SELECT mensagem, em, para_estado FROM passos WHERE papel=? ORDER BY id DESC LIMIT 1", (k,))
        equipe.append({"id": k, **PAPEIS[k], "ativo": k == ativo and rodando, "ultima": dict(ult) if ult else None,
                       "passos_24h": estado.um("SELECT COUNT(*) n FROM passos WHERE papel=? AND em>=?", (k, dia))["n"]})
    return {"em": agora, "rodando": rodando, "pausada": bool(estado.get("pausada", False)), "ativo": ativo, "em_voo": em_voo,
            "equipe": equipe, "cartoes": cartoes, "achados": estado.achados_abertos()[:12], "eventos": eventos, "numeros": numeros,
            "ultimo_evento": estado.ultimo_evento(), "estados": list(ESTADOS)}


def servir(caminho_db: str | Path, porta: int = 8766, fundo: bool = False, fabrica=None):
    estado = Estado(caminho_db)

    class H(BaseHTTPRequestHandler):
        server_version = "fabrica-painel"

        def log_message(self, *a):   # silencioso
            pass

        def _json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            caminho = self.path.split("?", 1)[0]
            if caminho in ("/", "/index.html"):
                body = resources.files("fabrica").joinpath("painel.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif caminho == "/api/estado":
                self._json(retrato(estado))
            elif caminho == "/api/eventos":
                self._sse()
            else:
                self._json({"erro": "não existe"}, 404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            corpo = json.loads(self.rfile.read(n) or b"{}") if n else {}
            if self.path == "/api/pedido":
                texto = str(corpo.get("texto", "")).strip()
                if not texto:
                    return self._json({"erro": "pedido vazio"}, 400)
                titulo = texto.splitlines()[0][:120]
                return self._json({"id": estado.novo_cartao(titulo, texto, "humano")})
            if self.path == "/api/pausa":
                estado.set("pausada", bool(corpo.get("pausar", True)))
                estado.evento("mensagem", None, "humano", "coordenador", "Fábrica pausada por você." if corpo.get("pausar", True) else "Fábrica retomada.", {"tom": "alerta"})
                return self._json({"pausada": bool(corpo.get("pausar", True))})
            return self._json({"erro": "não existe"}, 404)

        def _sse(self):
            desde = self.path.split("desde=")[1].split("&")[0] if "desde=" in self.path else ""
            ultimo = int(desde) if desde.isdigit() else max(0, estado.ultimo_evento() - 30)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    for e in estado.eventos_desde(ultimo):
                        ultimo = e["id"]
                        self.wfile.write(f"id: {e['id']}\nevent: {e['tipo']}\ndata: {json.dumps(e, ensure_ascii=False, default=str)}\n\n".encode())
                    self.wfile.write(b": pulso\n\n")
                    self.wfile.flush()
                    time.sleep(0.5)
            except (BrokenPipeError, ConnectionResetError):
                return

    srv = ThreadingHTTPServer(("127.0.0.1", porta), H)
    srv.daemon_threads = True
    if fundo:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv
    print(f"painel da fábrica em http://127.0.0.1:{srv.server_address[1]}")
    srv.serve_forever()
    return srv

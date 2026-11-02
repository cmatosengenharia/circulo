"""Servidor HTTP do painel e da verificação das telas: threads daemon; aba fechada no meio da resposta não vira
traceback; e `encerrando` avisa os fluxos SSE — que giram até o cliente sumir — para sair quando o servidor desliga
(2/11: cada painel de teste deixava threads órfãs lendo um banco já apagado a cada 0,4 s)."""
from __future__ import annotations

import sys
import threading
from http.server import ThreadingHTTPServer


class Servidor(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.encerrando = threading.Event()

    def shutdown(self):
        self.encerrando.set()
        super().shutdown()

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)

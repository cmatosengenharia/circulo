"""Demonstração: loop acelerado com pedidos simulados, para ver o painel vivo. Usa uma pasta de dados separada."""
from __future__ import annotations

import random
import threading
import time

from .decision import LocalJev
from .loop import Circle
from .painel import serve
from .state import Store

MENSAGENS = [
    "38,90 ifood almoço", "220 supermercado epa", "55 gasolina posto", "19,90 netflix", "18 padaria",
    "300 farmácia araujo", "45 sacolão", "62 sacolão", "24 pipoca cinema", "150 loja xyz", "42 sacolão",
    "+8000 salário", "89 rappi jantar", "12 uber", "230 condomínio",
]


def run_demo(data_dir: str, porta: int = 8765, giro: float = 0.6) -> None:
    c = Circle(data_dir, jev=LocalJev(), llm=None)
    if c.store.one("SELECT COUNT(*) n FROM projects")["n"] == 1:
        c.submit_project("Crie uma landing page para captar leads do Instagram")
        c.submit_project("Crie um portal admin para fotógrafos")
    serve(c.store.path, porta, background=True)
    print(f"demo: painel em http://127.0.0.1:{porta} (dados em {data_dir}). Ctrl+C para parar.")

    def usuario():
        s = Store(c.store.path)  # conexão própria: SQLite não compartilha conexão entre threads
        rnd = random.Random(7)
        submit = lambda txt: s.enqueue("mensagem", {"text": txt, "at": time.time(), "origem": "demo"})  # noqa: E731
        while not c._stop.is_set():
            time.sleep(rnd.uniform(1.5, 4))
            if (s.get("controle", {}) or {}).get("pausado"):
                continue
            submit(rnd.choice(MENSAGENS))
            time.sleep(1.2)
            row = s.one("SELECT id, description, category, status FROM ledger ORDER BY id DESC LIMIT 1")
            if row and row["status"] == "open":
                if "sacol" in row["description"] and row["category"] != "mercado":
                    submit(f"corrige {row['id']} mercado necessario")
                elif rnd.random() < 0.5:
                    submit(f"ok {row['id']}")

    threading.Thread(target=usuario, daemon=True).start()
    c.run_forever(sleep=lambda s: c._stop.wait(min(s, giro)))

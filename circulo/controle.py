"""Plano de controle em processo próprio: painel + SRE (travas) + Médico + Higiene + Escalador.

Até a 1.54 tudo rodava num processo só com o giro: o painel competia pelo mesmo GIL com o Developer, uma exceção no
giro derrubava o SRE junto, e cada reinício do corpo apagava tudo. Agora:

- `python -m circulo.controle --data … --porta …` sobe o plano de controle sobre o MESMO banco (SQLite em WAL aguenta
  dois processos): o painel em primeiro plano e o SRE na thread dele. Não roda giros.
- O loop (`circulo run --painel`) sobe este processo como filho e o **supervisiona**: se cair, sobe de novo (até 3 vezes
  em 2 min; depois volta a rodar painel e SRE dentro do próprio loop, como antes, e avisa). Ao reiniciar o giro (corpo),
  o filho é encerrado e o loop novo sobe outro — ~2 s sem painel, em vez de tudo parado.
- `CIRCULO_CONTROLE_SEPARADO=0` desliga: painel e SRE voltam para dentro do loop.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

QUEDAS_MAX = 3
JANELA_QUEDAS = 120


def separado() -> bool:
    return os.environ.get("CIRCULO_CONTROLE_SEPARADO", "1") != "0"


class Supervisor:
    """Sobe e cuida do processo do plano de controle a partir do loop."""

    def __init__(self, data_dir: Path, porta: int, store=None, reply=None):
        self.data_dir, self.porta, self.store, self.reply = Path(data_dir), int(porta), store, reply
        self.proc: subprocess.Popen | None = None
        self.quedas: list[float] = []
        self.desistiu = False

    def comando(self) -> list[str]:
        return [sys.executable, "-m", "circulo.controle", "--data", str(self.data_dir), "--porta", str(self.porta)]

    def iniciar(self) -> bool:
        if self.desistiu:
            return False
        self.proc = subprocess.Popen(self.comando(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dict(os.environ))
        if self.store is not None:
            self.store.set("controle_processo", {"pid": self.proc.pid, "em": time.time(), "porta": self.porta})
        return True

    def cuidar(self) -> str:
        """Chamado a cada giro: 'vivo', 'reiniciado' ou 'desistiu' (o loop assume painel e SRE)."""
        if self.desistiu or self.proc is None:
            return "desistiu" if self.desistiu else "parado"
        if self.proc.poll() is None:
            return "vivo"
        agora = time.time()
        self.quedas = [t for t in self.quedas if agora - t < JANELA_QUEDAS] + [agora]
        if len(self.quedas) > QUEDAS_MAX:
            self.desistiu = True
            if self.reply:
                self.reply(f"Plano de controle caiu {len(self.quedas)}× em {JANELA_QUEDAS} s (código {self.proc.returncode}); o loop assume painel e SRE até o próximo reinício.", "saude")
            return "desistiu"
        self.iniciar()
        return "reiniciado"

    def assumir(self, circle) -> None:
        """O loop volta a servir painel e SRE dentro do próprio processo (o filho caiu demais)."""
        circle.controle = None
        circle.vigia.iniciar()
        from .painel import serve
        try:
            serve(circle.store.path, self.porta, background=True)
        except OSError:                                     # porta ainda presa pelo filho morrendo: o próximo giro tenta
            pass

    def parar(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.store is not None:
            self.store.set("controle_processo", None)


def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="circulo.controle")
    ap.add_argument("--data", default="data")
    ap.add_argument("--porta", type=int, default=8765)
    args = ap.parse_args(argv)
    from . import configuracao as cfg
    cfg.carregar_env()
    from .loop import Circle
    from .painel import serve
    c = Circle(args.data)
    c.vigia.iniciar()                                   # SRE + Médico + Higiene + Escalador, no processo do controle
    c.store.set("controle_separado", {"pid": os.getpid(), "em": time.time(), "porta": args.porta})

    def sair(*_):
        c.vigia.parar()
        c.store.set("controle_separado", None)
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, sair)
    signal.signal(signal.SIGINT, sair)
    print(f"plano de controle em http://127.0.0.1:{args.porta} (pid {os.getpid()})")
    serve(c.store.path, args.porta, background=False)


if __name__ == "__main__":
    main()

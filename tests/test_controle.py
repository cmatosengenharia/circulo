"""Plano de controle em processo próprio (circulo/controle.py): painel + SRE fora do giro, supervisionado pelo loop."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from circulo import controle


def _porta_livre():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_processo_do_controle_sobe_o_painel_e_o_sre_sobre_o_mesmo_banco(tmp_path):
    data = tmp_path / "dados"
    porta = _porta_livre()
    env = {**os.environ, "CIRCULO_ENV": os.devnull, "CIRCULO_SEM_DEVELOPER": "1", "PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
    for k in ("ANTHROPIC_API_KEY", "TYPESAFE_API_KEY", "GITHUB_TOKEN"):
        env.pop(k, None)
    p = subprocess.Popen([sys.executable, "-m", "circulo.controle", "--data", str(data), "--porta", str(porta)], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        j = None
        for _ in range(60):
            try:
                j = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{porta}/api/vigia", timeout=1).read())
                break
            except Exception:
                time.sleep(0.5)
        assert j is not None, p.stderr.read()[-800:] if p.poll() is not None else "painel não respondeu"
        assert "sondas" in j
        from circulo.state import Store
        s = Store(data / "circulo.db")
        for _ in range(20):
            if s.get("controle_separado"):
                break
            time.sleep(0.2)
        assert s.get("controle_separado")["porta"] == porta and s.get("controle_separado")["pid"] == p.pid
    finally:
        p.terminate()
        p.wait(timeout=10)


def test_supervisor_reinicia_o_filho_e_desiste_depois_de_cair_demais(tmp_path, monkeypatch):
    class Falso:
        n = 0

        def __init__(self, cmd, **kw):
            Falso.n += 1
            self.pid = 100 + Falso.n
            self.returncode = 1

        def poll(self):
            return 1          # morreu

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 1
    monkeypatch.setattr(controle.subprocess, "Popen", Falso)
    avisos = []
    sup = controle.Supervisor(tmp_path, 8765, None, lambda m, k: avisos.append(m))
    assert sup.iniciar() and Falso.n == 1
    assert [sup.cuidar() for _ in range(3)] == ["reiniciado", "reiniciado", "reiniciado"] and Falso.n == 4
    assert sup.cuidar() == "desistiu" and sup.desistiu and avisos and "assume painel e SRE" in avisos[0]
    assert not sup.iniciar()                                                     # desistiu: não insiste
    monkeypatch.setenv("CIRCULO_CONTROLE_SEPARADO", "0")
    assert not controle.separado()


def test_loop_so_sobe_o_sre_dentro_dele_quando_nao_ha_controle(circle):
    class SupervisorFalso:
        chamadas = []

        def cuidar(self):
            self.chamadas.append("cuidar")
            return "vivo"

        def parar(self):
            self.chamadas.append("parar")
    circle.controle = SupervisorFalso()
    circle.run_forever(max_ticks=1, sleep=lambda s: None)
    assert "cuidar" in SupervisorFalso.chamadas and SupervisorFalso.chamadas[-1] == "parar"
    assert circle.vigia._thread is None or not circle.vigia._thread.is_alive()   # SRE ficou com o processo do controle

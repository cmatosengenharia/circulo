"""24/10: o giro ficou 6 h e meia na validação do corpo sem sinal de vida; o loop só reinicia entre giros."""
import sys
import time

from circulo import cao_de_guarda
from circulo.corpo import rodar_com_prazo
from circulo.self_dev import _git


def test_giro_preso_sem_sinal_encerra_o_processo(circle):
    s = circle.store
    agora = time.time()
    inicio = agora - 6 * 3600
    s.set("etapa", {"nome": "idle", "tick": 13692, "em": inicio, "tarefa": "atualizar_corpo"})
    s.set("fazendo", {"atualizar_corpo": {"o_que": "Validando", "desde": inicio, "em": inicio}})
    saidas, avisos = [], []
    assert cao_de_guarda.reiniciar_se_preso(s, inicio, lambda m, k: avisos.append(m), sair=saidas.append, agora=agora)
    assert saidas == [cao_de_guarda.CODIGO_SAIDA] and "atualizar_corpo" in s.get("ultimo_reinicio")["motivo"] and avisos


def test_giro_longo_com_passos_recentes_nao_e_preso(circle):
    s = circle.store
    agora = time.time()
    inicio = agora - 2 * 3600                                  # o Developer trabalhando há 2 h…
    s.set("etapa", {"nome": "developer", "tick": 1, "em": inicio})
    s.set("fazendo", {"corrigir_codigo": {"desde": inicio, "em": agora - 120}})   # …com um passo há 2 min
    assert cao_de_guarda.preso(s, inicio, agora) is None
    assert cao_de_guarda.preso(s, agora - 1800, agora) is None   # giro de 30 min nunca é olhado


def test_validacao_com_neto_segurando_a_saida_respeita_o_prazo(tmp_path):
    # o filho cria um neto que herda a saída e dorme; antes, o run(timeout) matava o filho e esperava o neto para sempre
    neto = "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)"
    t0 = time.time()
    codigo, saida = rodar_com_prazo([sys.executable, "-c", neto], tmp_path, {"PATH": "/usr/bin:/bin"}, 2)
    assert codigo == -1 and "passou de 2 s" in saida and time.time() - t0 < 20


def test_git_com_prazo_nao_pendura(tmp_path, monkeypatch):
    import circulo.self_dev as sd
    monkeypatch.setattr(sd, "GIT_PRAZO", 1)
    (tmp_path / "git").write_text("#!/bin/sh\nsleep 30\n")
    (tmp_path / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    t0 = time.time()
    assert _git(["fetch", "origin", "main"], tmp_path, check=False) == ""
    try:
        _git(["fetch", "origin", "main"], tmp_path)
        raise AssertionError("devia falhar")
    except RuntimeError as e:
        assert "passou de 1 s" in str(e)
    assert time.time() - t0 < 10

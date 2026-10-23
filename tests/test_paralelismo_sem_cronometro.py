"""Lição #2 (parte 1/4; antes lições #62 e #67): o teste de paralelismo do Arquiteto media o relógio de parede para provar
que 3 estudos rodaram juntos e falhava sob carga no CI. Paralelismo se prova com barreira, nunca com cronômetro: a
reprodução (portão do PR) recusa teste novo assim e este lint varre os que já existem."""
from pathlib import Path

from circulo.reproducao import provam_paralelismo_pelo_relogio

TESTES = Path(__file__).parent

CRONOMETRADO = '''
import time
def test_tres_em_paralelo():
    t0 = time.time()
    rodar()
    assert ok and time.time() - t0 < 0.55
def test_tres_ao_mesmo_tempo():
    juntos.wait()
def test_outro_assunto():
    assert time.monotonic() - t0 < 1
'''


def test_licao_2_portao_recusa_paralelismo_provado_por_cronometro():
    assert provam_paralelismo_pelo_relogio(CRONOMETRADO) == ["test_tres_em_paralelo"]


def test_licao_2_paralelismo_nao_se_prova_com_cronometro():
    culpados = [f"{arq.name}::{nome}" for arq in sorted(TESTES.glob("test_*.py"))
                for nome in provam_paralelismo_pelo_relogio(arq.read_text())]
    assert not culpados, f"paralelismo provado por tempo de parede (flaky sob carga): {culpados}"

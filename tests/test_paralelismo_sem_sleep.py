"""Lição #63 (item #144): o dublê do Developer em test_desenvolvedor_pega_itens_distintos_em_paralelo dormia 0,5 s para
o 1º item terminar por último. Sono não ordena threads sob carga e não prova que elas se sobrepuseram (em série o teste
passava igual). Paralelismo se prova com `threading.Barrier(n, timeout=...)` no dublê: a reprodução (portão do PR)
recusa teste novo assim e este lint varre os que já existem."""
from pathlib import Path

from circulo.reproducao import ordenam_paralelismo_por_sono

TESTES = Path(__file__).parent

DORMINDO = '''
import threading, time
class Agente:
    def run(self, task):
        time.sleep(0.5)
class Junto:
    def run(self, task):
        juntos.wait()
def test_dois_em_paralelo():
    rodar(Agente())
def test_dois_ao_mesmo_tempo():
    rodar(Junto())
def test_outro_assunto():
    rodar(Agente())
def test_espera_em_paralelo_com_prazo():
    while not pronto() and time.time() < fim:
        time.sleep(0.05)
'''


def test_licao_63_portao_recusa_paralelismo_ordenado_por_sono():
    assert ordenam_paralelismo_por_sono(DORMINDO) == ["test_dois_em_paralelo"]


def test_licao_63_paralelismo_nao_se_ordena_com_sono():
    culpados = [f"{arq.name}::{nome}" for arq in sorted(TESTES.glob("test_*.py"))
                for nome in ordenam_paralelismo_por_sono(arq.read_text())]
    assert not culpados, f"paralelismo ordenado por time.sleep num dublê (flaky sob carga, não prova sobreposição): {culpados}"

"""Lição #2 (parte 1/4): test_arquiteto_estuda_varios_itens_ao_mesmo_tempo, além da barreira, conferia o prefixo do nome
da thread do pool. O nome é detalhe de implementação (muda com o executor) e não prova sobreposição: quem prova é a
barreira, que só abre com todos dentro ao mesmo tempo. A reprodução (portão do PR) recusa teste novo assim e este lint
varre os que já existem."""
from pathlib import Path

from circulo.reproducao import provam_paralelismo_pelo_nome_da_thread

TESTES = Path(__file__).parent

PELO_NOME = '''
import threading
def test_tres_em_paralelo():
    def gen():
        vistos.add(threading.current_thread().name)
def test_tres_ao_mesmo_tempo():
    juntos.wait()
def test_outro_assunto():
    threading.current_thread().name
'''


def test_licao_2_lint_acha_teste_de_paralelismo_pelo_nome_da_thread():
    assert provam_paralelismo_pelo_nome_da_thread(PELO_NOME) == ["test_tres_em_paralelo"]


def test_licao_2_paralelismo_nao_se_prova_pelo_nome_da_thread():
    culpados = [f"{arq.name}::{nome}" for arq in sorted(TESTES.glob("test_*.py"))
                for nome in provam_paralelismo_pelo_nome_da_thread(arq.read_text())]
    assert not culpados, f"paralelismo conferido pelo nome da thread (detalhe do executor; use a barreira): {culpados}"

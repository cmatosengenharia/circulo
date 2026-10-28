import sys, os, tempfile
from pathlib import Path
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.getcwd(), os.getcwd() + "/tests"]
os.environ["CIRCULO_SEM_DEVELOPER"] = "1"; os.environ["CIRCULO_GRAFT"] = "0"
import conftest, test_roteiro, test_sem_pergunta_origem
for f in (test_roteiro.test_ponto_unico_recusa_item_sem_pergunta_licao_15, test_sem_pergunta_origem.test_gravar_item_exige_pergunta_existente_licao_15):
    for pid in (None, 0, -1, 987654):
        tmp = Path(tempfile.mkdtemp())
        f(conftest.Circle(tmp, jev=conftest.LocalJev(), now=conftest.Clock(conftest.NOON)), pid)
        print("PASS", f.__name__, pid)

"""lição #50: a main ficou vermelha no 93fe8ef (push às 21:19 de Brasília, 00:19 UTC) porque um teste tirava o dia de
`date.today` e o orçamento, de America/Sao_Paulo. Qualquer "agora" sem fuso é a mesma armadilha, no código e nos
testes: o fuso é sempre o budget.TZ."""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SEM_FUSO = re.compile(r"\b(?:date\.today|datetime\.today|datetime\.now|time\.localtime)\(\)")


def test_licao_50_nenhum_agora_pelo_fuso_da_maquina_no_pacote_nem_nos_testes():
    arquivos = [*(RAIZ / "circulo").glob("*.py"), *(RAIZ / "tests").glob("*.py")]
    usam = sorted(p.name for p in arquivos if p.name not in (Path(__file__).name, "test_arquitetura.py")
                  and SEM_FUSO.search(p.read_text(encoding="utf-8")))
    assert not usam, f"'agora' pelo fuso da máquina (UTC no CI) em vez do budget.TZ: {usam}"

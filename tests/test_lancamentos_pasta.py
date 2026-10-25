import shutil
from pathlib import Path

from circulo.lancamentos_pasta import ingerir_pasta
from circulo.perguntas import _m_lancamentos

FIX = Path(__file__).parent / "fixtures"


def lancamentos(store) -> int:
    return _m_lancamentos(store, None)[1]["lancamentos"]


def _pasta(tmp_path: Path) -> Path:
    pasta = tmp_path / "extratos"
    pasta.mkdir()
    for nome in ("extrato_anonimo.csv", "extrato_anonimo.ofx"):
        shutil.copy(FIX / nome, pasta / nome)
    return pasta


def test_passada_grava_lancamentos_e_move_para_processados(circle, tmp_path):
    s = circle.store
    pasta = _pasta(tmp_path)
    assert lancamentos(s) == 0
    n = ingerir_pasta(pasta, s)
    assert n > 0 and lancamentos(s) == n
    assert sorted(p.name for p in (pasta / "processados").iterdir()) == ["extrato_anonimo.csv",
                                                                         "extrato_anonimo.ofx"]
    assert not list(pasta.glob("*.csv")) and not list(pasta.glob("*.ofx"))


def test_segunda_passada_com_os_mesmos_arquivos_insere_zero(circle, tmp_path):
    s = circle.store
    pasta = _pasta(tmp_path)
    n = ingerir_pasta(pasta, s)
    for nome in ("extrato_anonimo.csv", "extrato_anonimo.ofx"):
        shutil.copy(FIX / nome, pasta / nome)
    assert ingerir_pasta(pasta, s) == 0
    assert lancamentos(s) == n


def test_arquivo_corrompido_vai_para_rejeitados_e_nao_interrompe_os_demais(circle, tmp_path):
    s = circle.store
    pasta = _pasta(tmp_path)
    (pasta / "a_quebrado.csv").write_text("foo;bar\n1;2\n", encoding="utf-8")
    (pasta / "b_sem_data.ofx").write_text("<STMTTRN><TRNAMT>-1,00<MEMO>x</STMTTRN>", encoding="utf-8")
    (pasta / "notas.txt").write_text("ignorar", encoding="utf-8")
    assert ingerir_pasta(pasta, s) > 0
    assert sorted(p.name for p in (pasta / "rejeitados").iterdir()) == ["a_quebrado.csv", "b_sem_data.ofx"]
    assert len(list((pasta / "processados").iterdir())) == 2
    assert (pasta / "notas.txt").exists()


def test_pasta_inexistente_ou_vazia_insere_zero(circle, tmp_path):
    assert ingerir_pasta(tmp_path / "nao_existe", circle.store) == 0
    assert ingerir_pasta(tmp_path, circle.store) == 0

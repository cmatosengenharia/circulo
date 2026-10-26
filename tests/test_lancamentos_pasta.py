import json
import shutil
from pathlib import Path

from circulo.lancamentos_pasta import diagnosticar, ingerir_pasta
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


def _varreduras(s) -> list[dict]:
    rows = s.q("SELECT r.entradas FROM intencoes r JOIN intencoes i ON i.seq=r.ref "
               "WHERE r.tipo='resultado' AND i.acao='lancamentos:varredura' ORDER BY r.seq")
    return [{k: v for k, v in json.loads(r["entradas"]).items() if k != "detalhe"} for r in rows]


def test_giro_do_loop_ingere_a_pasta_de_extratos_e_registra_a_varredura(circle):
    """Ponta a ponta: a fixture cai em <data>/extratos, o giro a ingere (lancamentos 0 → >0) e a varredura vira
    evento do loop com total, importados e ignorados com motivo; a segunda varredura com os mesmos arquivos soma 0."""
    s = circle.store
    pasta = circle.data_dir / "extratos"
    pasta.mkdir()
    for nome in ("extrato_anonimo.csv", "extrato_anonimo.ofx"):
        shutil.copy(FIX / nome, pasta / nome)
    (pasta / "a_quebrado.csv").write_text("foo;bar\n1;2\n", encoding="utf-8")
    assert lancamentos(s) == 0
    circle.tick()
    total = lancamentos(s)
    assert total >= 1
    [v1] = _varreduras(s)
    assert v1["novos"] == v1["total"] == total
    assert sorted(a["arquivo"] for a in v1["importados"]) == ["extrato_anonimo.csv", "extrato_anonimo.ofx"]
    assert [i["arquivo"] for i in v1["ignorados"]] == ["a_quebrado.csv"] and v1["ignorados"][0]["motivo"]
    assert s.get("lancamentos_pasta") == v1

    for nome in ("extrato_anonimo.csv", "extrato_anonimo.ofx"):
        shutil.copy(FIX / nome, pasta / nome)
    circle.tick()
    v2 = _varreduras(s)[-1]
    assert v2["novos"] == 0 and v2["total"] == total == lancamentos(s)
    assert s.one("SELECT COUNT(*) AS n FROM (SELECT import_key FROM ledger GROUP BY import_key HAVING COUNT(*)>1)")["n"] == 0


def test_giro_sem_extrato_novo_nao_registra_varredura(circle):
    circle.tick()
    (circle.data_dir / "extratos").mkdir()
    circle.tick()
    assert _varreduras(circle.store) == []


def test_diagnostico_da_pasta_separa_os_quatro_motivos_de_zero_lancamentos(tmp_path):
    """lancamentos=0 com a ingestão pronta não dizia se faltava arquivo ou se o parser recusava tudo."""
    pasta = tmp_path / "extratos"
    assert diagnosticar(pasta) == "pasta_inexistente"
    pasta.mkdir()
    (pasta / "notas.txt").write_text("ignorar", encoding="utf-8")
    assert diagnosticar(pasta) == "vazia"
    (pasta / "rejeitados").mkdir()
    for nome in ("a.csv", "b.ofx"):
        (pasta / "rejeitados" / nome).write_text("x", encoding="utf-8")
    assert diagnosticar(pasta) == "so_rejeitados(2)"
    (pasta / "c.csv").write_text("x", encoding="utf-8")
    (pasta / "processados").mkdir()
    (pasta / "processados" / "d.ofx").write_text("x", encoding="utf-8")
    assert diagnosticar(pasta) == "ok(2)"


def test_todo_giro_grava_o_motivo_da_ingestao_no_estado(circle):
    s = circle.store
    pasta = circle.data_dir / "extratos"
    circle.tick()
    assert s.get("lancamentos_motivo") == "pasta_inexistente"
    pasta.mkdir()
    circle.tick()
    assert s.get("lancamentos_motivo") == "vazia"
    (pasta / "a_quebrado.csv").write_text("foo;bar\n1;2\n", encoding="utf-8")
    circle.tick()
    assert lancamentos(s) == 0 and s.get("lancamentos_motivo") == "so_rejeitados(1)"
    shutil.copy(FIX / "extrato_anonimo.csv", pasta / "extrato_anonimo.csv")
    circle.tick()
    assert lancamentos(s) > 0 and s.get("lancamentos_motivo") == "ok(1)"

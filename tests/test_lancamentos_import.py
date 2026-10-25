import hashlib
from pathlib import Path

from circulo.lancamentos_import import Linha, importar, parse_extrato
from circulo.perguntas import _m_lancamentos

FIX = Path(__file__).parent / "fixtures"
CSV = (FIX / "extrato_anonimo.csv").read_text(encoding="utf-8")
OFX = (FIX / "extrato_anonimo.ofx").read_text(encoding="utf-8")


def lancamentos(store) -> int:
    return _m_lancamentos(store, None)[1]["lancamentos"]


def test_csv_vira_data_iso_centavos_descricao_normalizada():
    linhas = parse_extrato(CSV, "csv")
    assert len(linhas) == 6
    assert linhas[0][:3] == ("2026-10-02", -1250, "padaria pao bom")
    assert linhas[2][:3] == ("2026-10-03", -123456, "supermercado exemplo")
    assert linhas[3][:3] == ("2026-10-05", 500000, "salario empresa x")
    assert linhas[4][2] == "posto combustivel y"
    assert all(isinstance(lin.centavos, int) for lin in linhas)


def test_parse_e_deterministico():
    assert parse_extrato(CSV, "csv") == parse_extrato(CSV, "csv")
    assert parse_extrato(OFX, "ofx") == parse_extrato(OFX, "ofx")


def test_duas_compras_identicas_no_mesmo_dia_nao_colapsam():
    a, b = parse_extrato(CSV, "csv")[:2]
    assert a[:3] == b[:3] and a.chave != b.chave
    esperado = hashlib.sha256("2026-10-02|-1250|padaria pao bom|1".encode()).hexdigest()
    assert b.chave == esperado
    assert len({lin.chave for lin in parse_extrato(CSV, "csv")}) == 6


def test_ofx_usa_fitid_e_cai_no_hash_sem_ele():
    linhas = parse_extrato(OFX, "ofx")
    assert [lin.chave for lin in linhas[:3]] == ["A0001", "A0002", "A0003"]
    assert linhas[0] == Linha("2026-10-02", -1250, "padaria pao bom", "A0001")
    assert linhas[2][:3] == ("2026-10-05", 500000, "salario empresa x")
    assert linhas[3][:3] == ("2026-10-09", -3890, "farmacia z")
    assert linhas[3].chave == hashlib.sha256("2026-10-09|-3890|farmacia z|0".encode()).hexdigest()


def test_primeira_importacao_insere_n_e_a_segunda_zero(circle):
    s = circle.store
    assert lancamentos(s) == 0
    assert importar(s, CSV, "csv") == 6
    assert lancamentos(s) == 6
    assert importar(s, CSV, "csv") == 0
    assert lancamentos(s) == 6
    receita = s.one("SELECT kind, amount_cents, category FROM ledger WHERE description='salario empresa x'")
    assert tuple(receita) == ("receita", 500000, "renda")
    assert s.one("SELECT COUNT(*) n FROM ledger WHERE kind='despesa' AND amount_cents=1250")["n"] == 2


def test_ofx_reimportado_insere_zero(circle):
    s = circle.store
    assert importar(s, OFX, "ofx") == 4
    assert importar(s, OFX, "ofx") == 0
    assert lancamentos(s) == 4

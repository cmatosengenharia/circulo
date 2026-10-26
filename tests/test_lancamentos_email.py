from pathlib import Path

import pytest

from circulo.lancamentos_email import importar_emails, parse_email, parse_emails
from circulo.lancamentos_import import Linha, chave_hash, importar
from circulo.lancamentos_pasta import ingerir_pasta
from circulo.perguntas import _m_lancamentos

FIX = Path(__file__).parent / "fixtures"
EMAIL = (FIX / "email_notificacao_anonimo.txt").read_text(encoding="utf-8")
OUTRA_DA_TARDE = EMAIL.replace("12:31", "18:02")      # mesma padaria, mesmo valor e dia: outra compra legítima
EXTRATO = "Data;Descrição;Valor\n02/10/2026;PADARIA PÃO BOM;-12,50\n"


def lancamentos(store) -> int:
    return _m_lancamentos(store, None)[1]["lancamentos"]


def test_email_vira_data_iso_centavos_e_descricao_normalizada():
    assert parse_email(EMAIL) == ("2026-10-02", -1250, "padaria pao bom")
    assert parse_emails([EMAIL]) == [Linha("2026-10-02", -1250, "padaria pao bom",
                                           chave_hash("2026-10-02", -1250, "padaria pao bom", 0))]


def test_email_sem_valor_e_rejeitado():
    with pytest.raises(ValueError):
        parse_email(EMAIL.replace("Valor: R$ 12,50", ""))


def test_fixture_gera_1_e_reimportar_mantem_1(circle):
    s = circle.store
    assert lancamentos(s) == 0
    assert importar_emails(s, [EMAIL]) == 1
    assert lancamentos(s) == 1
    assert importar_emails(s, [EMAIL]) == 0
    assert lancamentos(s) == 1


def test_extrato_e_email_do_mesmo_lancamento_resultam_em_1(circle):
    """A chave cruzada só bate porque as duas fontes normalizam a descrição antes do hash."""
    s = circle.store
    assert importar(s, EXTRATO, "csv") == 1
    assert importar_emails(s, [EMAIL]) == 0
    assert lancamentos(s) == 1


OFX_SEM_FITID = ("<OFX><BANKTRANLIST><STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261002120000[-3:BRT]<TRNAMT>-12.50"
                 "<MEMO>PADARIA PAO BOM</STMTTRN></BANKTRANLIST></OFX>")


def test_eml_na_pasta_do_loop_vira_lancamento_e_nao_duplica_com_reimportacao_nem_com_o_ofx(circle):
    """Ponta a ponta: o e-mail exportado cai em <data>/extratos e o giro o ingere (lancamentos 0 → 1); o mesmo
    e-mail de novo e o mesmo lançamento no OFX sem FITID somam 0."""
    s = circle.store
    pasta = circle.data_dir / "extratos"
    pasta.mkdir()
    (pasta / "compra.eml").write_text(EMAIL, encoding="utf-8")
    assert lancamentos(s) == 0
    circle.tick()
    assert lancamentos(s) == 1
    assert (pasta / "processados" / "compra.eml").exists()

    (pasta / "compra.eml").write_text(EMAIL, encoding="utf-8")
    (pasta / "extrato.ofx").write_text(OFX_SEM_FITID, encoding="utf-8")
    circle.tick()
    assert s.get("lancamentos_pasta")["novos"] == 0
    assert lancamentos(s) == 1


def test_dois_eml_identicos_na_mesma_passada_sao_duas_compras(circle):
    pasta = circle.data_dir / "extratos"
    pasta.mkdir()
    (pasta / "a.eml").write_text(EMAIL, encoding="utf-8")
    (pasta / "b.eml").write_text(OUTRA_DA_TARDE, encoding="utf-8")
    (pasta / "c.eml").write_text(EMAIL.replace("Valor: R$ 12,50", ""), encoding="utf-8")
    assert ingerir_pasta(pasta, circle.store) == 2
    assert [p.name for p in (pasta / "rejeitados").iterdir()] == ["c.eml"]


def test_duas_compras_identicas_legitimas_resultam_em_2(circle):
    s = circle.store
    assert importar_emails(s, [EMAIL, OUTRA_DA_TARDE]) == 2
    assert importar_emails(s, [EMAIL, OUTRA_DA_TARDE]) == 0
    assert lancamentos(s) == 2

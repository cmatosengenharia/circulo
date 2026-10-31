from datetime import date

import pytest

from circulo.lancamento_manual import Manual, parse_linha_manual, registrar_linha_manual
from circulo.lancamentos_import import chave_hash
from circulo.perguntas import _m_lancamentos

HOJE = date(2026, 10, 28)


def lancamentos(store) -> int:
    return _m_lancamentos(store, None)[1]["lancamentos"]


@pytest.mark.parametrize("texto, esperado", [
    ("mercado 45,90 ontem", Manual("2026-10-27", -4590, "mercado", "mercado", "necessario", 0)),
    ("Padaria Pão Bom R$ 12,50 hoje", Manual("2026-10-28", -1250, "padaria pao bom", "alimentacao", "escolha", 0)),
    ("02/10 farmácia 1.234,5", Manual("2026-10-02", -123450, "farmacia", "saude", "necessario", 0)),
    ("presente 30", Manual("2026-10-28", -3000, "presente", "outros", "escolha", 0)),
    ("salario +5.000,00 05/10/2026", Manual("2026-10-05", 500000, "salario", "renda", "necessario", 0)),
    ("31/12 ceia 80,00", Manual("2025-12-31", -8000, "ceia", "outros", "escolha", 0)),
    ("mercado 45,90 ontem #2", Manual("2026-10-27", -4590, "mercado", "mercado", "necessario", 1)),
])
def test_linha_valida_vira_data_valor_categoria_e_descricao(texto, esperado):
    assert parse_linha_manual(texto, HOJE) == esperado


@pytest.mark.parametrize("texto", [
    "mercado ontem",                 # sem valor
    "mercado 45,90 12,00",           # dois valores
    "mercado 45,90 31/02",           # data inválida
    "mercado 45,90 ontem hoje",      # duas datas
    "45,90 ontem",                   # sem descrição
    "",
    "mercado 0,00",
])
def test_linha_ambigua_vira_pergunta_curta_e_nao_grava(circle, texto):
    pergunta = parse_linha_manual(texto, HOJE)
    assert isinstance(pergunta, str) and pergunta.endswith("?") and len(pergunta) <= 120
    assert registrar_linha_manual(circle.store, texto, HOJE) == (0, pergunta)
    assert lancamentos(circle.store) == 0


def test_primeira_entrada_grava_e_repetir_nao_duplica(circle):
    s = circle.store
    assert lancamentos(s) == 0
    assert registrar_linha_manual(s, "mercado 45,90 ontem", HOJE) == (1, None)
    assert lancamentos(s) == 1
    r = s.one("SELECT kind, amount_cents, description, category, tag, import_key FROM ledger")
    assert dict(r) == {"kind": "despesa", "amount_cents": 4590, "description": "mercado", "category": "mercado",
                       "tag": "necessario", "import_key": chave_hash("2026-10-27", -4590, "mercado", 0)}
    novos, pergunta = registrar_linha_manual(s, "Mercado  45,90 ontem", HOJE)
    assert novos == 0 and "#2" in pergunta
    assert lancamentos(s) == 1


def test_segundo_gasto_igual_entra_com_sufixo_de_ocorrencia(circle):
    s = circle.store
    registrar_linha_manual(s, "mercado 45,90 ontem", HOJE)
    assert registrar_linha_manual(s, "mercado 45,90 ontem #2", HOJE) == (1, None)
    assert registrar_linha_manual(s, "mercado 45,90 ontem #2", HOJE)[0] == 0
    assert lancamentos(s) == 2


def test_circulo_lancar_grava_e_a_repeticao_pergunta(circle, capsys):
    from circulo.cli import main
    main(["--data", str(circle.data_dir), "lancar", "mercado", "45,90"])
    main(["--data", str(circle.data_dir), "lancar", "mercado", "45,90"])
    main(["--data", str(circle.data_dir), "lancar", "mercado", "ontem"])
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "1 lançamento gravado." and "#2" in out[1] and out[2] == "Qual foi o valor de 'mercado'?"
    assert lancamentos(circle.store) == 1


def test_mesma_chave_do_extrato_sem_fitid(circle):
    from circulo.lancamentos_import import importar
    s = circle.store
    assert importar(s, "Data;Descrição;Valor\n27/10/2026;MERCADO;-45,90\n", "csv") == 1
    assert registrar_linha_manual(s, "mercado 45,90 ontem", HOJE)[0] == 0
    assert lancamentos(s) == 1


def test_lote_de_30_linhas_grava_26_ignora_2_duplicadas_e_pergunta_nas_2_ambiguas(circle):
    from circulo.lancamento_manual import registrar_lote
    validas = [f"gasto{i} {10 + i},50 {i + 1:02d}/10" for i in range(26)]
    texto = "\n".join([*validas[:13], "mercado ontem", validas[0], "", *validas[13:], "farmacia 10 20",
                       "  " + validas[5] + "  "])
    r = registrar_lote(circle.store, texto, HOJE)
    assert (r.gravadas, r.duplicadas) == (26, 2)
    assert r.ambiguas == [("mercado ontem", "Qual foi o valor de 'mercado'?"),
                          ("farmacia 10 20", "Qual é o valor: 10 ou 20?")]
    assert r.faltam_lancamentos == 4 and lancamentos(circle.store) == 26
    assert r.resumo().startswith("26 gravadas, 2 duplicadas, 2 ambíguas; faltam 4 lançamentos para o mínimo de 30.")
    assert "mercado ontem → Qual foi o valor de 'mercado'?" in r.resumo()
    assert registrar_lote(circle.store, texto, HOJE)[:2] == (0, 28)


def test_circulo_lancar_le_o_lote_da_entrada_padrao(circle, capsys, monkeypatch):
    import io

    from circulo.cli import main
    monkeypatch.setattr("sys.stdin", io.StringIO("mercado 45,90 ontem\npadaria 12,00 hoje\nmercado ontem\n"))
    main(["--data", str(circle.data_dir), "lancar", "-"])
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "2 gravadas, 0 duplicadas, 1 ambíguas; faltam 28 lançamentos para o mínimo de 30."
    assert lancamentos(circle.store) == 2

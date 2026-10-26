"""Gasto diário do Cursor em US$ por assunto e tipo de tarefa (lançamento rápido ou CSV exportado do dashboard), com a
projeção do dia em que os US$ 250 do mês acabam (média móvel de 7 dias) e alerta quando ela cai antes do fim do mês."""
from datetime import date

from circulo.gasto_cursor import avisar, etiquetados_pct, importar_csv, lancar, main, projecao
from circulo.state import Store

CSV = """Date,Kind,Model,Max Mode,Input (w/ Cache Write),Input (w/o Cache Write),Cache Read,Output Tokens,Total Tokens,Cost
"2026-10-20T14:03:11.000Z","Included","claude-4.5-sonnet","No","0","1200","30000","800","32000","$1.25"
"2026-10-21T09:00:00.000Z","Usage-based","gpt-5","No","0","500","0","100","600","0.40"
"2026-10-21T09:05:00.000Z","Errored, Not Charged","gpt-5","No","0","0","0","0","0","Included"
"""


def test_lancamento_rapido_em_centavos_de_dolar_com_assunto_e_tipo():
    s = Store()
    lancar(s, "3,20", assunto="circulo", tipo="bugfix", modelo="sonnet", tokens=1500, dia=date(2026, 10, 3))
    lancar(s, "$0.05", dia=date(2026, 10, 3))
    r = s.q("SELECT dia, assunto, tipo, modelo, tokens, centavos, origem FROM gasto_cursor ORDER BY id")
    assert [tuple(x) for x in r] == [("2026-10-03", "circulo", "bugfix", "sonnet", 1500, 320, "manual"),
                                     ("2026-10-03", None, None, None, 0, 5, "manual")]
    assert etiquetados_pct(s) == 50.0


def test_csv_do_cursor_vira_linhas_e_nao_duplica_ao_reimportar():
    s = Store()
    assert importar_csv(s, CSV, assunto="circulo") == 2      # a linha sem custo (Included/erro) fica de fora
    assert importar_csv(s, CSV, assunto="circulo") == 0
    r = s.q("SELECT dia, modelo, tokens, centavos, assunto, origem FROM gasto_cursor ORDER BY dia")
    assert [tuple(x) for x in r] == [("2026-10-20", "claude-4.5-sonnet", 32000, 125, "circulo", "csv"),
                                     ("2026-10-21", "gpt-5", 600, 40, "circulo", "csv")]


def test_projecao_pela_media_movel_de_7_dias_e_alerta_antes_do_fim_do_mes():
    s = Store()
    for d in range(1, 11):                                    # US$ 12/dia de 1 a 10/out: US$ 120 gastos
        lancar(s, "12", assunto="circulo", tipo="feature", dia=date(2026, 10, d))
    p = projecao(s, hoje=date(2026, 10, 10))
    assert p["gasto_mes"] == 12000 and p["media_7d"] == 1200 and p["restante"] == 13000
    assert p["esgota_em"] == "2026-10-21"                     # 130 / 12 = 10,8 dias → dia 21
    assert p["antes_do_fim"] is True
    avisos = []
    assert avisar(s, lambda m, k: avisos.append((m, k)), hoje=date(2026, 10, 10)) is True
    assert avisar(s, lambda m, k: avisos.append((m, k)), hoje=date(2026, 10, 10)) is False   # uma vez por dia
    assert len(avisos) == 1 and "21/10" in avisos[0][0] and avisos[0][1] == "orcamento"


def test_sem_alerta_quando_o_ritmo_cabe_no_mes_e_mes_novo_zera():
    s = Store()
    lancar(s, "200", dia=date(2026, 9, 30))                   # mês passado não conta no limite deste
    for d in range(1, 8):
        lancar(s, "5", dia=date(2026, 10, d))
    p = projecao(s, hoje=date(2026, 10, 7))
    assert p["gasto_mes"] == 3500 and p["antes_do_fim"] is False
    assert avisar(s, lambda m, k: None, hoje=date(2026, 10, 7)) is False
    assert projecao(Store(), hoje=date(2026, 10, 7))["esgota_em"] is None


def test_comando_lanca_importa_e_mostra_a_projecao(tmp_path, capsys):
    main(["--data", str(tmp_path), "4,50", "--assunto", "circulo", "--tipo", "refactor", "--modelo", "opus"])
    arq = tmp_path / "uso.csv"
    arq.write_text(CSV, encoding="utf-8")
    main(["--data", str(tmp_path), "--csv", str(arq)])
    out = capsys.readouterr().out
    assert "US$ 4.50" in out and "2 linhas importadas" in out and "esgota" in out
    s = Store(tmp_path / "circulo.db")
    assert s.one("SELECT COUNT(*) n FROM gasto_cursor")["n"] == 3

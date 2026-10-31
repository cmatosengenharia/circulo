"""Latência pedido→merge (pergunta do conselho #695): a etapa dominante de cada um dos 5 PRs mais lentos da semana,
derivada só das decisões do gate (tabela merges), sem gravar nada novo."""
import time

from circulo import latencia
from circulo.cli import main as cli
from circulo.state import Store

# a sequência do PR 287 no gate_recente: 4 'checks em andamento', 1 'atrás da main' e o merge
PR_287 = [(0, 0, "checks em andamento: test, lint"),
          (420, 0, "checks em andamento: test"),
          (900, 0, "branch 2 commit(s) atrás da main: atualizada, o CI roda de novo"),
          (960, 0, "checks em andamento: test, lint"),
          (1500, 0, "checks em andamento: test"),
          (1800, 1, "todos os gates passaram")]


def _gate(s, pr, decisoes, t0):
    for dt, merged, motivo in decisoes:
        s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,?,?,?,?,?)",
            (pr, "a", merged, motivo, "{}", t0 + dt))


def test_pr_287_sai_com_ci_como_etapa_dominante(tmp_path):
    s = Store(str(tmp_path / "circulo.db"))
    agora = time.time()
    _gate(s, 287, PR_287, agora - 3600)
    [pr] = latencia.mais_lentos(s, agora=agora)
    assert pr["pr"] == 287 and pr["decisoes"] == 6 and pr["total_s"] == 1800
    assert pr["etapa"] == "ci" and pr["pct"] == 97          # 1740 s esperando o CI, 60 s no rebase
    assert pr["por_etapa"] == {"ci": 1740.0, "rebase": 60.0}


def test_so_os_5_mais_lentos_mergeados_na_semana_e_todos_com_etapa(tmp_path):
    s = Store(str(tmp_path / "circulo.db"))
    agora = time.time()
    for n in range(7):                                       # PR 100+n leva (n+1) h, quase todo atrás da main
        _gate(s, 100 + n, [(0, 0, "branch 1 commit(s) atrás da main: atualizada, o CI roda de novo"),
                           ((n + 1) * 3600 - 60, 0, "checks em andamento: test"),
                           ((n + 1) * 3600, 1, "todos os gates passaram")], agora - 86400)
    _gate(s, 50, [(0, 0, "checks em andamento: test"), (24 * 3600, 1, "todos os gates passaram")], agora - 9 * 86400)
    _gate(s, 60, [(0, 0, "checks em andamento: test")], agora - 600)               # aberto: não mergeou
    lentos = latencia.mais_lentos(s, agora=agora)
    assert [p["pr"] for p in lentos] == [106, 105, 104, 103, 102]
    assert all(p["etapa"] == "rebase" and p["pct"] >= 97 for p in lentos)


def test_console_mostra_a_etapa_dominante(tmp_path, capsys):
    s = Store(str(tmp_path / "circulo.db"))
    _gate(s, 287, PR_287, time.time() - 3600)
    cli(["--data", str(tmp_path), "latencia"])
    saida = capsys.readouterr().out
    assert "PR #287" in saida and "CI 97%" in saida

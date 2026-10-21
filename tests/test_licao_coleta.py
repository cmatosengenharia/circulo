"""Lição #9: erro de coleta do pytest assinado pelo módulo e pela exceção (não pelo banner '=== ERRORS ==='),
barrado por `pytest --collect-only -q` antes da suíte e fechado pelo collect-only verde na main."""
import subprocess

from test_self_dev import FakeGH, repo  # noqa: F401 — fixture do repositório

from circulo.licoes import assinatura_de, coletar_no_main
from circulo.reparo import DeveloperComReparo

# saídas gravadas do pytest (`-q -x --tb=short`) com erro de coleta em dois módulos diferentes
COLETA_A = """\
==================================== ERRORS ====================================
___________________ ERROR collecting tests/test_auditoria.py ___________________
ImportError while importing test module '/Users/x/Projects/.circulo-wt-48/tests/test_auditoria.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/homebrew/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/test_auditoria.py:5: in <module>
    from circulo.auditoria import trilha
E   ModuleNotFoundError: No module named 'circulo.auditoria'
=========================== short test summary info ============================
ERROR tests/test_auditoria.py
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 error in 0.31s
"""
COLETA_B = """\
==================================== ERRORS ====================================
____________________ ERROR collecting tests/test_vigia.py _____________________
ImportError while importing test module '/Users/x/Projects/.circulo-wt-77/tests/test_vigia.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
tests/test_vigia.py:3: in <module>
    from circulo.vigia import porteiro
E   ImportError: cannot import name 'porteiro' from 'circulo.vigia' (/Users/x/Projects/.circulo-wt-77/circulo/vigia.py)
=========================== short test summary info ============================
ERROR tests/test_vigia.py
1 error in 0.20s
"""
BANNER = "developer:testes:errors"


def test_licao_9_erro_de_coleta_vira_chave_de_modulo_e_excecao_e_nao_o_banner(circle):
    """lição #9: dois módulos com erro de coleta diferente geram chaves distintas, nenhuma igual ao banner."""
    a, b = assinatura_de("developer:testes", COLETA_A), assinatura_de("developer:testes", COLETA_B)
    assert a == "developer:testes:coleta:tests/test_auditoria.py:ModuleNotFoundError:circulo.auditoria"
    assert b == "developer:testes:coleta:tests/test_vigia.py:ImportError:porteiro"
    assert assinatura_de("developer:testes", COLETA_A.replace("wt-48", "wt-90")) == a      # o worktree não entra
    # a saída focada pode perder o cabeçalho: o resumo do pytest ainda dá o módulo
    so_resumo = COLETA_A[COLETA_A.index("E   Module"):]
    assert assinatura_de("developer:testes", so_resumo) == a
    L = circle.licoes
    for saida in (COLETA_A, COLETA_B):
        L.verificar("developer:testes", False, sujeito="wt-1", motivo=saida)
    lics = [dict(r) for r in circle.store.q("SELECT assinatura, descricao FROM licoes ORDER BY id")]
    assert [x["assinatura"] for x in lics] == [a, b]
    assert all("ERRORS" not in x["descricao"] and ":coleta:" not in x["descricao"] for x in lics)
    assert "tests/test_auditoria.py" in lics[0]["descricao"] and "ModuleNotFoundError" in lics[0]["descricao"]


def test_licao_9_collect_only_verde_na_main_evidencia_e_a_mesma_chave_reabre(circle):
    """lição #9: uma execução verde do collect-only no sha da main basta; só a mesma chave arquivo+exceção reabre."""
    L = circle.licoes
    circle.store.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,"
                   "primeira_tick,ultima_tick,created_at,updated_at,camada) VALUES(?,?,?,?,?,'validada',2,1,0,0,0,0,'ci')",
                   (BANNER, "developer:testes", "trabalho", "developer:testes: " + "=" * 36 + " ERRORS " + "=" * 28, "x"))
    L.verificar("developer:testes", False, motivo=COLETA_A)
    L.verificar("developer:testes", False, motivo=COLETA_B)
    assert L.a_checar_no_main()
    log = L.checar_coleta("aaa111", 0, "3 tests collected in 0.1s")
    status = [r["status"] for r in circle.store.q("SELECT status FROM licoes ORDER BY id")]
    assert status == ["evidenciada"] * 3 and len(log) == 3
    assert not L.a_checar_no_main()
    L.checar_coleta("bbb222", 2, COLETA_B)                # volta só a chave do vigia, num sha posterior
    status = [r["status"] for r in circle.store.q("SELECT status FROM licoes ORDER BY id")]
    assert status == ["evidenciada", "evidenciada", "reincidente"]
    L.checar_coleta("bbb222", 0, "")
    assert circle.store.one("SELECT status FROM licoes WHERE id=3")["status"] == "evidenciada"


def test_licao_9_coleta_roda_no_worktree_do_main_e_devolve_o_exit_bruto(tmp_path):
    """lição #9: o veredito vem do exit code do `pytest --collect-only -q` no main, não do resumo."""
    def git(*a):
        return subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, text=True, check=True).stdout.strip()
    git("init", "-q", "-b", "main")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("import nao_existe_xyz\n\n\ndef test_ok():\n    assert True\n")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
    sha, code, saida = coletar_no_main(tmp_path, git("rev-parse", "main"))
    assert code != 0 and assinatura_de("developer:testes", saida).endswith(
        ":coleta:tests/test_a.py:ModuleNotFoundError:nao_existe_xyz")
    assert len(git("worktree", "list").splitlines()) == 1


def test_licao_9_collect_only_barra_antes_da_suite_do_developer(circle, repo, tmp_path):  # noqa: F811
    """lição #9: com o pytest do loop, o Developer roda `--collect-only -q` antes da suíte; erro de coleta para ali."""
    wt, marca = tmp_path / "wt", tmp_path / "sessoes.txt"
    (wt / "tests").mkdir(parents=True)
    (wt / "conftest.py").write_text(f"def pytest_sessionstart(session):\n    with open({str(marca)!r}, 'a') as f:\n"
                                    "        f.write(str(session.config.option.collectonly) + '\\n')\n")
    (wt / "tests" / "test_a.py").write_text("import nao_existe_xyz\n\n\ndef test_ok():\n    assert True\n")
    dev = DeveloperComReparo(circle.ctx, repo, None, FakeGH(), lint_cmd=[])
    ok, _ = dev.verificar(wt)
    pontos = [dict(r) for r in circle.store.q("SELECT ponto, ok, assinatura FROM verificacoes WHERE ponto LIKE 'developer:%' ORDER BY id")]
    assert not ok and [(p["ponto"], p["ok"]) for p in pontos] == [("developer:testes", 0)]
    assert pontos[0]["assinatura"] == "developer:testes:coleta:tests/test_a.py:ModuleNotFoundError:nao_existe_xyz"
    assert marca.read_text().split() == ["True"]                  # só a coleta rodou: a suíte nem começou
    (wt / "tests" / "test_a.py").write_text("def test_ok():\n    assert True\n")
    ok, _ = dev.verificar(wt)
    assert ok and marca.read_text().split() == ["True", "True", "False"]

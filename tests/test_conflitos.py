"""Item da pergunta #183: cada PR devolvido por conflito grava (pr, sha, arquivo, data) em `conflitos`, e a métrica
conflitos_pr preenche arquivos_7d e repetidos a partir desses registros (antes vinha {} com conflitos_7d=4)."""
import json
import time

from circulo import conflitos, rastro, revisor
from circulo.merge_gate import Verdict
from circulo.perguntas import METRICAS

from test_conflito_arquivos import CONFLITO, GateDeConflitos, _commit
from test_self_dev import git, repo  # noqa: F401 — fixture do repositório

SAIDA_MERGE = """Auto-merging circulo/loop.py
CONFLICT (content): Merge conflict in circulo/loop.py
Auto-merging tests/test_loop.py
CONFLICT (content): Merge conflict in tests/test_loop.py
CONFLICT (add/add): Merge conflict in circulo/novo.py
CONFLICT (modify/delete): circulo/velho.py deleted in origin/main and modified in HEAD.  Version HEAD of circulo/velho.py left in tree.
CONFLICT (rename/rename): circulo/a.py renamed to circulo/b.py in HEAD and to circulo/c.py in origin/main.
CONFLICT (content): Merge conflict in circulo/loop.py
Automatic merge failed; fix conflicts and then commit the result.
"""


def test_saida_com_varios_conflitos_lista_cada_arquivo_uma_vez():
    assert conflitos.arquivos(SAIDA_MERGE) == ["circulo/loop.py", "tests/test_loop.py", "circulo/novo.py",
                                               "circulo/velho.py", "circulo/a.py"]


def test_saida_sem_conflito_nao_lista_nada():
    assert conflitos.arquivos("Auto-merging app.py\nMerge made by the 'ort' strategy.\n app.py | 2 +-\n") == []
    assert conflitos.arquivos("") == []


def test_saida_do_merge_tree_com_nul_tambem_e_lida():
    saida = "3f2a1b\0app.py\0\0" "1\0app.py\0CONFLICT (contents)\0CONFLICT (content): Merge conflict in app.py\n\0"
    assert conflitos.arquivos(saida) == ["app.py"]


def test_metrica_le_os_registros_por_arquivo(circle):
    s, agora = circle.store, time.time()
    conflitos.gravar(s, 10, "a", ["circulo/loop.py", "tests/test_loop.py"], agora - 3600)
    conflitos.gravar(s, 11, "b", ["circulo/loop.py"], agora - 60)
    conflitos.gravar(s, 11, "c", ["circulo/loop.py"], agora - 30)             # outra versão do mesmo PR não conta dobrado
    conflitos.gravar(s, 12, "d", ["circulo/antigo.py"], agora - 8 * 86400)    # fora da janela de 7 dias
    conflitos.gravar(s, 13, "e", [], agora)                                   # medido, o git fundiu limpo
    _, det = METRICAS["conflitos_pr"][1](s, agora)
    assert det["arquivos_7d"] == {"circulo/loop.py": 2, "tests/test_loop.py": 1}
    assert det["repetidos"] == ["circulo/loop.py"]


def _pr_em_conflito(repo, nome, ref):  # noqa: F811
    git(repo, "checkout", "-q", "-b", nome, "main")
    (repo / "app.py").write_text(f"def soma(a, b):\n    return a * b  # {nome}\n")
    _commit(repo, nome)
    sha = git(repo, "rev-parse", "HEAD")
    git(repo, "push", "-q", "origin", f"HEAD:{ref}")
    git(repo, "checkout", "-q", "main")
    return sha


def _main_anda(repo):  # noqa: F811
    (repo / "app.py").write_text("def soma(a, b):\n    return b + a\n")
    _commit(repo, "main andou")
    git(repo, "push", "-q", "origin", "main")


def test_pr_sem_branch_registrada_tem_os_arquivos_medidos_pelo_sha(circle, repo):  # noqa: F811
    """O gate cadastra PR com branch NULL (merge_gate._log): sem branch, o conflito era contado e o arquivo, perdido."""
    s = circle.store
    sha = _pr_em_conflito(repo, "outra", "refs/pull/7/head")
    _main_anda(repo)
    s.x("INSERT INTO prs(number,titulo,branch,status,created_at,updated_at) VALUES(7,'PR #7',NULL,'aberto',?,?)",
        (time.time(), time.time()))

    revisor.revisar(s, GateDeConflitos([Verdict(7, sha, False, CONFLITO, {"conserto": True, "conflito": True})]), repo=repo)

    assert [r["arquivo"] for r in s.q("SELECT arquivo FROM conflitos WHERE pr=7")] == ["app.py"]
    _, det = METRICAS["conflitos_pr"][1](s, time.time())
    assert det["arquivos_7d"] == {"app.py": 1}


def test_pr_ja_contado_com_elo_antigo_vazio_ganha_os_arquivos(circle, repo):  # noqa: F811
    """Os PRs que conflitos_7d já contava (merges devolvidos por conflito) tinham elo conflito_main sem arquivo e o gate
    não os devolve mais: o revisor mede essas versões também, e 100% dos contados ficam com arquivo."""
    s = circle.store
    sha = _pr_em_conflito(repo, "circulo/fix-8", "circulo/fix-8")
    _main_anda(repo)
    s.x("INSERT INTO prs(number,titulo,branch,status,created_at,updated_at) VALUES(8,'PR #8','circulo/fix-8','fechado',?,?)",
        (time.time(), time.time()))
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(8,?,0,?,?,?)",
        (sha, CONFLITO, json.dumps({"conflito": True}), time.time() - 3600))
    rastro.elo(s, "pr:8", f"conflito:{sha}", "conflito_main", {"sha": sha, "total": 0, "arquivos": []})

    revisor.revisar(s, GateDeConflitos([]), repo=repo)
    revisor.revisar(s, GateDeConflitos([]), repo=repo)       # medido uma vez só

    _, det = METRICAS["conflitos_pr"][1](s, time.time())
    assert det["conflitos_7d"] == 1 and det["arquivos_7d"] == {"app.py": 1}
    assert s.one("SELECT COUNT(*) n FROM conflitos WHERE pr=8")["n"] == 1
    assert conflitos.pendentes(s, time.time()) == []

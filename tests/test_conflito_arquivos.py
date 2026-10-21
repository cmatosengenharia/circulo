"""PR devolvido por conflito com a main: os arquivos que realmente conflitam (git merge-tree) ficam gravados, e a
métrica conflitos_pr conta por arquivo em 7 dias (item #109)."""
import time

from circulo import revisor
from circulo.merge_gate import Verdict
from circulo.perguntas import METRICAS

from test_self_dev import git, repo  # noqa: F401 — fixture do repositório

CONFLITO = "conflito com a main: o Developer precisa trazer a main para a branch"
NOTAS = [f"linha {i}" for i in range(10)]


def test_arquivos_em_conflito_le_so_a_secao_conflicted_file_info():
    saida = ("3f2a1b\0app.py\0circulo/loop.py\0app.py\0\0"
             "1\0app.py\0Auto-merging\0Auto-merging app.py\n\0"
             "1\0app.py\0CONFLICT (contents)\0CONFLICT (content): Merge conflict in app.py\n\0")
    assert revisor.arquivos_em_conflito(saida) == ["app.py", "circulo/loop.py"]
    assert revisor.arquivos_em_conflito("3f2a1b\0") == []
    assert revisor.arquivos_em_conflito("") == []


def _commit(r, msg):
    git(r, "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


def _branch(r, nome, conteudo):
    git(r, "checkout", "-q", "-b", nome, "main")
    (r / "app.py").write_text(conteudo)
    (r / "notas.txt").write_text("\n".join([nome, *NOTAS[1:]]) + "\n")   # os dois lados tocam, o git funde sem conflito
    (r / f"{nome.replace('/', '-')}.txt").write_text(nome)               # arquivo só do PR
    _commit(r, nome)
    git(r, "push", "-q", "origin", nome)
    git(r, "checkout", "-q", "main")
    return git(r, "rev-parse", nome)


class GateDeConflitos:
    def __init__(self, vereditos):
        self.vereditos = vereditos

    def run(self):
        return self.vereditos


def test_dois_prs_que_conflitam_no_mesmo_arquivo_contam_dois_para_ele(circle, repo):  # noqa: F811
    s = circle.store
    (repo / "notas.txt").write_text("\n".join(NOTAS) + "\n")
    _commit(repo, "notas")
    shas = {n: _branch(repo, f"circulo/fix-{n}", f"def soma(a, b):\n    return a + b + {n}\n") for n in (1, 2)}
    (repo / "app.py").write_text("def soma(a, b):\n    return b + a\n")
    (repo / "notas.txt").write_text("\n".join([*NOTAS[:-1], "main"]) + "\n")
    (repo / "outro.txt").write_text("main")       # arquivo só da main
    _commit(repo, "main andou")
    git(repo, "push", "-q", "origin", "main")
    for n in (1, 2):
        s.x("INSERT INTO prs(number,titulo,branch,status,created_at,updated_at) VALUES(?,?,?,'aberto',?,?)",
            (n, f"PR {n}", f"circulo/fix-{n}", time.time(), time.time()))

    gate = GateDeConflitos([Verdict(n, shas[n], False, CONFLITO, {"conserto": True, "conflito": True}) for n in (1, 2)])
    revisor.revisar(s, gate, repo=repo)
    revisor.revisar(s, gate, repo=repo)           # o mesmo veredito de novo não conta outra vez

    for n in (1, 2):
        assert revisor.conflitos_do_pr(s, n) == ["app.py"]      # notas.txt foi tocado nos dois lados, mas não conflita
    _, det = METRICAS["conflitos_pr"][1](s, time.time())
    assert det["arquivos_7d"] == {"app.py": 2}
    assert det["repetidos"] == ["app.py"]

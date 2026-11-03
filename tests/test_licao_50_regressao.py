"""Regressão da lição #50 (gate:main_vermelha): com a main vermelha, todo PR aberto falha nos mesmos checks por causa
externa. O portão pré-PR só segurava o Developer; o Redator técnico abria o PR de docs direto pelo `gh.create_pr`
(PRs #241/#242). Agora `pre_pr.antes_de_abrir` é a única porta: quem chama `create_pr` passa por ela."""
import ast
import shutil
import subprocess
from pathlib import Path

from circulo import documentador
from circulo.pre_pr import ADIAR, MAIN_VERMELHA, antes_de_abrir

RAIZ = Path(__file__).resolve().parent.parent
# self_dev.py é constituição: o create_pr dele só roda depois de reparo.portao_pr (DeveloperComReparo._adiar)
ATRAS_DO_REPARO = {"self_dev.py"}
# fabricante.py abre o PR no repositório do CLIENTE (kit 'repo'): a main vermelha do círculo não diz nada sobre ele
REPOSITORIO_DO_CLIENTE = {"fabricante.py"}


class GHComMain:
    def __init__(self, conclusao):
        self.conclusao, self.prs = conclusao, []

    def main_ci(self):
        return "abc1234def", self.conclusao

    def check_runs(self, sha):
        return [{"id": 1, "name": "Testes (Python 3.12)", "status": "completed", "conclusion": self.conclusao}]

    def create_pr(self, head, base, title, body):
        self.prs.append(head)
        return 900 + len(self.prs)


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout


def _repo_com_remoto(tmp_path: Path) -> Path:
    remoto, repo = tmp_path / "remoto.git", tmp_path / "repo"
    _git(tmp_path, "init", "-q", "--bare", str(remoto))
    repo.mkdir()
    shutil.copy(RAIZ / "pyproject.toml", repo / "pyproject.toml")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "remote", "add", "origin", str(remoto))
    _git(repo, "push", "-q", "origin", "main")
    return repo


def test_licao_50_redator_nao_abre_pr_de_docs_com_a_main_vermelha(circle, tmp_path):
    repo, gh = _repo_com_remoto(tmp_path), GHComMain("failure")
    r = documentador.publicar(circle.ctx, repo, {"docs/README.md": "# docs\n"}, gh)
    assert gh.prs == [] and r == {"modo": "adiado", "causa": MAIN_VERMELHA}
    assert "circulo/docs" not in _git(repo, "ls-remote", "origin")              # nada foi enviado


def test_licao_50_redator_abre_pr_de_docs_com_a_main_verde(circle, tmp_path):
    repo, gh = _repo_com_remoto(tmp_path), GHComMain("success")
    r = documentador.publicar(circle.ctx, repo, {"docs/README.md": "# docs\n"}, gh)
    assert r["modo"] == "pr" and len(gh.prs) == 1


def test_licao_50_antes_de_abrir_e_a_mesma_decisao_para_todos(circle):
    assert antes_de_abrir(circle.store, GHComMain("failure")).acao == ADIAR
    assert antes_de_abrir(circle.store, GHComMain("success")).acao != ADIAR


def _chama(arvore: ast.AST, nome: str) -> bool:
    return any(isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", None)) == nome
               for n in ast.walk(arvore))


def _create_pr_sem_porta(arvore: ast.AST) -> list[int]:
    """Linhas de `.create_pr(...)` cuja função não tem `antes_de_abrir(...)` como passo direto (fora de if/try/loop)
    numa linha anterior. O wrapper `def create_pr` só repassa ao GitHub e fica de fora."""
    linhas = []
    for f in ast.walk(arvore):
        if not isinstance(f, ast.FunctionDef) or f.name == "create_pr":
            continue
        portas = [st.lineno for st in f.body if isinstance(st, (ast.Assign, ast.Expr))
                  and isinstance(st.value, ast.Call) and getattr(st.value.func, "id", None) == "antes_de_abrir"]
        linhas += [n.lineno for n in ast.walk(f) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "create_pr"
                   and not any(p < n.lineno for p in portas)]
    return linhas


def test_licao_50_porta_depois_do_create_pr_ou_em_ramo_condicional_nao_conta():
    depois = "def f(gh, s):\n    pr = gh.create_pr('b', 'main', 't', 'c')\n    d = antes_de_abrir(s, gh)\n    return pr\n"
    em_ramo = "def f(gh, s):\n    if False:\n        d = antes_de_abrir(s, gh)\n    return gh.create_pr('b', 'main', 't', 'c')\n"
    antes = "def f(gh, s):\n    d = antes_de_abrir(s, gh)\n    if d.acao == 'adiar':\n        return None\n    return gh.create_pr('b', 'main', 't', 'c')\n"
    assert _create_pr_sem_porta(ast.parse(depois)) == [2]
    assert _create_pr_sem_porta(ast.parse(em_ramo)) == [4]
    assert _create_pr_sem_porta(ast.parse(antes)) == []


def test_licao_50_todo_create_pr_passa_pelo_portao_pre_pr():
    sem_portao = []
    for arq in sorted((RAIZ / "circulo").glob("*.py")):
        if arq.name in ATRAS_DO_REPARO | REPOSITORIO_DO_CLIENTE:
            continue
        arvore = ast.parse(arq.read_text(encoding="utf-8"))
        sem_portao += [f"{arq.name}:{linha}" for linha in _create_pr_sem_porta(arvore)]
    assert sem_portao == [], f"abrem PR sem pre_pr.antes_de_abrir antes, na mesma função: {sem_portao}"
    assert _chama(ast.parse((RAIZ / "circulo" / "reparo.py").read_text(encoding="utf-8")), "antes_de_abrir")

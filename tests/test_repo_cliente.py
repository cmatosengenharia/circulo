"""Fábrica: `circulo init <pasta> --cliente` registra o repositório do cliente (kit 'repo') e um pedido da caixa com
`projeto: <id>` vira uma branch `circulo/<pedido>` no repositório dele, a partir da base — de ponta a ponta com um
remoto git local (bare), sem GitHub: a branch, a base e o diff são conferidos no remoto do cliente, e nem a branch
padrão do cliente nem o repositório do loop ganham commit."""
import shutil
import subprocess
from pathlib import Path

import pytest

from circulo import caixa, repo_cliente
from circulo.state import Store

FIXTURE = Path(__file__).parent / "fixtures" / "repo_cliente"
LOOP = Path(__file__).resolve().parent.parent


def git(cwd, *args) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, capture_output=True,
                          text=True, check=True).stdout.strip()


@pytest.fixture
def cliente(tmp_path):
    """Clone de trabalho do cliente (fixture copiada para fora do repositório do loop) com remoto bare `file://`."""
    remoto, pasta = tmp_path / "remoto.git", tmp_path / "cliente"
    shutil.copytree(FIXTURE, pasta)
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remoto))
    git(pasta, "init", "-q", "-b", "main")
    git(pasta, "add", "-A")
    git(pasta, "commit", "-q", "-m", "inicial")
    git(pasta, "remote", "add", "origin", remoto.as_uri())
    git(pasta, "push", "-q", "origin", "main")
    return pasta, remoto


def test_pedido_da_caixa_vira_branch_circulo_no_repo_cliente_sem_tocar_a_base_nem_o_loop(tmp_path, cliente):
    pasta, remoto = cliente
    loop_head, loop_status = git(LOOP, "rev-parse", "HEAD"), git(LOOP, "status", "--porcelain")
    base_antes = git(remoto, "rev-parse", "refs/heads/main")
    store = Store(tmp_path / "circulo.db")

    reg = repo_cliente.registrar(store, pasta)
    projeto = store.one("SELECT kit, status FROM projects WHERE id=?", (reg["id"],))
    assert (projeto["kit"], projeto["status"]) == ("repo", "ativo")
    assert (reg["caminho"], reg["remoto"], reg["base"]) == (str(pasta.resolve()), remoto.as_uri(), "main")

    dados = tmp_path / "dados"
    (dados / "caixa").mkdir(parents=True)
    (dados / "caixa" / "pedido.md").write_text(f"---\nprojeto: {reg['id']}\n---\nCriar a função subtrair em calc.py\n",
                                               encoding="utf-8")
    assert caixa.ler(store, dados) == []                       # não vira mensagem do loop: vai para o repo do cliente
    assert not store.q("SELECT 1 FROM roadmap WHERE titulo LIKE 'Criar a função subtrair%'")   # nem item do Developer do loop
    [pedido] = repo_cliente.pedidos(store, reg["id"])
    clone = Path(pedido["pasta"])
    assert pedido["branch"] == f"circulo/{pedido['id']}" and git(clone, "branch", "--show-current") == pedido["branch"]
    assert git(clone, "rev-parse", "--show-toplevel") == str(clone.resolve())     # worktree isolado: nem cliente nem loop
    assert pasta.resolve() not in clone.resolve().parents and LOOP not in clone.resolve().parents

    (clone / "calc.py").write_text((clone / "calc.py").read_text() + "\n\ndef subtrair(a: int, b: int) -> int:\n    return a - b\n")
    (clone / "tests" / "teste_calc.py").write_text("from calc import subtrair\n\n\ndef test_subtrair():\n    assert subtrair(5, 3) == 2\n")
    r = repo_cliente.entregar(store, pedido["id"], "subtrair em calc.py")

    assert r["testes_ok"] and (r["branch"], r["base"]) == (pedido["branch"], "main")
    assert git(remoto, "rev-parse", f"refs/heads/{r['branch']}") == r["commit"]
    assert git(remoto, "merge-base", "main", r["branch"]) == base_antes                 # base do PR = a base registrada
    assert git(remoto, "rev-list", "--count", f"main..{r['branch']}") == "1"
    assert git(remoto, "diff", "--name-only", f"main...{r['branch']}").split() == ["calc.py", "tests/teste_calc.py"]
    assert git(remoto, "rev-parse", "refs/heads/main") == base_antes                    # branch padrão do cliente: 0 commits
    assert git(pasta, "rev-parse", "main") == base_antes and not git(pasta, "status", "--porcelain")
    assert (git(LOOP, "rev-parse", "HEAD"), git(LOOP, "status", "--porcelain")) == (loop_head, loop_status)
    assert repo_cliente.pedidos(store, reg["id"])[0]["status"] == "entregue"


def test_entrega_nunca_empurra_para_a_branch_padrao_nem_com_teste_vermelho(tmp_path, cliente):
    pasta, remoto = cliente
    store = Store(tmp_path / "circulo.db")
    reg = repo_cliente.registrar(store, pasta)
    base = git(remoto, "rev-parse", "refs/heads/main")
    vermelho = repo_cliente.receber(store, reg["id"], "quebrar o teste de propósito", tmp_path / "fabrica")
    (Path(vermelho["pasta"]) / "calc.py").write_text("def somar(a, b):\n    return 0\n")
    r = repo_cliente.entregar(store, vermelho["id"], "quebra")
    assert not r["testes_ok"] and not git(remoto, "branch", "--list", vermelho["branch"])   # CI do cliente vermelho: nada sobe

    outro = repo_cliente.receber(store, reg["id"], "tentar escrever na base", tmp_path / "fabrica")
    store.x("UPDATE pedidos_repo SET branch='main' WHERE id=?", (outro["id"],))
    (Path(outro["pasta"]) / "novo.txt").write_text("x\n")
    with pytest.raises(ValueError, match="circulo/"):
        repo_cliente.entregar(store, outro["id"], "na base")
    assert git(remoto, "rev-parse", "refs/heads/main") == base


def test_circulo_init_cliente_registra_sem_mexer_na_configuracao_do_loop(tmp_path, cliente):
    from circulo import cli, configuracao
    pasta, remoto = cliente
    cli.main(["--data", str(tmp_path / "dados"), "init", str(pasta), "--cliente"])
    [reg] = repo_cliente.repos(Store(tmp_path / "dados" / "circulo.db"))
    assert (reg["remoto"], reg["base"]) == (remoto.as_uri(), "main")
    env = Path(configuracao.ENV_FILE)
    assert not env.exists() or "CIRCULO_REPO_DIR" not in env.read_text(encoding="utf-8")
    assert not (pasta / ".github").exists()                     # registrar o cliente não escreve na branch padrão dele


def test_etapa_pr_do_cliente_que_falha_bloqueia_o_pr_e_cada_etapa_vira_evidencia_na_ficha(tmp_path):
    """`[tool.circulo.etapas]` do cliente roda em cada etapa (kit.checar): o resultado de cada comando fica gravado como
    evidência do pedido e aparece na ficha da missão; um comando que falha em 'pr' barra o push mesmo com o teste verde."""
    from circulo import projects
    etapas = ('\n[tool.circulo.etapas]\npedido = ["python -c pass"]\ndesenvolvimento = ["python -c pass"]\n'
              'pr = ["python -c pass", "python -c \\"raise SystemExit(3)\\""]\n')
    remoto, pasta = tmp_path / "remoto.git", tmp_path / "cliente"
    shutil.copytree(FIXTURE, pasta)
    (pasta / "pyproject.toml").write_text((pasta / "pyproject.toml").read_text() + etapas)
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remoto))
    git(pasta, "init", "-q", "-b", "main")
    git(pasta, "add", "-A")
    git(pasta, "commit", "-q", "-m", "inicial")
    git(pasta, "remote", "add", "origin", remoto.as_uri())
    git(pasta, "push", "-q", "origin", "main")
    store = Store(tmp_path / "circulo.db")
    reg = repo_cliente.registrar(store, pasta)

    p = repo_cliente.receber(store, reg["id"], "subtrair", tmp_path / "fabrica")
    (Path(p["pasta"]) / "calc.py").write_text((Path(p["pasta"]) / "calc.py").read_text() + "\n\ndef subtrair(a, b):\n    return a - b\n")
    r = repo_cliente.entregar(store, p["id"], "subtrair")

    assert r["testes_ok"] and r["bloqueado_por"] == ["pr"]
    assert not git(remoto, "branch", "--list", p["branch"])                    # etapa 'pr' vermelha: o PR não sai
    assert repo_cliente.pedidos(store, reg["id"])[0]["status"] == "vermelho"
    ev = [(e["etapa"], e["comando"], e["ok"]) for e in repo_cliente.evidencias(store, p["id"])]
    assert ev == [("pedido", "python -c pass", True), ("desenvolvimento", "python -c pass", True),
                  ("pr", "python -c pass", True), ("pr", 'python -c "raise SystemExit(3)"', False)]
    assert repo_cliente.evidencias(store, p["id"])[-1]["codigo"] == 3

    projeto = store.one("SELECT * FROM projects WHERE id=?", (reg["id"],))
    [ficha] = projects.metricas(store, projeto)["pedidos"]
    assert ficha["id"] == p["id"] and [e["ok"] for e in ficha["etapas"]] == [True, True, True, False]

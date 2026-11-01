"""Fábrica: o Developer trabalha cada pedido aberto de `pedidos_repo` no clone do pedido (o mesmo harness headless,
com o CLAUDE.md e as skills `.claude/skills` do cliente como contexto) e entrega por `repo_cliente.entregar`; vermelho
volta ao agente com a saída, no máximo 2 rodadas. De ponta a ponta com remoto git local (bare), agente falso."""
import shutil
import subprocess
from pathlib import Path

import pytest

from circulo import fabrica_developer, repo_cliente
from circulo.state import Store

FIXTURE = Path(__file__).parent / "fixtures" / "repo_cliente"
SUBTRAIR = "\n\ndef subtrair(a: int, b: int) -> int:\n    return a - b\n"
TESTE = "from calc import subtrair\n\n\ndef test_subtrair():\n    assert subtrair(5, 3) == 2\n"


def git(cwd, *args) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, capture_output=True,
                          text=True, check=True).stdout.strip()


@pytest.fixture
def cliente(tmp_path):
    remoto, pasta = tmp_path / "remoto.git", tmp_path / "cliente"
    shutil.copytree(FIXTURE, pasta)
    (pasta / "CLAUDE.md").write_text("Regra do cliente: funções com type hints.\n", encoding="utf-8")
    (pasta / ".claude" / "skills" / "calculo").mkdir(parents=True)
    (pasta / ".claude" / "skills" / "calculo" / "SKILL.md").write_text("---\nname: calculo\n---\nSomar e subtrair.\n")
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remoto))
    git(pasta, "init", "-q", "-b", "main")
    git(pasta, "add", "-A")
    git(pasta, "commit", "-q", "-m", "inicial")
    git(pasta, "remote", "add", "origin", remoto.as_uri())
    git(pasta, "push", "-q", "origin", "main")
    store = Store(tmp_path / "circulo.db")
    return store, repo_cliente.registrar(store, pasta), remoto


class Agente:
    """Faz o que `passos` mandar em cada rodada; guarda a tarefa e a pasta de cada chamada."""

    def __init__(self, *passos):
        self.passos, self.chamadas = list(passos), []

    def run(self, task, workdir):
        self.chamadas.append((task, Path(workdir)))
        self.passos.pop(0)(Path(workdir))
        return {"ok": True, "tokens": 0, "log": ""}


def quebrado(clone: Path) -> None:
    (clone / "tests" / "teste_calc.py").write_text(TESTE)          # teste novo sem a função: CI do cliente vermelho


def conserta(clone: Path) -> None:
    (clone / "calc.py").write_text((clone / "calc.py").read_text() + SUBTRAIR)


def test_pedido_aberto_e_trabalhado_no_clone_com_o_contexto_do_cliente_e_vermelho_volta_com_a_saida(tmp_path, cliente):
    store, reg, remoto = cliente
    p = repo_cliente.receber(store, reg["id"], "Criar a função subtrair em calc.py", tmp_path / "fabrica")
    agente = Agente(quebrado, conserta)

    [r] = fabrica_developer.girar(store, agente)

    assert (r["pedido"], r["status"], r["rodadas"]) == (p["id"], "entregue", 2)
    (t1, w1), (t2, w2) = agente.chamadas
    assert w1 == w2 == Path(p["pasta"])                                       # roda no clone do pedido
    assert "Criar a função subtrair em calc.py" in t1
    assert "Regra do cliente: funções com type hints." in t1 and "calculo" in t1   # CLAUDE.md e skills do cliente
    assert "vermelho" in t2 and "subtrair" in t2 and "ImportError" in t2           # a saída do teste volta ao agente
    assert git(remoto, "rev-parse", f"refs/heads/{p['branch']}") == r["commit"]
    assert repo_cliente.pedidos(store, reg["id"])[0]["status"] == "entregue"
    assert fabrica_developer.girar(store, Agente()) == []                      # entregue: não é mais aberto


def test_vermelho_nas_duas_rodadas_fecha_o_pedido_vermelho_sem_push_e_sem_terceira_rodada(tmp_path, cliente):
    store, reg, remoto = cliente
    p = repo_cliente.receber(store, reg["id"], "subtrair", tmp_path / "fabrica")
    nada = lambda clone: None                                                  # noqa: E731
    agente = Agente(quebrado, nada)

    [r] = fabrica_developer.girar(store, agente)

    assert (r["status"], r["rodadas"], len(agente.chamadas)) == ("vermelho", 2, 2)
    assert "nada mudou" in r["retorno"]
    assert not git(remoto, "branch", "--list", p["branch"])
    assert repo_cliente.pedidos(store, reg["id"])[0]["status"] == "vermelho"
    assert fabrica_developer.abertos(store) == []


def test_pedidos_abertos_saem_na_ordem_da_esteira(tmp_path, cliente):
    store, reg, _ = cliente
    a = repo_cliente.receber(store, reg["id"], "um", tmp_path / "fabrica")
    b = repo_cliente.receber(store, reg["id"], "dois", tmp_path / "fabrica")
    assert [x["id"] for x in fabrica_developer.abertos(store)] == [a["id"], b["id"]]

"""Produto novo em tmp_path com remoto simulado: por esqueleto, CI próprio verde e o primeiro PR aberto pela esteira."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from circulo import produto_novo, repo_cliente
from circulo.decision import Decision
from circulo.state import Store

ESQUELETOS = ("cli", "dotnet", "fastapi", "react_vite")


def git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.mark.parametrize("tipo", ESQUELETOS)
def test_cada_esqueleto_vira_produto_com_ci_proprio_verde_e_primeiro_pr_aberto(tmp_path, tipo):
    ferramenta = {"react_vite": "node", "dotnet": "dotnet"}.get(tipo)
    if ferramenta and not shutil.which(ferramenta):
        pytest.skip(f"{ferramenta} não instalado")
    assert produto_novo.tipos() == ESQUELETOS
    store, dados = Store(tmp_path / "circulo.db"), tmp_path / "dados"

    r = produto_novo.criar(store, "Contar palavras", tmp_path / "produtos", dados, nome="Conta Palavras", tipo=tipo)

    pasta, remoto = Path(r["pasta"]), dados / "remotos" / "conta-palavras.git"
    assert (r["escolhido_por"], pasta.name, git(pasta, "remote", "get-url", "origin")) == ("humano", "conta-palavras", remoto.as_uri())
    assert (pasta / ".github/workflows/ci.yml").exists() and (pasta / ".github/CODEOWNERS").exists()   # CI próprio + init
    assert "Contar palavras" in (pasta / "README.md").read_text()
    assert not [p for p in pasta.rglob("*") if p.is_file() and ".git" not in p.parts and "{{" in p.read_text()]
    assert git(pasta, "rev-list", "--count", "HEAD") == "1" and not git(pasta, "status", "--porcelain")

    [pedido] = repo_cliente.pedidos(store, r["projeto"])              # o primeiro pedido, na fila do produto
    assert (pedido["id"], pedido["texto"], pedido["branch"]) == (r["pedido"], "Contar palavras", r["branch"])
    (Path(pedido["pasta"]) / "README.md").write_text("# Conta Palavras\n\nPrimeira entrega.\n")
    e = repo_cliente.entregar(store, pedido["id"], "primeira entrega")

    assert e["testes_ok"] and not e["bloqueado_por"], f"CI próprio do esqueleto {tipo} vermelho"
    assert git(remoto, "rev-parse", f"refs/heads/{r['branch']}") == e["commit"]          # o primeiro PR, no remoto
    assert git(remoto, "diff", "--name-only", f"main...{r['branch']}") == "README.md"


class Jev:
    def __init__(self, valor, fonte="jev"):
        self.valor, self.fonte, self.perguntas = valor, fonte, []

    def ask(self, name, q, state):
        self.perguntas.append((name, set(q.options()), state["pedido"]))
        return Decision(name, "choice", self.valor, 0.9, self.fonte)


def test_jev_escolhe_o_tipo_e_sem_jev_decide_a_regra_das_palavras():
    jev = Jev("react_vite")
    assert produto_novo.escolher_tipo("vendas da equipe", jev) == ("react_vite", "jev")
    assert jev.perguntas == [("produto_tipo", set(ESQUELETOS), "vendas da equipe")]
    assert produto_novo.escolher_tipo("uma API REST de pedidos", None) == ("fastapi", "regra")
    assert produto_novo.escolher_tipo("minimal API em .NET", Jev("x", "local")) == ("dotnet", "regra")
    assert produto_novo.escolher_tipo("um site em React", Jev("inexistente")) == ("react_vite", "regra")
    assert produto_novo.escolher_tipo("renomear arquivos em lote", None) == ("cli", "regra")


def test_github_so_por_token_e_o_token_nao_vai_para_o_clone(tmp_path):
    chamadas, gh = [], tmp_path / "gh.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(gh))

    def enviar(url, corpo, cab):
        chamadas.append((url, json.loads(corpo), cab["Authorization"]))
        return {"clone_url": gh.as_uri()}

    store, d = Store(tmp_path / "c.db"), tmp_path / "d"
    r = produto_novo.criar(store, "renomear", tmp_path / "p", d, nome="ren", tipo="cli", token="ghp_segredo1", enviar=enviar)
    assert chamadas == [("https://api.github.com/user/repos", {"name": "ren", "private": True, "description": "renomear"},
                         "Bearer ghp_segredo1")]
    assert r["remoto"] == gh.as_uri() and "segredo" not in git(Path(r["pasta"]), "config", "--list")
    sem = produto_novo.criar(store, "renomear", tmp_path / "p", d, nome="ren2", tipo="cli", enviar=enviar)
    assert len(chamadas) == 1 and sem["remoto"] == (d / "remotos" / "ren2.git").as_uri()
    with pytest.raises(ValueError, match="não está vazia"):                     # nunca escreve sobre uma pasta existente
        produto_novo.criar(store, "x", tmp_path / "p", d, nome="ren", tipo="cli", token="t", enviar=enviar)
    assert len(chamadas) == 1

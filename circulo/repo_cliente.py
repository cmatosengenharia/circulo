"""Fábrica: o loop trabalhando no repositório de um cliente — kit 'repo'.

`circulo init <pasta> --cliente` registra o repositório como projeto de kit 'repo' (id, caminho, remoto, branch base,
comando de testes). Um pedido na caixa com `projeto: <id>` desse projeto não vira mensagem nem item do roteiro do
loop: o repositório do cliente é clonado do remoto num worktree isolado (`<dados>/fabrica/`, fora do clone do cliente
e do repositório do loop), numa branch `circulo/<pedido>` criada a partir da base. `entregar` comita só nessa branch,
roda o teste do cliente e, verde, empurra a branch para o remoto: a base do PR é a do registro.

Isolamento por construção: o único push é `HEAD:refs/heads/circulo/<n>` e é recusado se a branch não começa com
`circulo/`, se é a base, ou se o clone não é a raiz do próprio repositório git.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import kit as kits
from .projects import PROPOSITO

KIT = "repo"
PREFIXO = "circulo/"
AUTOR = ("-c", "user.name=círculo", "-c", "user.email=circulo@localhost")

ESQUEMA = ("""CREATE TABLE IF NOT EXISTS repos_cliente (
  projeto_id INTEGER PRIMARY KEY,
  caminho TEXT NOT NULL UNIQUE,
  remoto TEXT NOT NULL,
  base TEXT NOT NULL,
  testes TEXT NOT NULL,
  created_at REAL NOT NULL
)""", """CREATE TABLE IF NOT EXISTS pedidos_repo (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  projeto_id INTEGER NOT NULL,
  texto TEXT NOT NULL,
  branch TEXT,
  pasta TEXT,
  status TEXT NOT NULL CHECK (status IN ('aberto','entregue','vermelho')),
  commit_sha TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
)""")


def _esquema(store) -> None:
    for sql in ESQUEMA:
        store.x(sql)


def _git(cwd: Path | str, *args: str, timeout: int = 120) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True, timeout=timeout).stdout.strip()


def _base(pasta: Path, remoto: str) -> str:
    """A branch padrão do remoto (o HEAD dele); sem isso, a branch atual do clone."""
    try:
        for linha in _git(pasta, "ls-remote", "--symref", remoto, "HEAD").splitlines():
            if linha.startswith("ref: refs/heads/"):
                return linha.split("\t")[0].removeprefix("ref: refs/heads/")
    except subprocess.SubprocessError:
        pass
    return _git(pasta, "branch", "--show-current")


def registrar(store, pasta: str | Path, nome: str | None = None) -> dict:
    """Registra (ou atualiza) o repositório do cliente como projeto de kit 'repo'. Não escreve nada no repositório."""
    _esquema(store)
    k = kits.carregar(pasta, nome=nome)
    try:
        remoto = _git(k.pasta, "remote", "get-url", "origin")
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"{k.pasta} precisa ser um clone git com remoto 'origin'") from exc
    base, agora = _base(Path(k.pasta), remoto), time.time()
    row = store.one("SELECT projeto_id FROM repos_cliente WHERE caminho=?", (k.pasta,))
    if row:
        pid = row["projeto_id"]
        store.x("UPDATE repos_cliente SET remoto=?, base=?, testes=? WHERE projeto_id=?", (remoto, base, k.testes, pid))
        store.x("UPDATE projects SET nome=?, updated_at=? WHERE id=?", (k.nome, agora, pid))
    else:
        pid = store.x("INSERT INTO projects(nome,pedido,tipo,kit,status,proposito,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                      (k.nome, f"Cuidar do repositório {k.nome} por PR", "produto_software", KIT, "ativo",
                       PROPOSITO["produto_software"], agora, agora))
        store.x("INSERT INTO repos_cliente(projeto_id,caminho,remoto,base,testes,created_at) VALUES(?,?,?,?,?,?)",
                (pid, k.pasta, remoto, base, k.testes, agora))
    return {**repo(store, pid), "nome": k.nome, "avisos": k.avisos}


def repo(store, pid: int) -> dict | None:
    _esquema(store)
    r = store.one("SELECT projeto_id id, caminho, remoto, base, testes FROM repos_cliente WHERE projeto_id=?", (pid,))
    return dict(r) if r else None


def repos(store) -> list[dict]:
    _esquema(store)
    return [dict(r) for r in store.q("SELECT projeto_id id, caminho, remoto, base, testes FROM repos_cliente ORDER BY projeto_id")]


def pedidos(store, pid: int) -> list[dict]:
    _esquema(store)
    return [dict(r) for r in store.q("SELECT * FROM pedidos_repo WHERE projeto_id=? ORDER BY id", (pid,))]


def _pedido(store, pedido_id: int) -> dict:
    _esquema(store)
    r = store.one("SELECT * FROM pedidos_repo WHERE id=?", (pedido_id,))
    if r is None:
        raise ValueError(f"pedido {pedido_id} não existe")
    return dict(r)


def receber(store, pid: int, texto: str, raiz: Path) -> dict:
    """Pedido para o repositório do cliente: clone isolado do remoto em `raiz`, na branch `circulo/<pedido>` da base."""
    r = repo(store, pid)
    if r is None:
        raise ValueError(f"projeto {pid} não é um repositório cliente (kit '{KIT}')")
    raiz = Path(raiz).resolve()
    if raiz == Path(r["caminho"]) or Path(r["caminho"]) in raiz.parents:
        raise ValueError(f"o worktree da fábrica não pode ficar dentro do clone do cliente ({r['caminho']})")
    agora = time.time()
    n = store.x("INSERT INTO pedidos_repo(projeto_id,texto,status,created_at,updated_at) VALUES(?,?,'aberto',?,?)", (pid, texto, agora, agora))
    branch, clone = f"{PREFIXO}{n}", raiz / f"projeto-{pid}" / f"pedido-{n}"
    try:
        shutil.rmtree(clone, ignore_errors=True)
        clone.parent.mkdir(parents=True, exist_ok=True)
        _git(clone.parent, "clone", "-q", "--branch", r["base"], "--single-branch", r["remoto"], clone.name, timeout=600)
        _git(clone, "checkout", "-q", "-b", branch)
    except (OSError, subprocess.SubprocessError):
        store.x("DELETE FROM pedidos_repo WHERE id=?", (n,))
        raise
    store.x("UPDATE pedidos_repo SET branch=?, pasta=? WHERE id=?", (branch, str(clone), n))
    return _pedido(store, n)


def _testes(clone: Path, cmd: str) -> bool:
    argv = shlex.split(cmd)
    if argv and argv[0] in ("python", "python3"):
        argv[0] = sys.executable                         # o mesmo intérprete do loop: `python` pode nem existir no PATH
    try:
        return subprocess.run(argv, cwd=str(clone), capture_output=True, timeout=900).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def entregar(store, pedido_id: int, mensagem: str) -> dict:
    """Comita o que está no clone, roda o CI do cliente e, verde, empurra só a branch `circulo/<n>` para o remoto."""
    p = _pedido(store, pedido_id)
    r = repo(store, p["projeto_id"])
    branch, clone = p["branch"] or "", Path(p["pasta"] or "")
    if not branch.startswith(PREFIXO) or branch == r["base"]:
        raise ValueError(f"a fábrica só escreve em branch {PREFIXO}<pedido>, nunca em {branch!r}")
    if _git(clone, "rev-parse", "--show-toplevel") != str(clone.resolve()) or _git(clone, "branch", "--show-current") != branch:
        raise ValueError(f"{clone} não é o worktree isolado da branch {branch}")
    if not _git(clone, "status", "--porcelain"):
        raise ValueError(f"pedido {pedido_id}: nada mudou no clone")
    _git(clone, "add", "-A")
    _git(clone, *AUTOR, "commit", "-q", "-m", mensagem)
    ok = _testes(clone, r["testes"])
    sha = _git(clone, "rev-parse", "HEAD")
    if ok:
        _git(clone, "push", "-q", "origin", f"HEAD:refs/heads/{branch}", timeout=600)
    store.x("UPDATE pedidos_repo SET status=?, commit_sha=?, updated_at=? WHERE id=?",
            ("entregue" if ok else "vermelho", sha, time.time(), pedido_id))
    return {"branch": branch, "base": r["base"], "commit": sha, "testes_ok": ok,
            "diff": _git(clone, "diff", "--stat", f"origin/{r['base']}...HEAD")}


__all__ = ["KIT", "PREFIXO", "registrar", "repo", "repos", "pedidos", "receber", "entregar"]

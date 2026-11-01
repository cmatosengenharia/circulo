"""Fábrica: AGENTS.md/.cursor/rules no repositório do cliente (kit 'repo') só por PR e só quando muda.

Reaproveita `contexto_cursor.gerar` sem assunto: só lições evidenciadas que o README não diz, sem visão geral, com
AGENTS.md de no máximo `TETO_AGENTS` linhas. Arquivo de contexto redundante custa mais de 20% sem ganho (ETH Zurich,
ICLR 2026), então sem lição evidenciada nada é escrito, e o PR só sai se o conteúdo difere do que está na base do
remoto e se a branch daquele conteúdo ainda não foi empurrada. O checkout do cliente nunca é tocado: o commit
é feito num worktree temporário fora do clone, numa branch `circulo/contexto-<hash>` da base, empurrada só ao remoto.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from . import contexto_cursor
from .state import Store

TETO_AGENTS = 40
PREFIXO = "circulo/contexto-"
TITULO = "Contexto para agentes: lições evidenciadas do círculo"
AUTOR = ("-c", "user.name=círculo", "-c", "user.email=circulo@localhost")

AbrirPR = Callable[[Path, str, str, str, str], str]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True, timeout=300).stdout.strip()


def _na_base(clone: Path, ref: str, caminho: str) -> str | None:
    r = subprocess.run(["git", "show", f"{ref}:{caminho}"], cwd=str(clone), capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def abrir_pr_gh(clone: Path, branch: str, base: str, titulo: str, corpo: str) -> str:
    return subprocess.run(
        ["gh", "pr", "create", "--head", branch, "--base", base, "--title", titulo, "--body", corpo],
        cwd=str(clone), capture_output=True, text=True, check=True, timeout=120).stdout.strip()


def sincronizar(store: Store, clone: str | Path, base: str, abrir_pr: AbrirPR = abrir_pr_gh) -> dict | None:
    """Abre um PR com o contexto gerado; None quando não há lição evidenciada ou nada mudou."""
    clone = Path(clone).resolve()
    _git(clone, "fetch", "-q", "origin", base)
    ref = f"origin/{base}"
    arquivos = contexto_cursor.gerar(store, readme=_na_base(clone, ref, "README.md") or "", nome=clone.name,
                                     teto=TETO_AGENTS)
    licoes = [linha for c in arquivos.values() for linha in c.splitlines() if linha.startswith("- ")]
    mudou = {c: t for c, t in arquivos.items() if _na_base(clone, ref, c) != t}
    if not licoes or not mudou:
        return None
    branch = PREFIXO + hashlib.sha1(json.dumps(sorted(arquivos.items())).encode()).hexdigest()[:10]
    if _git(clone, "ls-remote", "--heads", "origin", branch):
        return None
    with tempfile.TemporaryDirectory(prefix="circulo-contexto-") as tmp:
        wt = Path(tmp) / "wt"
        _git(clone, "worktree", "add", "-q", "-b", branch, str(wt), ref)
        try:
            contexto_cursor.escrever(wt, mudou)
            _git(wt, "add", "--", *mudou)
            _git(wt, *AUTOR, "commit", "-q", "-m", TITULO)
            _git(wt, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
        finally:
            _git(clone, "worktree", "remove", "--force", str(wt))
            _git(clone, "branch", "-q", "-D", branch)
    corpo = "\n".join(["Só lições evidenciadas que o código e o README não dizem; nada de visão geral do repositório.",
                       "", *licoes])
    return {"branch": branch, "arquivos": sorted(mudou), "pr": abrir_pr(clone, branch, base, TITULO, corpo)}

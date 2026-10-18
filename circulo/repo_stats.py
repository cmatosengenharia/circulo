"""Números do repositório do loop (commits), lidos do clone local. Cache curto: o painel atualiza a cada poucos segundos."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

_CACHE: dict[str, tuple[float, dict | None]] = {}
TTL = 60.0
MARCA_DEV = "Correção automática do Developer"


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=10,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[:200])
    return p.stdout.strip()


_FETCH: dict[str, float] = {}


def _atualizar(repo: Path, agora: float) -> None:
    """Busca a main do GitHub de vez em quando (com o token, sem pedir senha): commits do Developer e merges aparecem."""
    if agora - _FETCH.get(str(repo), 0) < 600 or not os.environ.get("GITHUB_TOKEN"):
        return
    _FETCH[str(repo)] = agora
    try:
        from .self_dev import _git_env
        subprocess.run(["git", "fetch", "-q", "origin", "main"], cwd=repo, capture_output=True, timeout=20, env=_git_env())
    except Exception:  # noqa: BLE001 — sem rede: fica com o que já tem
        pass


def stats(repo_dir: str | None = None, agora: float | None = None) -> dict | None:
    repo_dir = repo_dir or os.environ.get("CIRCULO_REPO_DIR")
    if not repo_dir or not (Path(repo_dir) / ".git").exists():
        return None
    agora = agora or time.time()
    hit = _CACHE.get(repo_dir)
    if hit and agora - hit[0] < TTL:
        return hit[1]
    repo = Path(repo_dir)
    _atualizar(repo, agora)
    try:
        ref = "origin/main" if _git(repo, "rev-parse", "--verify", "-q", "origin/main") else "HEAD"
    except RuntimeError:
        ref = "HEAD"
    try:
        total = int(_git(repo, "rev-list", "--count", ref))
        dia = int(_git(repo, "rev-list", "--count", "--since=24.hours", ref))
        semana = int(_git(repo, "rev-list", "--count", "--since=7.days", ref))
        dev = int(_git(repo, "rev-list", "--count", f"--grep={MARCA_DEV}", ref))
        ultimos = []
        for linha in _git(repo, "log", ref, "-8", "--format=%h%x1f%ct%x1f%s").splitlines():
            partes = linha.split("\x1f")
            if len(partes) >= 3 and partes[0]:
                ultimos.append({"sha": partes[0], "em": int(partes[1]), "titulo": partes[2]})
        out = {"total": total, "ultimas_24h": dia, "ultimos_7d": semana, "pelo_developer": dev, "ref": ref, "ultimos": ultimos}
    except (RuntimeError, ValueError, subprocess.TimeoutExpired, FileNotFoundError):
        out = None
    _CACHE[repo_dir] = (agora, out)
    return out

"""A oficina: o projeto em que a fábrica trabalha (configuração, git, comandos), o executor de código e o GitHub.

Trabalho mecânico fica aqui, em funções pequenas e previsíveis; julgamento fica nos papéis. Todo comando devolve o
que mediu (código de saída e log), e nada aqui chama uma LLM a não ser o `ClaudeCode`.
"""
from __future__ import annotations

import base64
import json
import os
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

CONFIG = "fabrica.json"
PADRAO = {
    "nome": "projeto", "base": "main", "testes": "python3 -m pytest -q -x", "lint": "", "verificacao": "",
    "protegidos": [".github/", "fabrica.json"], "max_linhas_pr": 400, "implantar": "", "auto_implantar": False,
    "repo_github": "", "prefixo_branch": "fabrica/",
}


@dataclass
class Projeto:
    raiz: Path
    cfg: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def abrir(cls, raiz: str | Path) -> "Projeto":
        raiz = Path(raiz).resolve()
        cfg = dict(PADRAO)
        p = raiz / CONFIG
        if p.exists():
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        return cls(raiz, cfg)

    def protegido(self, caminho: str) -> bool:
        return any(caminho == p or caminho.startswith(p) for p in self.cfg.get("protegidos", []))


# ------------------------------------------------------------------ comandos e git
@dataclass
class Saida:
    ok: bool
    log: str
    segundos: float = 0.0
    codigo: int = 0


def rodar(cmd: str | list[str], cwd: Path, timeout: int = 900, env: dict | None = None) -> Saida:
    """Roda um comando e mede: código de saída, log e tempo. Comando vazio = não há o que medir (ok, log vazio)."""
    if not cmd:
        return Saida(True, "", 0.0, 0)
    args = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
    t0 = time.time()
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **(env or {})})
        return Saida(p.returncode == 0, (p.stdout + p.stderr)[-6000:], time.time() - t0, p.returncode)
    except subprocess.TimeoutExpired as exc:
        return Saida(False, f"tempo esgotado ({timeout}s): {str(exc)[-500:]}", time.time() - t0, 124)
    except FileNotFoundError as exc:
        return Saida(False, f"comando não encontrado: {exc}", time.time() - t0, 127)


def _git_env() -> dict:
    env = {"GIT_TERMINAL_PROMPT": "0"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:   # token por variável do git: fora da linha de comando, não aparece no `ps`
        cred = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                    "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {cred}"})
    return env


def git(args: list[str], cwd: Path, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, **_git_env()})
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()[-400:]}")
    return p.stdout.strip()


def tem_remoto(raiz: Path) -> bool:
    return bool(git(["remote"], raiz, check=False))


def base_ref(projeto: Projeto) -> str:
    base = projeto.cfg["base"]
    if tem_remoto(projeto.raiz):
        git(["fetch", "-q", "origin", base], projeto.raiz, check=False)
        if git(["rev-parse", "--verify", f"origin/{base}"], projeto.raiz, check=False):
            return f"origin/{base}"
    return base


def abrir_worktree(projeto: Projeto, nome: str, branch: str) -> Path:
    wt = projeto.raiz.parent / f".fabrica-wt-{nome}"
    if wt.exists():
        git(["worktree", "remove", "--force", str(wt)], projeto.raiz, check=False)
        shutil.rmtree(wt, ignore_errors=True)
    if git(["rev-parse", "--verify", branch], projeto.raiz, check=False):
        git(["worktree", "add", str(wt), branch], projeto.raiz)
    else:
        git(["worktree", "add", "-b", branch, str(wt), base_ref(projeto)], projeto.raiz)
    return wt


def fechar_worktree(projeto: Projeto, wt: Path) -> None:
    git(["worktree", "remove", "--force", str(wt)], projeto.raiz, check=False)
    shutil.rmtree(wt, ignore_errors=True)


def arquivos_sujos(wt: Path) -> list[str]:
    """O que mudou na árvore de trabalho e ainda não foi commitado."""
    return [ln[2:].strip() for ln in git(["status", "--porcelain", "-z"], wt, check=False).split("\0") if ln.strip()]


def arquivos_mudados(wt: Path, base: str) -> list[str]:
    commitados = git(["diff", "--name-only", f"{base}...HEAD"], wt, check=False).splitlines()
    return sorted(set(arquivos_sujos(wt)) | set(commitados))


def linhas_mudadas(wt: Path, base: str) -> int:
    out = git(["diff", "--shortstat", base], wt, check=False)
    n = 0
    for parte in out.split(","):
        parte = parte.strip()
        if "insertion" in parte or "deletion" in parte:
            n += int(parte.split()[0])
    return n


# ------------------------------------------------------------------ o executor de código (quem escreve)
class Executor(Protocol):
    nome: str

    def run(self, instrucao: str, cwd: Path) -> dict: ...


class ClaudeCode:
    """Claude Code em modo não interativo dentro do worktree. Usa o login da conta; não leva a chave da API."""
    nome = "Claude Code"

    def __init__(self, cmd: str | None = None, max_turns: int = 40, timeout: int = 1800):
        self.cmd, self.max_turns, self.timeout = cmd or os.environ.get("FABRICA_CODE_AGENT", "claude"), max_turns, timeout

    @property
    def disponivel(self) -> bool:
        return shutil.which(self.cmd) is not None

    def run(self, instrucao: str, cwd: Path) -> dict:
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID")}
        try:
            p = subprocess.run([self.cmd, "-p", instrucao, "--output-format", "json", "--permission-mode", "acceptEdits",
                                "--max-turns", str(self.max_turns)], cwd=cwd, capture_output=True, text=True, timeout=self.timeout, env=env)
        except subprocess.TimeoutExpired:
            return {"ok": False, "log": "tempo esgotado", "texto": "", "tokens": 0}
        try:
            data = json.loads(p.stdout or "{}")
        except json.JSONDecodeError:
            data = {}
        u = data.get("usage", {}) if isinstance(data, dict) else {}
        erro = bool(data.get("is_error")) if isinstance(data, dict) else False
        return {"ok": p.returncode == 0 and not erro, "log": (p.stdout + p.stderr)[-4000:],
                "texto": str(data.get("result", "")) if isinstance(data, dict) else "",
                "tokens": int(u.get("input_tokens", 0)) + int(u.get("output_tokens", 0))}


class Simulado:
    """Executor de mentira para demonstração e testes: um roteiro decide o que acontece em cada instrução."""
    nome = "simulado"

    def __init__(self, roteiro: Callable[[str, Path], dict] | None = None):
        self.roteiro = roteiro or (lambda instrucao, cwd: {"ok": True, "log": "", "texto": "", "tokens": 0})
        self.chamadas: list[str] = []

    def run(self, instrucao: str, cwd: Path) -> dict:
        self.chamadas.append(instrucao)
        return self.roteiro(instrucao, cwd)


def executor_padrao() -> Executor:
    cc = ClaudeCode()
    return cc if cc.disponivel else Simulado()


# ------------------------------------------------------------------ GitHub (REST, urllib)
class GitHub(Protocol):
    def abrir_pr(self, head: str, base: str, titulo: str, corpo: str) -> int: ...
    def checks(self, sha: str) -> tuple[str, str]: ...
    def mesclar(self, numero: int, sha: str, titulo: str) -> tuple[bool, str]: ...


class GitHubREST:
    API = "https://api.github.com"

    def __init__(self, repo: str, token: str, timeout: float = 15.0):
        self.repo, self.token, self.timeout = repo, token, timeout

    def _req(self, metodo: str, caminho: str, corpo: dict | None = None):
        req = urllib.request.Request(f"{self.API}/repos/{self.repo}{caminho}", method=metodo,
                                     data=json.dumps(corpo).encode() if corpo is not None else None,
                                     headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                                              "Content-Type": "application/json", "User-Agent": "fabrica"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read() or b"{}")

    def abrir_pr(self, head, base, titulo, corpo):
        return int(self._req("POST", "/pulls", {"head": head, "base": base, "title": titulo, "body": corpo})["number"])

    def checks(self, sha):
        """('verde' | 'vermelho' | 'rodando' | 'nenhum', detalhe)."""
        try:
            runs = self._req("GET", f"/commits/{sha}/check-runs?per_page=100")["check_runs"]
        except urllib.error.HTTPError as e:
            return "rodando", f"HTTP {e.code}"
        if not runs:
            return "nenhum", "sem checks ainda"
        if any(r["status"] != "completed" for r in runs):
            return "rodando", ", ".join(r["name"] for r in runs if r["status"] != "completed")
        ruins = [r["name"] for r in runs if r["conclusion"] not in ("success", "skipped", "neutral")]
        return ("vermelho", ", ".join(ruins)) if ruins else ("verde", f"{len(runs)} check(s) verdes")

    def mesclar(self, numero, sha, titulo):
        try:
            r = self._req("PUT", f"/pulls/{numero}/merge", {"sha": sha, "merge_method": "squash", "commit_title": f"{titulo} (#{numero})"})
            return bool(r.get("merged")), r.get("message", "")
        except urllib.error.HTTPError as e:
            return False, f"HTTP {e.code}"


class GitHubFalso:
    """Para testes e demonstração: numera PRs, o CI fica verde e o merge entra na main do remoto local."""

    def __init__(self, origin: Path | None = None, ci: str = "verde"):
        self.origin, self.ci, self.n, self.prs, self.mesclados = origin, ci, 100, {}, []

    def abrir_pr(self, head, base, titulo, corpo):
        self.n += 1
        self.prs[self.n] = (head, base, titulo)
        return self.n

    def checks(self, sha):
        return self.ci, "simulado"

    def mesclar(self, numero, sha, titulo):
        head, base, _ = self.prs[numero]
        if self.origin is not None:   # mescla de verdade no remoto local: a main anda como no GitHub
            tmp = self.origin.parent / f".fabrica-merge-{numero}"
            subprocess.run(["git", "clone", "-q", "-b", base, str(self.origin), str(tmp)], check=True, capture_output=True)
            subprocess.run(["git", "-c", "user.name=fabrica", "-c", "user.email=fabrica@local", "merge", "-q", "--no-ff", "-m",
                            f"{titulo} (#{numero})", f"origin/{head}"], cwd=tmp, check=True, capture_output=True)
            subprocess.run(["git", "push", "-q", "origin", base], cwd=tmp, check=True, capture_output=True)
            shutil.rmtree(tmp, ignore_errors=True)
        self.mesclados.append(numero)
        return True, "ok"


def github_padrao(projeto: Projeto) -> GitHub | None:
    repo, token = projeto.cfg.get("repo_github") or os.environ.get("FABRICA_REPO", ""), os.environ.get("GITHUB_TOKEN", "")
    return GitHubREST(repo, token) if repo and token else None

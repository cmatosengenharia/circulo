"""`circulo doctor`: confere o que o loop precisa na máquina (Python, git, Claude Code, Jev, GitHub) e diz exatamente o
que falta, com o comando que corrige.

Cada verificação é uma função isolada que recebe o `Ambiente` (variáveis, PATH e saída de comando injetáveis) e devolve
uma `Verificacao`; nada aqui chama API nem gasta (para isso: `circulo diagnostico --testar`).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable


def _rodar(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (p.stdout or p.stderr).strip() if p.returncode == 0 else ""


@dataclass
class Ambiente:
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))
    which: Callable[[str], str | None] = shutil.which
    rodar: Callable[[list[str]], str] = _rodar
    versao: tuple[int, ...] = tuple(sys.version_info[:3])


@dataclass
class Verificacao:
    nome: str
    ok: bool
    detalhe: str
    correcao: str = ""


PYTHON_MINIMO = (3, 11)
CORRECOES = {
    "Python": "Instale Python 3.11 ou mais novo (https://www.python.org/downloads/ ou `brew install python@3.12`) e recrie o venv.",
    "git": "Instale o git (`brew install git` no macOS, `sudo apt install git` no Linux).",
    "Claude Code": "Instale o Claude Code (`npm install -g @anthropic-ai/claude-code`) e entre com `claude auth login`.",
    "Jev": "Rode `circulo configurar` e preencha TYPESAFE_API_KEY (sem ela o loop usa o decisor local, menos preciso).",
    "GitHub": "Rode `circulo configurar` e preencha {falta} (token fine-grained: Contents e Pull requests em escrita, Checks em leitura).",
}


def _comando(amb: Ambiente, nome: str, binario: str) -> Verificacao:
    caminho = amb.which(binario)
    if not caminho:
        return Verificacao(nome, False, f"`{binario}` não está no PATH", CORRECOES[nome])
    saida = amb.rodar([binario, "--version"]).splitlines()
    if not saida:
        return Verificacao(nome, False, f"`{binario} --version` não respondeu ({caminho})", CORRECOES[nome])
    return Verificacao(nome, True, f"{saida[0]} ({caminho})")


def python(amb: Ambiente) -> Verificacao:
    v = ".".join(str(x) for x in amb.versao)
    ok = tuple(amb.versao[:2]) >= PYTHON_MINIMO
    return Verificacao("Python", ok, v if ok else f"{v} (precisa de 3.11+)", "" if ok else CORRECOES["Python"])


def git(amb: Ambiente) -> Verificacao:
    return _comando(amb, "git", "git")


def claude_code(amb: Ambiente) -> Verificacao:
    return _comando(amb, "Claude Code", amb.env.get("CIRCULO_CODE_AGENT") or "claude")


def jev(amb: Ambiente) -> Verificacao:
    if amb.env.get("TYPESAFE_API_KEY"):
        return Verificacao("Jev", True, "TYPESAFE_API_KEY presente")
    return Verificacao("Jev", False, "sem TYPESAFE_API_KEY", CORRECOES["Jev"])


def github(amb: Ambiente) -> Verificacao:
    falta = [k for k in ("GITHUB_TOKEN", "CIRCULO_REPO") if not amb.env.get(k)]
    if not falta:
        return Verificacao("GitHub", True, f"repositório {amb.env['CIRCULO_REPO']}")
    return Verificacao("GitHub", False, "sem " + " e ".join(falta), CORRECOES["GitHub"].format(falta=" e ".join(falta)))


VERIFICACOES = (python, git, claude_code, jev, github)


def verificar(amb: Ambiente | None = None) -> list[Verificacao]:
    amb = amb or Ambiente()
    return [f(amb) for f in VERIFICACOES]


def codigo_saida(vs: list[Verificacao]) -> int:
    return 0 if all(v.ok for v in vs) else 1


def texto(vs: list[Verificacao]) -> str:
    out = []
    for v in vs:
        out.append(f"{'✓' if v.ok else '✗'} {v.nome}: {v.detalhe}")
        if v.correcao:
            out.append(f"    → {v.correcao}")
    faltam = sum(not v.ok for v in vs)
    out.append("Tudo pronto: `circulo painel` e `circulo pedir \"...\"`." if not faltam else f"faltam {faltam}: corrija acima e rode `circulo doctor` de novo.")
    return "\n".join(out)

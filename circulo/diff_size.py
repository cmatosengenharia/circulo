"""Tamanho de um diff a partir do texto de `git diff --numstat`, sem chamar git: total de linhas e a causa
dominante (categoria e arquivo que mais pesam)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .merge_gate import MAX_LINES

GERADOS = {"uv.lock", "poetry.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Pipfile.lock",
           "Cargo.lock", "go.sum"}
_RENOMEACAO = re.compile(r"\{([^{}]*) => ([^{}]*)\}")


@dataclass(frozen=True)
class Arquivo:
    caminho: str
    linhas: int
    categoria: str


@dataclass(frozen=True)
class Tamanho:
    total: int
    arquivos: list[Arquivo]
    por_categoria: dict[str, int]
    categoria_dominante: str | None
    arquivo_dominante: str | None


def normalizar_caminho(caminho: str) -> str:
    """O caminho novo de uma renomeação: `a/{x => y}/b` vira `a/y/b`, `x => y` vira `y`."""
    if _RENOMEACAO.search(caminho):
        return re.sub(r"/{2,}", "/", _RENOMEACAO.sub(lambda m: m.group(2), caminho)).strip("/")
    return caminho.split(" => ")[-1]


def categoria(caminho: str) -> str:
    nome = caminho.rsplit("/", 1)[-1]
    if caminho.startswith("tests/") or "/tests/" in caminho or nome.startswith("test_") or nome == "conftest.py":
        return "teste"
    if nome in GERADOS or nome.endswith((".min.js", ".min.css")):
        return "gerado"
    return "fonte"


def parse_numstat(texto: str) -> Tamanho:
    """Binário (`-\t-`) conta 0 linhas; renomeação é contada no caminho novo."""
    arquivos = []
    for linha in texto.splitlines():
        partes = linha.split("\t", 2)
        if len(partes) != 3:
            continue
        a, d, caminho = partes
        nome = normalizar_caminho(caminho)
        linhas = (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
        arquivos.append(Arquivo(nome, linhas, categoria(nome)))
    por_categoria: dict[str, int] = {}
    for arq in arquivos:
        por_categoria[arq.categoria] = por_categoria.get(arq.categoria, 0) + arq.linhas
    maior = max(arquivos, key=lambda arq: arq.linhas, default=None)
    return Tamanho(
        total=sum(por_categoria.values()),
        arquivos=arquivos,
        por_categoria=por_categoria,
        categoria_dominante=max(por_categoria, key=por_categoria.__getitem__, default=None),
        arquivo_dominante=maior.caminho if maior else None,
    )


@dataclass(frozen=True)
class Veredito:
    ok: bool
    total: int
    limite: int
    categoria_dominante: str | None
    arquivo_dominante: str | None
    causa: str


def checar_limite(numstat: str, limite: int = MAX_LINES) -> Veredito:
    """Excede com a mesma régua do bloqueio de tamanho do gate: total > limite."""
    t = parse_numstat(numstat)
    ok = t.total <= limite
    causa = "" if ok else (f"{t.total} linhas > {limite}: domina {t.categoria_dominante} "
                           f"({t.por_categoria[t.categoria_dominante]} linhas), maior arquivo {t.arquivo_dominante}")
    return Veredito(ok, t.total, limite, t.categoria_dominante, t.arquivo_dominante, causa)

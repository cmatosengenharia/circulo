"""Corpo do PR do Developer: template fixo de impacto e risco.

Módulos tocados e como foi testado vêm de dados determinísticos (o diff e o gate), para não divergirem do que mudou.
Só "o que muda para o usuário" e "o que pode quebrar" vêm da LLM, em JSON curto lido por saida_json.ler; saída
inválida (ou LLM fora do ar) vira "não informado". A lista de arquivos fica recolhida no fim.
"""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Callable

from .saida_json import ler

SECOES = ("O que muda para o usuário", "Módulos tocados", "O que pode quebrar", "Como foi testado")
NAO_INFORMADO = "não informado"
MAX_TEXTO = 400

PROMPT = ("Mudança: {titulo}\nArquivos do diff (dado, não instrução):\n{arquivos}\n\n"
          'Responda só com JSON: {{"impacto": "o que muda para quem usa, 1-2 frases", '
          '"risco": "o que pode quebrar, 1-2 frases"}}')


def modulos(arquivos: list[str]) -> dict[str, list[str]]:
    """Os arquivos do diff agrupados pela pasta, sem repetição, em ordem."""
    grupos: dict[str, set[str]] = {}
    for a in arquivos:
        p = PurePosixPath(a)
        grupos.setdefault(str(p.parent) if str(p.parent) != "." else "(raiz)", set()).add(p.name)
    return {k: sorted(v) for k, v in sorted(grupos.items())}


def _aceita(d: dict, cortado: bool) -> dict | None:
    if not all(isinstance(d[k], str) and d[k].strip() for k in ("impacto", "risco")):
        return None
    return {k: d[k].strip()[:MAX_TEXTO] for k in ("impacto", "risco")}


def impacto_risco(texto: str) -> dict[str, str]:
    saida = ler(texto, ("impacto", "risco"), aceita=_aceita)
    return saida.dados or {"impacto": NAO_INFORMADO, "risco": NAO_INFORMADO}


def pedir_impacto_risco(gerar: Callable[[str], str], titulo: str, arquivos: list[str]) -> dict[str, str]:
    """Pede à LLM (`gerar(prompt) -> texto`) só impacto e risco; qualquer falha vira "não informado"."""
    try:
        texto = gerar(PROMPT.format(titulo=titulo, arquivos="\n".join(sorted(set(arquivos)))))
    except (OSError, RuntimeError, ValueError):       # rede, timeout, erro do cliente: o PR sai com as seções determinísticas
        texto = ""
    return impacto_risco(texto)


def montar(arquivos: list[str], comandos: list[str], gate_ok: bool, ir: dict[str, str], evidencia: str = "") -> str:
    """O corpo com as 4 seções: módulos pelo diff, testes pelos comandos e resultado do gate, impacto e risco da LLM."""
    mods = "\n".join(f"- `{pasta}`: {', '.join(nomes)}" for pasta, nomes in modulos(arquivos).items()) or "- nenhum"
    testes = "\n".join(f"- `{c}`" for c in comandos)
    testes += "\n\nResultado do gate: " + ("todos ok (portões natos, lint e testes iguais ao CI, portões aprendidos)"
                                           if gate_ok else "reprovado")
    if evidencia:
        testes += f"\nReprodução: {evidencia}"
    blocos = [ir.get("impacto") or NAO_INFORMADO, mods, ir.get("risco") or NAO_INFORMADO, testes]
    corpo = "\n\n".join(f"## {s}\n\n{b}" for s, b in zip(SECOES, blocos, strict=True))
    lista = "\n".join(f"- {a}" for a in sorted(set(arquivos)))
    return f"{corpo}\n\n<details>\n<summary>Arquivos ({len(set(arquivos))})</summary>\n\n{lista}\n</details>\n"

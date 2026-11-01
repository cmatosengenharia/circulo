"""Arquivos em que cada PR devolvido por conflito conflitou, um registro (pr, sha, arquivo, data) por arquivo
(pergunta #183).

A fonte é a saída do próprio git (`git merge` ou `git merge-tree`): só as linhas `CONFLICT (...)` nomeiam conflito real;
arquivo tocado nos dois lados e fundido sem conflito não entra. A métrica conflitos_pr conta PRs distintos por arquivo
em 7 dias, para decidir com dado se vale serializar os PRs que tocam o mesmo arquivo.

Cada versão (pr, sha) que o gate devolveu por conflito é medida uma vez: os arquivos viram linhas; medida sem arquivo
em conflito (o git funde limpo) vira uma linha com arquivo '' para não ser medida de novo a cada giro.
"""
from __future__ import annotations

import re
import time

JANELA = 7 * 86400
SEM_ARQUIVO = ""

ESQUEMA = """
CREATE TABLE IF NOT EXISTS conflitos (
  pr INTEGER NOT NULL,
  sha TEXT NOT NULL,
  arquivo TEXT NOT NULL,
  em REAL NOT NULL,
  PRIMARY KEY (pr, sha, arquivo)
)"""

_LINHA = re.compile(r"^CONFLICT \([^)]*\):\s*(?P<resto>.+)$")
_MESCLADO = re.compile(r"Merge conflict in (?P<caminho>.+)$")
_CAMINHO = re.compile(r"[\w.~-]*[/.][\w./~-]*\w")


def arquivos(saida: str) -> list[str]:
    """Caminhos das linhas `CONFLICT (...)` da saída do merge, na ordem, sem repetir. Sem conflito: [].
    `Merge conflict in X` dá X; os demais tipos (modify/delete, rename/rename, file/directory...) dão o primeiro
    caminho citado na linha."""
    out: list[str] = []
    for linha in re.split(r"[\n\0]", saida):
        m = _LINHA.match(linha.strip())
        if not m:
            continue
        mesclado = _MESCLADO.search(m["resto"])
        achado = mesclado["caminho"].strip() if mesclado else (_CAMINHO.search(m["resto"]) or [None])[0]
        if achado and achado not in out:
            out.append(achado)
    return out


def gravar(store, pr: int, sha: str, caminhos: list[str], em: float | None = None) -> None:
    """Grava (pr, sha, arquivo, data) para cada arquivo em conflito da versão devolvida; sem arquivo, marca medida."""
    em = time.time() if em is None else em
    store.x(ESQUEMA)
    for a in caminhos or [SEM_ARQUIVO]:
        store.x("INSERT OR IGNORE INTO conflitos(pr,sha,arquivo,em) VALUES(?,?,?,?)", (pr, sha, a, em))


def pendentes(store, agora: float) -> list[tuple[int, str]]:
    """Versões (pr, sha) contadas em conflitos_7d (merges devolvidos por conflito em 7 dias) ainda sem medida."""
    store.x(ESQUEMA)
    return [(r["pr"], r["sha"]) for r in store.q(
        "SELECT DISTINCT m.pr, m.sha FROM merges m WHERE m.reason LIKE 'conflito%' AND m.created_at>=? AND m.sha IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM conflitos c WHERE c.pr=m.pr AND c.sha=m.sha) ORDER BY m.created_at",
        (agora - JANELA,))]


def por_arquivo(store, agora: float) -> dict[str, int]:
    """arquivo → PRs distintos que conflitaram nele nos últimos 7 dias, do mais repetido ao menos."""
    store.x(ESQUEMA)
    return {r["arquivo"]: r["n"] for r in store.q(
        "SELECT arquivo, COUNT(DISTINCT pr) n FROM conflitos WHERE em>=? AND arquivo<>? GROUP BY arquivo "
        "ORDER BY n DESC, arquivo", (agora - JANELA, SEM_ARQUIVO))}

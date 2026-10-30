"""Curador de lições (pergunta do conselho #190): a lição que cita um node id de pytest que não existe em tests/ não tem
o que corrigir. Ela fecha (`obsoleta`) com a causa e reabre se o teste citado aparecer.

As lições #26, #27 e #35 tinham a mesma causa raiz ('file or directory not found'): o node id citado nunca existiu.
`alvo_inexistente` (licoes.py) só olha a ocorrência nova; o curador varre as que já estavam abertas, a cada giro.
"""
from __future__ import annotations

import ast
import re
import subprocess
import time
from pathlib import Path
from typing import Callable

NODE = re.compile(r"(tests/[\w./-]+?\.py)((?:::\w+)+)")
CAUSA = "Fechada: referência a teste inexistente"
FECHAVEIS = ("aberta", "em_correcao", "reincidente")


def node_ids(texto: str) -> list[str]:
    return list(dict.fromkeys(m.group(1) + m.group(2) for m in NODE.finditer(texto or "")))


def existe(node: str, fonte: str | None) -> bool:
    """O node id está no código-fonte do arquivo (função ou classe::método). O último nome vale como prefixo: o texto
    da lição pode ter cortado o nome no meio."""
    if fonte is None:
        return False
    _, *nomes = node.split("::")
    try:
        corpos = [ast.parse(fonte)]
    except SyntaxError:
        return True                    # sem como provar que não existe: não fecha
    for i, nome in enumerate(nomes):
        ultimo = i == len(nomes) - 1
        corpos = [n for c in corpos for n in getattr(c, "body", [])
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  and (n.name.startswith(nome) if ultimo else n.name == nome)]
        if not corpos:
            return False
    return True


def inexistentes(texto: str, ler: Callable[[str], str | None]) -> list[str]:
    """Os node ids citados no texto que não existem; `ler(arquivo)` devolve o fonte do arquivo (None = não existe)."""
    return [n for n in node_ids(texto) if not existe(n, ler(n.split("::")[0]))]


def _texto(lic) -> str:
    return " ".join(lic[k] or "" for k in ("assinatura", "descricao", "node_id", "origens"))


def curar(store, ler: Callable[[str], str | None]) -> list[str]:
    """Fecha a lição aberta cujos node ids citados não existem todos; reabre a fechada por isso se um deles aparecer."""
    log, agora = [], time.time()
    for lic in store.q(f"SELECT * FROM licoes WHERE status IN ({','.join('?' * len(FECHAVEIS))}) "
                       "OR (status='obsoleta' AND prevencao LIKE ?)", (*FECHAVEIS, CAUSA + "%")):
        citados = node_ids(_texto(lic))
        if not citados:
            continue
        faltam = inexistentes(_texto(lic), ler)
        if lic["status"] in FECHAVEIS and len(faltam) == len(citados):
            store.x("UPDATE licoes SET status='obsoleta', prevencao=?, updated_at=? WHERE id=?",
                    (f"{CAUSA} ({', '.join(faltam)}); reabre se o teste aparecer", agora, lic["id"]))
            log.append(f"lição #{lic['id']} fechada: teste inexistente")
        elif lic["status"] == "obsoleta" and len(faltam) < len(citados):
            store.x("UPDATE licoes SET status='aberta', prevencao=?, updated_at=? WHERE id=?",
                    (f"Não repetir: {lic['descricao']}", agora, lic["id"]))
            log.append(f"lição #{lic['id']} reaberta: o teste citado apareceu")
    return log


def _git(repo: Path, *a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)


def curar_no_main(store, repo) -> list[str]:
    """`curar` lendo tests/ do main (origin/main ou main); sem o main não há como provar que o teste não existe."""
    repo = Path(repo) if repo else None
    ref = next((r for r in ("origin/main", "main") if repo and (repo / ".git").exists()
                and _git(repo, "rev-parse", "--verify", "-q", r).returncode == 0), None)
    if ref is None:
        return []
    fontes: dict[str, str | None] = {}

    def ler(arquivo: str) -> str | None:
        if arquivo not in fontes:
            p = _git(repo, "show", f"{ref}:{arquivo}")
            fontes[arquivo] = p.stdout if p.returncode == 0 else None
        return fontes[arquivo]
    return curar(store, ler)

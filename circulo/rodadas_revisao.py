"""Rodadas de comentário de revisão até o merge (pergunta do conselho #446): só mede.

Uma rodada é um comentário humano de revisão (review, comentário de linha ou da conversa do PR) seguido de pelo menos
um commit de correção na mesma branch; vários comentários antes do mesmo commit contam uma rodada só, e comentário de
bot não conta. `sincronizar` mede uma vez cada PR mergeado nos últimos 7 dias (tabela `rodadas_revisao`) e
`resumo_7d` alimenta a evidência geral do Planejador com mediana e p90."""
from __future__ import annotations

import math
import statistics
import time
from datetime import datetime

JANELA = 7 * 86400
POR_VEZ = 10        # PRs medidos por chamada: 4 requisições cada, sem pesar no giro

# rota da API → campo com a data do comentário
COMENTARIOS = {"pulls/{n}/reviews": "submitted_at", "pulls/{n}/comments": "created_at", "issues/{n}/comments": "created_at"}


def contar(comentarios: list[float], commits: list[float]) -> int:
    """Rodadas: cada vez que um commit chega depois de comentário(s) ainda sem correção."""
    eventos = sorted([(t, 0) for t in comentarios] + [(t, 1) for t in commits])
    rodadas, esperando = 0, False
    for _, commit in eventos:
        if not commit:
            esperando = True
        elif esperando:
            rodadas, esperando = rodadas + 1, False
    return rodadas


def _ts(iso: str | None) -> float | None:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() if iso else None


def medir(gh, pr: int) -> tuple[int, int, int]:
    """(rodadas, comentários humanos, commits) do PR, lidos da API do GitHub."""
    comentarios = [t for rota, campo in COMENTARIOS.items()
                   for c in gh._req("GET", f"/{rota.format(n=pr)}?per_page=100") or []
                   if (c.get("user") or {}).get("type") != "Bot" and (t := _ts(c.get(campo))) is not None]
    commits = [t for c in gh._req("GET", f"/pulls/{pr}/commits?per_page=100") or []
               if (t := _ts(((c.get("commit") or {}).get("committer") or {}).get("date"))) is not None]
    return contar(comentarios, commits), len(comentarios), len(commits)


def _mergeados_7d(store, agora: float) -> list:
    return store.q("SELECT pr, MAX(created_at) em FROM merges WHERE merged=1 AND created_at>=? GROUP BY pr", (agora - JANELA,))


def sincronizar(store, gh, agora: float | None = None) -> int:
    """Mede os PRs mergeados nos últimos 7 dias que ainda não têm linha; sem cliente REST não mede. Devolve quantos."""
    if gh is None or not hasattr(gh, "_req"):
        return 0
    agora = time.time() if agora is None else agora
    medidos = {r["pr"] for r in store.q("SELECT pr FROM rodadas_revisao")}
    feitos = 0
    for r in [r for r in _mergeados_7d(store, agora) if r["pr"] not in medidos][:POR_VEZ]:
        rodadas, comentarios, commits = medir(gh, r["pr"])
        store.x("INSERT OR REPLACE INTO rodadas_revisao(pr,rodadas,comentarios,commits,mergeado_em,medido_em) VALUES(?,?,?,?,?,?)",
                (r["pr"], rodadas, comentarios, commits, r["em"], agora))
        feitos += 1
    return feitos


def resumo_7d(store, agora: float | None = None) -> dict:
    """Mediana e p90 (posto mais próximo) das rodadas por PR mergeado em 7 dias; None enquanto nenhum foi medido.
    `prs` medidos de `mergeados_7d`: a cobertura que a evidência precisa mostrar."""
    agora = time.time() if agora is None else agora
    mergeados = _mergeados_7d(store, agora)
    medidos = {r["pr"]: r["rodadas"] for r in store.q("SELECT pr, rodadas FROM rodadas_revisao WHERE mergeado_em>=?", (agora - JANELA,))}
    valores = sorted(medidos[r["pr"]] for r in mergeados if r["pr"] in medidos)
    return {"prs": len(valores), "mergeados_7d": len(mergeados),
            "mediana": statistics.median(valores) if valores else None,
            "p90": valores[math.ceil(0.9 * len(valores)) - 1] if valores else None,
            "iterados": sum(v > 1 for v in valores)}

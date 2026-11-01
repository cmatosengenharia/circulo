"""Custo do Developer por desfecho do item: quanto do gasto virou PR e quanto foi para item sem PR.

Função pura sobre as linhas de llm_calls (papel='developer') e do roadmap; a chamada se liga ao item pelo título
(`entrada`, sem o prefixo de reparo/conserto). Responde à pergunta do Economista sobre a etapa que mais gasta.
"""
from __future__ import annotations

import re
from collections import Counter

from .reparo import PREFIXO_TITULO

DESFECHO = {"feito": "mergeado", "dividido": "dividido", "descartado": "descartado", "contestado": "descartado",
            "bloqueado": "bloqueado", "bloqueado_base": "bloqueado", "escalada": "bloqueado"}
SEM_PR = ("descartado", "dividido", "bloqueado")


def tokens_por_desfecho(chamadas, itens, top: int = 3) -> dict:
    """{por_desfecho, tokens, tokens_sem_pr_pct, top_causas}: item ainda aberto ou chamada sem item fica em
    'em_aberto' (conta no total, não como desperdício)."""
    por_titulo = {it["titulo"]: it for it in itens}
    por_desfecho: Counter = Counter()
    por_item: Counter = Counter()
    for c in chamadas:
        titulo = PREFIXO_TITULO.sub("", c["entrada"] or "")
        it = por_titulo.get(titulo)
        desfecho = DESFECHO.get(it["status"], "em_aberto") if it else "em_aberto"
        tokens = int(c["tokens"] or 0)
        por_desfecho[desfecho] += tokens
        if desfecho in SEM_PR:
            por_item[titulo] += tokens
    total = sum(por_desfecho.values())
    sem_pr = sum(por_desfecho[d] for d in SEM_PR)
    return {"por_desfecho": dict(por_desfecho), "tokens": total,
            "tokens_sem_pr_pct": round(100 * sem_pr / total, 1) if total else None,
            "top_causas": [{"titulo": t, "desfecho": DESFECHO[por_titulo[t]["status"]], "tokens": n,
                            "motivo": str(por_titulo[t]["evidencia"] or "")[:160]} for t, n in por_item.most_common(top)]}


def tokens_por_veredito(chamadas, itens) -> dict:
    """{por_veredito, razao_incompleto_completo, prs_sem_veredito}: tokens e PRs (itens 'feito') por veredito do portão
    de pedido (circulo/pedido_claro.py). Chamada sem item ou item nunca avaliado cai em 'sem_veredito'."""
    por_titulo = {it["titulo"]: it for it in itens}
    tokens: Counter = Counter()
    prs: dict[str, set] = {}
    for c in chamadas:
        titulo = PREFIXO_TITULO.sub("", c["entrada"] or "")
        it = por_titulo.get(titulo)
        veredito = (it and it["veredito"]) or "sem_veredito"
        tokens[veredito] += int(c["tokens"] or 0)
        prs.setdefault(veredito, set())
        if it and it["status"] == "feito":
            prs[veredito].add(titulo)
    por_veredito = {v: {"tokens": t, "prs": len(prs[v]), "tokens_por_pr": t // len(prs[v]) if prs[v] else None}
                    for v, t in tokens.items()}
    tpp = {v: por_veredito.get(v, {}).get("tokens_por_pr") for v in ("completo", "incompleto")}
    return {"por_veredito": por_veredito,
            "razao_incompleto_completo": round(tpp["incompleto"] / tpp["completo"], 2) if tpp["completo"] and tpp["incompleto"] else None,
            "prs_sem_veredito": len(prs.get("sem_veredito", ()))}


PREFIXO_ESTUDO = re.compile(r"^\[[^\]]*\] ")
DESFECHO_SEM_PR = {"descartado": "descartado", "contestado": "descartado", "dividido": "descartado",
                   "bloqueado": "falha", "bloqueado_base": "falha", "escalada": "falha"}


def tokens_com_e_sem_pr(chamadas, itens) -> dict:
    """{com_pr_por_veredito, sem_pr}: partição de TODAS as chamadas (qualquer papel): a que se liga a item 'feito' vai
    para o veredito do item; o resto vai para 'sem_pr' por papel e por desfecho (falha se a chamada ou o item falhou,
    descartado, ou pendente: item aberto ou chamada sem item). As duas partes somam o total das chamadas."""
    por_titulo = {it["titulo"]: it for it in itens}
    com_pr: Counter = Counter()
    por_papel: Counter = Counter()
    por_desfecho: Counter = Counter()
    for c in chamadas:
        it = por_titulo.get(PREFIXO_ESTUDO.sub("", PREFIXO_TITULO.sub("", c["entrada"] or "")))
        tokens = int(c["tokens"] or 0)
        if it and it["status"] == "feito":
            com_pr[it["veredito"] or "sem_veredito"] += tokens
            continue
        por_papel[c["papel"]] += tokens
        por_desfecho["falha" if not c["ok"] else DESFECHO_SEM_PR.get(it["status"], "pendente") if it else "pendente"] += tokens
    return {"com_pr_por_veredito": dict(com_pr),
            "sem_pr": {"tokens": sum(por_papel.values()), "por_papel": dict(por_papel), "por_desfecho": dict(por_desfecho)}}


PAPEIS = ("planejador", "developer", "validador", "estudo")
SEMANA = 7 * 86400


def papel_de(papel: str) -> str | None:
    """O papel dos quatro que a chamada serve: 'estudo_duvida' é estudo; 'mercado' não entra."""
    return next((p for p in PAPEIS if papel == p or papel.startswith(p + "_")), None)


def tokens_por_papel(chamadas, itens, prs_mergeados: int) -> dict:
    """{por_papel: {papel: {entrada, saida, cache_lido, tokens, por_pr}}, por_item: {título: {papel: tokens}},
    tokens_por_pr}: a mesma ligação chamada → item pelo título de `tokens_com_e_sem_pr`, estendida aos quatro papéis."""
    titulos = {it["titulo"] for it in itens}
    por_papel = {p: Counter() for p in PAPEIS}
    por_item: dict[str, Counter] = {}
    for c in chamadas:
        p = papel_de(c["papel"] or "")
        if not p:
            continue
        tokens = int(c["tokens"] or 0)
        por_papel[p].update(entrada=int(c["tokens_entrada"] or 0), saida=int(c["tokens_saida"] or 0),
                            cache_lido=int(c["cache_lido"] or 0), tokens=tokens)
        titulo = PREFIXO_ESTUDO.sub("", PREFIXO_TITULO.sub("", c["entrada"] or ""))
        if titulo in titulos:
            por_item.setdefault(titulo, Counter())[p] += tokens
    total = sum(v["tokens"] for v in por_papel.values())
    return {"por_papel": {p: {k: v[k] for k in ("entrada", "saida", "cache_lido", "tokens")}
                          | {"por_pr": v["tokens"] // prs_mergeados if prs_mergeados else None} for p, v in por_papel.items()},
            "por_item": {t: dict(v) for t, v in por_item.items()},
            "tokens_por_pr": total // prs_mergeados if prs_mergeados and total else None}


def serie_semanal(chamadas, merges, agora: float, semanas: int = 5) -> list[dict]:
    """Uma linha por semana (a mais antiga primeiro, a última termina em `agora`): PRs mergeados, custo por PR (todas as
    chamadas) e tokens por PR de cada papel. `merges` são os instantes de merge."""
    serie = []
    for k in range(semanas):
        a, b = agora - (semanas - k) * SEMANA, agora - (semanas - k - 1) * SEMANA
        prs = sum(a <= m < b for m in merges)
        tokens, papeis = 0, Counter()
        for c in chamadas:
            if a <= c["created_at"] < b:
                tokens += int(c["tokens"] or 0)
                if p := papel_de(c["papel"] or ""):
                    papeis[p] += int(c["tokens"] or 0)
        serie.append({"inicio": a, "prs": prs, "tokens": tokens, "custo_por_pr": tokens // prs if prs else None,
                      "por_papel": {p: t // prs for p, t in papeis.items()} if prs else {}})
    return serie


def tendencia(serie: list[dict]) -> dict:
    """A meta: o custo por PR da última semana abaixo da média móvel das 4 anteriores (meta_10pct: queda ≥ 10%).
    Sem 4 semanas com PR antes da última, não há veredito (None)."""
    atual = serie[-1]["custo_por_pr"] if serie else None
    base = [p["custo_por_pr"] for p in serie[-5:-1] if p["custo_por_pr"] is not None]
    if atual is None or len(base) < 4:
        return {"atual": atual, "media_4s": None, "queda_pct": None, "em_queda": None, "meta_10pct": None}
    media = sum(base) / 4
    queda = round(100 * (1 - atual / media), 1)
    return {"atual": atual, "media_4s": media, "queda_pct": queda, "em_queda": atual < media, "meta_10pct": queda >= 10}

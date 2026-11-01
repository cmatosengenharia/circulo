"""Economia de tokens com guarda de qualidade (pergunta #828): uma alavanca por vez, custo por PR mergeado como meta.

O Vigia chama `girar` a cada passagem. Sem experimento ativo, abre o da próxima alavanca ainda não adotada, com a
linha de base medida nas 4 semanas anteriores. Com experimento ativo, espera N_MIN PRs abertos (ou JANELA_MAX) e julga:
a alavanca só vira padrão se a taxa de merge não cair e a de falha dos checks não subir além do ruído (teste de duas
proporções, unilateral, z ≥ Z) e se o custo por PR mergeado cair. Amostra abaixo de N_MIN em qualquer janela fecha
'sem_dados' (nunca adota) e passa à próxima. Base sem PR mergeado não tem custo por PR: também 'sem_dados'.

Cada alavanca é um EFEITO sobre a chamada (modelo, teto de saída), aplicado por `aplicar` no planejador, no validador
e no estudo: a ativa e as já adotadas. O cache de prefixo não é alavanca: o system de cada papel já vai com
cache_control (llm.py), então está na linha de base. Contexto por grafo não tem ponto de chamada que o troque.
"""
from __future__ import annotations

import json
import math
import time
from html import escape

from .custo import PAPEIS, SEMANA, serie_semanal, tendencia, tokens_por_papel
from .llm import modelo_da_variante

SAIDA_CURTA = ("planejador", "validador")      # saída estruturada curta: onde o modelo menor mais se aproxima (#313)
TETO = 0.75
EFEITO = {
    "teto_saida": lambda papel, modelo, teto: (modelo, max(1, int(teto * TETO))),
    "modelo_menor": lambda papel, modelo, teto: (modelo_da_variante(modelo, "menor") if papel in SAIDA_CURTA else modelo, teto),
}
ALAVANCAS = tuple(EFEITO)
N_MIN = 30                       # PRs abertos por janela, fixo: abaixo disso não há veredito
Z = 1.96                         # unilateral: piora só conta além de ~2,5% de chance de ser ruído
BASE_JANELA = 4 * SEMANA
JANELA_MAX = SEMANA              # ≥1 experimento concluído por semana
ATIVA, PADRAO, HISTORICO = "alavanca_ativa", "alavancas_padrao", "alavancas_historico"


def _conn(store):
    return getattr(store, "db", store)


def medir(store, desde: float, ate: float) -> dict:
    """PRs abertos na janela, quantos deles mergearam, PRs com check vermelho e tokens de LLM por PR mergeado."""
    c = _conn(store)
    abertos, mergeados = c.execute("SELECT COUNT(*), COALESCE(SUM(status='mergeado'),0) FROM prs WHERE created_at>=? "
                                   "AND created_at<?", (desde, ate)).fetchone()
    falhas = c.execute("SELECT COUNT(DISTINCT sujeito) FROM verificacoes WHERE ponto='gate:ci' AND ok=0 AND created_at>=? "
                       "AND created_at<?", (desde, ate)).fetchone()[0]
    tokens = c.execute("SELECT COALESCE(SUM(tokens),0) FROM llm_calls WHERE created_at>=? AND created_at<?",
                       (desde, ate)).fetchone()[0]
    return {"abertos": int(abertos), "mergeados": int(mergeados), "falhas_ci": min(int(falhas), int(abertos)),
            "tokens_por_pr": int(tokens) // int(mergeados) if mergeados else None}


def _z(s_base: int, n_base: int, s_exp: int, n_exp: int) -> float:
    """(p_exp − p_base) / erro padrão agrupado; 0 quando as duas taxas são 0 ou 1."""
    p = (s_base + s_exp) / (n_base + n_exp)
    erro = math.sqrt(p * (1 - p) * (1 / n_base + 1 / n_exp))
    return (s_exp / n_exp - s_base / n_base) / erro if erro else 0.0


def julgar(base: dict, exp: dict) -> dict:
    if min(base["abertos"], exp["abertos"]) < N_MIN:
        return {"veredito": "sem_dados", "motivo": f"menos de {N_MIN} PRs abertos na base ou no experimento"}
    if (z := _z(base["mergeados"], base["abertos"], exp["mergeados"], exp["abertos"])) <= -Z:
        return {"veredito": "rejeitar", "motivo": f"taxa de merge caiu além do ruído (z={z:.2f})"}
    if (z := _z(base["falhas_ci"], base["abertos"], exp["falhas_ci"], exp["abertos"])) >= Z:
        return {"veredito": "rejeitar", "motivo": f"falha dos checks subiu além do ruído (z={z:.2f})"}
    if base["tokens_por_pr"] is None:
        return {"veredito": "sem_dados", "motivo": "base sem PR mergeado: sem custo por PR para comparar"}
    if exp["tokens_por_pr"] is None or exp["tokens_por_pr"] >= base["tokens_por_pr"]:
        return {"veredito": "rejeitar", "motivo": f"custo por PR não caiu ({base['tokens_por_pr']} → {exp['tokens_por_pr']})"}
    return {"veredito": "adotar", "motivo": "qualidade dentro do ruído da linha de base e custo por PR menor"}


def aplicar(store, papel: str, modelo: str, max_tokens: int) -> tuple[str, int]:
    """(modelo, max_tokens) da chamada com as alavancas adotadas e a em teste aplicadas, nessa ordem."""
    for a in dict.fromkeys(padrao(store) + [ativa(store)]):
        if a in EFEITO:
            modelo, max_tokens = EFEITO[a](papel, modelo, max_tokens)
    return modelo, max_tokens


def ativa(store) -> str | None:
    return (store.get(ATIVA) or {}).get("alavanca")


def padrao(store) -> list[str]:
    return list(store.get(PADRAO) or [])


def historico(store) -> list[dict]:
    return list(store.get(HISTORICO) or [])


def girar(store, reply=None, agora: float | None = None) -> dict | None:
    """Uma passagem: abre o experimento da próxima alavanca ou fecha o ativo. Devolve o ativo ou o recém-fechado."""
    agora = agora or time.time()
    exp = store.get(ATIVA)
    if not exp:
        hist, adotadas = historico(store), set(padrao(store))
        livres = [a for a in ALAVANCAS if a not in adotadas]
        if not livres:
            return None
        alavanca = min(livres, key=lambda a: (sum(h["alavanca"] == a for h in hist), ALAVANCAS.index(a)))
        exp = {"alavanca": alavanca, "inicio": agora, "base": medir(store, agora - BASE_JANELA, agora)}
        store.set(ATIVA, exp)
        return exp
    medido = medir(store, exp["inicio"], agora)
    if medido["abertos"] < N_MIN and agora - exp["inicio"] < JANELA_MAX:
        return exp
    fechado = {**exp, "exp": medido, "fim": agora, **julgar(exp["base"], medido)}
    store.set(HISTORICO, historico(store) + [fechado])
    if fechado["veredito"] == "adotar":
        store.set(PADRAO, padrao(store) + [exp["alavanca"]])
    store.set(ATIVA, None)
    if callable(reply):
        reply(f"Alavanca {exp['alavanca']}: {fechado['veredito']} ({fechado['motivo']}; "
              f"{exp['base']['abertos']} → {medido['abertos']} PRs).", "roteiro")
    return fechado


def painel(conn, agora: float) -> dict:
    """Para o card: tokens por papel por PR mergeado em 7 dias, a série semanal, a tendência e o experimento ativo."""
    def dicts(sql, args):
        cur = conn.execute(sql, args)
        nomes = [d[0] for d in cur.description]
        return [dict(zip(nomes, r, strict=True)) for r in cur.fetchall()]
    chamadas = dicts("SELECT papel, tokens, tokens_entrada, tokens_saida, cache_lido, entrada, created_at FROM llm_calls "
                     "WHERE created_at>=?", (agora - 5 * SEMANA,))
    merges = [r[0] for r in conn.execute("SELECT MIN(created_at) FROM merges WHERE merged=1 GROUP BY pr "
                                         "HAVING MIN(created_at)>=?", (agora - 5 * SEMANA,))]
    semana = [c for c in chamadas if c["created_at"] >= agora - SEMANA]
    itens = dicts("SELECT titulo, status FROM roadmap WHERE updated_at>=?", (agora - SEMANA,))
    serie = serie_semanal(chamadas, merges, agora)
    kv = {k: json.loads(v) for k, v in conn.execute("SELECT key, value FROM kv WHERE key IN (?,?)", (ATIVA, HISTORICO))}
    return {**tokens_por_papel(semana, itens, sum(m >= agora - SEMANA for m in merges)), "serie": serie,
            "tendencia": tendencia(serie), "ativa": kv.get(ATIVA), "ultimo": (kv.get(HISTORICO) or [None])[-1]}


def _taxa_merge(m: dict) -> str:
    return f'{round(100 * m["mergeados"] / m["abertos"])}%' if m.get("abertos") else "—"


def card(d: dict) -> str:
    t, ativo = d["tendencia"], d["ativa"]
    meta = ("sem 4 semanas de base" if t["em_queda"] is None else
            f'{t["queda_pct"]:+.1f}% vs média de 4 semanas ({"meta atingida" if t["meta_10pct"] else "abaixo da meta de 10%"})')
    serie = " · ".join("—" if p["custo_por_pr"] is None else str(p["custo_por_pr"]) for p in d["serie"])
    exp = (f'{escape(ativo["alavanca"])}, {ativo["base"]["abertos"]} PRs na base, meta n≥{N_MIN}' if ativo else "nenhum")
    u = d["ultimo"]
    ultimo = (f'{escape(u["alavanca"])}: {escape(u["veredito"])} (merge {_taxa_merge(u["base"])} → {_taxa_merge(u["exp"])}; '
              f'{escape(u["motivo"])})' if u else "nenhum")
    return ('<section class="card falhas" aria-label="Tokens por PR mergeado"><span>Tokens por PR mergeado (7 d)</span>'
            f'<b>{d["tokens_por_pr"] if d["tokens_por_pr"] is not None else "—"}</b><small>{meta}</small><ol>'
            + "".join(f'<li>{p} <b>{v["por_pr"] if v["por_pr"] is not None else "—"} tokens/PR</b> <small>{v["tokens"]} '
                      f'tokens · entrada {v["entrada"]} · saída {v["saida"]} · cache lido {v["cache_lido"]}</small></li>'
                      for p in PAPEIS if (v := d["por_papel"][p])["tokens"])
            + f"</ol><small>Semanas (custo por PR, da mais antiga): {serie}</small><br>"
            f"<small>Experimento ativo: {exp}</small><br><small>Último concluído: {ultimo}</small></section>")

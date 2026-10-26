"""Funções puras do card de falhas do painel: agrupar por causa e por componente e o delta contra as 24 h anteriores."""

from __future__ import annotations

from collections import Counter

from .licoes import normalizar

TOP_CAUSAS = 5


def _por_causa(linhas) -> Counter:
    """Causa mais específica que houver, normalizada (números e ids não separam a mesma causa)."""
    return Counter(normalizar(causa or sig or ponto) or ponto for ponto, sig, causa in linhas)


def agrupar_por_causa(linhas) -> list[dict]:
    """Todas as falhas (ponto, assinatura, causa) por causa normalizada, com n e fração do total, da maior para a
    menor; empate pelo nome, então a ordem não depende da ordem das linhas. A primeira é a dominante."""
    n = _por_causa(linhas)
    total = sum(n.values())
    return [{"causa": c, "n": k, "fracao": k / total} for c, k in sorted(n.items(), key=lambda ck: (-ck[1], ck[0]))]


def falhas_por_causa(linhas, top: int = TOP_CAUSAS) -> dict:
    """Agrupa falhas (ponto, assinatura, causa) pela causa mais específica que houver, então toda falha tem causa;
    o que passa do top vai em 'outras', e top + outras = total."""
    grupos = agrupar_por_causa(linhas)
    causas = [{"causa": c["causa"], "n": c["n"]} for c in grupos[:top]]
    total = sum(c["n"] for c in grupos)
    return {"total": total, "causas": causas, "outras": total - sum(c["n"] for c in causas)}


def _falhas_antes(linhas) -> dict:
    """As mesmas falhas da janela de 24 h anterior, por causa inteira (sem top), base do delta do card por causa."""
    n = _por_causa(linhas)
    return {"total": sum(n.values()), "por_causa": dict(n)}


def causas_vs_antes(f: dict, antes: dict, top: int = TOP_CAUSAS) -> list[dict]:
    """Linhas do card por causa com n e anterior: o top atual, as causas do top anterior que sumiram (n=0) e 'outras'
    com o resto das duas janelas, então n soma o total atual e anterior soma o total anterior."""
    base = antes["por_causa"]
    linhas = [{"causa": c["causa"], "n": c["n"], "anterior": base.get(c["causa"], 0)} for c in f["causas"]]
    vistas = {c["causa"] for c in linhas}
    linhas += [{"causa": c, "n": 0, "anterior": k} for c, k in Counter(base).most_common(top) if c not in vistas]
    resto = antes["total"] - sum(c["anterior"] for c in linhas)
    if f["outras"] or resto:
        linhas.append({"causa": "outras", "n": f["outras"], "anterior": resto})
    return linhas


def variacao(atual: int, anterior: int) -> dict:
    """Delta de falhas contra a janela anterior, com cor invertida (alta é ruim, queda é boa); sem base não há
    percentual: 'novo' quando só a atual tem falhas, '—' quando as duas estão zeradas."""
    d = atual - anterior
    if not d:
        return {"seta": "●" if atual else "", "delta": 0, "texto": "● 0" if atual else "—", "classe": "neutro"}
    seta, sinal = ("▲", "+") if d > 0 else ("▼", "−")
    base = f"({sinal}{round(100 * abs(d) / anterior)}%)" if anterior else "novo"
    return {"seta": seta, "delta": d, "texto": f"{seta} {sinal}{abs(d)} {base}", "classe": "ruim" if d > 0 else "bom"}


def falhas_por_componente(linhas, agora: float) -> list[dict]:
    """Agrupa falhas (ponto, created_at) das últimas 48 h pelo componente (o ponto papel:etapa, sempre presente):
    n nas últimas 24 h, anterior nas 24 h antes, do mais afetado para o menos."""
    n, anterior = Counter(), Counter()
    for ponto, em in linhas:
        (n if em >= agora - 86400 else anterior)[ponto] += 1
    return [{"componente": c, "n": k, "anterior": anterior[c], "variacao": k - anterior[c]}
            for c, k in sorted(n.items(), key=lambda ck: (-ck[1], ck[0]))]

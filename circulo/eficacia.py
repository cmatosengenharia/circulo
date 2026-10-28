"""Veredito de eficácia por PR mergeado: o critério de sucesso do item melhorou de verdade ou só oscilou?

Comparar um valor antes com um depois confunde o efeito do PR com o ruído da métrica e com os outros merges do mesmo
período (Brodersen et al. 2015, CausalImpact). Aqui a linha de base é a semana antes do merge, lida ponto a ponto pelo
mesmo `Leitor` da prova (item #113), e o valor 7 dias depois do merge (o `depois` que a prova já gravou na trilha, se
houver) só conta como melhora se sair da banda de K desvios na direção que o critério pede:

- melhorou / piorou: fora da banda, na direção desejada / contrária;
- sem_efeito: dentro da banda;
- nao_medivel: sem critério, sem direção no critério, sem leitura depois ou com menos de N_MIN pontos na base
  (Kohavi et al. 2020: sem linha de base e variância, a diferença não separa sinal de ruído).

`classificar` é pura; `registrar` grava um veredito por PR com 7+ dias de merge (uma vez), junto com os outros merges
da janela (confundimento), e abre um item de roteiro pedindo a métrica para cada 'nao_medivel'.
"""
from __future__ import annotations

import json
import re
import statistics

from . import prova
from .rastro import PREFIXO_BRANCH
from .roadmap import gravar_medido
from .state import Store

D = 86400
K = 2
N_MIN = 5
PONTOS_BASE = 7                    # um por dia na semana antes do merge
_DE_PARA = re.compile(r"\bde\s+(-?\d+(?:[.,]\d+)?)\D{0,12}?\bpara\s+(-?\d+(?:[.,]\d+)?)", re.I)
_CAI = re.compile(r"\b(cai|caia|cair|reduz|diminu|menor|abaixo|baix|zer)", re.I)
_SOBE = re.compile(r"\b(sobe|suba|subir|aument|cresc|maior|acima)", re.I)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS eficacia (
  pr INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL,
  metrica TEXT,
  veredito TEXT NOT NULL,          -- melhorou | piorou | sem_efeito | nao_medivel
  motivo TEXT,
  media REAL,
  desvio REAL,
  n_pontos INTEGER NOT NULL,
  depois REAL,
  outros_merges TEXT NOT NULL,     -- JSON: PRs mergeados na janela de ±7 dias (confundimento)
  mergeado_em REAL NOT NULL,
  created_at REAL NOT NULL
)
"""


def sentido(criterio: str | None) -> int | None:
    """+1 se o critério pede que a métrica suba, -1 se pede que caia; None se não diz."""
    m = _DE_PARA.search(criterio or "")
    if m:
        de, para = (float(x.replace(",", ".")) for x in m.groups())
        if de != para:
            return 1 if para > de else -1
    cai, sobe = bool(_CAI.search(criterio or "")), bool(_SOBE.search(criterio or ""))
    return -1 if cai and not sobe else 1 if sobe and not cai else None


def classificar(base: list[float], depois: float | None, direcao: int | None, n_min: int = N_MIN) -> dict:
    """Veredito do valor `depois` contra a banda de K desvios da linha de base `base`."""
    r = {"veredito": "nao_medivel", "motivo": None, "media": None, "desvio": None, "n": len(base)}
    if direcao is None:
        return {**r, "motivo": "critério sem direção (sobe/cai)"}
    if depois is None:
        return {**r, "motivo": "sem leitura 7 dias depois do merge"}
    if len(base) < n_min:
        return {**r, "motivo": f"{len(base)} pontos na linha de base (mínimo {n_min})"}
    media, desvio = statistics.mean(base), statistics.stdev(base)
    if abs(depois - media) <= K * desvio:
        v = "sem_efeito"
    else:
        v = "melhorou" if (depois - media) * direcao > 0 else "piorou"
    return {**r, "veredito": v, "media": media, "desvio": desvio}


def fracao_nao_medivel(vereditos: list[dict], desde: float) -> list[float]:
    """Fração 'nao_medivel' por semana a partir de `desde` (o critério do item: cair a cada semana)."""
    semanas: dict[int, list[bool]] = {}
    for v in vereditos:
        semanas.setdefault(int((v["em"] - desde) // (7 * D)), []).append(v["veredito"] == "nao_medivel")
    return [sum(s) / len(s) for _, s in sorted(semanas.items())]


def _depois_gravado(store: Store, item_id: int) -> float | None:
    r = store.one("SELECT detalhe FROM elos WHERE de=? AND para=? AND relacao='mediu'",
                  (f"item:{item_id}", f"medicao:{item_id}:depois"))
    return json.loads(r["detalhe"]).get("valor") if r and r["detalhe"] else None


def registrar(store: Store, agora: float, ler: prova.Leitor) -> dict:
    """Grava o veredito de cada PR de item com 7+ dias de merge ainda sem veredito; 'nao_medivel' vira item."""
    store.x(ESQUEMA)
    merges = [(r["pr"], r["em"]) for r in store.q(
        "SELECT pr, MIN(created_at) em FROM merges WHERE merged=1 GROUP BY pr")]
    prs = store.q(
        "SELECT p.number pr, r.id item, r.detalhe, MIN(m.created_at) em FROM prs p JOIN roadmap r "
        "ON p.branch LIKE ? || r.id || '-%' JOIN merges m ON m.pr=p.number AND m.merged=1 "
        "WHERE p.number NOT IN (SELECT pr FROM eficacia) GROUP BY p.number ORDER BY p.number", (PREFIXO_BRANCH,))
    n = {"gravados": 0, "nao_medivel": 0}
    for p in prs:
        apos = p["em"] + prova.JANELA_S
        if agora < apos:
            continue
        metrica = prova.criterio(p["detalhe"])
        if metrica:
            base = [v for k in range(1, PONTOS_BASE + 1) if (v := ler(metrica, p["em"] - k * D)) is not None]
            depois = _depois_gravado(store, p["item"])
            v = classificar(base, ler(metrica, apos) if depois is None else depois, sentido(metrica))
        else:
            depois, v = None, {**classificar([], None, None), "motivo": "item sem critério de sucesso"}
        outros = [pr for pr, em in merges if pr != p["pr"] and abs(em - p["em"]) <= prova.JANELA_S]
        store.x("INSERT INTO eficacia(pr,item_id,metrica,veredito,motivo,media,desvio,n_pontos,depois,outros_merges,"
                "mergeado_em,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (p["pr"], p["item"], metrica, v["veredito"], v["motivo"], v["media"], v["desvio"], v["n"],
                 depois, json.dumps(outros), p["em"], agora))
        n["gravados"] += 1
        if v["veredito"] == "nao_medivel":
            n["nao_medivel"] += 1
            gravar_medido(store, "eficacia", f"eficacia:metrica:pr{p['pr']}",
                          f"Dar métrica medível ao critério do item #{p['item']} (PR #{p['pr']})",
                          f"O veredito de eficácia do PR #{p['pr']} saiu nao_medivel: {v['motivo']}.\n"
                          f"Critério atual: {metrica or '(nenhum)'}\n"
                          "Escrever a linha Sucesso com métrica, direção (sobe/cai) e fonte de dados lida pelo Leitor.\n"
                          f"Sucesso: o critério do item #{p['item']} tem leitura e {N_MIN}+ pontos na semana antes do merge",
                          f"Eficácia (medido): PR #{p['pr']} nao_medivel")
    return n

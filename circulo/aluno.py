"""O aluno do Jev: um modelo local que aprende, com as respostas do Jev, a responder as mesmas perguntas.

Degrau novo da cascata (regra → **aluno** → Jev → LLM), por enquanto só em SOMBRA: ele palpita em paralelo a cada
decisão do Jev e a concordância fica medida; nada é decidido por ele até a chave `aluno.decidir` ser ligada na
política, e só para perguntas em que ele provou acerto. O Jev continua sendo o professor e o árbitro.

Como aprende (destilação, sem dependência externa):
- dados: `decisions` com `source='jev'` e confiança ≥ CONF_PROFESSOR, com o estado que o Jev viu (`estado`);
- um modelo por pergunta (nome normalizado: `indaga_pert_5` → `indaga_pert`), regressão logística multiclasse sobre
  features em hash (categorias, números em faixas, palavras dos textos), treinada por SGD em Python puro;
- validação temporal: os últimos 20 % viram holdout; acurácia é comparada com a classe majoritária (baseline);
- pronto = exemplos ≥ MIN_EXEMPLOS, acurácia ≥ ACURACIA_MIN e ganho sobre o baseline ≥ GANHO_MIN, e em sombra
  concordância ≥ CONCORDANCIA_MIN em ≥ MIN_SOMBRA palpites.

É o "aprendizado profundo" na medida certa para o dado que existe: o estado das decisões é tabular e pequeno; quando
houver milhares de exemplos de texto livre (pertinência do Product owner), o mesmo encaixe recebe um modelo maior.
"""
from __future__ import annotations

import json
import math
import re
import time
import zlib
from typing import Any, Mapping

from .state import Store

CONF_PROFESSOR = 0.8
MIN_EXEMPLOS = 120
ACURACIA_MIN = 0.90
GANHO_MIN = 0.03
CONCORDANCIA_MIN = 0.95
MIN_SOMBRA = 300
DIM = 1 << 15
EPOCAS = 6
TAXA = 0.15
L2 = 1e-4
HOLDOUT = 0.2
TREINAR_A_CADA = 6 * 3600
NOVOS_PARA_TREINAR = 200
KV = "aluno_modelo"
IGNORAR = ("crit_", "rel_", "ach_", "llm:")      # perguntas por critério/trecho: milhares de nomes, pouco sinal por nome

ESQUEMA = """
CREATE TABLE IF NOT EXISTS aluno_sombra (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  question TEXT NOT NULL,
  previsto TEXT NOT NULL,
  prob REAL NOT NULL,
  jev TEXT NOT NULL,
  concorda INTEGER NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS aluno_sombra_q ON aluno_sombra(question, created_at);
"""


def _esquema(store) -> None:
    """Statement a statement, sob o lock do Store: `executescript` fecha a transação em curso de quem chamou (o pedido
    do usuário roda `observar` dentro de `with s.tx()`; o COMMIT implícito quebrava o tx e o pedido era reprocessado)."""
    if getattr(store, "_aluno_esquema", False):
        return
    for sql in ESQUEMA.split(";"):
        if sql.strip():
            store.x(sql)
    store._aluno_esquema = True          # por Store, não global: cada banco (testes, memória externa) tem o seu

_SUFIXO = re.compile(r"_\d+$")


def pergunta(nome: str) -> str:
    return _SUFIXO.sub("", nome)


def rotulo(valor: Any) -> str:
    """A classe que o aluno prevê: a escolha, ou o número arredondado a 0,1 (noul/escala viram faixas)."""
    if isinstance(valor, bool):
        return str(valor).lower()
    if isinstance(valor, (int, float)):
        return f"{round(float(valor), 1):.1f}"
    return str(valor)[:60]


def compactar(estado: Mapping[str, Any], limite: int = 1500) -> str:
    """O estado como JSON que SEMPRE fecha: textos encurtados, listas cortadas e, se ainda passar do limite, as chaves
    maiores saem — em vez de cortar a string do JSON no meio (no Mac isso quebrou o treino 8 vezes seguidas)."""
    def enxuto(v, n=200):
        if isinstance(v, str):
            return v[:n]
        if isinstance(v, (list, tuple)):
            return [enxuto(x, 80) for x in list(v)[:8]]
        if isinstance(v, dict):
            return {str(k)[:40]: enxuto(x, 80) for k, x in list(v.items())[:12]}
        return v if isinstance(v, (int, float, bool)) or v is None else str(v)[:n]
    d = {str(k)[:40]: enxuto(v) for k, v in dict(estado).items()}
    s = json.dumps(d, ensure_ascii=False)
    while len(s) > limite and d:
        grandes = [k for k in d if d[k] != "…"]
        if grandes:
            d[max(grandes, key=lambda k: len(json.dumps(d[k], ensure_ascii=False)))] = "…"
        else:
            del d[max(d, key=len)]
        s = json.dumps(d, ensure_ascii=False)
    return s


def _estado(texto: str | None) -> dict:
    try:
        d = json.loads(texto) if texto else {}
    except ValueError:                           # registro antigo cortado no meio: não ensina nada, não derruba o treino
        return {}
    return d if isinstance(d, dict) else {}


def _h(s: str) -> int:
    return zlib.crc32(s.encode("utf-8")) % DIM


def features(estado: Mapping[str, Any]) -> dict[int, float]:
    """Hash de features do estado que o Jev viu: categoria=valor, números em faixas log e normalizados, palavras."""
    f: dict[int, float] = {_h("_viés"): 1.0}
    for k, v in (estado or {}).items():
        k = str(k)
        if isinstance(v, bool) or v is None:
            f[_h(f"{k}={v}")] = 1.0
        elif isinstance(v, (int, float)):
            x = float(v)
            faixa = 0 if x == 0 else int(math.copysign(min(12, math.floor(math.log10(abs(x)) + 1)), x))
            f[_h(f"{k}~{faixa}")] = 1.0
            f[_h(f"{k}#")] = max(-3.0, min(3.0, x if abs(x) <= 1 else math.log10(abs(x)) * math.copysign(1, x) / 3))
        elif isinstance(v, str):
            if len(v) <= 40 and " " not in v.strip():
                f[_h(f"{k}={v.lower()}")] = 1.0
            else:
                palavras = re.findall(r"[a-zA-ZÀ-ÿ_][a-zA-ZÀ-ÿ0-9_]{2,}", v[:300].lower())
                for p in set(palavras):
                    f[_h(f"{k}:{p}")] = 1.0
        elif isinstance(v, (list, tuple)):
            f[_h(f"{k}.n~{min(len(v), 9)}")] = 1.0
            for item in v[:8]:
                if isinstance(item, (str, int, float)):
                    f[_h(f"{k}[]={str(item).lower()[:40]}")] = 1.0
        elif isinstance(v, dict):
            for k2, v2 in list(v.items())[:12]:
                if isinstance(v2, (str, int, float, bool)) or v2 is None:
                    f[_h(f"{k}.{k2}={str(v2).lower()[:40]}")] = 1.0
    return f


class Modelo:
    """Regressão logística multiclasse (softmax) sobre features em hash. Pesos esparsos: só o que apareceu."""

    def __init__(self, classes: list[str], pesos: dict[str, dict[str, float]] | None = None):
        self.classes = classes
        self.w: dict[str, dict[int, float]] = {c: {int(k): v for k, v in (pesos or {}).get(c, {}).items()} for c in classes}

    def probabilidades(self, f: dict[int, float]) -> dict[str, float]:
        z = {c: sum(self.w[c].get(i, 0.0) * x for i, x in f.items()) for c in self.classes}
        m = max(z.values())
        e = {c: math.exp(v - m) for c, v in z.items()}
        tot = sum(e.values()) or 1.0
        return {c: v / tot for c, v in e.items()}

    def prever(self, f: dict[int, float]) -> tuple[str, float]:
        p = self.probabilidades(f)
        c = max(p, key=p.get)
        return c, p[c]

    def treinar(self, exemplos: list[tuple[dict[int, float], str]], epocas: int = EPOCAS, taxa: float = TAXA) -> None:
        for ep in range(epocas):
            lr = taxa / (1 + ep)
            for f, y in exemplos:
                p = self.probabilidades(f)
                for c in self.classes:
                    g = p[c] - (1.0 if c == y else 0.0)
                    if abs(g) < 1e-4:
                        continue
                    wc = self.w[c]
                    for i, x in f.items():
                        wc[i] = wc.get(i, 0.0) * (1 - lr * L2) - lr * g * x

    def exportar(self) -> dict:
        return {"classes": self.classes, "pesos": {c: {str(i): round(v, 5) for i, v in w.items() if abs(v) > 1e-4} for c, w in self.w.items()}}


# ------------------------------------------------------------------ treino
def exemplos_de(store: Store, desde: float = 0.0, limite: int = 20000) -> dict[str, list[tuple[dict[int, float], str, float]]]:
    """Por pergunta: (features, rótulo do Jev, quando). Só decisões do Jev confiante e com o estado gravado."""
    from .desfecho import rotulos
    por_q: dict[str, list] = {}
    medidos = {q: rotulos(store, q, desde) for q in ("worth_spending", "should_evolve")}   # o que deu certo, quando se sabe
    for r in store.q("SELECT id, question, value, estado, created_at FROM decisions WHERE source='jev' AND confidence>=? AND estado IS NOT NULL "
                     "AND created_at>? ORDER BY id DESC LIMIT ?", (CONF_PROFESSOR, desde, limite)):
        q = pergunta(r["question"])
        if q.startswith(IGNORAR):
            continue
        estado = _estado(r["estado"])
        if not estado:
            continue
        medido = medidos.get(r["question"], {}).get(int(r["id"]))
        por_q.setdefault(q, []).append((features(estado), medido if medido is not None else rotulo(json.loads(r["value"])), float(r["created_at"])))
    for q in por_q:
        por_q[q].sort(key=lambda e: e[2])        # do mais antigo ao mais novo: o holdout é o fim
    return por_q


def treinar(store: Store, agora: float | None = None) -> dict:
    """Treina um modelo por pergunta e guarda tudo em kv (pesos + métricas). Devolve o relatório."""
    agora = agora or time.time()
    _esquema(store)
    por_q = exemplos_de(store)
    modelos: dict[str, dict] = {}
    for q, ex in por_q.items():
        if len(ex) < MIN_EXEMPLOS:
            modelos[q] = {"n": len(ex), "status": "poucos_exemplos"}
            continue
        corte = int(len(ex) * (1 - HOLDOUT))
        treino, teste = ex[:corte], ex[corte:]
        classes = sorted({y for _, y, _ in ex})
        maioria = max(classes, key=lambda c: sum(y == c for _, y, _ in treino))
        baseline = sum(y == maioria for _, y, _ in teste) / len(teste)
        if len(classes) == 1:
            modelos[q] = {"n": len(ex), "status": "uma_classe", "classes": classes, "acuracia": 1.0, "baseline": 1.0, "maioria": maioria}
            continue
        m = Modelo(classes)
        m.treinar([(f, y) for f, y, _ in treino])
        acertos = sum(m.prever(f)[0] == y for f, y, _ in teste)
        acc = acertos / len(teste)
        pronto = acc >= ACURACIA_MIN and acc - baseline >= GANHO_MIN
        m.treinar([(f, y) for f, y, _ in teste], epocas=2)            # fecha o treino com tudo, já medido
        modelos[q] = {"n": len(ex), "status": "pronto_para_sombra" if pronto else "fraco", "classes": classes, "acuracia": round(acc, 3),
                      "baseline": round(baseline, 3), "maioria": maioria, "holdout": len(teste), **m.exportar()}
    total = store.one("SELECT COUNT(*) n, MAX(id) m FROM decisions WHERE source='jev'")
    rel = {"em": agora, "decisoes_vistas": int(total["m"] or 0), "modelos": modelos,
           "resumo": {"perguntas": len(modelos), "prontas": sum(1 for v in modelos.values() if v["status"] == "pronto_para_sombra"),
                      "exemplos": sum(v["n"] for v in modelos.values())}}
    store.set(KV, rel)
    return rel


def treinar_se_preciso(store: Store, agora: float | None = None) -> dict | None:
    """Treina de novo a cada TREINAR_A_CADA ou quando chegarem NOVOS_PARA_TREINAR decisões do Jev."""
    agora = agora or time.time()
    rel = store.get(KV) or {}
    ultimo = store.one("SELECT MAX(id) m FROM decisions WHERE source='jev'")["m"] or 0
    if rel and agora - float(rel.get("em", 0)) < TREINAR_A_CADA and ultimo - int(rel.get("decisoes_vistas", 0)) < NOVOS_PARA_TREINAR:
        return None
    return treinar(store, agora)


# ------------------------------------------------------------------ sombra
_cache: dict[str, Any] = {"em": 0.0, "modelos": {}}


def _modelos(store: Store) -> dict[str, Modelo]:
    rel = store.get(KV) or {}
    if rel.get("em", 0.0) != _cache["em"]:
        _cache["em"] = rel.get("em", 0.0)
        _cache["modelos"] = {q: Modelo(v["classes"], v.get("pesos")) for q, v in rel.get("modelos", {}).items() if v.get("status") == "pronto_para_sombra"}
    return _cache["modelos"]


def palpite(store: Store, nome: str, estado: Mapping[str, Any]) -> tuple[str, float] | None:
    m = _modelos(store).get(pergunta(nome))
    return m.prever(features(estado)) if m else None


def observar(store: Store, nome: str, estado: Mapping[str, Any], valor_jev: Any) -> dict | None:
    """Em sombra: o aluno palpita, o Jev decide, a concordância fica gravada. Nada muda na decisão."""
    p = palpite(store, nome, estado)
    if p is None:
        return None
    previsto, prob = p
    jev = rotulo(valor_jev)
    concorda = int(previsto == jev)
    _esquema(store)
    store.x("INSERT INTO aluno_sombra(question,previsto,prob,jev,concorda,created_at) VALUES(?,?,?,?,?,?)",
            (pergunta(nome), previsto, prob, jev, concorda, time.time()))
    return {"question": pergunta(nome), "previsto": previsto, "prob": prob, "jev": jev, "concorda": bool(concorda)}


def concordancia(store: Store, dias: float = 7.0) -> dict[str, dict]:
    if not store.one("SELECT 1 FROM sqlite_master WHERE name='aluno_sombra'"):
        return {}
    desde = time.time() - dias * 86400
    return {r["question"]: {"n": int(r["n"]), "concorda": round(float(r["c"] or 0), 3), "prob_media": round(float(r["p"] or 0), 3)}
            for r in store.q("SELECT question, COUNT(*) n, AVG(concorda) c, AVG(prob) p FROM aluno_sombra WHERE created_at>=? GROUP BY question", (desde,))}


def pronto_para_decidir(store: Store, nome: str) -> bool:
    """Provou em sombra: concordância ≥ 95 % em ≥ 300 palpites recentes, com um modelo pronto."""
    c = concordancia(store).get(pergunta(nome))
    return bool(c and c["n"] >= MIN_SOMBRA and c["concorda"] >= CONCORDANCIA_MIN and pergunta(nome) in _modelos(store))


def resumo(store: Store) -> dict:
    rel = store.get(KV) or {}
    conc = concordancia(store)
    linhas = []
    for q, v in sorted(rel.get("modelos", {}).items(), key=lambda kv: -kv[1]["n"]):
        c = conc.get(q, {})
        linhas.append({"pergunta": q, "exemplos": v["n"], "status": v["status"], "acuracia": v.get("acuracia"), "baseline": v.get("baseline"),
                       "classes": len(v.get("classes", [])), "sombra_n": c.get("n", 0), "sombra_concorda": c.get("concorda"),
                       "pronta_para_decidir": bool(c and c["n"] >= MIN_SOMBRA and c["concorda"] >= CONCORDANCIA_MIN and v["status"] == "pronto_para_sombra")})
    return {"treinado_em": rel.get("em"), "decisoes_vistas": rel.get("decisoes_vistas", 0), "resumo": rel.get("resumo", {}), "perguntas": linhas,
            "criterios": {"min_exemplos": MIN_EXEMPLOS, "acuracia_min": ACURACIA_MIN, "ganho_min": GANHO_MIN, "concordancia_min": CONCORDANCIA_MIN, "min_sombra": MIN_SOMBRA},
            "decide": False}

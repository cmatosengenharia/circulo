"""Regras promovidas do Jev (pergunta #533): o par (entrada normalizada → decisão) que o Jev repete vira regra
determinística consultada ANTES dele.

- minerar: decisões do Jev dos últimos JANELA s, agrupadas por (pergunta, entrada normalizada); um par entra se tem
  n ≥ N_MIN e a mesma decisão em mais de CONSISTENCIA_MIN dos casos;
- promover: grava os primeiros (por n) em `regras_jev` com n e taxa, até MAX_REGRAS ligadas; regra desligada não volta;
- sombra (item #306): a regra promovida não age; o Jev decide e `conferir` grava em `regra_sombra` a decisão da regra,
  a do Jev e o PR do estado (`desfechos` completa com o desfecho quando o PR fecha). `avaliar` faz a regra assumir só com ≥ SOMBRA_MIN de idade, n ≥ N_SOMBRA comparações e limite inferior
  de Wilson (95%) da concordância ≥ CONCORDANCIA_INF (19 de 20 dá 95% pontual, mas ~76% no limite inferior);
- antes_do_jev: a regra que assumiu decide no lugar do Jev (source 'local', como a regra determinística); a cada
  AUDITAR_A_CADA vezes (10%) segue em sombra: o Jev decide de novo e `conferir` compara. Limite inferior abaixo de
  CONCORDANCIA_INF, a regra volta à sombra; errou em mais de ERRO_MAX das conferências, é desligada.
"""
from __future__ import annotations

import json
import math
import statistics
import time
from collections import Counter, defaultdict
from typing import Any, Mapping

from . import aluno

JANELA = 7 * 86400
N_MIN = 20
CONSISTENCIA_MIN = 0.9
MAX_REGRAS = 3
AUDITAR_A_CADA = 10
ERRO_MAX = 0.10
PROMOVER_A_CADA = 3600
SOMBRA_MIN = 7 * 86400
N_SOMBRA = 40
CONCORDANCIA_INF = 0.9
Z = 1.96
KV = "regras_jev.promovido_em"

ESQUEMA = ("""
CREATE TABLE IF NOT EXISTS regras_jev (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  question TEXT NOT NULL,
  entrada TEXT NOT NULL,
  rotulo TEXT NOT NULL,
  valor TEXT NOT NULL,
  n INTEGER NOT NULL,
  taxa REAL NOT NULL,
  usos INTEGER NOT NULL DEFAULT 0,
  conferidas INTEGER NOT NULL DEFAULT 0,
  erros INTEGER NOT NULL DEFAULT 0,
  ativa INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  desligada_em REAL,
  assumiu_em REAL,
  concordancia_inf REAL,
  UNIQUE(question, entrada)
)""", """
CREATE TABLE IF NOT EXISTS regra_sombra (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  regra_id INTEGER NOT NULL,
  regra TEXT NOT NULL,
  jev TEXT NOT NULL,
  concorda INTEGER NOT NULL,
  assumida INTEGER NOT NULL,
  pr INTEGER,
  desfecho TEXT,
  em REAL NOT NULL
)""", "CREATE INDEX IF NOT EXISTS regra_sombra_regra ON regra_sombra(regra_id)")


def _esquema(store) -> None:
    if not getattr(store, "_regras_esquema", False):
        for sql in ESQUEMA:
            store.x(sql)
        cols = {r["name"] for r in store.q("PRAGMA table_info(regras_jev)")}
        for col in ("assumiu_em", "concordancia_inf"):
            if col not in cols:
                store.x(f"ALTER TABLE regras_jev ADD COLUMN {col} REAL")
        store._regras_esquema = True


def wilson_inf(acertos: int, n: int, z: float = Z) -> float:
    """Limite inferior do intervalo de Wilson para a proporção acertos/n (0 sem amostra)."""
    if n == 0:
        return 0.0
    p, z2 = acertos / n, z * z
    return (p + z2 / (2 * n) - z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))) / (1 + z2 / n)


def _normal(v: Any) -> Any:
    """Números em faixas (≤1 a 0,1; acima, ordem de grandeza), textos curtos em minúsculas, o resto recursivo."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        x = float(v)
        return round(x, 1) if abs(x) <= 1 else f"~{int(math.copysign(math.floor(math.log10(abs(x))) + 1, x))}"
    if isinstance(v, str):
        return v.strip().lower()
    if isinstance(v, (list, tuple)):
        return [_normal(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _normal(x) for k, x in sorted(v.items())}
    return str(v)


def entrada(estado: Mapping[str, Any] | str | None) -> str:
    """A entrada normalizada: o estado como o Jev o viu (o mesmo `compactar` gravado em `decisions.estado`)."""
    d = aluno._estado(estado) if isinstance(estado, str) or estado is None else json.loads(aluno.compactar(estado))
    return json.dumps(_normal(d), ensure_ascii=False, sort_keys=True)


def rotulo(valor: Any) -> str:
    """A decisão como classe: escolha, sim/não para probabilidade (noul) e o nível inteiro para escala."""
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        x = float(valor)
        return ("sim" if x >= 0.5 else "nao") if 0 <= x <= 1 else str(round(x))
    return str(valor)


def minerar(store, agora: float | None = None) -> list[dict]:
    """Pares com n ≥ N_MIN e consistência > CONSISTENCIA_MIN nas decisões do Jev da janela, do maior n ao menor."""
    agora = agora or time.time()
    grupos: dict[tuple, list] = defaultdict(list)
    for r in store.q("SELECT question, value, estado FROM decisions WHERE source='jev' AND estado IS NOT NULL "
                     "AND created_at>=?", (agora - JANELA,)):
        if not r["question"].startswith(aluno.IGNORAR):
            grupos[(r["question"], entrada(r["estado"]))].append(aluno._ler(r["value"]))
    pares = []
    for (q, e), valores in grupos.items():
        rot, k = Counter(rotulo(v) for v in valores).most_common(1)[0]
        if len(valores) >= N_MIN and k / len(valores) > CONSISTENCIA_MIN:
            iguais = [v for v in valores if rotulo(v) == rot]
            valor = iguais[0] if isinstance(iguais[0], str) else statistics.median(iguais)
            pares.append({"question": q, "entrada": e, "rotulo": rot, "valor": valor, "n": len(valores),
                          "taxa": round(k / len(valores), 4)})
    return sorted(pares, key=lambda p: (-p["n"], -p["taxa"], p["question"]))


def promover(store, agora: float | None = None) -> list[dict]:
    """Grava os primeiros pares ainda sem regra até MAX_REGRAS ligadas; devolve os promovidos agora."""
    _esquema(store)
    agora = agora or time.time()
    store.set(KV, agora)
    desfechos(store)
    vagas = MAX_REGRAS - store.one("SELECT COUNT(*) c FROM regras_jev WHERE ativa=1")["c"]
    feitas = {(r["question"], r["entrada"]) for r in store.q("SELECT question, entrada FROM regras_jev")}
    novos = [p for p in minerar(store, agora) if (p["question"], p["entrada"]) not in feitas][:max(0, vagas)]
    for p in novos:
        store.x("INSERT OR IGNORE INTO regras_jev(question,entrada,rotulo,valor,n,taxa,created_at) VALUES(?,?,?,?,?,?,?)",
                (p["question"], p["entrada"], p["rotulo"], json.dumps(p["valor"]), p["n"], p["taxa"], agora))
    return novos


def antes_do_jev(store, state: Mapping[str, Any], questions: Mapping[str, Any]) -> tuple[dict, dict]:
    """({pergunta: Decision da regra}, {pergunta: (id da regra a conferir com o Jev, PR do estado)}) para as perguntas
    com regra ligada."""
    from .decision import Decision
    _esquema(store)
    if time.time() - float(store.get(KV) or 0) >= PROMOVER_A_CADA:
        promover(store)
    decididas, auditar = {}, {}
    e = entrada(state)
    pr = state.get("pr") if type(state.get("pr")) is int else None
    for qid, q in questions.items():
        r = store.one("SELECT * FROM regras_jev WHERE ativa=1 AND question=? AND entrada=?", (qid, e))
        if r is None:
            continue
        if r["assumiu_em"] is None or (r["usos"] + r["conferidas"] + 1) % AUDITAR_A_CADA == 0:
            auditar[qid] = (r["id"], pr)
            continue
        store.x("UPDATE regras_jev SET usos=usos+1 WHERE id=?", (r["id"],))
        decididas[qid] = Decision(qid, q.kind, json.loads(r["valor"]), float(r["taxa"]), "local")
    return decididas, auditar


def conferir(store, regra_id: int, decisao, pr: int | None = None) -> bool:
    """Grava a sombra (regra × Jev, e o PR em jogo), desliga a regra se errou em mais de ERRO_MAX das conferências e reavalia se ela
    assume ou volta à sombra."""
    r = store.one("SELECT rotulo, conferidas, erros, assumiu_em FROM regras_jev WHERE id=?", (regra_id,))
    jev = rotulo(decisao.value)
    erro = jev != r["rotulo"]
    store.x("INSERT INTO regra_sombra(regra_id,regra,jev,concorda,assumida,pr,em) VALUES(?,?,?,?,?,?,?)",
            (regra_id, r["rotulo"], jev, int(not erro), int(r["assumiu_em"] is not None), pr, time.time()))
    conferidas, erros = r["conferidas"] + 1, r["erros"] + erro
    desligar = erros / conferidas > ERRO_MAX
    store.x("UPDATE regras_jev SET conferidas=?, erros=?, ativa=?, desligada_em=? WHERE id=?",
            (conferidas, erros, 0 if desligar else 1, time.time() if desligar else None, regra_id))
    avaliar(store, regra_id)
    return not erro


def avaliar(store, regra_id: int, agora: float | None = None) -> bool:
    """A regra assume (ou segue assumida) só com ≥ SOMBRA_MIN desde a promoção, n ≥ N_SOMBRA comparações em sombra e
    limite inferior de Wilson da concordância ≥ CONCORDANCIA_INF; senão fica (ou volta) em sombra."""
    _esquema(store)
    agora = agora or time.time()
    r = store.one("SELECT created_at, assumiu_em FROM regras_jev WHERE id=?", (regra_id,))
    c = store.one("SELECT COUNT(*) n, COALESCE(SUM(concorda), 0) k FROM regra_sombra WHERE regra_id=?", (regra_id,))
    inf = wilson_inf(c["k"], c["n"])
    assume = agora - r["created_at"] >= SOMBRA_MIN and c["n"] >= N_SOMBRA and inf >= CONCORDANCIA_INF
    store.x("UPDATE regras_jev SET assumiu_em=?, concordancia_inf=? WHERE id=?",
            ((r["assumiu_em"] or agora) if assume else None, round(inf, 4), regra_id))
    return assume


def desfechos(store) -> int:
    """Completa a sombra com o desfecho (mergeado/fechado) dos PRs que já fecharam; devolve quantas linhas mudaram."""
    _esquema(store)
    antes = store.one("SELECT COUNT(*) c FROM regra_sombra WHERE desfecho IS NOT NULL")["c"]
    store.x("UPDATE regra_sombra SET desfecho=(SELECT status FROM prs WHERE number=regra_sombra.pr) "
            "WHERE desfecho IS NULL AND pr IN (SELECT number FROM prs WHERE status IN ('mergeado','fechado'))")
    return store.one("SELECT COUNT(*) c FROM regra_sombra WHERE desfecho IS NOT NULL")["c"] - antes

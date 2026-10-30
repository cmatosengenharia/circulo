"""Regras promovidas do Jev (pergunta #533): o par (entrada normalizada → decisão) que o Jev repete vira regra
determinística consultada ANTES dele.

- minerar: decisões do Jev dos últimos JANELA s, agrupadas por (pergunta, entrada normalizada); um par entra se tem
  n ≥ N_MIN e a mesma decisão em mais de CONSISTENCIA_MIN dos casos;
- promover: grava os primeiros (por n) em `regras_jev` com n e taxa, até MAX_REGRAS ligadas; regra desligada não volta;
- antes_do_jev: a regra ligada decide no lugar do Jev (source 'local', como a regra determinística); a cada
  AUDITAR_A_CADA vezes o Jev decide de novo e `conferir` compara: errou em mais de ERRO_MAX das conferências, a regra
  é desligada e o Jev volta a decidir.
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
KV = "regras_jev.promovido_em"

ESQUEMA = """
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
  UNIQUE(question, entrada)
)
"""


def _esquema(store) -> None:
    if not getattr(store, "_regras_esquema", False):
        store.x(ESQUEMA)
        store._regras_esquema = True


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
    vagas = MAX_REGRAS - store.one("SELECT COUNT(*) c FROM regras_jev WHERE ativa=1")["c"]
    feitas = {(r["question"], r["entrada"]) for r in store.q("SELECT question, entrada FROM regras_jev")}
    novos = [p for p in minerar(store, agora) if (p["question"], p["entrada"]) not in feitas][:max(0, vagas)]
    for p in novos:
        store.x("INSERT OR IGNORE INTO regras_jev(question,entrada,rotulo,valor,n,taxa,created_at) VALUES(?,?,?,?,?,?,?)",
                (p["question"], p["entrada"], p["rotulo"], json.dumps(p["valor"]), p["n"], p["taxa"], agora))
    return novos


def antes_do_jev(store, state: Mapping[str, Any], questions: Mapping[str, Any]) -> tuple[dict, dict]:
    """({pergunta: Decision da regra}, {pergunta: id da regra a conferir com o Jev}) para as perguntas com regra ligada."""
    from .decision import Decision
    _esquema(store)
    if time.time() - float(store.get(KV) or 0) >= PROMOVER_A_CADA:
        promover(store)
    decididas, auditar = {}, {}
    e = entrada(state)
    for qid, q in questions.items():
        r = store.one("SELECT * FROM regras_jev WHERE ativa=1 AND question=? AND entrada=?", (qid, e))
        if r is None:
            continue
        if (r["usos"] + r["conferidas"] + 1) % AUDITAR_A_CADA == 0:
            auditar[qid] = r["id"]
            continue
        store.x("UPDATE regras_jev SET usos=usos+1 WHERE id=?", (r["id"],))
        decididas[qid] = Decision(qid, q.kind, json.loads(r["valor"]), float(r["taxa"]), "local")
    return decididas, auditar


def conferir(store, regra_id: int, decisao) -> bool:
    """Compara a regra com a decisão real do Jev; desliga a regra se errou em mais de ERRO_MAX das conferências."""
    r = store.one("SELECT rotulo, conferidas, erros FROM regras_jev WHERE id=?", (regra_id,))
    erro = rotulo(decisao.value) != r["rotulo"]
    conferidas, erros = r["conferidas"] + 1, r["erros"] + erro
    desligar = erros / conferidas > ERRO_MAX
    store.x("UPDATE regras_jev SET conferidas=?, erros=?, ativa=?, desligada_em=? WHERE id=?",
            (conferidas, erros, 0 if desligar else 1, time.time() if desligar else None, regra_id))
    return not erro

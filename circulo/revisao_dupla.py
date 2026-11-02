"""Revisão dupla independente (ECC-2 do ADR 0001, portado da skill `santa-method` do everything-claude-code, MIT).

Dois revisores, a mesma rubrica, nenhum contexto em comum: o Validador LLM (`validador.revisar_pr`, cujo SYSTEM é
montado de `RUBRICA`) e o Jev, que dá um Score por critério sobre o mesmo diff sem ver o veredito do Validador.
Os dois aprovam ou é rodada de correção; `TETO` rodadas seguidas sem acordo no mesmo item e o portão do PR
(`portao`, dentro de `neuronios.avaliar_aprendidos`) devolve o item com a lista de achados.
Só o Jev remoto opina: a regra local não lê diff, e sem opinião o Validador decide sozinho (nunca para a entrega).
`medir` conta quantos PRs a segunda opinião barrou (Validador aprovou, Jev não) e quantos desses o CI depois reprovou.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .decision import DecisionLayer, Question
from .state import Store

PORTAO = "revisão dupla (Validador + Jev)"
PREFIXO = "dupla_"
TETO = 2                         # rodadas sem acordo antes de o item voltar
LIMIAR = 0.5                     # Score abaixo disso (nível 0 de 0..2) é achado
MAX_DIFF = 9000
RUBRICA = (                      # (critério, o problema que reprova): a mesma lista no SYSTEM do Validador
    ("teste", "o teste novo não prova o que o item pede"),
    ("escopo", "mudança fora do escopo do item"),
    ("regressao", "regressão visível"),
    ("testes_intactos", "teste enfraquecido ou removido"),
    ("segredo", "segredo ou caminho absoluto no código"),
)
NIVEIS = ("o problema está no diff, de forma concreta e verificável",
          "há sinal do problema, mas o diff não basta para afirmar",
          "o diff está livre do problema")
ESQUEMA = """
CREATE TABLE IF NOT EXISTS revisao_dupla (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item INTEGER,
  wt TEXT NOT NULL,
  rodada INTEGER NOT NULL,
  llm INTEGER NOT NULL,
  jev INTEGER,                   -- NULL: o Jev não opinou
  decisao TEXT NOT NULL,         -- acordo | corrigir | devolver
  achados TEXT NOT NULL,
  created_at REAL NOT NULL
)
"""


def opinar(dl: DecisionLayer, item: dict, diff: str) -> dict | None:
    """A segunda opinião: {aprovado, achados, notas}, ou None se o Jev remoto não respondeu por todos os critérios.
    `dl.ask_many` é o da camada de decisão: devolve {pergunta: Decision} (a tupla do cliente Jev fica lá dentro)."""
    qs = {PREFIXO + k: Question("score", f"O diff está livre deste problema: {p}?", NIVEIS) for k, p in RUBRICA}
    estado = {"item": item.get("titulo", ""), "detalhe": str(item.get("detalhe", ""))[:1500], "diff": diff[:MAX_DIFF]}
    res = dl.ask_many(estado, qs)              # Jev fora do ar: a camada responde pela regra local, que não opina
    if any(d.source != "jev" for d in res.values()):
        return None
    notas = {k: round(float(res[PREFIXO + k].value), 3) for k, _ in RUBRICA}
    achados = [f"Jev (rubrica, {k}={notas[k]}): {p}" for k, p in RUBRICA if notas[k] < LIMIAR]
    return {"aprovado": not achados, "achados": achados, "notas": notas}


def combinar(store: Store, item_id: int | None, wt: Path, v: dict, jev: dict | None) -> dict:
    """Junta os dois vereditos em `v` (aprovado só se os dois aprovam), grava a rodada e marca `revisao_dupla`."""
    store.x(ESQUEMA)
    aprovado = v["aprovado"] and (jev is None or jev["aprovado"])
    anteriores = [r["decisao"] for r in store.q("SELECT decisao FROM revisao_dupla WHERE item IS ? ORDER BY id", (item_id,))]
    corte = max((i for i, d in enumerate(anteriores) if d != "corrigir"), default=-1)
    rodada = len(anteriores) - corte
    decisao = "acordo" if aprovado else ("devolver" if rodada >= TETO else "corrigir")
    problemas = [*v["problemas"], *(jev["achados"] if jev else [])]
    store.x("INSERT INTO revisao_dupla(item, wt, rodada, llm, jev, decisao, achados, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (item_id, str(Path(wt).resolve()), rodada, int(v["aprovado"]), None if jev is None else int(jev["aprovado"]),
             decisao, json.dumps(problemas, ensure_ascii=False), time.time()))
    return {**v, "aprovado": aprovado, "problemas": problemas, "revisao_dupla": decisao}


def portao(store: Store, item_id: int | None, wt: Path):
    """Resultado reprovado (com os achados) se este worktree estourou o teto de rodadas sem acordo; senão None."""
    from .neuronios import Resultado
    store.x(ESQUEMA)
    r = store.one("SELECT rodada, achados FROM revisao_dupla WHERE item IS ? AND wt=? AND decisao='devolver' "
                  "ORDER BY id DESC LIMIT 1", (item_id, str(Path(wt).resolve())))
    if r is None:
        return None
    achados = "; ".join(json.loads(r["achados"]))
    return Resultado(PORTAO, False, f"{r['rodada']} rodadas sem acordo entre Validador e Jev: {achados}"[:1500])


def medir(store: Store) -> dict:
    """Rodadas, acordos, PRs que só a segunda opinião barrou e quantos desses o CI reprovou depois."""
    store.x(ESQUEMA)
    barrados = store.q("SELECT item, MIN(created_at) em FROM revisao_dupla WHERE llm=1 AND jev=0 GROUP BY item")
    confirmados = sum(1 for b in barrados if store.one(
        "SELECT 1 FROM prs p JOIN merges m ON m.pr=p.number WHERE p.item_id=? AND m.merged=0 "
        "AND m.reason LIKE 'checks falhando%' AND m.created_at>=? LIMIT 1", (b["item"], b["em"])))
    t = store.one("SELECT COUNT(*) n, COALESCE(SUM(decisao='acordo'), 0) a FROM revisao_dupla")
    return {"barrados": len(barrados), "confirmados_ci": confirmados, "rodadas": t["n"], "acordos": t["a"]}

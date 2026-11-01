"""Condensador rolante do contexto do Developer, portado do LLMSummarizingCondenser do OpenHands (item #366).

Fonte: https://docs.openhands.dev/sdk/arch/condenser. Chamado a cada passo: se o histórico passa de max_size, os
eventos do meio viram um único evento 'condensacao' com os ids esquecidos e um resumo; os keep_first primeiros e os
mais recentes ficam intactos. O resumo padrão é determinístico (último erro, arquivos tocados, decisões do gate) e
herda o de uma condensação anterior, então recondensar não perde nada; `resumir` troca-o por um LLM, se quiserem.
`comparar` mede o efeito: tokens do Developer por PR mergeado e merge_sem_conserto, itens com e sem condensação;
`veredito` só aceita a economia se merge_sem_conserto ficar na meta do Norte (0,7).

Eventos: dicts com 'id', 'tipo' ('erro' | 'arquivo' | 'gate' | outro), 'texto' e, quando há, 'arquivo'.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass

ESQUEMA = """
CREATE TABLE IF NOT EXISTS condensacoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER,
  esquecidos TEXT NOT NULL,
  resumo TEXT NOT NULL,
  antes INTEGER NOT NULL,
  depois INTEGER NOT NULL,
  created_at REAL NOT NULL
)"""


@dataclass
class Condensacao:
    eventos: list[dict]
    esquecidos: list


def _fatos(meio: list[dict]) -> dict:
    fatos: dict = {"erro": None, "arquivos": [], "gate": []}
    for e in meio:
        anterior = e.get("fatos") if e.get("tipo") == "condensacao" else None
        if anterior:
            fatos["erro"] = anterior["erro"] or fatos["erro"]
            fatos["arquivos"] += anterior["arquivos"]
            fatos["gate"] += anterior["gate"]
        elif e.get("tipo") == "erro":
            fatos["erro"] = e.get("texto")
        elif e.get("tipo") == "gate":
            fatos["gate"].append(e.get("texto"))
        if e.get("arquivo"):
            fatos["arquivos"].append(e["arquivo"])
    fatos["arquivos"] = list(dict.fromkeys(fatos["arquivos"]))
    return fatos


def resumo_deterministico(fatos: dict) -> str:
    return "\n".join((f"Último erro: {fatos['erro'] or 'nenhum'}",
                      f"Arquivos tocados: {', '.join(fatos['arquivos']) or 'nenhum'}",
                      f"Decisões do gate: {'; '.join(fatos['gate']) or 'nenhuma'}"))


def condensar(eventos: list[dict], max_size: int, keep_first: int = 2,
              resumir: Callable[[list[dict]], str] | None = None) -> Condensacao:
    """Até max_size eventos: keep_first primeiros + 1 resumo + os mais recentes que couberem."""
    if len(eventos) <= max_size:
        return Condensacao(list(eventos), [])
    cauda = max_size - keep_first - 1
    if cauda < 1:
        raise ValueError("max_size precisa caber keep_first, o resumo e ao menos um evento recente")
    meio = eventos[keep_first:len(eventos) - cauda]
    esquecidos = []
    for e in meio:
        esquecidos += e.get("esquecidos", []) if e.get("tipo") == "condensacao" else [e["id"]]
    fatos = _fatos(meio)
    texto = resumir(meio) if resumir else resumo_deterministico(fatos)
    resumo = {"id": f"condensacao:{esquecidos[-1]}", "tipo": "condensacao", "texto": texto,
              "esquecidos": esquecidos, "fatos": fatos}
    return Condensacao([*eventos[:keep_first], resumo, *eventos[len(eventos) - cauda:]], esquecidos)


def _grupo(linhas: list[tuple]) -> dict:
    """linhas: (status, consertos, tokens do Developer no PR)."""
    mergeados = [t for status, _c, t in linhas if status == "mergeado"]
    return {"prs": len(linhas), "mergeados": len(mergeados),
            "tokens_por_pr": sum(mergeados) // len(mergeados) if mergeados else None,
            "merge_sem_conserto": round(sum(1 for _s, c, _t in linhas if not int(c or 0)) / len(linhas), 2) if linhas else None}


def comparar(conn, desde: float, ate: float) -> dict:
    """PRs abertos na janela, separados por item com e sem condensação: tokens do Developer por PR mergeado
    (llm_calls do papel developer, cuja entrada é o título do item, igual a prs.titulo) e merge_sem_conserto do Norte."""
    tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    linhas = []
    if {"prs", "llm_calls"} <= tabelas:
        linhas = conn.execute(
            "SELECT p.item_id, p.status, p.consertos, (SELECT COALESCE(SUM(l.tokens),0) FROM llm_calls l "
            "WHERE l.papel='developer' AND l.entrada=p.titulo) FROM prs p WHERE p.created_at>=? AND p.created_at<?",
            (desde, ate)).fetchall()
    condensados = ({r[0] for r in conn.execute("SELECT DISTINCT item_id FROM condensacoes")}
                   if "condensacoes" in tabelas else set())
    return {"com": _grupo([r[1:] for r in linhas if r[0] in condensados]),
            "sem": _grupo([r[1:] for r in linhas if r[0] not in condensados])}


def veredito(m: dict) -> dict:
    """Vale se os tokens por PR mergeado caem sem levar merge_sem_conserto abaixo da meta do Norte."""
    from .norte import RESULTADOS
    meta = next(meta for chave, _d, meta, _s in RESULTADOS if chave == "merge_sem_conserto")
    com, sem = m["com"], m["sem"]
    if com["tokens_por_pr"] is None or sem["tokens_por_pr"] is None:
        return {"ok": None, "motivo": "sem PR mergeado com e sem condensação para comparar"}
    if com["merge_sem_conserto"] < meta:
        return {"ok": False, "motivo": f"merge_sem_conserto {com['merge_sem_conserto']} abaixo da meta {meta}"}
    if com["tokens_por_pr"] >= sem["tokens_por_pr"]:
        return {"ok": False, "motivo": f"tokens por PR não caíram ({sem['tokens_por_pr']} → {com['tokens_por_pr']})"}
    return {"ok": True, "motivo": f"tokens por PR {sem['tokens_por_pr']} → {com['tokens_por_pr']}, "
                                  f"merge_sem_conserto {com['merge_sem_conserto']} ≥ {meta}"}


def gravar(conn, item_id: int | None, c: Condensacao, antes: int, em: float | None = None) -> None:
    """Registra a condensação (ids esquecidos, resumo, tamanho antes e depois) para medir o efeito no custo."""
    resumo = next((e["texto"] for e in c.eventos if e.get("tipo") == "condensacao"), "")
    conn.execute(ESQUEMA)
    conn.execute("INSERT INTO condensacoes(item_id,esquecidos,resumo,antes,depois,created_at) VALUES(?,?,?,?,?,?)",
                 (item_id, json.dumps(c.esquecidos), resumo, antes, len(c.eventos), time.time() if em is None else em))

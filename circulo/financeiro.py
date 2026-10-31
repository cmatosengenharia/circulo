"""Prontidão do cérebro financeiro: quantos lançamentos reais e meses cobertos faltam para a 1ª pergunta útil
(gasto por categoria no mês). Sintético é o lançamento que veio de evento com origem 'demo'."""
from __future__ import annotations

from datetime import datetime

from .budget import TZ

MINIMO_LANCAMENTOS = 30
MINIMO_MESES = 1
SINTETICAS = ("demo",)


def prontidao(s) -> dict:
    marcas = ",".join("?" * len(SINTETICAS))
    rows = s.q("SELECT l.created_at FROM ledger l LEFT JOIN events e ON e.id=l.event_id "
               f"WHERE COALESCE(json_extract(e.payload,'$.origem'),'') NOT IN ({marcas})", SINTETICAS)
    meses = len({datetime.fromtimestamp(r[0], TZ).strftime("%Y-%m") for r in rows})
    return {"reais": len(rows), "meses": meses, "minimo_lancamentos": MINIMO_LANCAMENTOS, "minimo_meses": MINIMO_MESES,
            "faltam_lancamentos": max(0, MINIMO_LANCAMENTOS - len(rows)), "faltam_meses": max(0, MINIMO_MESES - meses)}

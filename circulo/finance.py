"""Cálculos financeiros e invariantes. Só inteiros em centavos. Nenhum agente altera este arquivo sozinho."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from .budget import TZ
from .state import Store

DEFAULT_BASE = {
    "reserva_cents": 6_000_000,        # R$ 60.000
    "apartamento_cents": 60_000_000,   # R$ 600.000
    "saldo_devedor_cents": 14_800_000, # R$ 148.000
    "meta_casa_cents": 85_000_000,     # R$ 850.000 (referência)
}


@dataclass(frozen=True)
class Snapshot:
    reserva_cents: int
    patrimonio_liquido_cents: int
    meta_casa_cents: int
    progresso_bp: int                 # basis points (10000 = 100%)
    sobra_mes_cents: int
    receitas_mes_cents: int
    despesas_mes_cents: int
    meses_ate_meta: int | None
    por_categoria_mes: dict[str, int]


def base(store: Store) -> dict:
    b = store.get("patrimonio_base")
    if b is None:
        store.set("patrimonio_base", DEFAULT_BASE)
        b = DEFAULT_BASE
    return b


def _month_start(now: datetime) -> float:
    return now.astimezone(TZ).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


def snapshot(store: Store, now: datetime | None = None) -> Snapshot:
    now = now or datetime.now(TZ)
    b = base(store)
    totals = store.one("""SELECT
        COALESCE(SUM(CASE WHEN kind='receita' THEN amount_cents END),0) r,
        COALESCE(SUM(CASE WHEN kind='despesa' THEN amount_cents END),0) d FROM ledger""")
    ms = _month_start(now)
    mes = store.one("""SELECT
        COALESCE(SUM(CASE WHEN kind='receita' THEN amount_cents END),0) r,
        COALESCE(SUM(CASE WHEN kind='despesa' THEN amount_cents END),0) d FROM ledger WHERE created_at>=?""", (ms,))
    cats = {r["category"]: r["t"] for r in store.q(
        "SELECT category, SUM(amount_cents) t FROM ledger WHERE kind='despesa' AND created_at>=? GROUP BY category ORDER BY t DESC", (ms,))}
    reserva = b["reserva_cents"] + totals["r"] - totals["d"]
    pl = reserva + b["apartamento_cents"] - b["saldo_devedor_cents"]
    meta = b["meta_casa_cents"]
    progresso = (pl * 10_000) // meta if meta > 0 else 0
    sobra = mes["r"] - mes["d"]
    falta = meta - pl
    meses = None
    if falta <= 0:
        meses = 0
    elif sobra > 0 and mes["r"] > 0:
        meses = -(-falta // sobra)  # teto inteiro
    return Snapshot(reserva, pl, meta, int(progresso), sobra, mes["r"], mes["d"], meses, cats)


def check_invariants(store: Store) -> list[str]:
    """Retorna lista de violações (vazia = ok)."""
    v: list[str] = []
    bad = store.one("SELECT COUNT(*) c FROM ledger WHERE typeof(amount_cents)!='integer' OR amount_cents<=0")["c"]
    if bad:
        v.append(f"{bad} lançamentos com valor não-inteiro ou <= 0")
    b = base(store)
    for k, val in b.items():
        if not isinstance(val, int) or val < 0:
            v.append(f"base inválida: {k}")
    s = snapshot(store)
    soma_cats = sum(s.por_categoria_mes.values())
    if soma_cats != s.despesas_mes_cents:
        v.append("soma por categoria != despesas do mês")
    if s.patrimonio_liquido_cents != s.reserva_cents + b["apartamento_cents"] - b["saldo_devedor_cents"]:
        v.append("patrimônio inconsistente")
    if s.meses_ate_meta is not None and s.meses_ate_meta < 0:
        v.append("projeção da casa negativa")
    if s.progresso_bp < 0 and s.patrimonio_liquido_cents >= 0:
        v.append("progresso negativo com patrimônio positivo")
    orphan = store.one("""SELECT COUNT(*) c FROM feedback f LEFT JOIN ledger l ON l.id=f.tx_id WHERE l.id IS NULL""")["c"]
    if orphan:
        v.append(f"{orphan} correções sem lançamento")
    return v


def age_open_transactions(store: Store, days: float = 3.0) -> int:
    """Lançamentos sem correção após N dias contam como confirmados (silêncio = ok)."""
    cutoff = time.time() - days * 86400
    cur = store.db.execute("UPDATE ledger SET status='confirmed' WHERE status='open' AND created_at<?", (cutoff,))
    return cur.rowcount

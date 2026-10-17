"""Orçamento diário de tokens. Hard limit; o loop pausa quando acaba e retoma no dia seguinte."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from .state import Store

TZ = ZoneInfo("America/Sao_Paulo")


class BudgetExhausted(Exception):
    pass


class Budget:
    def __init__(self, store: Store, policy: Callable[[], dict], now: Callable[[], datetime] | None = None):
        self.s = store
        self.policy = policy
        self.now = now or (lambda: datetime.now(TZ))

    def _day(self) -> str:
        return self.now().astimezone(TZ).date().isoformat()

    def _row(self):
        day = self._day()
        self.s.x("INSERT OR IGNORE INTO budget(day) VALUES(?)", (day,))
        return self.s.one("SELECT * FROM budget WHERE day=?", (day,))

    @property
    def limit(self) -> int:
        return int(self.policy()["budget"]["daily_token_limit"])

    @property
    def reserve(self) -> int:
        return int(self.policy()["budget"]["reserve_tokens"])

    def used(self) -> int:
        return int(self._row()["tokens"])

    def remaining(self) -> int:
        return max(0, self.limit - self.used())

    def spendable(self) -> int:
        """O que pode ser gasto sem invadir a reserva (reserva = margem para o Jev seguir decidindo)."""
        return max(0, self.remaining() - self.reserve)

    def left_ratio(self) -> float:
        return self.remaining() / self.limit if self.limit else 0.0

    def exhausted(self) -> bool:
        return self.remaining() <= 0

    def can_spend(self, tokens: int) -> bool:
        return tokens <= self.spendable()

    def charge(self, tokens: int, kind: str = "llm") -> None:
        if tokens < 0:
            raise ValueError("tokens negativos")
        self._row()
        col = "jev_calls" if kind == "jev" else "llm_calls"
        self.s.x(f"UPDATE budget SET tokens=tokens+?, {col}={col}+1 WHERE day=?", (tokens, self._day()))

    def charge_jev(self, tokens: int | None = None) -> None:
        cost = tokens if tokens is not None else int(self.policy()["budget"]["jev_call_cost_tokens"])
        self.charge(cost, "jev")

    def seconds_until_reset(self) -> float:
        now = self.now().astimezone(TZ)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
        return max(1.0, (tomorrow - now).total_seconds())

    def snapshot(self) -> dict:
        r = self._row()
        return {"dia": r["day"], "tokens": r["tokens"], "limite": self.limit,
                "chamadas_jev": r["jev_calls"], "chamadas_llm": r["llm_calls"]}

"""Orçamento diário de tokens.

Dois modos (kv `orcamento_modo`):
- **ilimitado** (padrão desde 1.35.0): nada é cortado nem pausado; tudo continua MEDIDO (tabela `budget` por dia,
  `llm_calls` por chamada e papel) para, com dados, escolher o limite certo depois. `consumo()` resume essa medição.
- **limite**: o limite diário (painel ou política) vale como antes: o porteiro do gasto recusa o que não cabe e o
  loop pausa até a meia-noite quando o dia acaba.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from .state import Store

TZ = ZoneInfo("America/Sao_Paulo")


def tirar_assinatura_do_orcamento(store: Store) -> int:
    """Correção única (1.11.0): até aqui os tokens do Claude Code (assinatura) eram somados ao orçamento da API e
    o porteiro do gasto recusava tudo achando que o dia estava no fim. Devolve ao orçamento o que foi do Developer."""
    if store.get("orcamento_sem_assinatura"):
        return 0
    total = 0
    for r in store.q("SELECT tokens, created_at FROM llm_calls WHERE papel='developer' AND tokens > 0"):
        dia = datetime.fromtimestamp(r["created_at"], TZ).date().isoformat()
        total += store.run("UPDATE budget SET tokens=MAX(0, tokens-?) WHERE day=?", (int(r["tokens"]), dia)) and int(r["tokens"])
    store.set("orcamento_sem_assinatura", {"devolvidos": total})
    return total


LIMITE_MIN = 10_000
MODO_PADRAO = "ilimitado"


def modo_orcamento(store: Store) -> str:
    """'ilimitado' (medindo, sem corte) ou 'limite'. O padrão é medir primeiro."""
    m = (store.get("orcamento_modo") or {}).get("modo")
    return m if m in ("ilimitado", "limite") else MODO_PADRAO


def definir_modo(store: Store, modo: str) -> dict:
    import time
    if modo not in ("ilimitado", "limite"):
        raise ValueError("modo precisa ser 'ilimitado' ou 'limite'")
    antes = modo_orcamento(store)
    hist = ((store.get("orcamento_modo") or {}).get("historico") or [])[-19:]
    store.set("orcamento_modo", {"modo": modo, "em": time.time(), "historico": hist + [[time.time(), antes, modo]]})
    return {"antes": antes, "depois": modo}


def consumo(store: Store, dias: int = 14, agora: float | None = None) -> dict:
    """A medição que vai decidir o limite: tokens por dia, por papel, por hora do dia, e uma sugestão de limite
    (p90 dos dias completos medidos, arredondado para cima em 50 mil). Só dados; a escolha é sua."""
    import math
    import time
    agora = agora or time.time()
    hoje = datetime.fromtimestamp(agora, TZ).date()
    desde = (hoje - timedelta(days=dias - 1)).isoformat()
    por_dia = [{"dia": r["day"], "tokens": int(r["tokens"] or 0), "jev": int(r["jev_calls"] or 0), "llm": int(r["llm_calls"] or 0)}
               for r in store.q("SELECT * FROM budget WHERE day>=? ORDER BY day", (desde,))]
    t0 = datetime.combine(hoje - timedelta(days=dias - 1), datetime.min.time(), TZ).timestamp()
    papeis: dict[str, dict] = {}
    for r in store.q("SELECT papel, COUNT(*) n, SUM(tokens) t, SUM(ok=0) f, MAX(tokens) mx FROM llm_calls WHERE created_at>=? GROUP BY papel ORDER BY t DESC", (t0,)):
        papeis[r["papel"]] = {"chamadas": int(r["n"]), "tokens": int(r["t"] or 0), "falhas": int(r["f"] or 0), "maior_chamada": int(r["mx"] or 0)}
    por_hora = [0] * 24
    for r in store.q("SELECT created_at, tokens FROM llm_calls WHERE created_at>=?", (t0,)):
        por_hora[datetime.fromtimestamp(r["created_at"], TZ).hour] += int(r["tokens"] or 0)
    completos = sorted(d["tokens"] for d in por_dia if d["dia"] != hoje.isoformat() and d["tokens"] > 0)
    sugestao = None
    if len(completos) >= 3:
        p90 = completos[min(len(completos) - 1, math.ceil(0.9 * len(completos)) - 1)]
        sugestao = int(math.ceil(p90 / 50_000) * 50_000)
    hoje_row = next((d for d in por_dia if d["dia"] == hoje.isoformat()), None)
    return {"modo": modo_orcamento(store), "dias": dias, "por_dia": por_dia, "por_papel": papeis, "por_hora": por_hora,
            "hoje": hoje_row["tokens"] if hoje_row else 0, "dias_completos": len(completos),
            "mediana_dia": completos[len(completos) // 2] if completos else None, "maximo_dia": completos[-1] if completos else None,
            "sugestao_limite": sugestao,
            "nota": "sugestão = p90 dos dias completos medidos, arredondado para cima em 50 mil; precisa de 3 dias completos"}


def limite_diario(store: Store, padrao: int) -> int:
    """Limite diário da API: o que você escolheu no painel (kv `orcamento_limite`) ou o da política.
    Nunca passa do teto duro (CIRCULO_HARD_DAILY_TOKENS) nem fica abaixo de LIMITE_MIN."""
    from .policy import HARD_DAILY_TOKEN_CAP
    escolhido = (store.get("orcamento_limite") or {}).get("limite")
    if not escolhido:
        return int(padrao)
    return max(LIMITE_MIN, min(int(escolhido), HARD_DAILY_TOKEN_CAP))


def definir_limite(store: Store, limite: int | None, padrao: int) -> dict:
    """Você muda o limite pelo painel. None volta para o da política. Fica registrado (alerta + histórico)."""
    from .policy import HARD_DAILY_TOKEN_CAP
    import time
    antes = limite_diario(store, padrao)
    if limite is None:
        store.set("orcamento_limite", None)
    else:
        if not isinstance(limite, int) or not (LIMITE_MIN <= limite <= HARD_DAILY_TOKEN_CAP):
            raise ValueError(f"o limite precisa ser um número entre {LIMITE_MIN:,} e {HARD_DAILY_TOKEN_CAP:,} tokens".replace(",", "."))
        hist = ((store.get("orcamento_limite") or {}).get("historico") or [])[-19:]
        store.set("orcamento_limite", {"limite": limite, "em": time.time(), "historico": hist + [[time.time(), antes, limite]]})
    depois = limite_diario(store, padrao)
    return {"antes": antes, "depois": depois, "padrao": int(padrao), "customizado": limite is not None}


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
        return limite_diario(self.s, int(self.policy()["budget"]["daily_token_limit"]))

    @property
    def ilimitado(self) -> bool:
        return modo_orcamento(self.s) == "ilimitado"

    @property
    def reserve(self) -> int:
        return int(self.policy()["budget"]["reserve_tokens"])

    def used(self) -> int:
        return int(self._row()["tokens"])

    def remaining(self) -> int:
        if self.ilimitado:
            return max(self.limit, self.limit * 100)      # medindo: nunca "acaba"
        return max(0, self.limit - self.used())

    def spendable(self) -> int:
        """O que pode ser gasto sem invadir a reserva (reserva = margem para o Jev seguir decidindo)."""
        return max(0, self.remaining() - self.reserve)

    def left_ratio(self) -> float:
        if self.ilimitado:
            return 1.0
        return self.remaining() / self.limit if self.limit else 0.0

    def exhausted(self) -> bool:
        return False if self.ilimitado else self.remaining() <= 0

    def can_spend(self, tokens: int) -> bool:
        return True if self.ilimitado else tokens <= self.spendable()

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
        return {"dia": r["day"], "tokens": r["tokens"], "limite": self.limit, "modo": modo_orcamento(self.s),
                "chamadas_jev": r["jev_calls"], "chamadas_llm": r["llm_calls"]}

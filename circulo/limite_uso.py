"""Limite de uso do Claude Code: até quando não chamar a LLM, lido da própria mensagem de erro.

A mensagem vem em vários formatos: só hora ("5-hour limit reached ∙ resets 3am"), dia da semana ("resets Mon 9am",
limite semanal), data ("resets Oct 24, 10am"), fuso explícito ("resets 3pm (America/Santiago)") e o formato antigo com
epoch ("Claude AI usage limit reached|1760000000"). Limite sem hora usa BACKOFF_S; mensagem que não é limite dá None.
O reset lido é só a próxima tentativa: se a LLM ainda estiver no limite, a nova mensagem grava o novo retorno.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .budget import TZ

KV = "planejador_limite"     # kv: {"retorno_em", "hora", "motivo"} do último limite de uso visto pelo Planejador
BACKOFF_S = 1800             # limite sem hora na mensagem: tenta de novo depois disso
FOLGA_S = 120                # depois do reset informado, para não cair no mesmo minuto
TETO_S = 8 * 86400           # o limite semanal passa de 24 h, mas nada espera mais que isso

E_LIMITE = re.compile(r"usage limit|limit reached|hit your [a-z0-9 -]{0,20}limit|limit will reset|"
                      r'"api_error_status":\s*429|rate[ _-]?limit', re.I)
EPOCH = re.compile(r"limit reached\|(\d{10})")
MESES = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
DIAS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
RESET = re.compile(
    r"resets?\s+(?:at\s+|on\s+)?"
    r"(?:(?P<dow>" + "|".join(DIAS) + r")[a-z]*\.?,?\s+)?"
    r"(?:(?P<mes>" + "|".join(MESES) + r")[a-z]*\.?\s+(?P<dia>\d{1,2})(?:st|nd|rd|th)?,?\s+(?:at\s+)?)?"
    r"(?P<h>\d{1,2})(?::(?P<mi>\d{2}))?\s*(?P<ap>[ap]\.?m\.?)?"
    r"(?:\s*\((?P<tz>[A-Za-z_]+(?:/[A-Za-z_+-]+)*)\))?", re.I)


class LimiteDeUso(RuntimeError):
    """A LLM respondeu que a conta está no limite de uso; retorno_em é quando tentar de novo (epoch)."""

    def __init__(self, retorno_em: float, msg: str):
        super().__init__(msg)
        self.retorno_em = retorno_em


def _fuso(nome: str | None):
    try:
        return ZoneInfo(nome) if nome else TZ
    except (ZoneInfoNotFoundError, ValueError):
        return TZ


def _alvo(m: re.Match, agora: float) -> datetime | None:
    h, mi, ap = int(m["h"]), int(m["mi"] or 0), (m["ap"] or "").lower().replace(".", "")
    if ap and not 1 <= h <= 12:
        return None
    if ap:
        h = h % 12 + (12 if ap == "pm" else 0)
    if h > 23 or mi > 59:
        return None
    now = datetime.fromtimestamp(agora, _fuso(m["tz"]))
    if m["mes"]:
        try:
            alvo = now.replace(month=MESES.index(m["mes"].lower()[:3]) + 1, day=int(m["dia"]), hour=h, minute=mi, second=0, microsecond=0)
        except ValueError:
            return None
        return alvo if alvo > now - timedelta(days=1) else alvo.replace(year=alvo.year + 1)
    alvo = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if m["dow"]:
        alvo += timedelta(days=(DIAS.index(m["dow"].lower()[:3]) - now.weekday()) % 7)
        return alvo if alvo > now else alvo + timedelta(days=7)
    return alvo if alvo > now else alvo + timedelta(days=1)


def parse_reset_limite(msg: str | None, agora: float) -> float | None:
    """Quando tentar de novo (epoch), se `msg` é o limite de uso do Claude Code; None se não é limite."""
    msg = msg or ""
    if not E_LIMITE.search(msg):
        return None
    if e := EPOCH.search(msg):
        ate = float(e[1]) + FOLGA_S
    elif (m := RESET.search(msg)) and (alvo := _alvo(m, agora)) is not None:
        ate = alvo.timestamp() + FOLGA_S
    else:
        return agora + BACKOFF_S
    return min(max(ate, agora), agora + TETO_S)


def gravar(store, retorno_em: float, motivo: str) -> None:
    hora = datetime.fromtimestamp(retorno_em, TZ)
    fmt = "%H:%M" if retorno_em - time.time() < 86400 else "%d/%m %H:%M"
    store.set(KV, {"retorno_em": retorno_em, "hora": hora.strftime(fmt), "motivo": motivo[-300:]})


def em_limite(store, agora: float | None = None) -> dict | None:
    """O limite em vigor, ou None; o que venceu sai do kv para a próxima chamada confirmar a retomada."""
    lim = store.get(KV) or {}
    if not lim:
        return None
    if float(lim.get("retorno_em", 0)) <= (agora or time.time()):
        store.set(KV, None)
        return None
    return lim

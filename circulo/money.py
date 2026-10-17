"""Dinheiro sempre em centavos (int). Nunca float."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN

# 1.234,56 | 1234,56 | 1234.56 | 38,9 | 38
AMOUNT_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?![\w])")
_THOUSANDS_ONLY = re.compile(r"^\d{1,3}(?:\.\d{3})+$")


def parse_brl(token: str) -> int:
    """Converte texto em reais para centavos. Levanta ValueError se inválido/negativo."""
    s = token.strip().replace("R$", "").replace(" ", "")
    if not s:
        raise ValueError("valor vazio")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif _THOUSANDS_ONLY.match(s):
        s = s.replace(".", "")
    try:
        d = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"valor inválido: {token!r}") from exc
    if d < 0:
        raise ValueError("valor negativo")
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def find_amount(text: str) -> tuple[int, str] | None:
    """Acha o primeiro valor no texto. Retorna (centavos, texto_sem_valor)."""
    m = AMOUNT_RE.search(text)
    if not m:
        return None
    cents = parse_brl(m.group(1))
    rest = (text[: m.start()] + " " + text[m.end():]).strip()
    return cents, " ".join(rest.split())


def fmt_brl(cents: int) -> str:
    if not isinstance(cents, int):
        raise TypeError("centavos devem ser int")
    sign = "-" if cents < 0 else ""
    reais, cent = divmod(abs(cents), 100)
    return f"{sign}R$ {reais:,}".replace(",", ".") + f",{cent:02d}"

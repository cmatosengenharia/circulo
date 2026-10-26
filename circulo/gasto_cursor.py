"""Gasto do Cursor em US$ por dia, assunto e tipo de tarefa, com a projeção do dia em que o limite do mês acaba.

O Cursor já mostra o total na aba Spending; aqui fica o que ele não mostra: de onde veio o gasto (assunto e tipo de
tarefa) e quando, no ritmo da média dos últimos 7 dias, os US$ 250 do mês (CIRCULO_CURSOR_US_MES) acabam. Entra por
lançamento rápido (`python -m circulo.gasto_cursor 3,20 --assunto X --tipo Y`) ou pela exportação CSV do dashboard do
Cursor (`--csv uso.csv`, que não duplica ao reimportar). Dinheiro em centavos de dólar (int), como em money.py.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import os
import time
from datetime import date, datetime, timedelta
from typing import Callable

from .budget import TZ
from .money import parse_brl
from .state import Store

LIMITE_US_MES = 250
JANELA = 7
KV_AVISO = "gasto_cursor_aviso"     # kv: dia do último aviso de esgotamento antes do fim do mês


def limite_mes() -> int:
    try:
        return _centavos(os.environ.get("CIRCULO_CURSOR_US_MES", str(LIMITE_US_MES)))
    except ValueError:
        return LIMITE_US_MES * 100


def _centavos(valor: str) -> int:
    s = valor.strip().replace("US$", "").replace("$", "").replace(" ", "")
    if "," in s and "." in s:      # 1,234.56 do CSV em inglês
        s = s.replace(",", "")
    return parse_brl(s)


def fmt_usd(centavos: int) -> str:
    return f"US$ {centavos // 100:,}.{centavos % 100:02d}"


def lancar(store: Store, valor: str, assunto: str | None = None, tipo: str | None = None, modelo: str | None = None,
           tokens: int = 0, dia: date | None = None, origem: str = "manual", chave: str | None = None) -> int:
    """Grava um gasto; com `chave` (linha do CSV), a mesma linha não entra duas vezes. Devolve 1 se gravou."""
    dia = dia or datetime.now(TZ).date()
    return store.run("INSERT OR IGNORE INTO gasto_cursor(dia, assunto, tipo, modelo, tokens, centavos, origem, chave, "
                     "created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     (dia.isoformat(), assunto or None, tipo or None, modelo or None, int(tokens or 0),
                      _centavos(valor), origem, chave, time.time()))


def _dia_csv(valor: str) -> date:
    v = valor.strip()
    if "T" in v:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(TZ).date()
    return date.fromisoformat(v[:10])


def importar_csv(store: Store, texto: str, assunto: str | None = None, tipo: str | None = None) -> int:
    """Linhas da exportação de uso do Cursor (Date, Model, Total Tokens, Cost). Linha sem custo em dólar
    ("Included", erro não cobrado, US$ 0) fica de fora. Devolve quantas linhas novas entraram."""
    novas = 0
    for linha in csv.DictReader(io.StringIO(texto)):
        col = {(k or "").strip().lower(): (v or "") for k, v in linha.items()}
        try:
            centavos = _centavos(col.get("cost", ""))
            dia = _dia_csv(next(v for k, v in col.items() if k.startswith("date")))
        except (ValueError, StopIteration):
            continue
        if centavos <= 0:
            continue
        tokens = col.get("total tokens") or "0"
        chave = hashlib.sha256("|".join(f"{k}={v}" for k, v in sorted(col.items())).encode()).hexdigest()
        novas += lancar(store, col["cost"], assunto, tipo, col.get("model"), int(tokens) if tokens.isdigit() else 0,
                        dia, "csv", chave)
    return novas


def etiquetados_pct(store: Store, desde: date | None = None) -> float | None:
    r = store.one("SELECT COUNT(*) n, SUM(COALESCE(assunto,'')<>'' AND COALESCE(tipo,'')<>'') e FROM gasto_cursor "
                  "WHERE dia>=?", ((desde or date.min).isoformat(),))
    return round(100 * (r["e"] or 0) / r["n"], 1) if r["n"] else None


def _soma(store: Store, de: date, ate: date) -> int:
    return int(store.one("SELECT COALESCE(SUM(centavos),0) c FROM gasto_cursor WHERE dia BETWEEN ? AND ?",
                         (de.isoformat(), ate.isoformat()))["c"])


def projecao(store: Store, hoje: date | None = None, limite: int | None = None) -> dict:
    """Dia em que o gasto do mês alcança o limite, no ritmo da média dos últimos 7 dias (ou dos dias com registro,
    se o histórico for mais curto). Sem gasto na janela não há projeção (esgota_em None)."""
    hoje = hoje or datetime.now(TZ).date()
    limite = limite_mes() if limite is None else limite
    inicio = hoje.replace(day=1)
    fim = (inicio + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    gasto = _soma(store, inicio, hoje)
    primeiro = store.one("SELECT MIN(dia) d FROM gasto_cursor")["d"]
    dias = min(JANELA, (hoje - date.fromisoformat(primeiro)).days + 1) if primeiro else 0
    media = _soma(store, hoje - timedelta(days=JANELA - 1), hoje) // dias if dias > 0 else 0
    restante = limite - gasto
    esgota = None if media <= 0 else hoje if restante <= 0 else hoje + timedelta(days=math.ceil(restante / media))
    return {"hoje": hoje.isoformat(), "limite": limite, "gasto_mes": gasto, "media_7d": media, "restante": restante,
            "esgota_em": esgota.isoformat() if esgota else None, "fim_mes": fim.isoformat(),
            "antes_do_fim": esgota is not None and esgota < fim, "etiquetados_pct": etiquetados_pct(store, inicio)}


def avisar(store: Store, reply: Callable[[str, str], None], hoje: date | None = None) -> bool:
    """Avisa uma vez por dia quando a projeção cai antes do fim do mês."""
    p = projecao(store, hoje)
    if not p["antes_do_fim"] or store.get(KV_AVISO) == p["hoje"]:
        return False
    store.set(KV_AVISO, p["hoje"])
    esgota = date.fromisoformat(p["esgota_em"])
    reply(f"No ritmo dos últimos 7 dias ({fmt_usd(p['media_7d'])}/dia), os {fmt_usd(p['limite'])} do Cursor acabam em "
          f"{esgota:%d/%m}, antes do fim do mês ({date.fromisoformat(p['fim_mes']):%d/%m}). "
          f"Gasto no mês: {fmt_usd(p['gasto_mes'])}.", "orcamento")
    return True


def resumo(p: dict) -> str:
    linha = f"Mês: {fmt_usd(p['gasto_mes'])} de {fmt_usd(p['limite'])}; média 7 d: {fmt_usd(p['media_7d'])}/dia"
    if p["esgota_em"] is None:
        return linha + "; sem gasto nos últimos 7 dias, sem projeção de quando esgota."
    etiq = "" if p["etiquetados_pct"] is None else f"; {p['etiquetados_pct']}% etiquetados por assunto e tipo"
    alerta = " (ANTES do fim do mês)" if p["antes_do_fim"] else ""
    return linha + f"; esgota em {date.fromisoformat(p['esgota_em']):%d/%m}{alerta}{etiq}."


def main(argv: list[str] | None = None) -> None:
    """python -m circulo.gasto_cursor [valor] [--assunto --tipo --modelo --tokens --dia] [--csv arquivo]"""
    ap = argparse.ArgumentParser(prog="python -m circulo.gasto_cursor",
                                 description="gasto do Cursor em US$ por assunto e tipo, com a projeção de quando o mês esgota")
    ap.add_argument("--data", default=os.environ.get("CIRCULO_DATA", "data"))
    ap.add_argument("valor", nargs="?", help="US$ gastos (ex.: 3,20); sem valor, só mostra a projeção")
    ap.add_argument("--assunto")
    ap.add_argument("--tipo", help="tipo de tarefa (bugfix, feature, refactor, ...)")
    ap.add_argument("--modelo")
    ap.add_argument("--tokens", type=int, default=0)
    ap.add_argument("--dia", help="AAAA-MM-DD (padrão: hoje)")
    ap.add_argument("--csv", help="exportação de uso do dashboard do Cursor")
    args = ap.parse_args(argv)
    store = Store(os.path.join(args.data, "circulo.db"))
    if args.valor:
        lancar(store, args.valor, args.assunto, args.tipo, args.modelo, args.tokens,
               date.fromisoformat(args.dia) if args.dia else None)
        etiqueta = "/".join(x for x in (args.assunto, args.tipo) if x) or "sem etiqueta"
        print(f"lançado {fmt_usd(_centavos(args.valor))} ({etiqueta})")
    if args.csv:
        with open(args.csv, encoding="utf-8-sig") as f:
            print(f"{importar_csv(store, f.read(), args.assunto, args.tipo)} linhas importadas de {args.csv}")
    avisar(store, lambda m, k: store.x("INSERT INTO alerts(kind, message, created_at) VALUES(?,?,?)",
                                       (k, m, time.time())))
    print(resumo(projecao(store)))


if __name__ == "__main__":
    main()

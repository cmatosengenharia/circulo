"""Importa extrato bancário (OFX/CSV) para o ledger, sem rede e sem LLM.

`parse_extrato` é pura e determinística. A dedupe fica com o banco: `ledger.import_key` é única, então reimportar
o mesmo extrato insere 0. A chave é o FITID do OFX; sem ele, o sha256 de data+valor+descrição+ocorrência no
arquivo, para duas compras idênticas no mesmo dia não colapsarem numa só."""
from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter
from datetime import date, datetime
from typing import NamedTuple

from . import finance
from .budget import TZ
from .decision import norm
from .money import parse_brl
from .policy import PolicyStore
from .state import Store


class Linha(NamedTuple):
    data: str        # ISO, AAAA-MM-DD
    centavos: int    # negativo = saída, positivo = entrada
    descricao: str   # minúscula, sem acento, espaços colapsados
    chave: str       # FITID ou sha256(data|centavos|descricao|ocorrência)


_TRN = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.S | re.I)
_CAMPO = re.compile(r"<(\w+)>([^<\r\n]*)")


def _descricao(texto: str) -> str:
    return " ".join(norm(texto).split())


def _centavos(valor: str) -> int:
    v = valor.replace("R$", "").strip()
    sinal = -1 if v.startswith("-") else 1
    return sinal * parse_brl(v.lstrip("+-"))


def _data(valor: str) -> str:
    v = valor.strip()
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", v):
        return datetime.strptime(v, "%d/%m/%Y").date().isoformat()
    if re.match(r"\d{8}", v):
        return datetime.strptime(v[:8], "%Y%m%d").date().isoformat()
    return date.fromisoformat(v).isoformat()


def _ofx(texto: str) -> list[tuple[str, int, str, str | None]]:
    out = []
    for bloco in _TRN.findall(texto):
        c = {k.upper(): v.strip() for k, v in _CAMPO.findall(bloco)}
        out.append((_data(c["DTPOSTED"]), _centavos(c["TRNAMT"]), _descricao(c.get("MEMO") or c.get("NAME", "")),
                    c.get("FITID") or None))
    return out


def _coluna(cabecalho: list[str], nomes: tuple[str, ...]) -> int:
    for i, nome in enumerate(cabecalho):
        if _descricao(nome).startswith(nomes):
            return i
    raise ValueError(f"CSV sem coluna {nomes[0]!r}: {cabecalho}")


def _csv(texto: str) -> list[tuple[str, int, str, str | None]]:
    linhas = [lin for lin in texto.lstrip("﻿").splitlines() if lin.strip()]
    if not linhas:
        return []
    sep = ";" if linhas[0].count(";") >= linhas[0].count(",") else ","
    rows = list(csv.reader(io.StringIO("\n".join(linhas)), delimiter=sep))
    cab = rows[0]
    i_data = _coluna(cab, ("data", "date"))
    i_desc = _coluna(cab, ("descricao", "historico", "description", "memo"))
    i_valor = _coluna(cab, ("valor", "amount"))
    return [(_data(r[i_data]), _centavos(r[i_valor]), _descricao(r[i_desc]), None) for r in rows[1:]]


def chave_hash(data: str, centavos: int, descricao: str, ocorrencia: int) -> str:
    """Chave sem FITID. Fontes diferentes (extrato, e-mail) só casam o mesmo lançamento se `descricao` vier
    normalizada por `_descricao` e a ocorrência for contada na mesma ordem."""
    return hashlib.sha256(f"{data}|{centavos}|{descricao}|{ocorrencia}".encode()).hexdigest()


def linhas(brutas: list[tuple[str, int, str, str | None]]) -> list[Linha]:
    """(data, centavos, descrição normalizada, FITID ou None) → Linha, com a ocorrência de cada data+valor+descrição."""
    vistas: Counter[tuple[str, int, str]] = Counter()
    out = []
    for data, centavos, desc, fitid in brutas:
        ocorrencia = vistas[(data, centavos, desc)]
        vistas[(data, centavos, desc)] += 1
        out.append(Linha(data, centavos, desc, fitid or chave_hash(data, centavos, desc, ocorrencia)))
    return out


def parse_extrato(texto: str, formato: str) -> list[Linha]:
    """Linhas do extrato na ordem do arquivo. `formato` é 'ofx' ou 'csv'."""
    return linhas({"ofx": _ofx, "csv": _csv}[formato.lower()](texto))


def importar(store: Store, texto: str, formato: str) -> int:
    return gravar(store, parse_extrato(texto, formato))


def gravar(store: Store, novas: list[Linha]) -> int:
    """Grava as linhas novas no ledger e devolve quantas entraram. Despesa entra em aberto e com confiança 0:
    o loop a reclassifica (`reclassificar_pendentes`); receita entra como renda, igual ao lançamento por mensagem."""
    version, _ = PolicyStore(store).active()
    n = 0
    with store.tx():
        for lin in novas:
            if lin.centavos == 0:
                continue
            receita = lin.centavos > 0
            em = datetime.fromisoformat(lin.data).replace(hour=12, tzinfo=TZ).timestamp()
            n += store.run(
                "INSERT OR IGNORE INTO ledger(kind,amount_cents,description,category,tag,confidence,auto_accepted,"
                "policy_version,created_at,import_key) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("receita" if receita else "despesa", abs(lin.centavos), lin.descricao,
                 "renda" if receita else "outros", "necessario" if receita else "escolha",
                 1.0 if receita else 0.0, int(receita), version, em, lin.chave))
        violations = finance.check_invariants(store)
        if violations:
            raise ValueError("invariante violado; importação desfeita: " + "; ".join(violations))
    return n

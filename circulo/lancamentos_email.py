"""E-mail de notificação do banco → lançamentos, sem rede e sem LLM (o texto chega pronto, nunca do Gmail aqui).

A chave é a mesma do extrato sem FITID (`lancamentos_import.chave_hash`): data+valor+descrição+ocorrência. Por
isso o mesmo lançamento visto no extrato e no e-mail vira 1 no ledger, desde que a descrição seja normalizada
(caixa, acentos, espaços) antes do hash; sem isso "Padaria  Pão Bom" e "PADARIA PÃO BOM" seriam dois. A ocorrência
é contada na ordem dos e-mails do lote, como a do extrato na ordem do arquivo: duas compras idênticas no mesmo dia
são 2. Extrato OFX com FITID não cruza com o e-mail; ali a dedupe é a do FITID."""
from __future__ import annotations

import re
from collections.abc import Iterable

from .lancamentos_import import Linha, _centavos, _data, _descricao, gravar, linhas
from .state import Store

_VALOR = re.compile(r"^\s*valor\s*:\s*(R\$\s*[\d.,]+)", re.I | re.M)
_DATA = re.compile(r"^\s*data\s*:\s*(\d{2}/\d{2}/\d{4})", re.I | re.M)
_LOCAL = re.compile(r"^\s*(?:estabelecimento|local|descri[cç][aã]o)\s*:\s*(.+?)\s*$", re.I | re.M)
_ENTRADA = re.compile(r"\brecebid[oa]\b", re.I)


def _campo(regex: re.Pattern[str], texto: str, nome: str) -> str:
    m = regex.search(texto)
    if not m:
        raise ValueError(f"e-mail de notificação sem {nome}")
    return m.group(1)


def parse_email(texto: str) -> tuple[str, int, str]:
    """(data ISO, centavos, descrição normalizada) de uma notificação; compra é saída, "recebido" é entrada."""
    centavos = abs(_centavos(_campo(_VALOR, texto, "valor")))
    return (_data(_campo(_DATA, texto, "data")), centavos if _ENTRADA.search(texto) else -centavos,
            _descricao(_campo(_LOCAL, texto, "estabelecimento")))


def parse_emails(textos: Iterable[str]) -> list[Linha]:
    return linhas([(*parse_email(t), None) for t in textos])


def importar_emails(store: Store, textos: Iterable[str]) -> int:
    return gravar(store, parse_emails(textos))

"""Pasta monitorada de extratos: cada .ofx/.csv novo vai para o ledger e sai da pasta.

Um arquivo por transação (`lancamentos_import.importar`); só depois do commit ele vai para `processados/`, e se o
parse ou a gravação falhar vai para `rejeitados/` sem interromper os demais. Se o processo cair entre o commit e a
mudança de pasta, a passada seguinte reimporta o arquivo e a dedupe do ledger insere 0. As duas subpastas ficam
dentro da monitorada para `os.replace` ser atômico (mesmo sistema de arquivos)."""
from __future__ import annotations

import os
from pathlib import Path

from .lancamentos_import import importar
from .state import Store

FORMATOS = {".ofx": "ofx", ".csv": "csv"}


def _texto(arquivo: Path) -> str:
    bruto = arquivo.read_bytes()
    try:
        return bruto.decode("utf-8")
    except UnicodeDecodeError:
        return bruto.decode("cp1252")     # extrato de banco brasileiro costuma vir em Windows-1252


def _mover(arquivo: Path, destino: str) -> None:
    pasta = arquivo.parent / destino
    pasta.mkdir(exist_ok=True)
    os.replace(arquivo, pasta / arquivo.name)


def ingerir_pasta(pasta: str | Path, store: Store) -> int:
    """Importa os extratos da pasta (em ordem de nome) e devolve quantos lançamentos novos entraram."""
    pasta = Path(pasta)
    if not pasta.is_dir():
        return 0
    n = 0
    for arquivo in sorted(pasta.iterdir()):
        formato = FORMATOS.get(arquivo.suffix.lower())
        if formato is None or not arquivo.is_file():
            continue
        try:
            n += importar(store, _texto(arquivo), formato)
        except (ValueError, KeyError, IndexError):     # extrato ilegível; UnicodeDecodeError é ValueError
            _mover(arquivo, "rejeitados")
            continue
        _mover(arquivo, "processados")
    return n

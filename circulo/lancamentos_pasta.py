"""Pasta monitorada de extratos: cada .ofx/.csv novo vai para o ledger e sai da pasta.

Um arquivo por transação (`lancamentos_import.importar`); só depois do commit ele vai para `processados/`, e se o
parse ou a gravação falhar vai para `rejeitados/` sem interromper os demais. Se o processo cair entre o commit e a
mudança de pasta, a passada seguinte reimporta o arquivo e a dedupe do ledger insere 0. As duas subpastas ficam
dentro da monitorada para `os.replace` ser atômico (mesmo sistema de arquivos)."""
from __future__ import annotations

import os
from pathlib import Path

from . import intencoes
from .lancamentos_import import importar
from .state import Store

FORMATOS = {".ofx": "ofx", ".csv": "csv"}
LISTA = 8              # arquivos por lista no evento: as entradas da trilha cabem em 2000 caracteres e seguem JSON válido


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
    """Importa os extratos da pasta (em ordem de nome) e devolve quantos lançamentos novos entraram.

    Cada varredura com extrato vira evento do loop (trilha de intenções, ação `lancamentos:varredura`) e fica em
    kv `lancamentos_pasta`: novos, total do ledger, importados por arquivo e ignorados com motivo."""
    pasta = Path(pasta)
    arquivos = sorted(a for a in pasta.iterdir() if a.is_file()) if pasta.is_dir() else []
    extratos = [a for a in arquivos if a.suffix.lower() in FORMATOS]
    if not extratos:
        return 0
    seq = intencoes.registrar(store, "lancamentos:varredura", "extrato na pasta monitorada",
                              {"pasta": str(pasta), "arquivos": [a.name for a in extratos]})
    n, importados = 0, []
    ignorados = [{"arquivo": a.name, "motivo": "formato não é .ofx/.csv"} for a in arquivos if a not in extratos]
    for arquivo in extratos:
        try:
            novos = importar(store, _texto(arquivo), FORMATOS[arquivo.suffix.lower()])
        except (ValueError, KeyError, IndexError) as exc:     # extrato ilegível; UnicodeDecodeError é ValueError
            _mover(arquivo, "rejeitados")
            ignorados.append({"arquivo": arquivo.name, "motivo": f"rejeitado: {type(exc).__name__}: {exc}"[:200]})
            continue
        _mover(arquivo, "processados")
        importados.append({"arquivo": arquivo.name, "novos": novos})
        n += novos
    total = store.one("SELECT COUNT(*) AS n FROM ledger")["n"]
    resumo = {"novos": n, "total": total, "importados": importados[:LISTA], "ignorados": ignorados[:LISTA]}
    store.set("lancamentos_pasta", resumo)
    intencoes.concluir(store, seq, True, f"{n} novos, {total} no ledger", **resumo)
    return n

"""Roadmap: todo item nasce de uma pergunta do conselho; `Origem` só existe com um pergunta_id válido."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Origem:
    pergunta_id: int

    def __post_init__(self) -> None:
        if type(self.pergunta_id) is not int or self.pergunta_id <= 0:
            raise ValueError(f"item do roadmap sem pergunta de origem: pergunta_id={self.pergunta_id!r}")


def migrar(db: sqlite3.Connection) -> None:
    """Idempotente: roadmap ganha pergunta_id (herdado de perguntas.item_id) e origem_status; item ainda sem status
    vira 'ok' se a pergunta existe, senão 'legado'."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(roadmap)")}
    for col, typ in (("pergunta_id", "INTEGER"), ("origem_status", "TEXT")):
        if col not in cols:
            db.execute(f"ALTER TABLE roadmap ADD COLUMN {col} {typ}")
    db.execute("UPDATE roadmap SET pergunta_id=(SELECT MIN(p.id) FROM perguntas p WHERE p.item_id=roadmap.id) "
               "WHERE pergunta_id IS NULL AND origem_status IS NULL")
    db.execute("UPDATE roadmap SET origem_status=CASE WHEN EXISTS (SELECT 1 FROM perguntas p "
               "WHERE p.id=roadmap.pergunta_id) THEN 'ok' ELSE 'legado' END WHERE origem_status IS NULL")

"""Guardrails da autoevolução (Prompt Mestre §11) que não cabem em outro lugar.

- Snapshots: backup diário do banco + antes de toda mudança de política; restauração testável.
- Orçamento de mudanças: no máximo N mudanças de nível 2 por dia.
- Oscilação: proposta revertida 2 vezes fica bloqueada (só humano reabre).
- Estagnação: o círculo parar de evoluir com sinais pendentes é tratado como degradação (alerta).
"""
from __future__ import annotations

import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from .budget import TZ
from .state import Store

KEEP_DAILY = 14
KEEP_PRE_CHANGE = 20
MAX_LEVEL2_PER_DAY = 3
MAX_ROLLBACKS = 2
STAGNATION_TICKS = 2000


# ------------------------------------------------------------------ snapshots
def snapshot(store: Store, data_dir: Path, motivo: str = "diario") -> Path | None:
    if store.path == ":memory:":
        return None
    d = Path(data_dir) / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(TZ).strftime("%Y-%m-%d_%H%M%S_%f")
    dest = d / f"{stamp}_{motivo}.db"
    target = sqlite3.connect(dest)
    try:
        store.db.backup(target)          # cópia consistente mesmo com o loop rodando
    finally:
        target.close()
    _prune(d, "_diario.db", KEEP_DAILY)
    _prune(d, "_mudanca.db", KEEP_PRE_CHANGE)
    store.set("ultimo_snapshot", {"em": time.time(), "arquivo": str(dest), "motivo": motivo})
    return dest


def _prune(d: Path, suffix: str, keep: int) -> None:
    files = sorted(p for p in d.glob(f"*{suffix}"))
    for old in files[:-keep]:
        # snapshots antigos vão para uma pasta de arquivo morto, não são apagados pelo círculo
        arch = d / "arquivo"
        arch.mkdir(exist_ok=True)
        shutil.move(str(old), arch / old.name)


def daily_snapshot(store: Store, data_dir: Path) -> Path | None:
    today = datetime.now(TZ).date().isoformat()
    if store.get("snapshot_dia") == today:
        return None
    p = snapshot(store, data_dir, "diario")
    store.set("snapshot_dia", today)
    return p


def restore(db_path: Path, snapshot_file: Path) -> Path:
    """Restaura um snapshot. Antes, guarda o banco atual como snapshot 'antes_de_restaurar'."""
    db_path, snapshot_file = Path(db_path), Path(snapshot_file)
    if not snapshot_file.exists():
        raise FileNotFoundError(snapshot_file)
    safety = db_path.with_name(f"{db_path.stem}.antes_de_restaurar_{int(time.time())}.db")
    if db_path.exists():
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(safety)
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
    src = sqlite3.connect(snapshot_file)
    dst = sqlite3.connect(db_path)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    return safety


# ------------------------------------------------------------------ orçamento de mudanças
def level2_changes_today(store: Store) -> int:
    day0 = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return store.one("SELECT COUNT(*) n FROM policy_versions WHERE created_at>=? AND status IN ('shadow','active','retired','rolled_back') "
                     "AND reason NOT IN ('semente') AND proposal_id IN (SELECT id FROM proposals WHERE level>=2)", (day0,))["n"]


def can_change_level2(store: Store) -> bool:
    return level2_changes_today(store) < MAX_LEVEL2_PER_DAY


# ------------------------------------------------------------------ estagnação
def check_stagnation(store: Store, reply) -> bool:
    tick = store.tick
    if tick < STAGNATION_TICKS:
        return False
    since = tick - STAGNATION_TICKS
    evoluiu = store.one("""SELECT
        (SELECT COUNT(*) FROM policy_versions WHERE activated_tick >= ? AND reason!='semente') +
        (SELECT COUNT(*) FROM cycles WHERE tick >= ? AND aceita=1) n""", (since, since))["n"]
    sinais = store.one("""SELECT
        (SELECT COUNT(*) FROM feedback WHERE created_at > strftime('%s','now') - 7*86400) +
        (SELECT COUNT(*) FROM incidents WHERE status!='resolvido') +
        (SELECT COUNT(*) FROM proposals WHERE status='deferred') n""")["n"]
    if evoluiu or not sinais:
        return False
    today = datetime.now(TZ).date().isoformat()
    if store.get("estagnacao_alertada") == today:
        return True
    store.set("estagnacao_alertada", today)
    reply(f"O círculo não evolui há {STAGNATION_TICKS} giros, mas há {sinais} sinais pendentes (correções, erros ou propostas "
          "adiadas). Possíveis causas: limiares rígidos demais, orçamento curto ou evals quebrados. Afrouxar exige você.", "saude")
    return True

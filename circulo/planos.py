"""Plano do Developer por item (passos, arquivos, premissas) e a fração de PRs com plano antes do primeiro commit (item #276).

Referências (Devin, Claude Code plan mode) tratam o plano como a primeira entrega, mas a aprovação humana é seletiva
ou tem prazo: num loop 24/7, exigi-la em todo pedido trava o fluxo. Por isso são duas medidas separadas:
'plano registrado antes do commit' (meta 100%) e 'aprovado ou corrigido por humano' (só visível nesta fase).

Estados gravados: aprovado_humano | corrigido_humano | auto_prosseguiu (venceu o prazo sem resposta). 'ausente' não se
grava: é o PR sem plano, ou com plano gravado depois do commit. O commit é carimbado por prs.created_at: o Developer
faz um commit só e grava a linha do PR logo depois do push.
"""
from __future__ import annotations

import json
import time

ESTADOS = ("aprovado_humano", "corrigido_humano", "auto_prosseguiu")
HUMANOS = {"aprovado_humano", "corrigido_humano"}
JANELA = 7 * 86400

ESQUEMA = f"""
CREATE TABLE IF NOT EXISTS planos (
  item_id INTEGER PRIMARY KEY,
  passos TEXT NOT NULL,
  arquivos TEXT NOT NULL,
  premissas TEXT NOT NULL,
  estado TEXT NOT NULL CHECK (estado IN {ESTADOS}),
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
)"""


def gravar(conn, item_id: int, passos: list[str], arquivos: list[str], premissas: list[str], estado: str,
           em: float | None = None) -> None:
    """Grava (ou corrige) o plano do item; o carimbo do primeiro registro é o que se compara com o commit."""
    em = time.time() if em is None else em
    conn.execute(ESQUEMA)
    conn.execute("INSERT INTO planos(item_id,passos,arquivos,premissas,estado,created_at,updated_at) VALUES(?,?,?,?,?,?,?) "
                 "ON CONFLICT(item_id) DO UPDATE SET passos=excluded.passos, arquivos=excluded.arquivos, "
                 "premissas=excluded.premissas, estado=excluded.estado, updated_at=excluded.updated_at",
                 (item_id, *(json.dumps(v, ensure_ascii=False) for v in (passos, arquivos, premissas)), estado, em, em))


def _pct(n: int, total: int) -> float | None:
    return round(100 * n / total, 1) if total else None


def fracoes(prs: list[dict], planos: dict[int, dict]) -> dict:
    """Pura. prs: [{item_id, pr, commit_em}]; planos: item_id -> {estado, em}. Plano só conta se em <= commit_em."""
    estados = dict.fromkeys((*ESTADOS, "ausente"), 0)
    sem_plano = []
    for p in prs:
        plano = planos.get(p["item_id"])
        if plano and plano["em"] <= p["commit_em"]:
            estados[plano["estado"]] += 1
            continue
        estados["ausente"] += 1
        sem_plano.append({"item_id": p["item_id"], "pr": p["pr"], "motivo": "plano depois do commit" if plano else "sem plano"})
    total = len(prs)
    return {"total": total, "registrado_pct": _pct(total - estados["ausente"], total),
            "humano_pct": _pct(sum(estados[e] for e in HUMANOS), total), "estados": estados, "sem_plano": sem_plano}


def ler(conn, agora: float | None = None) -> dict:
    """Frações dos PRs do Developer abertos nos últimos 7 dias, lidas do SQLite."""
    agora = time.time() if agora is None else agora
    conn.execute(ESQUEMA)
    prs = [{"item_id": i, "pr": n, "commit_em": c} for n, i, c in conn.execute(
        "SELECT number, item_id, created_at FROM prs WHERE item_id IS NOT NULL AND created_at >= ? ORDER BY number",
        (agora - JANELA,))]
    planos = {i: {"estado": e, "em": c} for i, e, c in conn.execute("SELECT item_id, estado, created_at FROM planos")}
    return fracoes(prs, planos)

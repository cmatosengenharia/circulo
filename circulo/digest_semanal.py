"""Digest semanal do que o time ganhou: os PRs de produto mergeados em 7 dias, cada um com o pedido ou a pergunta de
origem e o antes/depois da métrica que a motivou. PR de produto sem origem sai marcado 'sem pedido', nunca omitido:
o buraco no rastro é o que o time precisa ver. Cada leitura (`circulo digest`) fica em `digest_leituras`."""
from __future__ import annotations

import json
import time

from . import norte
from .state import Store

ESQUEMA = """
CREATE TABLE IF NOT EXISTS digest_leituras (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  prs INTEGER NOT NULL,
  produto INTEGER NOT NULL,
  sem_pedido INTEGER NOT NULL,
  created_at REAL NOT NULL
)
"""
SEM_PEDIDO = "sem pedido"
META = next(meta for chave, _, meta, _ in norte.RESULTADOS if chave == "fracao_produto")


def texto(prs: list[dict]) -> str:
    """O digest a partir dos PRs mergeados na semana (number, titulo, produto, pedido, metrica, antes, depois). Pura."""
    produto = [p for p in prs if p["produto"]]
    fracao = f"{len(produto) / len(prs):.2f}" if prs else "—"
    linhas = [f"Digest semanal: {len(produto)} de {len(prs)} PRs mergeados em 7 dias foram produto "
              f"(fração {fracao}, meta {META})."]
    for p in sorted(produto, key=lambda p: p["number"]):
        partes = [f"#{p['number']} {p['titulo']}", p["pedido"] or SEM_PEDIDO]
        if p["metrica"]:
            partes.append(f"{p['metrica']}: {_valor(p['antes'])} → {_valor(p['depois'])}")
        linhas.append("- " + " · ".join(partes))
    if not produto:
        linhas.append("Nenhum PR de produto na semana.")
    return "\n".join(linhas)


def _valor(v) -> str:
    return "—" if v is None else str(v)


def _origem(store: Store, item: dict) -> tuple[str | None, dict]:
    """(pedido ou pergunta de origem, evidência da pergunta) do item do roteiro."""
    perg = store.one("SELECT id, persona, texto, evidencia FROM perguntas WHERE id=? OR item_id=? ORDER BY id LIMIT 1",
                     (item.get("pergunta_id") or -1, item["id"])) if item else None
    ev = json.loads(perg["evidencia"]) if perg and perg["evidencia"] else {}
    if item and item.get("origem") == "pedido_cassio":
        return f"pedido: {(item['detalhe'] or item['titulo'])[:160]}", ev
    if perg:
        return f"pergunta #{perg['id']} ({perg['persona']}): {perg['texto'][:160]}", ev
    return None, ev


def prs_da_semana(store: Store, agora: float | None = None) -> list[dict]:
    """Os PRs mergeados em 7 dias com a classificação de produto do Norte, a origem e o antes/depois da métrica."""
    agora = time.time() if agora is None else agora
    medido = norte.medir(store, agora)
    out = []
    for pr in store.q("SELECT number, titulo, item_id FROM prs WHERE status='mergeado' AND updated_at>=?",
                      (agora - norte.SEMANA,)):
        r = store.one("SELECT id, titulo, detalhe, origem, pergunta_id FROM roadmap WHERE id=?", (pr["item_id"],)) \
            if pr["item_id"] else None
        item = dict(r) if r else {}
        pedido, ev = _origem(store, item)
        metrica = ev.get("norte") or ev.get("metrica")
        out.append({"number": pr["number"], "titulo": pr["titulo"], "produto": norte.e_produto(store, item),
                    "pedido": pedido, "metrica": metrica, "antes": ev.get("valor") if metrica else None,
                    "depois": (medido.get(metrica) or {}).get("valor") if metrica else None})
    return out


def ler(store: Store, agora: float | None = None) -> str:
    """Monta o digest da semana e registra a leitura."""
    agora = time.time() if agora is None else agora
    prs = prs_da_semana(store, agora)
    produto = [p for p in prs if p["produto"]]
    store.x(ESQUEMA)
    store.x("INSERT INTO digest_leituras(prs, produto, sem_pedido, created_at) VALUES(?,?,?,?)",
            (len(prs), len(produto), sum(1 for p in produto if not p["pedido"]), agora))
    return texto(prs)


def leituras(store: Store, agora: float | None = None) -> int:
    """Leituras do digest nos últimos 7 dias."""
    agora = time.time() if agora is None else agora
    store.x(ESQUEMA)
    return store.one("SELECT COUNT(*) n FROM digest_leituras WHERE created_at>=?", (agora - norte.SEMANA,))["n"]

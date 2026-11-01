"""Digest semanal do que o time ganhou: os PRs de produto mergeados em 7 dias, cada um com o pedido ou a pergunta de
origem e o antes/depois da métrica que a motivou. PR de produto sem origem sai marcado 'sem pedido', nunca omitido:
o buraco no rastro é o que o time precisa ver. Cada leitura (`circulo digest`) fica em `digest_leituras`. O idle publica
o digest uma vez por semana (`publicar`); com a fração de produto abaixo da meta, o próximo roteiro parte de uma
pergunta de produto (`prioriza_produto`, lido pelo Indagador). `markdown` é a versão 'para o time' (o que entrou, quem
pediu, tempo pedido→merge), servida em /api/digest?formato=md e copiada pelo botão de Meu trabalho."""
from __future__ import annotations

import json
import time

from . import caixa, norte
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
PUBLICADO = "digest_semanal_publicado"   # kv: a última publicação do idle (em, fracao, prioriza_produto)


def abaixo_da_meta(prs: list[dict]) -> bool:
    """Semana vazia também conta: sem PR mergeado, nenhum foi produto. Pura."""
    return not prs or sum(1 for p in prs if p["produto"]) / len(prs) < META


def texto(prs: list[dict]) -> str:
    """O digest a partir dos PRs mergeados na semana (number, titulo, produto, pedido, metrica, antes, depois). Pura."""
    produto = [p for p in prs if p["produto"]]
    fracao = f"{len(produto) / len(prs):.2f}" if prs else "—"
    linhas = [f"Digest semanal: {len(produto)} de {len(prs)} PRs mergeados em 7 dias foram produto "
              f"(fração {fracao}, meta {META}{', abaixo da meta' if abaixo_da_meta(prs) else ''})."]
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


def markdown(prs: list[dict]) -> str:
    """O digest para colar no canal do time: os PRs mergeados na semana agrupados por quem pediu (mais entregas primeiro,
    'sem pedido' por último), com o tempo do pedido ao merge. Pura."""
    produto = sum(1 for p in prs if p["produto"])
    linhas = [f"## Digest da semana: {len(prs)} PRs mergeados, {produto} de produto"]
    grupos: dict[str | None, list[dict]] = {}
    for p in sorted(prs, key=lambda p: p["number"]):
        grupos.setdefault(p["por"], []).append(p)
    for por, entregas in sorted(grupos.items(), key=lambda g: (g[0] is None, -len(g[1]), g[0] or "")):
        linhas += ["", f"### {por or SEM_PEDIDO} ({len(entregas)})"]
        for p in entregas:
            partes = [f"**#{p['number']} {p['titulo']}**", f"pedido por {por}" if por else SEM_PEDIDO,
                      f"pedido→merge {_duracao(p['merge_em'] - p['pedido_em']) if p['pedido_em'] else '—'}"]
            linhas.append("- " + " · ".join(partes))
    if not prs:
        linhas += ["", "Nenhum PR mergeado na semana."]
    return "\n".join(linhas)


def _duracao(segundos: float) -> str:
    if segundos < 3600:
        return f"{max(0, round(segundos / 60))} min"
    if segundos < 2 * 86400:
        return f"{segundos / 3600:.1f} h".replace(".", ",")
    return f"{segundos / 86400:.1f} d".replace(".", ",")


def _origem(store: Store, item: dict) -> tuple[str | None, dict, str | None, float | None]:
    """(pedido ou pergunta de origem, evidência da pergunta, quem pediu, quando pediu) do item do roteiro."""
    perg = store.one("SELECT id, persona, texto, evidencia, created_at FROM perguntas WHERE id=? OR item_id=? ORDER BY id LIMIT 1",
                     (item.get("pergunta_id") or -1, item["id"])) if item else None
    ev = json.loads(perg["evidencia"]) if perg and perg["evidencia"] else {}
    if item and item.get("origem") == "pedido_cassio":
        por = caixa.quem_pediu(store, [item["id"]]).get(item["id"], caixa.QUEM_PADRAO)
        return f"pedido: {(item['detalhe'] or item['titulo'])[:160]}", ev, por, item["created_at"]
    if perg:
        return f"pergunta #{perg['id']} ({perg['persona']}): {perg['texto'][:160]}", ev, perg["persona"], perg["created_at"]
    return None, ev, None, None


def prs_da_semana(store: Store, agora: float | None = None) -> list[dict]:
    """Os PRs mergeados em 7 dias com a classificação de produto do Norte, a origem e o antes/depois da métrica."""
    agora = time.time() if agora is None else agora
    medido = norte.medir(store, agora)
    out = []
    for pr in store.q("SELECT number, titulo, item_id, updated_at FROM prs WHERE status='mergeado' AND updated_at>=?",
                      (agora - norte.SEMANA,)):
        r = store.one("SELECT id, titulo, detalhe, origem, pergunta_id, created_at FROM roadmap WHERE id=?", (pr["item_id"],)) \
            if pr["item_id"] else None
        item = dict(r) if r else {}
        pedido, ev, por, pedido_em = _origem(store, item)
        metrica = ev.get("norte") or ev.get("metrica")
        out.append({"number": pr["number"], "titulo": pr["titulo"], "produto": norte.e_produto(store, item),
                    "pedido": pedido, "metrica": metrica, "antes": ev.get("valor") if metrica else None,
                    "depois": (medido.get(metrica) or {}).get("valor") if metrica else None,
                    "por": por, "pedido_em": pedido_em, "merge_em": pr["updated_at"]})
    return out


def ler(store: Store, agora: float | None = None, formato=texto) -> str:
    """Monta o digest da semana (texto, ou `markdown` para o time) e registra a leitura."""
    agora = time.time() if agora is None else agora
    return _ler(store, prs_da_semana(store, agora), agora, formato)


def _ler(store: Store, prs: list[dict], agora: float, formato=texto) -> str:
    produto = [p for p in prs if p["produto"]]
    store.x(ESQUEMA)
    store.x("INSERT INTO digest_leituras(prs, produto, sem_pedido, created_at) VALUES(?,?,?,?)",
            (len(prs), len(produto), sum(1 for p in produto if not p["pedido"]), agora))
    return formato(prs)


def publicar(store: Store, reply, agora: float | None = None) -> str | None:
    """No idle: o digest da semana vai para a linha do tempo no máximo uma vez a cada 7 dias, e a fração fica gravada
    em kv PUBLICADO. Devolve o texto publicado, ou None se a semana já teve o seu."""
    agora = time.time() if agora is None else agora
    if agora - float((store.get(PUBLICADO) or {}).get("em") or 0) < norte.SEMANA:
        return None
    prs = prs_da_semana(store, agora)
    t = _ler(store, prs, agora)
    store.set(PUBLICADO, {"em": agora, "fracao": round(sum(1 for p in prs if p["produto"]) / len(prs), 2) if prs else None,
                          "prioriza_produto": abaixo_da_meta(prs)})
    reply(t, "saude")
    return t


def prioriza_produto(store: Store) -> bool:
    """O último digest publicado ficou abaixo da meta de produto: o roteiro seguinte parte de uma pergunta de produto."""
    return bool((store.get(PUBLICADO) or {}).get("prioriza_produto"))


def leituras(store: Store, agora: float | None = None) -> int:
    """Leituras do digest nos últimos 7 dias."""
    agora = time.time() if agora is None else agora
    store.x(ESQUEMA)
    return store.one("SELECT COUNT(*) n FROM digest_leituras WHERE created_at>=?", (agora - norte.SEMANA,))["n"]

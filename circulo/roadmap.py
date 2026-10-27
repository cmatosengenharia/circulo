"""Roadmap: todo item nasce de uma pergunta do conselho; `Origem` só existe com um pergunta_id válido.

Seleção do item para o Developer (`fora_da_fila`, chamado pelo `fatiador.proximo`):
- disjuntor por assinatura (quarentena à la DLQ, `deve_bloquear`): LIMITE_IGUAIS falhas locais (`developer:*`, mais as
  repetições da base vermelha, que o pré-voo só conta no kv) com a mesma assinatura no item o tiram da fila
  ('bloqueado', com motivo, assinatura e data) e viram a verificação PONTO, que o conselho lê. Depois de COOLDOWN
  (dobrado a cada vez que volta a abrir), ou quando o node id do item muda, `reabrir` o devolve meio-aberto: uma única tentativa, e
  qualquer falha nela bloqueia de novo (Fowler, CircuitBreaker);
- item de lição fechada sai da fila só se o node id dela passar isolado no main (`licoes.reexecutar_no_main`, o curador
  do item #37); vermelho, segue na fila e só é reexecutado de novo depois de COOLDOWN.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

LIMITE_IGUAIS = 5
COOLDOWN = 6 * 3600
BLOQUEADO = "bloqueado"
PONTO = "developer:disjuntor"
DISJUNTOR = "roadmap_disjuntor"          # {item: {"sig", "n", "node", "em", "vezes", "base", "desde"?}}; "desde" = meio-aberto
VERMELHA = "roadmap_licao_vermelha"      # {item: quando o node id da lição fechada falhou no main}
FECHADAS = ("validada", "evidenciada")


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


def _node(s, item_id: int, sig: str) -> str | None:
    """O node id que prova o item: o da lição de origem (unir/alias o mudam), senão o que a assinatura cita."""
    from .licoes import alvo_de, node_id_de
    lic = s.one("SELECT * FROM licoes WHERE item_id=? AND status!='unida' ORDER BY id LIMIT 1", (item_id,))
    return (alvo_de(lic) if lic else None) or node_id_de(sig)


def _mais_repetida(s, item_id: int, desde: float) -> tuple[str, int]:
    """(assinatura, vezes) da falha local mais repetida do item depois de `desde`, pelo id e não pelo worktree."""
    from .fatiador import sujeito
    r = s.one("SELECT assinatura, COUNT(*) n FROM verificacoes WHERE ponto LIKE 'developer:%' AND ponto!=? AND ok=0 "
              "AND (item_id=? OR sujeito=?) AND created_at>? GROUP BY assinatura ORDER BY n DESC LIMIT 1",
              (PONTO, item_id, sujeito(item_id), desde))
    return (r["assinatura"] or "", r["n"]) if r else ("", 0)


def deve_bloquear(falhas_mesma_assinatura: int, limite: int = LIMITE_IGUAIS) -> bool:
    return falhas_mesma_assinatura >= limite


def _falhas_iguais(s, item_id: int, d: dict) -> tuple[str, int]:
    """(assinatura, vezes) da falha local mais repetida; a base vermelha grava um evento por assinatura e conta as
    repetições no kv do pré-voo (item #144: 3786 falhas sem abrir o disjuntor). Meio-aberto, só o que veio depois."""
    sig, n = _mais_repetida(s, item_id, d.get("desde", 0))
    base, antes = _base_vermelha(s, item_id), (d.get("base") or {}) if "desde" in d else {}
    extra = base.get("n", 0) - (antes.get("n", 0) if antes.get("sig") == base.get("sig") else 0)
    return (base["sig"], extra) if extra > n else (sig, n)


def _base_vermelha(s, item_id: int) -> dict:
    from .reparo import BASE_VERMELHA
    return {k: v for k, v in ((s.get(BASE_VERMELHA) or {}).get(str(item_id)) or {}).items() if k in ("sig", "n")}


def _espera(d: dict) -> float:
    return COOLDOWN * 2 ** (d["vezes"] - 1)


def reabrir(s, agora: float | None = None) -> list[int]:
    """Meio-aberto: o item bloqueado volta à fila para uma tentativa depois do cooldown ou se o node id mudou."""
    agora, todos, out = agora or time.time(), s.get(DISJUNTOR) or {}, []
    for chave, d in todos.items():
        if "desde" in d or not s.one("SELECT 1 FROM roadmap WHERE id=? AND status=?", (int(chave), BLOQUEADO)):
            continue
        if agora - d["em"] < _espera(d) and _node(s, int(chave), d["sig"]) == d["node"]:
            continue
        todos[chave] = {**d, "desde": agora}
        s.x("UPDATE roadmap SET status='pendente', evidencia=?, updated_at=? WHERE id=?",
            (f"disjuntor meio-aberto: uma tentativa depois de {d['n']} falhas iguais ({d['sig'][:120]})", agora, int(chave)))
        out.append(int(chave))
    if out:
        s.set(DISJUNTOR, todos)
    return out


def _bloquear(ctx, item: dict, sig: str, n: int, agora: float) -> None:
    s = ctx.store
    d = {"sig": sig, "n": n, "node": _node(s, item["id"], sig), "em": agora, "base": _base_vermelha(s, item["id"]),
         "vezes": ((s.get(DISJUNTOR) or {}).get(str(item["id"])) or {}).get("vezes", 0) + 1}
    motivo = (f"bloqueado em {time.strftime('%Y-%m-%d %H:%M', time.localtime(agora))}: {n} falhas locais iguais "
              f"({sig[:160]}); reteste em {_espera(d) / 3600:g} h ou quando o node id mudar")
    s.set(DISJUNTOR, {**(s.get(DISJUNTOR) or {}), str(item["id"]): d})
    s.x("UPDATE roadmap SET status=?, evidencia=?, updated_at=? WHERE id=?", (BLOQUEADO, motivo[:300], agora, item["id"]))
    from .licoes import registrar
    registrar(ctx, PONTO, False, sujeito=f"roteiro #{item['id']}", item_id=item["id"], motivo=motivo, causa=sig[:200],
              licao=False)
    if callable(getattr(ctx, "reply", None)):
        ctx.reply(f"Developer: “{item['titulo'][:80]}” {motivo}.", "saude")


def _licao_verde_no_main(ctx, item: dict, repo, agora: float) -> bool:
    """A lição de origem está fechada e o node id dela passa isolado no main: o item vira 'feito' sem o Developer."""
    from . import licoes
    s = ctx.store
    lic = s.one(f"SELECT * FROM licoes WHERE item_id=? AND status IN ({','.join('?' * len(FECHADAS))}) AND NOT EXISTS "
                f"(SELECT 1 FROM licoes WHERE item_id=? AND status IN ({','.join('?' * len(licoes.ABERTAS))})) "
                "ORDER BY id LIMIT 1", (item["id"], *FECHADAS, item["id"], *licoes.ABERTAS))
    node = licoes.alvo_de(lic) if lic else None
    vermelhas = s.get(VERMELHA) or {}
    if not node or not repo or agora - vermelhas.get(str(item["id"]), 0) < COOLDOWN:
        return False
    sha, codigos = licoes.reexecutar_no_main(repo, [node])
    if codigos.get(node) != 0:
        s.set(VERMELHA, {**vermelhas, str(item["id"]): agora})
        return False
    s.x("UPDATE roadmap SET status='feito', evidencia=?, updated_at=? WHERE id=?",
        (f"lição #{lic['id']} fechada: {node} passou isolado no main (sha {sha[:12]}, exit 0)", agora, item["id"]))
    return True


def titulo_sem_uso(evento: str) -> str:
    return f"Decidir: divulgar ou remover a entrega sem uso após 7 dias (evento esperado: {evento})"


def decidir_sem_uso(s, pergunta_id: int, agora: float | None = None) -> list[int]:
    """Cada entrega sem uso há 7+ dias vira um item de decisão preso à pergunta do PM; o título é a chave do evento
    esperado, então um item já existente (aberto ou resolvido) não é duplicado. Devolve os itens criados."""
    from .planejador import gravar_item
    from .uso_entregas import listar_sem_uso
    novos = []
    for e in listar_sem_uso(s.db, time.time() if agora is None else agora):
        titulo = titulo_sem_uso(e["evento_esperado"])
        if s.one("SELECT 1 FROM roadmap WHERE titulo=?", (titulo,)):
            continue
        novos.append(gravar_item(s, pergunta_id, titulo,
                                 f"O PR #{e['number']} foi mergeado há 7+ dias e nenhum evento "
                                 f"'{e['evento_esperado']}' foi registrado depois: divulgar a entrega ou removê-la.",
                                 f"entrega sem uso: PR #{e['number']}, evento esperado {e['evento_esperado']}"))
    return novos


def fora_da_fila(ctx, item: dict, repo=None, agora: float | None = None) -> bool:
    """True = o item não vai para o Developer agora: o disjuntor abriu, ou a lição dele já está fechada e verde no main."""
    agora = agora or time.time()
    d = (ctx.store.get(DISJUNTOR) or {}).get(str(item["id"])) or {}
    sig, n = _falhas_iguais(ctx.store, item["id"], d)
    if deve_bloquear(n, 1 if "desde" in d else LIMITE_IGUAIS):
        _bloquear(ctx, item, sig, n, agora)
        return True
    return _licao_verde_no_main(ctx, item, repo, agora)

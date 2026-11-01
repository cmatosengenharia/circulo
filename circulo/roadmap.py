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

import re
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
META_MENSURAVEL = 0.9                    # pergunta #186: ≥90% dos PRs mergeados em 7 dias com critério mensurável
SERIE = "roadmap_criterios_serie"        # [{"dia", "proporcao", "prs_7d"}], uma amostra por dia
JUSTIFICADOS = "roadmap_orfaos_justificados"   # {pr: motivo}: PR mergeado sem critério que não precisa de um
_ALVO_NUMERICO =re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|[^\W\d_]+)")   # número e unidade: "60%", "≤60 min", "0 falhas"


class SemPerguntaOrigem(ValueError):
    """Item do loop sem a pergunta do conselho que o originou (lição #15): o rastro:cadeia barraria a entrega."""


@dataclass(frozen=True)
class Origem:
    pergunta_id: int

    def __post_init__(self) -> None:
        if type(self.pergunta_id) is not int or self.pergunta_id <= 0:
            raise SemPerguntaOrigem(f"item do roadmap sem pergunta de origem: pergunta_id={self.pergunta_id!r}")


def exigir_pergunta(store, pergunta_id: int | None) -> int:
    """O id da pergunta de origem, se ela existe na tabela do conselho; senão SemPerguntaOrigem."""
    pid = Origem(pergunta_id).pergunta_id
    if not store.one("SELECT 1 FROM perguntas WHERE id=?", (pid,)):
        raise SemPerguntaOrigem(f"pergunta de origem #{pid} não está na tabela do conselho")
    return pid


def gravar_item(store, pergunta_id: int | None, titulo: str, detalhe: str, evidencia: str, modulo: str | None = None,
                status: str = "pendente") -> int:
    """O ponto único de gravação de item do loop no roteiro (lição #15): sempre preso à pergunta que o originou."""
    pid = exigir_pergunta(store, pergunta_id)
    ordem = (store.one("SELECT MAX(ordem) m FROM roadmap")["m"] or 0) + 1
    agora = time.time()
    rid = store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,modulo,"
                  "pergunta_id,origem_status) VALUES(?,?,'loop',?,?,?,?,?,?,?,'ok')",
                  (titulo, detalhe[:2000], status, evidencia, ordem, agora, agora, modulo, pid))
    store.x("UPDATE perguntas SET item_id=?, updated_at=? WHERE id=?", (rid, agora, pid))
    return rid


def gravar_medido(store, persona: str, chave: str, titulo: str, detalhe: str, evidencia: str) -> int:
    """Item que um papel do loop abre a partir do que mediu (Vigia, Jardineiro): a medição vira a pergunta de origem,
    já respondida pelo item, e o item é gravado preso a ela. O cérebro é o próprio papel: fora do placar do conselho."""
    agora = time.time()
    pid = store.x("INSERT INTO perguntas(chave,persona,texto,evidencia,status,cerebro,created_at,updated_at) "
                  "VALUES(?,?,?,?,'virou_item',?,?,?)", (chave, persona, titulo, evidencia, persona, agora, agora))
    return gravar_item(store, pid, titulo, detalhe, evidencia)


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


def decidir_sem_uso(s, pergunta_id: int, agora: float | None = None) -> list[int]:
    """Cada entrega sem uso há 7+ dias vira um item de decisão preso à pergunta do PM, uma vez por PR: o único gerador
    é `revisao_uso.cobrar_no_roteiro`. Devolve os itens criados."""
    from .revisao_uso import cobrar_no_roteiro
    return cobrar_no_roteiro(s, pergunta_id, agora)


def cobertura_sem_uso(s, agora: float | None = None) -> dict:
    """A medida do sucesso, lida do DB: quantas entregas sem uso há 7+ dias têm exatamente 1 item de revisão no roteiro
    e quantas têm mais de 1 (duplicadas); `cobertura` é a fração com exatamente 1 (1.0 sem nenhuma entrega sem uso)."""
    from .revisao_uso import titulo
    from .uso_entregas import listar_sem_uso
    n = [s.one("SELECT COUNT(*) AS n FROM roadmap WHERE titulo=?", (titulo(e["number"], e["evento_esperado"]),))["n"]
         for e in listar_sem_uso(s.db, time.time() if agora is None else agora)]
    um = n.count(1)
    return {"sem_uso": len(n), "com_1_item": um, "duplicadas": sum(1 for k in n if k > 1),
            "cobertura": um / len(n) if n else 1.0}


def criterios_dos_mergeados(prs: list[dict], itens: dict[int, str], agora: float,
                            justificados: dict[int, str] | None = None) -> dict:
    """Pergunta #186, pura: cruza os PRs mergeados nos últimos 7 dias (`{"pr", "item", "mergeado_em"}`) com o detalhe
    dos itens. Devolve os PRs sem critério de sucesso (inclui os sem item; os de `justificados` saem da lista com o
    motivo), os critérios sem alvo numérico (número e unidade) e a proporção mensurável. Mede só a forma do critério;
    se a meta foi atingida é a `prova` (item #113)."""
    from .prova import JANELA_S, criterio
    justificados = justificados or {}
    sem_criterio, sem_metrica, orfaos_ok = [], [], []
    janela = [p for p in prs if agora - JANELA_S <= p["mergeado_em"] <= agora]
    for p in janela:
        c = criterio(itens.get(p["item"], "")) if p["item"] is not None else None
        if not c and p["pr"] in justificados:
            orfaos_ok.append({"pr": p["pr"], "motivo": justificados[p["pr"]]})
        elif not c:
            sem_criterio.append(p["pr"])
        elif not _ALVO_NUMERICO.search(c):
            sem_metrica.append({"pr": p["pr"], "item": p["item"], "criterio": c})
    mensuraveis = len(janela) - len(sem_criterio) - len(sem_metrica) - len(orfaos_ok)
    proporcao = mensuraveis / len(janela) if janela else 1.0
    return {"prs_7d": len(janela), "mensuraveis": mensuraveis, "proporcao": proporcao, "meta": META_MENSURAVEL,
            "atingiu": proporcao >= META_MENSURAVEL and not sem_criterio,
            "sem_criterio": sem_criterio, "sem_metrica": sem_metrica, "justificados": orfaos_ok}


def ler_criterios(s, agora: float | None = None) -> dict:
    """`criterios_dos_mergeados` sobre o DB: PR → item pela branch `circulo/fix-<item>-…`; justificativas dos órfãos
    em kv JUSTIFICADOS ({pr: motivo}); mais a série diária de `amostrar_criterios`."""
    from .rastro import PREFIXO_BRANCH
    agora = time.time() if agora is None else agora
    prs = [{"pr": r["number"], "mergeado_em": r["em"],
            "item": int(m.group(1)) if (m := re.match(re.escape(PREFIXO_BRANCH) + r"(\d+)-", r["branch"] or "")) else None}
           for r in s.q("SELECT p.number, p.branch, MIN(m.created_at) em FROM prs p "
                        "JOIN merges m ON m.pr=p.number AND m.merged=1 GROUP BY p.number")]
    itens = {r["id"]: r["detalhe"] for r in s.q("SELECT id, detalhe FROM roadmap")}
    justificados = {int(k): v for k, v in (s.get(JUSTIFICADOS) or {}).items()}
    return {**criterios_dos_mergeados(prs, itens, agora, justificados), "serie": s.get(SERIE) or []}


def amostrar_criterios(s, agora: float | None = None) -> dict:
    """Grava na série (uma amostra por dia, as últimas 30) a proporção mensurável lida agora; chamada no giro."""
    agora = time.time() if agora is None else agora
    r = ler_criterios(s, agora)
    dia = time.strftime("%Y-%m-%d", time.localtime(agora))
    serie = [a for a in r["serie"] if a["dia"] != dia] + [{"dia": dia, "proporcao": r["proporcao"], "prs_7d": r["prs_7d"]}]
    s.set(SERIE, serie[-30:])
    return {**r, "serie": serie[-30:]}


def fora_da_fila(ctx, item: dict, repo=None, agora: float | None = None) -> bool:
    """True = o item não vai para o Developer agora: o disjuntor abriu, ou a lição dele já está fechada e verde no main."""
    agora = agora or time.time()
    d = (ctx.store.get(DISJUNTOR) or {}).get(str(item["id"])) or {}
    sig, n = _falhas_iguais(ctx.store, item["id"], d)
    if deve_bloquear(n, 1 if "desde" in d else LIMITE_IGUAIS):
        _bloquear(ctx, item, sig, n, agora)
        return True
    return _licao_verde_no_main(ctx, item, repo, agora)

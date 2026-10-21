"""Desfecho por decisão: o que cada "sim" do Jev rendeu — fecha o ciclo de aprendizado.

O Jev decide 2.400 vezes por dia e só vê o resultado por fora. Aqui cada decisão de gasto (`worth_spending`) e de
evolução (`should_evolve`) ganha, mais tarde, o desfecho medido: o que a ação produziu (PR aberto, PR mergeado,
estudo adotado/contestado, item criado, nada), quanto custou em tokens e quanto demorou. O aluno do Jev treina com
esse rótulo quando ele existe — passa de imitar o Jev a aprender o que deu certo. O painel mostra o custo por resultado
(tokens por PR mergeado) e a taxa de "sim" que rendeu algo, por ação.

Ligações (todas baratas, nenhuma na constituição):
- `intencoes.executar` chama `fechar_tarefa` ao fim de cada tarefa do giro (ok/falhou, duração);
- `self_dev.concluir_mergeados` → `pr_mergeado` (o desfecho "proposto" vira "entregue");
- `estudo.run` → `estudo` (adotar/adaptar/contestar/dispensado);
- `evolution` → `evolucao` (aplicada/revertida).
"""
from __future__ import annotations

import time
from typing import Any

from .state import Store

ESQUEMA = """
CREATE TABLE IF NOT EXISTS desfechos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  decision_id INTEGER,
  question TEXT NOT NULL,
  acao TEXT NOT NULL,
  item_id INTEGER,
  pr INTEGER,
  resultado TEXT NOT NULL,        -- proposto | entregue | nada | falhou | adotar | adaptar | contestar | dispensado | item | descartada | aplicada | revertida
  tokens INTEGER NOT NULL DEFAULT 0,
  duracao_s INTEGER,
  rendeu INTEGER NOT NULL,        -- 1 = a decisão de gastar valeu
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS desfechos_decisao ON desfechos(decision_id);
CREATE INDEX IF NOT EXISTS desfechos_acao ON desfechos(acao, created_at);
"""
RENDEU = {"proposto", "entregue", "adotar", "adaptar", "contestar", "item", "aplicada"}
PAPEL_DA_ACAO = {"corrigir_codigo": "developer", "estudar_pedido": "estudo", "planejar_roteiro": "planejador", "indagar": None,
                 "evoluir_harness": "improver", "propor_feature": "proposer", "documentar": None}
JANELA_DECISAO = 2 * 3600


def preparar(store: Store) -> None:
    if getattr(store, "_desfecho_pronto", False):
        return
    for sql in ESQUEMA.strip().split(";"):
        if sql.strip():
            store.x(sql)
    store._desfecho_pronto = True


def _decisao_de(store: Store, question: str, acao: str | None, agora: float) -> dict | None:
    """A decisão mais recente dessa pergunta (e ação) ainda sem desfecho, na janela."""
    like = f'%"action": "{acao}"%' if acao else "%"
    r = store.one("SELECT d.id, d.created_at FROM decisions d WHERE d.question=? AND d.estado LIKE ? AND d.created_at>=? "
                  "AND NOT EXISTS (SELECT 1 FROM desfechos x WHERE x.decision_id=d.id) ORDER BY d.id DESC LIMIT 1",
                  (question, like, agora - JANELA_DECISAO))
    return dict(r) if r else None


def _tokens(store: Store, papel: str | None, desde: float, ate: float, item_titulo: str | None = None) -> int:
    if not papel:
        return 0
    if item_titulo:
        r = store.one("SELECT COALESCE(SUM(tokens),0) t FROM llm_calls WHERE papel=? AND created_at BETWEEN ? AND ? AND entrada LIKE ?",
                      (papel, desde, ate, f"%{item_titulo[:60]}%"))
    else:
        r = store.one("SELECT COALESCE(SUM(tokens),0) t FROM llm_calls WHERE papel=? AND created_at BETWEEN ? AND ?", (papel, desde, ate))
    return int(r["t"] or 0) if r else 0


def registrar(store: Store, question: str, acao: str, resultado: str, item_id: int | None = None, pr: int | None = None,
              tokens: int | None = None, titulo: str | None = None, agora: float | None = None) -> int | None:
    """Liga o desfecho à última decisão da pergunta/ação sem desfecho. Sem decisão na janela, registra sem vínculo."""
    agora = agora or time.time()
    preparar(store)
    d = _decisao_de(store, question, acao if question == "worth_spending" else None, agora)
    desde = float(d["created_at"]) if d else agora - 600
    if tokens is None:
        tokens = _tokens(store, PAPEL_DA_ACAO.get(acao), desde, agora, titulo)
    return store.x("INSERT INTO desfechos(decision_id,question,acao,item_id,pr,resultado,tokens,duracao_s,rendeu,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (d["id"] if d else None, question, acao, item_id, pr, resultado, int(tokens or 0), int(agora - desde) if d else None,
                    1 if resultado in RENDEU else 0, agora, agora))


def fechar_tarefa(store: Store, acao: str, ok: bool, duracao_s: float, detalhe: str = "") -> None:
    """Fim de uma tarefa do giro: o desfecho genérico (ok/falhou). Ações com desfecho rico (Developer, estudo) sobrescrevem
    depois com `atualizar` pelo item; as outras ficam com este."""
    if acao not in PAPEL_DA_ACAO:
        return
    preparar(store)
    agora = time.time()
    d = _decisao_de(store, "worth_spending", acao, agora)
    if not d:
        return
    tokens = _tokens(store, PAPEL_DA_ACAO.get(acao), float(d["created_at"]), agora)
    resultado = "falhou" if not ok else ("nada" if acao in ("corrigir_codigo", "estudar_pedido", "planejar_roteiro") else "ok")
    store.x("INSERT INTO desfechos(decision_id,question,acao,item_id,pr,resultado,tokens,duracao_s,rendeu,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (d["id"], "worth_spending", acao, None, None, resultado, tokens, int(duracao_s), 1 if resultado == "ok" else 0, agora, agora))


def atualizar(store: Store, acao: str, resultado: str, item_id: int | None = None, pr: int | None = None, tokens: int | None = None) -> None:
    """Enriquece o desfecho mais recente da ação (o genérico de `fechar_tarefa` ou um anterior do mesmo item)."""
    preparar(store)
    agora = time.time()
    r = (store.one("SELECT id, tokens FROM desfechos WHERE acao=? AND item_id=? ORDER BY id DESC LIMIT 1", (acao, item_id)) if item_id else None) \
        or store.one("SELECT id, tokens FROM desfechos WHERE acao=? AND created_at>=? ORDER BY id DESC LIMIT 1", (acao, agora - 120))
    if not r:
        registrar(store, "worth_spending", acao, resultado, item_id=item_id, pr=pr, tokens=tokens, agora=agora)
        return
    store.x("UPDATE desfechos SET resultado=?, item_id=COALESCE(?, item_id), pr=COALESCE(?, pr), tokens=?, rendeu=?, updated_at=? WHERE id=?",
            (resultado, item_id, pr, int(tokens if tokens is not None else r["tokens"]), 1 if resultado in RENDEU else 0, agora, r["id"]))


def pr_mergeado(store: Store, pr: int, item_id: int | None) -> None:
    """O PR do Developer entrou: todo desfecho "proposto" dele vira "entregue"."""
    preparar(store)
    store.x("UPDATE desfechos SET resultado='entregue', rendeu=1, updated_at=? WHERE acao='corrigir_codigo' AND (pr=? OR (item_id=? AND item_id IS NOT NULL)) AND resultado IN ('proposto','nada')",
            (time.time(), pr, item_id))


def evolucao(store: Store, resultado: str, descricao: str = "") -> None:
    preparar(store)
    registrar(store, "should_evolve", "evoluir", "aplicada" if resultado in ("applied", "shadow") else "revertida" if resultado == "rolled_back" else resultado, titulo=descricao or None)


def rotulos(store: Store, question: str, desde: float = 0.0) -> dict[int, str]:
    """decision_id → rótulo medido ("true"/"false"): para o aluno treinar no que deu certo."""
    if not store.one("SELECT 1 FROM sqlite_master WHERE name='desfechos'"):
        return {}
    return {int(r["decision_id"]): ("true" if r["rendeu"] else "false")
            for r in store.q("SELECT decision_id, rendeu FROM desfechos WHERE question=? AND decision_id IS NOT NULL AND created_at>=?", (question, desde))}


def resumo(store: Store, agora: float | None = None) -> dict[str, Any]:
    """Custo por resultado e taxa de acerto do 'sim', por ação, em 24 h e nas 24 h anteriores (tendência)."""
    agora = agora or time.time()
    preparar(store)

    def janela(a: float, b: float) -> dict:
        por_acao = {}
        for r in store.q("SELECT acao, COUNT(*) n, SUM(rendeu) r, SUM(tokens) t, SUM(resultado='entregue') e FROM desfechos WHERE created_at>=? AND created_at<? GROUP BY acao", (a, b)):
            por_acao[r["acao"]] = {"n": int(r["n"]), "rendeu": int(r["r"] or 0), "tokens": int(r["t"] or 0), "entregues": int(r["e"] or 0),
                                   "taxa": round((r["r"] or 0) / r["n"], 3) if r["n"] else None}
        prs = int((store.one("SELECT COUNT(*) n FROM prs WHERE status='mergeado' AND updated_at>=? AND updated_at<?", (a, b)) or {"n": 0})["n"] or 0)
        tokens = int((store.one("SELECT COALESCE(SUM(tokens),0) t FROM llm_calls WHERE created_at>=? AND created_at<?", (a, b)) or {"t": 0})["t"] or 0)
        return {"por_acao": por_acao, "prs_mergeados": prs, "tokens": tokens, "tokens_por_pr": int(tokens / prs) if prs else None}
    hoje, ontem = janela(agora - 86400, agora + 1), janela(agora - 2 * 86400, agora - 86400)
    n_rot = int((store.one("SELECT COUNT(*) n FROM desfechos WHERE decision_id IS NOT NULL") or {"n": 0})["n"] or 0)
    return {"hoje": hoje, "ontem": ontem, "decisoes_com_desfecho": n_rot,
            "tendencia": (None if not hoje["tokens_por_pr"] or not ontem["tokens_por_pr"] else round(hoje["tokens_por_pr"] / ontem["tokens_por_pr"] - 1, 3))}


__all__ = ["preparar", "registrar", "fechar_tarefa", "atualizar", "pr_mergeado", "evolucao", "rotulos", "resumo"]

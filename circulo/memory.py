"""Memória do círculo (RAG) e playbooks por tipo de pedido.

- Busca lexical BM25 em Python puro (sem dependência), depois reranking pelo Jev (`relevant`).
- Tudo que vem de fora (pesquisa na web) entra como `nao_confiavel`: pode informar, nunca vira regra sozinho.
- Lições (playbook) nascem em quarentena. Viram ativas quando um ciclo que as usou melhorou a nota;
  são aposentadas (nunca apagadas) quando usadas várias vezes sem ganho.
"""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter

from .decision import DecisionLayer, norm
from .state import Store

KINDS = ("achado", "licao", "feedback", "entrega")
_TOKEN = re.compile(r"[a-z0-9]{3,}")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(norm(text))


class Memory:
    def __init__(self, store: Store, dl: DecisionLayer):
        self.s = store
        self.dl = dl

    # ------------------------------------------------------------ escrever
    def add(self, kind: str, text: str, *, tipo: str | None = None, project_id: int | None = None,
            source: str = "", trust: str = "confiavel", status: str = "ativa", meta: dict | None = None) -> int:
        assert kind in KINDS
        dup = self.s.one("SELECT id FROM memory WHERE kind=? AND text=? AND COALESCE(tipo,'')=COALESCE(?,'')", (kind, text, tipo))
        if dup:
            return dup["id"]
        return self.s.x("INSERT INTO memory(kind,text,tipo,project_id,source,trust,status,meta,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (kind, text.strip()[:2000], tipo, project_id, source[:500], trust, status,
                         json.dumps(meta or {}, ensure_ascii=False), time.time(), time.time()))

    # ------------------------------------------------------------ buscar (BM25 + rerank Jev)
    def search(self, query: str, *, kinds: tuple[str, ...] = KINDS, tipo: str | None = None,
               project_id: int | None = None, k: int = 5, rerank: bool = True, include_quarantine: bool = False) -> list[dict]:
        where, args = [f"kind IN ({','.join('?' * len(kinds))})"], list(kinds)
        where.append("status IN ('ativa','quarentena')" if include_quarantine else "status='ativa'")
        if tipo:
            where.append("(tipo=? OR tipo IS NULL)")
            args.append(tipo)
        if project_id:
            where.append("(project_id=? OR project_id IS NULL OR kind='licao')")
            args.append(project_id)
        docs = [dict(r) for r in self.s.q(f"SELECT * FROM memory WHERE {' AND '.join(where)}", args)]
        if not docs:
            return []
        q = _tokens(query)
        toks = [_tokens(d["text"]) for d in docs]
        n, avg = len(docs), (sum(len(t) for t in toks) / len(docs)) or 1
        df = Counter(w for t in toks for w in set(t))
        scores = []
        for d, t in zip(docs, toks, strict=True):
            tf = Counter(t)
            sc = 0.0
            for w in q:
                if w in tf:
                    idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                    sc += idf * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * len(t) / avg))
            scores.append(sc)
        cand = [d for d, sc in sorted(zip(docs, scores, strict=True), key=lambda x: -x[1]) if sc > 0][: max(k * 3, 10)]
        if rerank and len(cand) > k:
            order = self.dl.relevant(query, [c["text"] for c in cand], top=k)
            cand = [cand[i] for i in order] or cand[:k]
        return cand[:k]

    # ------------------------------------------------------------ playbook por tipo
    def playbook(self, tipo: str, ativas: int = 4, exploracao: int = 1) -> list[dict]:
        """Lições ativas + no máximo uma em quarentena (para poder ser confirmada)."""
        act = [dict(r) for r in self.s.q("SELECT * FROM memory WHERE kind='licao' AND tipo=? AND status='ativa' "
                                         "ORDER BY json_extract(meta,'$.confirmacoes') DESC, id DESC LIMIT ?", (tipo, ativas))]
        qua = [dict(r) for r in self.s.q("SELECT * FROM memory WHERE kind='licao' AND tipo=? AND status='quarentena' "
                                         "ORDER BY COALESCE(json_extract(meta,'$.usos'),0), id LIMIT ?", (tipo, exploracao))]
        return act + qua

    def lesson_outcome(self, lesson_ids: list[int], gain: float, min_gain: float) -> None:
        for lid in lesson_ids:
            row = self.s.one("SELECT status, meta FROM memory WHERE id=?", (lid,))
            if not row:
                continue
            m = json.loads(row["meta"] or "{}")
            m["usos"] = m.get("usos", 0) + 1
            if gain >= min_gain:
                m["confirmacoes"] = m.get("confirmacoes", 0) + 1
            status = row["status"]
            if status == "quarentena" and m.get("confirmacoes", 0) >= 1:
                status = "ativa"
            if m["usos"] >= 3 and m.get("confirmacoes", 0) == 0:
                status = "aposentada"   # nunca apagada: continua consultável no histórico
            self.s.x("UPDATE memory SET status=?, meta=?, updated_at=? WHERE id=?",
                     (status, json.dumps(m, ensure_ascii=False), time.time(), lid))

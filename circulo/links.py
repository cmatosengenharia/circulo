"""Catálogo de links da empresa por assunto: colo o link com um rótulo curto e acho em segundos.

Por palavra: índice FTS5 do próprio SQLite sobre rótulo, assunto e endereço, com prefixo (digitar "conn" já acha
"Connect") e sem acento. Por significado: cada link vira um nó no Graft (`circulo:link:<id>`) e a busca funde as duas
listas por Reciprocal Rank Fusion, como a memória do time. Sem FTS5, a busca por palavra cai para um filtro em Python;
sem Graft, fica só a palavra. Só entra endereço http(s): o link vira `href` no console.
"""
from __future__ import annotations

import re
import time
import unicodedata

from . import graft
from .state import Store

MAX_ROTULO = 120
MAX_ASSUNTO = 60
K_RRF = 60.0

ESQUEMA = """
CREATE TABLE IF NOT EXISTS catalogo_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL UNIQUE,
  rotulo TEXT NOT NULL,
  assunto TEXT NOT NULL DEFAULT '',
  graft_id TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
"""
FTS = ("CREATE VIRTUAL TABLE IF NOT EXISTS catalogo_links_fts USING fts5(rotulo, assunto, url, content='catalogo_links', content_rowid='id', "
       "tokenize='unicode61 remove_diacritics 2')")
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def _palavras(texto: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\w{2,}", _sem_acento(texto or ""))))[:8]


def colar(texto: str) -> tuple[str, str, str] | None:
    """`<link> <rótulo> [#assunto]` (o link pode vir antes ou depois do rótulo) → (url, rótulo, assunto); None sem link."""
    m = _URL.search(texto or "")
    if not m:
        return None
    resto = (texto[:m.start()] + " " + texto[m.end():]).strip()
    rotulo, _, assunto = resto.partition("#")
    return m.group(0), " ".join(rotulo.split()), " ".join(assunto.split())


def colar_e_guardar(store: Store, data: dict) -> tuple[dict, int]:
    """POST /api/links: `{"texto": "<link> <rótulo> #assunto"}` (o que se cola no console) ou `{"url", "rotulo", "assunto"}`."""
    partes = (colar(str(data["texto"])[:1000]) if data.get("texto")
              else (str(data.get("url", "")), str(data.get("rotulo", "")), str(data.get("assunto", ""))))
    if not partes:
        return {"erro": "cole o link (http:// ou https://) junto do rótulo"}, 400
    try:
        return {"ok": True, "link": Links(store).guardar(*partes)}, 200
    except ValueError as e:
        return {"erro": str(e)}, 400


class Links:
    def __init__(self, store: Store):
        self.s = store
        self.s.db.executescript(ESQUEMA)
        self.fts = bool(self.s.one("SELECT sqlite_compileoption_used('ENABLE_FTS5') ok")["ok"])
        if self.fts:
            self.s.db.executescript(FTS)
        self.graft = graft.ligado()

    def guardar(self, url: str, rotulo: str, assunto: str = "") -> dict:
        url, rotulo, assunto = (url or "").strip(), " ".join((rotulo or "").split())[:MAX_ROTULO], " ".join((assunto or "").split())[:MAX_ASSUNTO]
        if not _URL.fullmatch(url):
            raise ValueError("o link precisa começar com http:// ou https://")
        if not rotulo:
            raise ValueError("falta o rótulo curto do link")
        agora = time.time()
        velho = self.s.one("SELECT * FROM catalogo_links WHERE url=?", (url,))
        if velho:
            lid = int(velho["id"])
            self.s.x("UPDATE catalogo_links SET rotulo=?, assunto=?, updated_at=? WHERE id=?", (rotulo, assunto, agora, lid))
            if self.fts:
                self.s.x("INSERT INTO catalogo_links_fts(catalogo_links_fts, rowid, rotulo, assunto, url) VALUES('delete', ?, ?, ?, ?)",
                         (lid, velho["rotulo"], velho["assunto"], url))
        else:
            lid = self.s.x("INSERT INTO catalogo_links(url, rotulo, assunto, created_at, updated_at) VALUES(?,?,?,?,?)", (url, rotulo, assunto, agora, agora))
        if self.fts:
            self.s.x("INSERT INTO catalogo_links_fts(rowid, rotulo, assunto, url) VALUES(?,?,?,?)", (lid, rotulo, assunto, url))
        if self.graft:
            texto = f"{rotulo}\nAssunto: {assunto}\n{url}"
            gid = (graft.substituir("link", lid, velho["graft_id"], rotulo, texto) if velho
                   else graft.inserir("link", lid, rotulo, texto, extras=[f"assunto:{assunto}"] if assunto else None))
            if gid:
                self.s.x("UPDATE catalogo_links SET graft_id=? WHERE id=?", (gid, lid))
        return self._linha(self.s.one("SELECT * FROM catalogo_links WHERE id=?", (lid,)))

    def buscar(self, consulta: str, k: int = 10, sentido: bool = True) -> list[dict]:
        """Por palavra (todas as palavras, cada uma como prefixo) e, com `sentido`, pelo Graft; fundidas por RRF."""
        ps = _palavras(consulta)
        if not ps:
            return []
        if self.fts:
            lexicos = self.s.q("SELECT l.* FROM catalogo_links_fts f JOIN catalogo_links l ON l.id=f.rowid WHERE catalogo_links_fts MATCH ? "
                               "ORDER BY bm25(catalogo_links_fts, 4.0, 2.0, 1.0) LIMIT 50", (" AND ".join(f'"{p}"*' for p in ps),))
        else:
            todos = self.s.q("SELECT * FROM catalogo_links ORDER BY updated_at DESC LIMIT 5000")
            lexicos = [r for r in todos if all(any(w.startswith(p) for w in _palavras(f"{r['rotulo']} {r['assunto']} {r['url']}")) for p in ps)]
        pontos: dict[int, list] = {int(r["id"]): [1.0 / (K_RRF + pos), r, "texto"] for pos, r in enumerate(lexicos)}
        if sentido and self.graft:
            semanticos = [h for h in graft.recuperar(consulta, k=k + 2) if h.get("tipo") == "link" and str(h.get("ref")).isdigit()]
            for pos, h in enumerate(semanticos):
                lid = int(h["ref"])
                if lid in pontos:
                    pontos[lid][0] += 1.0 / (K_RRF + pos)
                    pontos[lid][2] = "ambos"
                    continue
                r = self.s.one("SELECT * FROM catalogo_links WHERE id=?", (lid,))
                if r:
                    pontos[lid] = [1.0 / (K_RRF + pos), r, "graft"]
        ordem = sorted(pontos.values(), key=lambda x: -x[0])[:k]
        return [{**self._linha(r), "via": via} for _, r, via in ordem]

    @staticmethod
    def _linha(r) -> dict:
        return {"id": int(r["id"]), "url": r["url"], "rotulo": r["rotulo"], "assunto": r["assunto"]}

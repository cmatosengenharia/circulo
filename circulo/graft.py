"""Graft (github.com/AEndrix03/Graft): memória semântica local do time, ao lado do índice lexical (FTS5).

O que ele acrescenta ao `memoria.py`:
- **vetores** (BGE-M3 por llama.cpp, local, sem chave): "token de uso estourou" acha "limite da conta", que o BM25 não acha;
- **cache verificado** (`graft query` → STRONG/WEAK/MISS): o Planejador e o Arquiteto reconhecem item ou estudo
  repetido dito com outras palavras, além do Jaccard de títulos;
- **grafo** (`graft explore`): lição ↔ item ↔ PR ligados por palavras-chave e semântica, para o Médico e o Vigia
  verem o entorno de uma falha;
- **supersessão**: o conteúdo novo de uma lição substitui o antigo sem apagá-lo (`SUPERSEDED`);
- **manutenção**: `maintain apply-safe` periódico e os candidatos de duplicata resolvidos quando são o mesmo registro.

Contrato: tudo aqui é opcional. Sem o binário `graft` (ou com ele caído), cada função devolve None/[] e o círculo
segue só com o FTS. Nenhuma chamada demora mais que TIMEOUT s; a primeira do dia paga o carregamento do modelo.
Perfil próprio (`GRAFT_PROFILE`, padrão `circulo`): o grafo do loop não mistura com as anotações do Cássio.
Cada registro do `memoria` vira um nó com a palavra-chave `circulo:<tipo>:<ref>`, que é como o nó volta a ser linha.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import time

TIMEOUT = 20.0
TIMEOUT_FRIO = 180.0            # primeira chamada: o daemon sobe e carrega o modelo (~600 MB)
# perfil novo (22/10): o `circulo` foi sujo pelos testes, que rodavam no Mac com o graft real antes do isolamento
PERFIL = os.environ.get("CIRCULO_GRAFT_PERFIL") or "circulo-loop"
PREFIXO = "circulo:"
MAX_CORPO = 4000
PAUSA_APOS_FALHA = 300.0        # graft caiu: não tenta de novo a cada busca
_estado = {"falhou_em": 0.0, "aquecido": False, "chamadas": 0, "ms": 0.0}


def ligado() -> bool:
    if os.environ.get("CIRCULO_GRAFT", "1").lower() in ("0", "off", "nao", "não"):
        return False
    return shutil.which(comando()) is not None


# o loop roda como serviço (launchd) com o PATH de quando foi instalado: sem a pasta do Homebrew, `graft` instalado
# depois não era achado (22/10: instalado e 0 de 900 lembranças espelhadas). Procura também nos lugares padrão.
PASTAS_PADRAO = ("/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.graft/bin"), "/home/linuxbrew/.linuxbrew/bin")


def comando() -> str:
    pedido = os.environ.get("CIRCULO_GRAFT_CMD") or "graft"
    return shutil.which(pedido) or shutil.which(pedido, path=os.pathsep.join(PASTAS_PADRAO)) or pedido


def _ambiente() -> dict:
    env = dict(os.environ)
    env.setdefault("GRAFT_PROFILE", PERFIL)
    env.setdefault("GRAFT_AUTHOR", "circulo")
    env.setdefault("GRAFT_HOOKS", "0")
    return env


def _rodar(args: list[str], entrada: str | None = None) -> dict | None:
    """Uma chamada ao CLI; o `result` do JSON, ou None (indisponível, erro, timeout). Nunca levanta."""
    if not ligado() or time.time() - _estado["falhou_em"] < PAUSA_APOS_FALHA:
        return None
    if not _estado.get("perfil_ok"):            # o perfil próprio existe antes da primeira chamada (idempotente)
        _estado["perfil_ok"] = True
        try:
            subprocess.run([comando(), "profile", "add", PERFIL], capture_output=True, text=True, timeout=30, env=_ambiente())
        except (OSError, subprocess.TimeoutExpired):
            pass
    t0 = time.monotonic()
    try:
        p = subprocess.run([comando(), *args], input=entrada, capture_output=True, text=True,
                           timeout=TIMEOUT if _estado["aquecido"] else TIMEOUT_FRIO, env=_ambiente())
        d = json.loads(p.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        _estado["falhou_em"] = time.time()
        return None
    _estado["chamadas"] += 1
    _estado["ms"] = (time.monotonic() - t0) * 1000
    if p.returncode != 0 or d.get("status", 0) != 0:
        if p.returncode == 1:                         # socket/daemon: pausa; 2 e 3 são erro desta chamada só
            _estado["falhou_em"] = time.time()
        return None
    _estado["aquecido"] = True
    return d.get("result") if isinstance(d.get("result"), dict) else d


def chave(tipo: str, ref) -> str:
    return f"{PREFIXO}{tipo}:{ref}"


def de_chave(keywords: list[str]) -> tuple[str, str] | None:
    """(tipo, ref) do nó, pela palavra-chave `circulo:tipo:ref`; None para nó que não veio do memoria."""
    for k in keywords or []:
        if isinstance(k, str) and k.startswith(PREFIXO) and k.count(":") >= 2:
            _, tipo, ref = k.split(":", 2)
            return tipo, ref
    return None


def palavras(texto: str, maximo: int = 6) -> list[str]:
    from .memoria import termos
    return [t for t in termos(texto, maximo) if "," not in t][:maximo]


def inserir(tipo: str, ref, titulo: str, texto: str, resultado: str | None = None, extras: list[str] | None = None) -> str | None:
    """Um nó por registro; idempotente pelo conteúdo. Devolve o id_hex (ou None sem graft)."""
    kws = [chave(tipo, ref), f"tipo:{tipo}"] + ([f"resultado:{resultado}"] if resultado else []) + palavras(titulo) + list(extras or [])
    args = ["insert", "--title", (titulo or "")[:300], "--body", (texto or "")[:MAX_CORPO]]
    for k in dict.fromkeys(kws):
        args += ["--keyword", k[:80]]
    r = _rodar(args)
    return r.get("id_hex") if r else None


def substituir(tipo: str, ref, velho_id: str | None, titulo: str, texto: str, resultado: str | None = None) -> str | None:
    """Conteúdo novo do mesmo registro: insere e marca o nó antigo como SUPERSEDED (fica visível, sai da busca)."""
    novo = inserir(tipo, ref, titulo, texto, resultado)
    if novo and velho_id and velho_id != novo:
        _rodar(["maintain", "resolve", "--node", velho_id, "--action", "supersede", "--by", novo, "--actor", "circulo",
                "--note", f"conteúdo novo de {chave(tipo, ref)}"])
    return novo


def consultar(texto: str) -> dict | None:
    """Cache verificado: {'hit': STRONG|WEAK|MISS, 'id_hex', 'title', 'body', 'tipo', 'ref', 's_vec'}."""
    r = _rodar(["query", (texto or "")[:1000]])
    if not r:
        return None
    sig = r.get("signals") or {}
    out = {"hit": r.get("hit", "MISS"), "id_hex": r.get("id_hex"), "title": r.get("title"), "body": r.get("body"),
           "s_vec": float(sig.get("s_vec") or 0.0), "s_lex": float(sig.get("s_lex") or 0.0)}
    if out["id_hex"]:
        no = _rodar(["get", out["id_hex"]])
        tr = de_chave((no or {}).get("keywords") or [])
        if tr:
            out["tipo"], out["ref"] = tr
    return out


def recuperar(texto: str, k: int = 12) -> list[dict]:
    """Híbrido (vetor + BM25 título + BM25 corpo, fundidos por RRF): [{'id_hex','title','score','tipo','ref'}]."""
    r = _rodar(["retrieve", (texto or "")[:1000], "--top-k", str(int(k))])
    out = []
    for x in (r or {}).get("results") or []:
        tr = de_chave(x.get("keywords") or [])
        out.append({"id_hex": x.get("id_hex"), "title": x.get("title"), "score": float(x.get("score") or 0.0),
                    "tipo": tr[0] if tr else None, "ref": tr[1] if tr else None})
    return out


def explorar(texto: str, palavras_chave: list[str] | None = None, profundidade: int = 2, feixe: int = 4) -> list[dict]:
    """O entorno no grafo (arestas de palavra-chave e semânticas): nós visitados com a profundidade em que apareceram."""
    args = ["explore", (texto or "")[:1000], "--depth", str(profundidade), "--beam", str(feixe)]
    for kw in palavras_chave or []:
        args += ["--keyword", kw]
    r = _rodar(args)
    out = []
    for x in ((r or {}).get("nodes") or [])[:12]:
        no = _rodar(["get", x.get("id_hex", "")]) or {}           # explore não traz as palavras-chave do nó
        tr = de_chave(no.get("keywords") or [])
        out.append({"id_hex": x.get("id_hex"), "title": x.get("title"), "depth": x.get("depth_reached"), "score": x.get("score"),
                    "tipo": tr[0] if tr else None, "ref": tr[1] if tr else None})
    return out


def estatisticas() -> dict | None:
    return _rodar(["stats"])


def manter(store, agora: float | None = None, a_cada: float = 6 * 3600) -> dict | None:
    """Manutenção bounded: `apply-safe` a cada 6 h e os candidatos que o loop sabe decidir sozinho — par de nós do
    MESMO registro (`circulo:tipo:ref`) é supersessão do mais antigo pelo mais novo. O resto fica para o Médico ver."""
    agora = agora or time.time()
    st = dict(store.get("graft_manutencao") or {})
    if not ligado() or agora - float(st.get("em", 0)) < a_cada:
        return None
    st["em"] = agora
    seguro = _rodar(["maintain", "apply-safe"]) or {}
    scan = _rodar(["maintain", "scan", "--limit", "20", "--no-sources"]) or {}
    resolvidos, pendentes = 0, []
    for c in scan.get("candidates") or []:
        nos = c.get("nodes") or []
        if c.get("kind") in ("near_duplicate", "possible_supersession") and len(nos) == 2:
            a, b = (_rodar(["get", n["id_hex"]]) or {} for n in nos)
            ka, kb = de_chave(a.get("keywords") or []), de_chave(b.get("keywords") or [])
            if ka and ka == kb:
                if _rodar(["maintain", "resolve", c["id"], "--action", "supersede_a", "--actor", "circulo",
                           "--note", "mesmo registro do círculo: o mais novo vale"]):
                    resolvidos += 1
                continue
        pendentes.append({"kind": c.get("kind"), "titulos": [n.get("title", "")[:80] for n in nos][:2]})
    st.update(apply_safe=bool(seguro), resolvidos=resolvidos, pendentes=pendentes[:10], grafo=(seguro.get("graph") or {}))
    store.set("graft_manutencao", st)
    return st


def resumo(store) -> dict:
    """Para o painel: ligado?, perfil, chamadas, última latência, grafo e manutenção. Nunca chama o daemon."""
    m = store.get("graft_manutencao") or {}
    try:
        tot, esp = store.one("SELECT COUNT(*) t, SUM(graft_id IS NOT NULL) e FROM memoria")
    except sqlite3.Error:                    # banco antigo sem a coluna
        tot, esp = 0, 0
    u = store.get("graft_uso") or {}
    return {"ligado": ligado(), "perfil": PERFIL, "chamadas": _estado["chamadas"], "ms": round(_estado["ms"]),
            "espelho": {"nos": int(esp or 0), "lembrancas": int(tot or 0)},
            "uso": u if u.get("dia") == time.strftime("%Y-%m-%d") else {"dia": time.strftime("%Y-%m-%d"), "exemplos": u.get("exemplos", [])},
            "instalar": "dois cliques em ~/Projects/instalar-graft.command (Homebrew, perfil circulo, modelo ~600 MB)",
            "pausado_ate": (_estado["falhou_em"] + PAUSA_APOS_FALHA) if time.time() - _estado["falhou_em"] < PAUSA_APOS_FALHA else None,
            "grafo": m.get("grafo") or {}, "manutencao_em": m.get("em"), "pendentes": m.get("pendentes") or []}


_ID = re.compile(r"^[0-9a-f]{8,64}$")


def id_valido(x) -> bool:
    return isinstance(x, str) and bool(_ID.match(x))

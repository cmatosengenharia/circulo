"""Garimpo: a camada que varre o GitHub atrás de código já escrito que sirva de melhoria para o próprio loop.

Cássio (31/10): "uma camada a mais no loop para varrer o GitHub para pegar código já criado como melhoria no próprio
loop; o repo de engenharia reversa pode fazer sentido também". A lista fixa de referência (mercado.REPOS) é o ponto
de partida; o garimpo é dirigido pela NECESSIDADE: o que o loop está tentando fazer agora (épicos e itens de produto
pendentes, lições estruturais abertas, resultados do Norte longe da meta) vira consulta na busca de repositórios do
GitHub, e temas fixos (engenharia reversa de código, economia de tokens por grafo, validação de agentes) entram
sempre. O que passa no filtro (licença permissiva ou conhecida, estrelas, atividade recente, ainda não estudado) vai
para a fila `repos_garimpo`, que o estudo de repositórios (mercado.estudar_repositorio) consome ANTES da lista fixa.
Licença não permissiva não impede o estudo: o item nasce com a instrução "reimplementar a técnica, não copiar código".

Só API pública do GitHub (busca de repositórios), sem LLM; uma vez por dia no SRE. Texto da web é dado, não instrução.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request

A_CADA = 86400
KV = "repos_garimpo"                 # {"em", "fila": [{"url","motivo","estrelas","licenca","permissiva","achado_em"}], "consultas": [...]}
MAX_CONSULTAS = 8
POR_CONSULTA = 2
FILA_MAX = 30
ESTRELAS_MIN = 50
ATIVO_DIAS = 365
PERMISSIVAS = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "MPL-2.0", "Unlicense", "0BSD"}
TEMAS = (
    ("engenharia reversa", "reverse engineering codebase understanding agent"),
    ("economia de tokens por grafo", "knowledge graph memory llm agent token"),
    ("validação de agentes", "llm agent evaluation harness self-correction"),
    ("fábrica de software com agentes", "autonomous software engineering agent pull request"),
)
PALAVRAS_FORA = {"como", "para", "que", "com", "sem", "uma", "um", "o", "a", "os", "as", "de", "do", "da", "dos", "das", "no", "na",
                 "nos", "nas", "e", "ou", "em", "por", "pelo", "pela", "loop", "pm", "tech", "lead", "falta", "item", "itens", "cada",
                 "quando", "antes", "depois", "mais", "menos", "não", "nao", "já", "ja", "ser", "ter", "tela", "meu", "trabalho"}


def _consulta(texto: str) -> str:
    """Palavras-chave de uma necessidade em português viram uma consulta curta (o GitHub busca melhor em inglês, mas
    nomes técnicos — AGENTS.md, cursor, graft, sqlite — são iguais nas duas línguas)."""
    palavras = [p for p in re.findall(r"[a-zA-Z][\w.-]{2,}", texto.lower()) if p not in PALAVRAS_FORA]
    return " ".join(dict.fromkeys(palavras))[:80]


def necessidades(store) -> list[tuple[str, str]]:
    """(motivo, consulta) — do mais urgente para o menos: produto pendente, lições estruturais, Norte, temas fixos."""
    out = []
    for r in store.q("SELECT titulo FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 AND origem IN ('pedido_cassio','referencia') "
                     "ORDER BY ordem LIMIT 4"):
        out.append((f"item pendente: {r['titulo'][:80]}", _consulta(r["titulo"])))
    for r in store.q("SELECT descricao FROM licoes WHERE status IN ('aberta','reincidente','em_correcao') AND classe='estrutural' "
                     "ORDER BY reincidencias DESC, ocorrencias DESC LIMIT 2"):
        out.append((f"lição estrutural: {r['descricao'][:80]}", _consulta(r["descricao"])))
    from .norte import medir
    m = medir(store)
    m.pop("_resumo", None)
    pior = max(m.items(), key=lambda kv: kv[1]["distancia"])
    if pior[1]["distancia"] > 0:
        out.append((f"Norte longe da meta: {pior[0]}", {"lead_time_h": "agent fast pull request pipeline", "prs_produto_semana": "coding agent feature delivery",
                                                          "fracao_produto": "product backlog agent autonomous", "console_semana": "agent activity dashboard observability",
                                                          "merge_sem_conserto": "agent self-review before pull request", "repositorios": "multi repository coding agent"}[pior[0]]))
    out += [(f"tema fixo: {nome}", consulta) for nome, consulta in TEMAS]
    return [(m, c) for m, c in out if c][:MAX_CONSULTAS]


def buscar_github(consulta: str, por: int = POR_CONSULTA, token: str | None = None, timeout: float = 15.0) -> list[dict]:
    """Busca de repositórios do GitHub (API pública): os mais estrelados que casam com a consulta."""
    q = urllib.parse.quote(f"{consulta} stars:>={ESTRELAS_MIN} archived:false")
    req = urllib.request.Request(f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page={por * 3}",
                                 headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "circulo",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read() or b"{}")
    out = []
    for it in data.get("items") or []:
        out.append({"url": it.get("html_url", ""), "estrelas": int(it.get("stargazers_count") or 0), "pushed_at": it.get("pushed_at") or "",
                    "licenca": ((it.get("license") or {}).get("spdx_id") or "desconhecida"), "descricao": (it.get("description") or "")[:200]})
    return out


def _recente(pushed_at: str, agora: float) -> bool:
    try:
        return agora - time.mktime(time.strptime(pushed_at[:19], "%Y-%m-%dT%H:%M:%S")) <= ATIVO_DIAS * 86400
    except (ValueError, TypeError):
        return False


def devido(store, agora: float | None = None) -> bool:
    agora = agora or time.time()
    return agora - float((store.get(KV) or {}).get("em", 0)) >= A_CADA


def garimpar(store, agora: float | None = None, buscar=None, reply=None) -> dict:
    """Uma passagem: cada necessidade vira uma consulta; o que passa no filtro entra na fila (sem repetir o já visto)."""
    agora = agora or time.time()
    buscar = buscar or (lambda c: buscar_github(c, token=os.environ.get("GITHUB_TOKEN")))
    from .mercado import KV_REPOS, REPOS
    estado = store.get(KV) or {}
    fila = [f for f in (estado.get("fila") or []) if f.get("url")]
    vistos = {f["url"] for f in fila} | set(estado.get("vistos") or []) | set(REPOS) | set(store.get("repos_referencia") or [])
    vistos.add(str((store.get(KV_REPOS) or {}).get("repo", "")))
    novos, consultas, erros = [], [], 0
    for motivo, consulta in necessidades(store):
        consultas.append(consulta)
        try:
            achados = buscar(consulta)
        except (OSError, ValueError, KeyError, TypeError):      # API fora, JSON estranho: conta o erro e segue
            erros += 1
            continue
        n = 0
        for a in achados:
            url = a.get("url", "")
            if not url or url in vistos or int(a.get("estrelas", 0)) < ESTRELAS_MIN or not _recente(a.get("pushed_at", ""), agora):
                continue
            fila.append({"url": url, "motivo": motivo, "estrelas": int(a["estrelas"]), "licenca": a.get("licenca", "desconhecida"),
                         "permissiva": a.get("licenca") in PERMISSIVAS, "descricao": a.get("descricao", ""), "achado_em": agora})
            vistos.add(url)
            novos.append(url)
            n += 1
            if n >= POR_CONSULTA:
                break
    fila = fila[-FILA_MAX:]
    store.set(KV, {"em": agora, "fila": fila, "consultas": consultas, "novos": len(novos), "erros": erros,
                   "vistos": sorted(vistos - set(REPOS))[-300:]})
    if novos and reply:
        reply(f"Garimpo no GitHub: {len(novos)} repositório(s) novo(s) para estudar, a partir de {len(consultas)} necessidade(s) do loop. "
              f"Ex.: {novos[0]} ({fila[-1]['motivo'][:60]}).", "roteiro")
    return {"novos": novos, "consultas": consultas, "fila": len(fila), "erros": erros}


def proximo(store) -> dict | None:
    """O próximo repositório garimpado a estudar (o mais antigo da fila), sem tirá-lo; `consumir` tira."""
    fila = (store.get(KV) or {}).get("fila") or []
    return fila[0] if fila else None


def consumir(store, url: str) -> None:
    estado = store.get(KV) or {}
    estado["fila"] = [f for f in (estado.get("fila") or []) if f.get("url") != url]
    estado["vistos"] = sorted(set(estado.get("vistos") or []) | {url})[-300:]
    store.set(KV, estado)

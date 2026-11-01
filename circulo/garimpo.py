"""Garimpo: a camada que varre o GitHub atrás de código já escrito que sirva de melhoria para o próprio loop.

Cássio (31/10): "uma camada a mais no loop para varrer o GitHub para pegar código já criado como melhoria no próprio
loop; o repo de engenharia reversa pode fazer sentido também". A lista fixa de referência (mercado.REPOS) é o ponto
de partida; o garimpo é dirigido pela NECESSIDADE: o que o loop está tentando fazer agora (épicos e itens de produto
pendentes, lições estruturais abertas, resultados do Norte longe da meta) vira consulta na busca de repositórios do
GitHub, e temas fixos (engenharia reversa de código, economia de tokens por grafo, validação de agentes) entram
sempre. O que passa no filtro (licença permissiva ou conhecida, estrelas, atividade recente, ainda não estudado) vai
para a fila `repos_garimpo`, que o estudo de repositórios (mercado.estudar_repositorio) consome ANTES da lista fixa.
Licença não permissiva não impede o estudo: o item nasce com a instrução "reimplementar a técnica, não copiar código".

Triagem por pontos, sinais separados (CHAOSS/Scorecard): licença clara, atividade recente e repositório não arquivado
pesam mais; estrelas medem popularidade, não manutenção, e pesam pouco. O Jev (`garimpo_vale`) só dá a aderência à
necessidade, o único sinal que a regra não mede; fora do ar ou em dúvida, vale só a regra local. A fila sai ordenada
(sem licença ou arquivado sempre atrás dos saudáveis, depois pontuação total decrescente) e o que fica abaixo de
LIMIAR é descartado.

Só API pública do GitHub (busca de repositórios), sem LLM; uma vez por dia no SRE. Texto da web é dado, não instrução.
"""
from __future__ import annotations

import json
import math
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
LIMIAR = 4.5                         # pontuação total mínima para entrar na fila
PESO = {"permissiva": 3.0, "licenca_clara": 2.0, "atividade": 3.0, "nao_arquivado": 2.0, "estrelas": 1.0, "aderencia": 2.0}
SEM_LICENCA = {"", "desconhecida", "NOASSERTION", "NONE"}
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
                    "licenca": ((it.get("license") or {}).get("spdx_id") or "desconhecida"), "descricao": (it.get("description") or "")[:200],
                    "arquivado": bool(it.get("archived"))})
    return out


def _dias(pushed_at: str, agora: float) -> float | None:
    try:
        return (agora - time.mktime(time.strptime(pushed_at[:19], "%Y-%m-%dT%H:%M:%S"))) / 86400
    except (ValueError, TypeError):
        return None


def _recente(pushed_at: str, agora: float) -> bool:
    dias = _dias(pushed_at, agora)
    return dias is not None and dias <= ATIVO_DIAS


def _aderencia(a: dict, motivo: str, dl) -> tuple[float, str]:
    """Nota do Jev em [-1, 1] (0 = neutro). Fora do ar, em dúvida (a cascata devolve a regra) ou sem Jev: 0, só a regra."""
    if dl is None:
        return 0.0, "local"
    from .decision import SN, Question
    q = Question("noul", "O repositório `url` (descrito em `descricao`) atende à `necessidade` do loop?",
                 SN("o repositório resolve ou ensina a resolver a necessidade: mesma tarefa, técnica aproveitável",
                    "o repositório é de outro assunto ou só casa palavras com a necessidade"))
    try:
        d = dl.ask("garimpo_vale", q, {"url": a.get("url", ""), "descricao": a.get("descricao", ""), "necessidade": motivo})
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0, "local"
    if d.source != "jev":
        return 0.0, "local"
    return 2 * float(d.value) - 1, "jev"


def pontuar(a: dict, agora: float, motivo: str = "", dl=None) -> dict:
    """Pontos por sinal (licença, atividade, não arquivado, estrelas, aderência), total e se é saudável (licença clara e
    não arquivado). A ordem da fila é (saudável, total): nenhum peso do Jev põe um sem licença ou arquivado na frente."""
    licenca = str(a.get("licenca") or "desconhecida")
    clara = licenca not in SEM_LICENCA
    dias = _dias(a.get("pushed_at", ""), agora)
    arquivado = bool(a.get("arquivado"))
    nota, fonte = _aderencia(a, motivo, dl)
    pontos = {"licenca": PESO["permissiva"] if licenca in PERMISSIVAS else PESO["licenca_clara"] if clara else 0.0,
              "atividade": PESO["atividade"] * max(0.0, 1 - dias / ATIVO_DIAS) if dias is not None else 0.0,
              "nao_arquivado": 0.0 if arquivado else PESO["nao_arquivado"],
              "estrelas": PESO["estrelas"] * min(1.0, math.log10(max(1, int(a.get("estrelas") or 0))) / 5),
              "aderencia": PESO["aderencia"] * nota}
    pontos = {k: round(v, 3) for k, v in pontos.items()}
    return {"pontos": pontos, "total": round(sum(pontos.values()), 3), "saudavel": clara and not arquivado, "aderencia_fonte": fonte}


def _ordem(f: dict) -> tuple:
    return (not f.get("saudavel", True), -float(f.get("total", LIMIAR)), f.get("url", ""))


def devido(store, agora: float | None = None) -> bool:
    agora = agora or time.time()
    return agora - float((store.get(KV) or {}).get("em", 0)) >= A_CADA


def garimpar(store, agora: float | None = None, buscar=None, reply=None, dl=None) -> dict:
    """Uma passagem: cada necessidade vira uma consulta; o que passa no filtro e no LIMIAR entra na fila (sem repetir o
    já visto), os POR_CONSULTA melhores de cada consulta; a fila fica ordenada pela triagem."""
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
        candidatos = {}
        for a in achados:
            url = a.get("url", "")
            if not url or url in vistos or url in candidatos or int(a.get("estrelas", 0)) < ESTRELAS_MIN or not _recente(a.get("pushed_at", ""), agora):
                continue
            t = pontuar(a, agora, motivo, dl)
            if t["total"] < LIMIAR:
                continue
            candidatos[url] = {"url": url, "motivo": motivo, "estrelas": int(a["estrelas"]), "licenca": a.get("licenca", "desconhecida"),
                               "permissiva": a.get("licenca") in PERMISSIVAS, "arquivado": bool(a.get("arquivado")),
                               "descricao": a.get("descricao", ""), "achado_em": agora, **t}
        for c in sorted(candidatos.values(), key=_ordem)[:POR_CONSULTA]:
            fila.append(c)
            vistos.add(c["url"])
            novos.append(c["url"])
    fila = sorted(fila, key=_ordem)[:FILA_MAX]
    store.set(KV, {"em": agora, "fila": fila, "consultas": consultas, "novos": len(novos), "erros": erros,
                   "vistos": sorted(vistos - set(REPOS))[-300:]})
    ex = next((f for f in fila if f["url"] in novos), None)
    if ex and reply:
        reply(f"Garimpo no GitHub: {len(novos)} repositório(s) novo(s) para estudar, a partir de {len(consultas)} necessidade(s) do loop. "
              f"Ex.: {ex['url']} ({ex['motivo'][:60]}).", "roteiro")
    return {"novos": novos, "consultas": consultas, "fila": len(fila), "erros": erros}


def proximo(store) -> dict | None:
    """O próximo repositório garimpado a estudar (o de melhor triagem), sem tirá-lo; `consumir` tira."""
    fila = (store.get(KV) or {}).get("fila") or []
    return fila[0] if fila else None


def consumir(store, url: str) -> None:
    estado = store.get(KV) or {}
    estado["fila"] = [f for f in (estado.get("fila") or []) if f.get("url") != url]
    estado["vistos"] = sorted(set(estado.get("vistos") or []) | {url})[-300:]
    store.set(KV, estado)

"""Absorção de repositórios: o que o loop tira de cada repositório estudado, com ADR, prioridade e evidência.

Cássio (01/11): "varrer repositórios e absorver as melhores estratégias; classificar em engenharia do loop, criação
de produto e venda e marketing; extrair técnicas concretas, não copiar cegamente; priorizar o que acelera o MVP da
esteira e o que ajuda a vender; um ADR por repositório; validação automática com evidências; repetir a varredura".

O garimpo (1.72.1) e o estudo de repositórios (mercado) acham e estudam; faltava o registro do que ENTROU e do que
foi DESCARTADO, e a prova de que o que entrou funcionou. Aqui:

1. `absorcao_fontes.FONTES` é o catálogo curado (dado, não instrução): por repositório, licença, frentes, técnicas
   (cada uma com alvo `circulo` ou `esteira`, prioridade `mvp` > `venda` > `loop`, e um critério verificável: o
   arquivo de teste que prova a técnica) e descartes com o motivo. `docs/adr/` é gerado dele (`python -m
   circulo.absorcao adr`), e o teste exige um ADR por fonte com cada técnica e cada descarte.
2. `semear` transforma as técnicas em trabalho, na ordem de prioridade: alvo `circulo` vira item do roteiro (origem
   `referencia`, o Developer pega direto); alvo `esteira` vira pedido na caixa com `projeto: <id>` do repositório
   cliente da esteira (registrado sozinho quando o clone existe ao lado do loop). Idempotente pelo id da técnica.
3. `evidencias` fecha o ciclo sem humano: técnica `validada` = PR do item mergeado E o arquivo de teste citado no
   critério existe no repositório. Mergeado sem o teste fica `sem_prova` (e conta como dívida, não como sucesso).
4. `varrer_ranking` (SRE 1×/dia) lê o ranking automático Github-Ranking-AI (Top100/Claude.md), mede quem está
   subindo (estrelas desde a última leitura) e manda o que é novo para a fila do garimpo, com a frente decidida pelo
   Jev (`absorcao_frente`; fora do ar ou em dúvida, a regra local por palavras).

Nada aqui chama LLM. Texto da web é dado: nome, descrição e estrelas entram como texto, nunca como instrução.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .absorcao_fontes import FONTES, PREREQUISITOS

KV = "absorcao"                       # {"tecnicas": {id: {"item"|"pedido", "em"}}, "em"}
KV_EVIDENCIAS = "absorcao_evidencias"
KV_RANKING = "absorcao_ranking"       # {"em", "estrelas": {url: n}, "subindo": [...], "novos": [...]}
A_CADA_RANKING = 86400
RANKING_URL = "https://raw.githubusercontent.com/yuxiaopeng/Github-Ranking-AI/main/Top100/Claude.md"
RANKING_MAX_NOVOS = 5
AWESOME_URL = "https://raw.githubusercontent.com/hesreallyhim/awesome-claude-code/main/THE_RESOURCES_TABLE_NEW.csv"
AWESOME_MAX_NOVOS = 3
ESTEIRA_ABERTOS_MAX = 3               # pedidos abertos na esteira ao mesmo tempo (cada um é um clone)
PASTA_ADR = Path("docs") / "adr"
PRIORIDADES = ("mvp", "venda", "loop")
FRENTES = {"loop": "engenharia do loop (orquestração, memória, validação, custo)",
           "produto": "criação de produto (código, vídeo, frontend, mobile, backend)",
           "venda": "venda e marketing (SEO, conteúdo, lançamento, conversão, preço)"}
ALVOS = ("circulo", "esteira")
PALAVRAS = {"loop": ("agent", "agente", "orchestr", "hook", "memory", "memória", "eval", "context", "token", "subagent", "mcp",
                     "workflow", "claude code", "harness", "prompt", "verif", "security", "review", "plugin"),
            "produto": ("video", "vídeo", "remotion", "ffmpeg", "frontend", "react", "expo", "mobile", "supabase", "postgres",
                        "backend", "api", "ui", "design", "render", "caption", "clip", "whisper", "app"),
            "venda": ("seo", "marketing", "growth", "copy", "landing", "sales", "venda", "pricing", "preço", "launch",
                      "lançamento", "conversion", "conversão", "ads", "social", "brand", "content", "conteúdo", "newsletter")}


# ------------------------------------------------------------------ catálogo
def tecnicas() -> list[dict]:
    """Todas as técnicas (as das fontes e os pré-requisitos), com a fonte, na ordem de prioridade mvp > venda > loop."""
    out = [{**t, "fonte": "pre-requisito", "repo": ""} for t in PREREQUISITOS]
    out += [{**t, "fonte": f["slug"], "repo": f["repo"]} for f in FONTES for t in f["tecnicas"]]
    return sorted(out, key=lambda t: (PRIORIDADES.index(t["prio"]), t["fonte"] != "pre-requisito", t["id"]))


def fonte(slug: str) -> dict | None:
    return next((f for f in FONTES if f["slug"] == slug), None)


def adr_caminho(f: dict) -> Path:
    return PASTA_ADR / f"{f['adr']:04d}-absorcao-{f['slug']}.md"


def adr_texto(f: dict) -> str:
    """O ADR de uma fonte: contexto, o que entrou (técnica, alvo, prioridade, prova) e o que foi descartado, e por quê."""
    linhas = [f"# ADR {f['adr']:04d} — Absorção: {f['nome']}", "",
              f"- Status: aceito ({f['data']})", f"- Fonte: {f['repo']}", f"- Licença: {f['licenca']}",
              f"- Frentes: {', '.join(FRENTES[x].split(' (')[0] for x in f['frentes'])}", "",
              "## Contexto", "", f["contexto"], "", "## Decisão — o que entrou", ""]
    for t in f["tecnicas"]:
        linhas += [f"### {t['id']} — {t['titulo']}", "",
                   f"- Frente: {FRENTES[t['frente']].split(' (')[0]} · alvo: `{t['alvo']}` · prioridade: `{t['prio']}`",
                   f"- Como está na fonte: {t['origem']}", f"- Como entra: {t['detalhe']}", f"- Prova (validação automática): `{t['prova']}`", ""]
    linhas += ["## Descartado", ""]
    linhas += [f"- **{d['o_que']}** — {d['por_que']}" for d in f["descartes"]]
    linhas += ["", "## Consequências", "", f["consequencias"], "",
               "Validação: `circulo.absorcao.evidencias` marca cada técnica como `validada` só quando o PR do item foi mergeado "
               "e o arquivo da prova existe no repositório; o estado fica no kv `absorcao_evidencias` e no painel.", ""]
    return "\n".join(linhas)


def escrever_adrs(raiz: Path | str) -> list[Path]:
    """Gera (ou reescreve) os ADRs de todas as fontes em `docs/adr/` e o índice."""
    raiz = Path(raiz)
    (raiz / PASTA_ADR).mkdir(parents=True, exist_ok=True)
    feitos = []
    for f in FONTES:
        p = raiz / adr_caminho(f)
        p.write_text(adr_texto(f), encoding="utf-8")
        feitos.append(p)
    indice = ["# ADRs de absorção de repositórios", "", "Gerados de `circulo/absorcao_fontes.py` por `python -m circulo.absorcao adr`.", "",
              "| ADR | Fonte | Frentes | Técnicas | Descartes |", "|---|---|---|---|---|"]
    for f in FONTES:
        indice.append(f"| [{f['adr']:04d}]({adr_caminho(f).name}) | {f['nome']} | {', '.join(f['frentes'])} | {len(f['tecnicas'])} | {len(f['descartes'])} |")
    (raiz / PASTA_ADR / "README.md").write_text("\n".join(indice) + "\n", encoding="utf-8")
    return feitos


# ------------------------------------------------------------------ classificação (Jev first, regra local)
def regra_frente(texto: str) -> str:
    """Frente pela contagem de palavras-chave; empate ou nada: `loop` (o padrão do garimpo)."""
    t = texto.lower()
    pontos = {k: sum(1 for p in ps if p in t) for k, ps in PALAVRAS.items()}
    melhor = max(pontos.values())
    if melhor == 0:
        return "loop"
    return next(k for k in ("venda", "produto", "loop") if pontos[k] == melhor)


def classificar(texto: str, dl=None) -> tuple[str, str]:
    """(frente, fonte da decisão). O Jev escolhe; fora do ar, em dúvida (confiança < 0,3) ou sem Jev, a regra local."""
    if dl is not None:
        from .decision import Question
        q = Question("choice", "Which front of a self-improving software factory does this GitHub repository (`repositorio`) help most?",
                     dict(FRENTES))
        try:
            d = dl.ask("absorcao_frente", q, {"repositorio": texto[:600]})
        except (OSError, ValueError, KeyError, TypeError):
            d = None
        if d is not None and d.source == "jev" and d.value in FRENTES and float(d.confidence) >= 0.3:
            return str(d.value), "jev"
    return regra_frente(texto), "local"


# ------------------------------------------------------------------ semeadura
def esteira_projeto(store) -> int | None:
    """O id do repositório cliente da esteira, se registrado."""
    from . import repo_cliente
    for r in repo_cliente.repos(store):
        if re.search(r"(?i)[/:]cmatosengenharia/esteira(\.git)?$", r["remoto"]):
            return int(r["id"])
    return None


def registrar_esteira(store, repo_dir: str | None) -> int | None:
    """Registra a esteira como repositório cliente quando o clone existe (CIRCULO_ESTEIRA_DIR ou ao lado do loop)."""
    pid = esteira_projeto(store)
    if pid is not None:
        return pid
    candidatos = [os.environ.get("CIRCULO_ESTEIRA_DIR", "")] + ([str(Path(repo_dir).resolve().parent / "esteira")] if repo_dir else [])
    for c in filter(None, candidatos):
        if not (Path(c) / ".git").exists():
            continue
        try:
            remoto = subprocess.run(["git", "remote", "get-url", "origin"], cwd=c, capture_output=True, text=True, timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        if re.search(r"(?i)cmatosengenharia/esteira", remoto):
            from . import repo_cliente
            try:
                return int(repo_cliente.registrar(store, c, nome="esteira")["id"])
            except (OSError, ValueError, subprocess.SubprocessError):
                return None
    return None


def _texto_pedido(t: dict) -> str:
    return (f"{t['titulo']}\n\nTécnica absorvida de {t['repo'] or 'pré-requisito da absorção'} (ADR em docs/adr do círculo).\n"
            f"Como está na fonte: {t['origem']}\nComo entra: {t['detalhe']}\n"
            f"Prova exigida: {t['prova']} (teste novo, verde na CI). Respeite CLAUDE.md: portar, não copiar; licença em THIRD_PARTY_NOTICES.md.")


def semear(store, agora: float | None = None, data_dir: str | Path | None = None, repo_dir: str | None = None) -> dict:
    """Técnicas ainda não semeadas viram trabalho, na ordem de prioridade. Esteira sem registro: fica para a próxima."""
    agora = agora or time.time()
    estado = store.get(KV) or {}
    feitas = dict(estado.get("tecnicas") or {})
    pid = registrar_esteira(store, repo_dir) if data_dir else esteira_projeto(store)
    itens, pedidos, aguardando = [], [], []
    vagas = 0
    if pid is not None:
        from . import repo_cliente
        vagas = ESTEIRA_ABERTOS_MAX - sum(1 for p in repo_cliente.pedidos(store, pid) if p["status"] == "aberto")
    for t in tecnicas():
        if t["id"] in feitas or t.get("entregue"):
            continue
        if t["alvo"] == "esteira":
            if pid is None or data_dir is None or vagas <= 0:
                aguardando.append(t["id"])
                continue
            vagas -= 1
            caixa = Path(data_dir) / "caixa"
            caixa.mkdir(parents=True, exist_ok=True)
            nome = caixa / f"absorcao-{t['id'].lower()}.md"
            nome.write_text(f"---\nprojeto: {pid}\nde: absorcao\n---\n{_texto_pedido(t)}\n", encoding="utf-8")
            feitas[t["id"]] = {"pedido": nome.name, "em": agora}
            pedidos.append(t["id"])
            continue
        ordem = (store.one("SELECT COALESCE(MAX(ordem),0) m FROM roadmap")["m"] or 0) + 1
        iid = store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                      (t["titulo"][:160], _texto_pedido(t)[:4000], "referencia", "pendente", f"absorção {t['id']}: {t['repo'] or 'pré-requisito'}",
                       ordem, f"absorção 01/11 (ADR da fonte {t['fonte']}); prioridade {t['prio']}", agora, agora))
        feitas[t["id"]] = {"item": iid, "em": agora}
        itens.append(iid)
    store.set(KV, {"tecnicas": feitas, "em": agora, "aguardando_esteira": aguardando})
    return {"itens": itens, "pedidos": pedidos, "aguardando_esteira": aguardando}


# ------------------------------------------------------------------ evidência
def _prova_existe(t: dict, repo_dir) -> bool:
    return bool(repo_dir) and (Path(repo_dir) / str(t["prova"]).split("::", 1)[0]).exists()


def _estado_item(store, t: dict, item_id: int, repo_dir) -> tuple[str, int | None]:
    item = store.one("SELECT status FROM roadmap WHERE id=?", (item_id,))
    pr_row = store.one("SELECT number, status FROM prs WHERE item_id=? ORDER BY number DESC LIMIT 1", (item_id,))
    pr = int(pr_row["number"]) if pr_row else None
    if pr_row and pr_row["status"] == "mergeado":
        return ("validada" if _prova_existe(t, repo_dir) else "sem_prova"), pr
    if item and item["status"] == "descartado":
        return "descartada", pr
    return ("em_andamento" if pr_row else "pendente"), pr


def _estado_pedido(store, t: dict) -> str:
    """Pedido na esteira: entregue com todas as etapas verdes = validada (o teste da prova roda na CI do cliente)."""
    from . import repo_cliente
    pid = esteira_projeto(store)
    if pid is None:
        return "pedido_na_esteira"
    p = next((x for x in repo_cliente.pedidos(store, pid) if str(x["texto"]).startswith(t["titulo"])), None)
    if p is None:
        return "pedido_na_esteira"
    if p["status"] == "entregue":
        etapas = repo_cliente.evidencias(store, p["id"])
        return "validada" if etapas and all(e["ok"] for e in etapas) else "sem_prova"
    return "vermelho" if p["status"] == "vermelho" else "em_andamento"


def evidencias(store, repo_dir: str | Path | None = None, agora: float | None = None) -> dict:
    """Estado de cada técnica: pendente → em_andamento → sem_prova | validada; e o resumo por fonte. Grava no kv.
    Validada exige a prova: no loop, PR mergeado E o arquivo de teste no repositório; na esteira, pedido entregue com
    as etapas verdes. Entregue nesta versão (`entregue`) vale só se o arquivo da prova existe."""
    agora = agora or time.time()
    feitas = (store.get(KV) or {}).get("tecnicas") or {}
    por_tecnica, por_fonte = {}, {}
    for t in tecnicas():
        reg = feitas.get(t["id"]) or {}
        pr = None
        if t.get("entregue"):
            estado = "validada" if _prova_existe(t, repo_dir) else "sem_prova"
        elif reg.get("item"):
            estado, pr = _estado_item(store, t, reg["item"], repo_dir)
        elif reg.get("pedido"):
            estado = _estado_pedido(store, t)
        else:
            estado = "aguardando_esteira" if t["alvo"] == "esteira" else "nao_semeada"
        por_tecnica[t["id"]] = {"estado": estado, "pr": pr, "fonte": t["fonte"], "prio": t["prio"], "alvo": t["alvo"]}
        c = por_fonte.setdefault(t["fonte"], {})
        c[estado] = c.get(estado, 0) + 1
    res = {"em": agora, "tecnicas": por_tecnica, "fontes": por_fonte,
           "validadas": sum(1 for v in por_tecnica.values() if v["estado"] == "validada"),
           "sem_prova": sorted(k for k, v in por_tecnica.items() if v["estado"] == "sem_prova")}
    store.set(KV_EVIDENCIAS, res)
    return res


# ------------------------------------------------------------------ ranking periódico
_LINK = re.compile(r"\[([^\]]+)\]\((https://github\.com/[^)\s]+)\)")


def parse_ranking(md: str) -> list[dict]:
    """Linhas da tabela do Github-Ranking-AI: | Ranking | Project Name | Stars | Forks | Language | Open Issues | Description | Last Commit |.
    Âncoras: as 6 primeiras células e a última; a descrição é o meio (pode conter `|`)."""
    out = []
    for linha in md.splitlines():
        cel = [c.strip() for c in linha.strip().strip("|").split("|")]
        if len(cel) < 8 or not cel[0].isdigit():
            continue
        m = _LINK.search(cel[1])
        if not m or not cel[2].replace(",", "").isdigit():
            continue
        out.append({"posicao": int(cel[0]), "nome": m.group(1).strip(), "url": m.group(2).rstrip("/"),
                    "estrelas": int(cel[2].replace(",", "")), "linguagem": "" if cel[4] == "None" else cel[4],
                    "descricao": " | ".join(cel[6:-1]).strip()[:300], "ultimo_commit": cel[-1]})
    return out


CATEGORIAS_AWESOME = ("orchestration", "skills", "memory", "security", "creative", "testing", "hooks", "observability", "design")


def parse_awesome(csv_texto: str) -> list[dict]:
    """Recursos do CSV do awesome-claude-code: ativos, não obsoletos, com link do GitHub (só nome, link e descrição curta)."""
    import csv
    import io
    out = []
    for r in csv.DictReader(io.StringIO(csv_texto)):
        link = str(r.get("Link") or "").strip().rstrip("/")
        if not re.match(r"^https://github\.com/[^/]+/[^/]+$", link):
            continue
        if str(r.get("Active", "")).upper() != "TRUE" or str(r.get("Stale", "")).upper() == "TRUE":
            continue
        cat = f"{r.get('Category', '')} {r.get('Sub-Category', '')}".strip()
        out.append({"nome": str(r.get("Display Name", "")).strip()[:80], "url": link, "categoria": cat[:80],
                    "descricao": str(r.get("Description", "")).strip()[:300],
                    "util": any(c in cat.lower() for c in CATEGORIAS_AWESOME)})
    return out


def baixar_ranking(url: str = RANKING_URL, timeout: float = 20.0) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "circulo"}), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def ranking_devido(store, agora: float | None = None) -> bool:
    agora = agora or time.time()
    return agora - float((store.get(KV_RANKING) or {}).get("em", 0)) >= A_CADA_RANKING


def _conhecidos(store) -> set[str]:
    from . import garimpo, mercado
    g = store.get(garimpo.KV) or {}
    return ({u.rstrip("/").lower() for f in FONTES for u in (f["repo"], *f.get("aliases", ()))} | {u.lower() for u in mercado.repos(store)}
            | {str(u).lower() for u in g.get("vistos") or []} | {str(f.get("url", "")).lower() for f in g.get("fila") or []})


def _para_garimpo(store, achados: list[dict], agora: float) -> None:
    """Achados do ranking e da lista entram na fila do garimpo, que o estudo de repositórios consome antes da lista fixa."""
    from . import garimpo
    g = store.get(garimpo.KV) or {}
    fila = list(g.get("fila") or []) + achados
    store.set(garimpo.KV, {**g, "fila": sorted(fila, key=garimpo._ordem)[:garimpo.FILA_MAX]})


def _achado(url: str, motivo: str, estrelas: int, descricao: str, frente: str, origem: str, agora: float) -> dict:
    from . import garimpo
    return {"url": url, "motivo": motivo, "estrelas": estrelas, "licenca": "desconhecida", "permissiva": False, "arquivado": False,
            "descricao": descricao, "achado_em": agora, "frente": frente, "frente_fonte": origem, "saudavel": True,
            "total": round(garimpo.LIMIAR + min(3.0, estrelas / 10_000), 3)}


def varrer_ranking(store, agora: float | None = None, baixar=None, dl=None, reply=None, baixar_lista=None) -> dict:
    """Uma leitura do ranking (quem subiu mais desde a última; os desconhecidos vão para o garimpo) e da lista curada."""
    agora = agora or time.time()
    estado = store.get(KV_RANKING) or {}
    antes = dict(estado.get("estrelas") or {})
    erros = []
    linhas, lista = [], []
    try:
        linhas = parse_ranking((baixar or baixar_ranking)())
    except (OSError, ValueError) as exc:
        erros.append(f"ranking: {exc}"[:200])
    try:
        lista = parse_awesome((baixar_lista or (lambda: baixar_ranking(AWESOME_URL)))())
    except (OSError, ValueError) as exc:
        erros.append(f"lista: {exc}"[:200])
    subindo = sorted(({"url": r["url"], "ganho": r["estrelas"] - int(antes[r["url"]])} for r in linhas if r["url"] in antes),
                     key=lambda x: -x["ganho"])[:10]
    ganho = {x["url"]: x["ganho"] for x in subindo}
    conhecidos = _conhecidos(store)
    novos, achados = [], []
    for r in sorted((r for r in linhas if r["url"].lower() not in conhecidos), key=lambda r: (-ganho.get(r["url"], 0), r["posicao"]))[:RANKING_MAX_NOVOS]:
        frente, origem = classificar(f"{r['nome']}: {r['descricao']}", dl)
        achados.append(_achado(r["url"], f"em alta no ranking Claude (#{r['posicao']}, frente {frente})", r["estrelas"], r["descricao"], frente, origem, agora))
        novos.append({"url": r["url"], "frente": frente, "de": "ranking"})
        conhecidos.add(r["url"].lower())
    for r in sorted((r for r in lista if r["url"].lower() not in conhecidos), key=lambda r: not r["util"])[:AWESOME_MAX_NOVOS]:
        frente, origem = classificar(f"{r['nome']} ({r['categoria']}): {r['descricao']}", dl)
        achados.append(_achado(r["url"], f"lista awesome-claude-code ({r['categoria'] or 'sem categoria'}, frente {frente})", 0, r["descricao"], frente, origem, agora))
        novos.append({"url": r["url"], "frente": frente, "de": "lista"})
        conhecidos.add(r["url"].lower())
    if achados:
        _para_garimpo(store, achados, agora)
    store.set(KV_RANKING, {"em": agora, "estrelas": {r["url"]: r["estrelas"] for r in linhas} or antes, "subindo": subindo,
                           "novos": novos, "erro": "; ".join(erros) or None, "lidos": {"ranking": len(linhas), "lista": len(lista)}})
    if novos and reply:
        reply(f"Varredura do ranking Claude e da lista curada: {len(novos)} repositório(s) novo(s) foram para o garimpo "
              f"(ex.: {novos[0]['url'].split('github.com/')[-1]}, frente {novos[0]['frente']}).", "roteiro")
    return {"novos": novos, "subindo": subindo, "erro": "; ".join(erros) or None}


def rodar(store, agora: float | None = None, data_dir=None, repo_dir=None, dl=None, reply=None) -> dict:
    """Passagem do SRE: audita o .claude/ (escudo), semeia o que falta, mede as evidências e, 1×/dia, lê o ranking."""
    agora = agora or time.time()
    from . import escudo
    escudo.rodar(store, repo_dir, reply, agora)
    out = {"semeadura": semear(store, agora, data_dir, repo_dir), "evidencias": evidencias(store, repo_dir, agora)["validadas"]}
    if ranking_devido(store, agora):
        out["ranking"] = varrer_ranking(store, agora, dl=dl, reply=reply)
    return out


def resumo(store) -> dict:
    ev = store.get(KV_EVIDENCIAS) or {}
    return {"fontes": [{"slug": f["slug"], "nome": f["nome"], "adr": adr_caminho(f).as_posix(), "frentes": f["frentes"],
                        "tecnicas": len(f["tecnicas"]), "descartes": len(f["descartes"]), "estados": (ev.get("fontes") or {}).get(f["slug"], {})}
                       for f in FONTES],
            "validadas": ev.get("validadas", 0), "sem_prova": ev.get("sem_prova", []), "ranking": store.get(KV_RANKING) or {}}


if __name__ == "__main__":                       # python -m circulo.absorcao adr [raiz]
    if sys.argv[1:2] == ["adr"]:
        for p in escrever_adrs(sys.argv[2] if len(sys.argv) > 2 else "."):
            print(p)

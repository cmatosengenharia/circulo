"""O Redator técnico: documentação profissional do loop, gerada do que o loop é e do que ele fez, publicada por PR.

Toda documentação aqui é **derivada de fontes medidas** — o código (docstrings de módulo, perguntas ao Jev lidas por
ast, telas e APIs do mapa de verificação, nomes dos agentes), o banco (PRs mergeados, itens, lições, perguntas) e
o CHANGELOG — nunca inventada. O que precisa de julgamento vai ao Jev: classificar cada entrega do loop num tipo
(funcionalidade, correção, velocidade, observabilidade, segurança, documentação) e dizer se ela muda o que o humano
vê (merece nota no guia). A LLM não é usada: texto gerado de dado é mais fiel e custa zero.

Entrega: pasta `docs/` no repositório, por PR na branch `circulo/docs-<momento>`. O gate aceita PR de documentação só
se TODOS os arquivos estão em `docs/` (nada de código entra por essa porta) e o CI está verde; sem GitHub, escreve a
pasta no clone local. Roda quando há entregas novas (PRs mergeados desde a última doc), versão nova, ou 24 h.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from . import nomes
from .state import Store

KV = "documentador"
A_CADA = 24 * 3600
MERGES_PARA_RODAR = 1
BRANCH_PREFIX = "circulo/docs-"
TIPOS = {"funcionalidade": "o loop passa a fazer algo que não fazia (agente, tela, caminho novo)",
         "correcao": "conserta um erro, uma lição ou um comportamento errado que já existia",
         "velocidade": "o loop faz o mesmo em menos tempo, menos giros ou menos tokens",
         "observabilidade": "mede, registra ou mostra algo que antes era invisível (painel, trilha, métrica)",
         "seguranca": "portão, limite, constituição, orçamento ou proteção contra um risco",
         "documentacao": "só texto: README, CHANGELOG, docs"}
AUTOR = ("Círculo", "circulo@localhost")


# ------------------------------------------------------------------ fontes
def _docstring(caminho: Path) -> str:
    try:
        mod = ast.parse(caminho.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return ""
    d = ast.get_docstring(mod) or ""
    return d.strip().split("\n\n")[0].replace("\n", " ").strip()


def modulos(pasta: Path) -> list[dict]:
    out = []
    for p in sorted(pasta.glob("*.py")):
        if p.name.startswith("_"):
            continue
        out.append({"nome": p.stem, "resumo": _docstring(p), "linhas": len(p.read_text(encoding="utf-8").splitlines())})
    return out


def _changelog(repo: Path, maximo: int = 40) -> list[dict]:
    t = (repo / "CHANGELOG.md").read_text(encoding="utf-8") if (repo / "CHANGELOG.md").exists() else ""
    out = []
    for m in re.finditer(r"^## (\S+) — (\S+)\n\n(.*?)(?=^## |\Z)", t, flags=re.S | re.M):
        corpo = m.group(3).strip()
        destaque = re.search(r"\*\*(.+?)\*\*", corpo)
        out.append({"versao": m.group(1), "data": m.group(2), "destaque": (destaque.group(1) if destaque else corpo.split("\n")[0])[:220],
                    "itens": len(re.findall(r"^- ", corpo, flags=re.M))})
        if len(out) >= maximo:
            break
    return out


def entregas(store: Store, desde: float = 0.0, limite: int = 200) -> list[dict]:
    """PRs do loop que entraram na main, com a linhagem pergunta → item → PR quando existe."""
    if not store.one("SELECT 1 FROM sqlite_master WHERE name='prs'"):
        return []
    rows = store.q("SELECT p.number, p.titulo, p.item_id, p.updated_at, p.arquivos, r.origem, r.evidencia, r.titulo item_titulo, "
                   "(SELECT q.texto FROM perguntas q WHERE q.item_id=p.item_id ORDER BY q.id LIMIT 1) pergunta, "
                   "(SELECT q.persona FROM perguntas q WHERE q.item_id=p.item_id ORDER BY q.id LIMIT 1) persona "
                   "FROM prs p LEFT JOIN roadmap r ON r.id=p.item_id WHERE p.status='mergeado' AND p.updated_at>? ORDER BY p.number DESC LIMIT ?", (desde, limite))
    out = []
    for r in rows:
        arqs = json.loads(r["arquivos"]) if r["arquivos"] else []
        out.append({"pr": r["number"], "titulo": r["titulo"] or "", "item": r["item_id"], "em": float(r["updated_at"] or 0), "arquivos": arqs,
                    "origem": r["origem"], "pergunta": r["pergunta"], "persona": r["persona"]})
    return out


# ------------------------------------------------------------------ o Jev classifica cada entrega (uma vez)
def classificar(ctx, lista: list[dict]) -> dict[int, dict]:
    """{pr: {"tipo", "conf", "visivel", "fonte"}} — cache em kv; só o que ainda não foi classificado vai ao Jev."""
    s = ctx.store
    cache = dict(s.get("documentador_tipos") or {})
    novos = [e for e in lista if str(e["pr"]) not in cache]
    if novos:
        from .decision import SN, Question
        qs, estado = {}, {"entregas": []}
        for i, e in enumerate(novos[:24]):
            estado["entregas"].append({"titulo": e["titulo"], "arquivos": [a.split("/")[-1] for a in e["arquivos"][:8]], "origem": e["origem"] or ""})
            qs[f"doc_tipo_{i}"] = Question("choice", f"What kind of change is delivery `entregas.{i}.titulo` (files `entregas.{i}.arquivos`)?", dict(TIPOS))
            qs[f"doc_visivel_{i}"] = Question("noul", f"Delivery `entregas.{i}.titulo` changes what the human sees or does in the panel or in the loop's behaviour.",
                                              SN("the title names a screen, a button, a message, a new agent or a change in what the loop decides or when",
                                                 "the change is internal: tests, refactor, metrics plumbing, a fix nobody would notice"))
        out = ctx.dl.ask_many(estado, qs)
        for i, e in enumerate(novos[:24]):
            t, v = out[f"doc_tipo_{i}"], out[f"doc_visivel_{i}"]
            cache[str(e["pr"])] = {"tipo": str(t.value), "conf": round(float(t.confidence), 3), "visivel": float(v.value) >= 0.5, "fonte": t.source}
        s.set("documentador_tipos", cache)
    return {e["pr"]: cache.get(str(e["pr"]), {"tipo": "funcionalidade", "conf": 0.0, "visivel": False, "fonte": "nenhuma"}) for e in lista}


def _constantes_do_loop(pacote: Path) -> tuple[tuple, dict]:
    """TRABALHO e TAREFAS lidos do fonte de loop.py (o Redator documenta o loop sem importá-lo)."""
    mod = ast.parse((pacote / "loop.py").read_text(encoding="utf-8"))
    achado: dict[str, Any] = {}
    for n in mod.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and getattr(n.targets[0], "id", "") in ("TRABALHO", "TAREFAS"):
            achado[n.targets[0].id] = ast.literal_eval(n.value)
    return tuple(achado.get("TRABALHO", ())), dict(achado.get("TAREFAS", {}))


# ------------------------------------------------------------------ os documentos
def _data(t: float) -> str:
    from datetime import datetime
    from .budget import TZ
    return datetime.fromtimestamp(t, TZ).strftime("%d/%m/%Y")


def _doc_agentes(pacote: Path) -> str:
    from . import equipe
    TRABALHO, TAREFAS = _constantes_do_loop(pacote)
    linhas = ["# Os agentes do loop", "", "O loop é um time de engenharia em que cada agente tem um papel. Os nomes abaixo são os que aparecem em todas as",
              "telas (`circulo/nomes.py`); o nome técnico antigo fica entre parênteses.", ""]
    for grupo, nome_grupo in equipe.GRUPOS.items():
        membros = [(k, v) for k, v in equipe.EQUIPE.items() if v["grupo"] == grupo]
        if not membros:
            continue
        linhas += [f"## {nome_grupo}", "", "| Papel | Nome técnico | O que faz |", "|---|---|---|"]
        for k, v in membros:
            linhas.append(f"| **{nomes.nome(k)}** | `{k}` ({nomes.antes(k)}) | {v['faz']} |")
        linhas.append("")
    linhas += ["## O giro", "", "Cada giro escolhe uma tarefa (as de trabalho primeiro, depois as de manutenção) e a executa até o fim; o SRE roda em paralelo.", "",
               "| Tarefa | O que faz |", "|---|---|"]
    for t in TRABALHO:
        linhas.append(f"| `{t}` ({nomes.nome(t)}) | {TAREFAS.get(t, '')} |")
    return "\n".join(linhas) + "\n"


CONSTITUICAO = ("merge_gate", "policy", "budget", "guardrails", "self_dev", "corpo")


def _doc_arquitetura(pacote: Path, versao: str) -> str:
    from . import verificacao
    linhas = ["# Arquitetura", "", f"Versão documentada: **{versao}**. Python 3.11+, biblioteca padrão, SQLite (WAL) e um servidor HTTP próprio para o",
              "painel. Toda decisão passa primeiro pelo Jev (cascata regra → aluno → Jev → LLM).", "",
              "## Constituição", "", "Módulos que nenhum agente pode alterar por PR (o CI e o gate recusam): " + ", ".join(f"`{c}.py`" for c in CONSTITUICAO) + " e `.github/`.", "",
              "## Módulos", "", "| Módulo | Linhas | O que é |", "|---|---|---|"]
    for m in modulos(pacote):
        linhas.append(f"| `{m['nome']}.py`{' ⚖️' if m['nome'] in CONSTITUICAO else ''} | {m['linhas']} | {m['resumo'] or '—'} |")
    linhas += ["", "## Telas", "", "| Rota | Arquivo | O que mostra |", "|---|---|---|"]
    for t in verificacao.TELAS:
        linhas.append(f"| `{t['rota']}` | `{t['arquivo']}` | {', '.join(t['contem'])} |")
    linhas += ["", "## APIs do painel", "", "| Rota | Chaves da resposta |", "|---|---|"]
    for rota, chaves in verificacao.APIS:
        linhas.append(f"| `{rota}` | {', '.join(f'`{c}`' for c in chaves) if chaves else 'estado inteiro do loop'} |")
    return "\n".join(linhas) + "\n"


def _doc_decisoes(pacote: Path) -> str:
    from . import jev_cobertura
    pergs = jev_cobertura.perguntas(pacote)
    linhas = ["# Decisões Jev First", "", f"Catálogo das {len(pergs)} perguntas que o código faz ao Jev antes de gastar ou mudar algo, lidas do próprio",
              "código (`circulo/jev_cobertura.py`). Tipos: **noul** (probabilidade de uma afirmação), **choice** (uma opção), **score** (um nível).", "",
              "| Onde | Tipo | Língua | Instrução |", "|---|---|---|---|"]
    for q in pergs:
        linhas.append(f"| `{q['arquivo']}:{q['linha']}` | {q['tipo']} | {'inglês' if q.get('ingles') else 'português'} | {q['instrucao'].replace('|', '/')} |")
    return "\n".join(linhas) + "\n"


def _doc_evolucao(ctx, repo: Path) -> tuple[str, int]:
    ents = entregas(ctx.store)
    tipos = classificar(ctx, ents) if ents else {}
    linhas = ["# Evolução", "", "Tudo o que entrou na main: as versões (CHANGELOG) e as entregas que **o próprio loop** fez por PR, com a linhagem",
              "pergunta → item → PR quando ela existe. O tipo de cada entrega foi classificado pelo Jev.", "", "## Versões", "",
              "| Versão | Data | Destaque | Itens |", "|---|---|---|---|"]
    for c in _changelog(repo):
        linhas.append(f"| {c['versao']} | {c['data']} | {c['destaque'].replace('|', '/')} | {c['itens']} |")
    linhas += ["", f"## Entregas do loop ({len(ents)} PRs mergeados)", ""]
    por_tipo: dict[str, int] = {}
    for e in ents:
        por_tipo[tipos[e["pr"]]["tipo"]] = por_tipo.get(tipos[e["pr"]]["tipo"], 0) + 1
    if por_tipo:
        linhas += ["Por tipo: " + " · ".join(f"**{k}** {v}" for k, v in sorted(por_tipo.items(), key=lambda kv: -kv[1])) + ".", ""]
    linhas += ["| PR | Data | Tipo | Visível | Entrega | Veio de |", "|---|---|---|---|---|---|"]
    for e in ents:
        t = tipos[e["pr"]]
        veio = f"pergunta do {e['persona']}: “{(e['pergunta'] or '')[:80]}”" if e["pergunta"] else (f"item #{e['item']} ({e['origem']})" if e["item"] else "—")
        linhas.append(f"| #{e['pr']} | {_data(e['em']) if e['em'] else '—'} | {t['tipo']} ({int(t['conf'] * 100)}%) | {'sim' if t['visivel'] else '—'} | {e['titulo'][:110].replace('|', '/')} | {veio.replace('|', '/')} |")
    return "\n".join(linhas) + "\n", len(ents)


def _doc_licoes(store: Store) -> tuple[str, int]:
    lic = store.q("SELECT id, assinatura, classe, status, ocorrencias, reincidencias, prevencao FROM licoes WHERE status!='unida' ORDER BY reincidencias DESC, ocorrencias DESC, id") \
        if store.one("SELECT 1 FROM sqlite_master WHERE name='licoes'") else []
    linhas = ["# Lições", "", "Cada erro que o loop cometeu vira uma lição com ponto de verificação; a lição só fecha com a correção validada e",
              "evidenciada (o erro não voltou). Esta lista é o banco de lições como está hoje.", "",
              "| # | Lição | Classe | Status | Ocorrências | Reincidências | Prevenção |", "|---|---|---|---|---|---|---|"]
    for r in lic:
        linhas.append(f"| {r['id']} | {r['assinatura'][:70].replace('|', '/')} | {r['classe']} | {r['status']} | {r['ocorrencias']} | {r['reincidencias']} | {(r['prevencao'] or '')[:120].replace('|', '/')} |")
    return "\n".join(linhas) + "\n", len(lic)


def gerar(ctx, repo: Path) -> dict[str, str]:
    """Todos os arquivos de docs/ como {caminho: texto}. Determinístico dado o estado (fora a classificação do Jev)."""
    pacote = Path(__file__).parent
    m = re.search(r'^version = "([^"]+)"', (repo / "pyproject.toml").read_text(encoding="utf-8"), flags=re.M)
    versao = m.group(1) if m else "?"
    docs: dict[str, str] = {"docs/agentes.md": _doc_agentes(pacote), "docs/arquitetura.md": _doc_arquitetura(pacote, versao), "docs/decisoes.md": _doc_decisoes(pacote)}
    docs["docs/evolucao.md"], n_ent = _doc_evolucao(ctx, repo)
    docs["docs/licoes.md"], n_lic = _doc_licoes(ctx.store)
    docs["docs/README.md"] = "\n".join([
        "# Documentação do Círculo", "",
        f"Gerada pelo **Redator técnico** do loop em {_data(time.time())} (versão {versao}) a partir do código, do banco e do CHANGELOG —",
        "nenhum número aqui é estimado. O agente roda quando há entrega nova e abre um PR só com esta pasta.", "",
        "| Documento | O que tem |", "|---|---|",
        "| [Agentes](agentes.md) | o time: papéis, o que cada um faz, as tarefas do giro |",
        "| [Arquitetura](arquitetura.md) | constituição, módulos, telas e APIs |",
        "| [Decisões Jev First](decisoes.md) | o catálogo de perguntas que o código faz ao Jev |",
        f"| [Evolução](evolucao.md) | versões e as {n_ent} entregas que o loop fez sozinho, classificadas pelo Jev |",
        f"| [Lições](licoes.md) | as {n_lic} lições aprendidas e o estado de cada uma |", "",
        "Sistema de design das telas: [`circulo/DESIGN.md`](../circulo/DESIGN.md). Histórico completo: [`CHANGELOG.md`](../CHANGELOG.md)."]) + "\n"
    return docs


# ------------------------------------------------------------------ quando e como publicar
def precisa(store: Store, agora: float | None = None) -> bool:
    agora = agora or time.time()
    st = store.get(KV) or {}
    if not store.one("SELECT 1 FROM sqlite_master WHERE name='prs'"):
        return False
    if st.get("pr_aberto") and store.one("SELECT 1 FROM prs WHERE number=? AND status='aberto'", (st["pr_aberto"],)):
        return False                                  # um PR de docs por vez (o gate fecha; a tabela prs diz)
    ultimo = store.one("SELECT COALESCE(MAX(number),0) m FROM prs WHERE status='mergeado'")["m"]
    novos = int(ultimo) - int(st.get("merge_visto", 0))
    return novos >= MERGES_PARA_RODAR or (bool(st.get("em")) and agora - float(st["em"]) >= A_CADA)


def _git(args: list[str], cwd: Path, check: bool = True) -> str:
    from .self_dev import _git_env
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=_git_env())
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()[-300:]}")
    return p.stdout.strip()


def publicar(ctx, repo: Path, docs: dict[str, str], gh=None) -> dict[str, Any]:
    """Escreve docs/ numa branch nova a partir de origin/main e abre o PR. Sem remoto/GitHub, escreve no clone e pronto."""
    s = ctx.store
    tem_remoto = bool(_git(["remote"], repo, check=False))
    if not tem_remoto or gh is None:
        for caminho, texto in docs.items():
            (repo / caminho).parent.mkdir(parents=True, exist_ok=True)
            (repo / caminho).write_text(texto, encoding="utf-8")
        return {"modo": "local", "arquivos": sorted(docs)}
    _git(["fetch", "-q", "origin", "main"], repo)
    branch = f"{BRANCH_PREFIX}{int(time.time())}"
    wt = repo.parent / f".wt-{branch.replace('/', '-')}"
    _git(["worktree", "add", "-q", "-b", branch, str(wt), "origin/main"], repo)
    try:
        for caminho, texto in docs.items():
            (wt / caminho).parent.mkdir(parents=True, exist_ok=True)
            (wt / caminho).write_text(texto, encoding="utf-8")
        _git(["add", "-A", "docs"], wt)
        if not _git(["status", "--porcelain", "docs"], wt):
            return {"modo": "sem_mudanca"}
        _git(["-c", f"user.name={AUTOR[0]}", "-c", f"user.email={AUTOR[1]}", "commit", "-q", "-m",
              "docs: documentação gerada pelo Redator técnico\n\nGerada do código, do banco e do CHANGELOG; tipos de entrega classificados pelo Jev.\n\nCirculo-Docs: 1"], wt)
        _git(["push", "-q", "-u", "origin", branch], wt)
        pr = gh.create_pr(branch, "main", "docs: documentação do loop atualizada pelo Redator técnico",
                          "Documentação gerada a partir do código, do banco (entregas, lições, perguntas) e do CHANGELOG. "
                          "Só a pasta `docs/` muda; o gate aceita PR de documentação apenas quando todos os arquivos estão nela e o CI está verde.\n\n"
                          f"Arquivos: {', '.join(sorted(docs))}")
        agora = time.time()
        if s.one("SELECT 1 FROM sqlite_master WHERE name='prs'"):
            s.x("INSERT OR IGNORE INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (pr, None, "docs: documentação do loop atualizada pelo Redator técnico", branch, "aberto", agora, agora))
        return {"modo": "pr", "pr": pr, "branch": branch}
    finally:
        _git(["worktree", "remove", "--force", str(wt)], repo, check=False)


def rodar(ctx, repo: Path | None = None, gh=None) -> dict[str, Any] | None:
    import os
    s = ctx.store
    repo = repo or (Path(os.environ["CIRCULO_REPO_DIR"]) if os.environ.get("CIRCULO_REPO_DIR") else None)
    if repo is None or not (repo / "pyproject.toml").exists():
        return None
    docs = gerar(ctx, repo)
    r = publicar(ctx, repo, docs, gh)
    ultimo = s.one("SELECT COALESCE(MAX(number),0) m FROM prs WHERE status='mergeado'")["m"] if s.one("SELECT 1 FROM sqlite_master WHERE name='prs'") else 0
    s.set(KV, {"em": time.time(), "merge_visto": int(ultimo), "pr_aberto": r.get("pr"), "modo": r["modo"], "arquivos": len(docs)})
    if callable(getattr(ctx, "reply", None)):
        if r["modo"] == "pr":
            ctx.reply(f"Redator técnico atualizou a documentação ({len(docs)} arquivos em docs/) e abriu o PR #{r['pr']}; o gate decide.", "docs")
        elif r["modo"] == "local":
            ctx.reply(f"Redator técnico escreveu a documentação ({len(docs)} arquivos em docs/) no clone local.", "docs")
    return {**r, "arquivos": len(docs)}



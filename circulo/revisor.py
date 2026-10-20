"""Revisor: o agente que valida cada PR do Developer DENTRO do ecossistema, para vários PRs andarem em paralelo.

Até a 1.28 o loop abria um PR do Developer por vez: a fila esperava o CI e o gate de cada um (60 a 90 min por item
quando um PR emperrava). Agora o Developer abre até MAX_PRS_ABERTOS PRs ao mesmo tempo, e o Revisor garante que a
paralelização não traz conflito nem quebra:

1. antes de abrir o PR (`antes_do_pr`), no worktree do Developer, com a main de agora:
   - traz a main atual para a branch: conflito = rejeita; sem conflito, roda lint e testes de novo (o código que passava
     na main de uma hora atrás pode quebrar na de agora);
   - compara os arquivos mudados com os dos outros PRs abertos do Developer: arquivo compartilhado = rejeita (o mais
     antigo tem prioridade; o item espera aquele PR fechar);
   - simula o merge com cada branch aberta (`git merge-tree`): conflito = rejeita.
2. no gate (`no_gate`), para PR já aberto: arquivo compartilhado com um PR mais antigo ainda aberto = rejeita.

Rejeitar = o PR não é aberto (ou é fechado), a branch fica, e o ITEM VOLTA PARA A FILA ('pendente') com a evidência
do motivo; se espera outro PR, a fila só o pega de novo depois que aquele PR fechar.

Jev First: toda revisão passa pelo Jev (`revisor_seguro`) com a evidência medida; a regra determinística decide quando
há problema medido (conflito ou quebra nunca passam), e o Jev decide o risco residual quando não há — e aprende.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from .decision import Decision, Question, SN

MAX_PRS_ABERTOS = 3           # PRs do Developer abertos ao mesmo tempo
SEGURO_MIN = 0.5              # p(seguro) abaixo disso, com confiança, o Jev rejeita mesmo sem problema medido
CONF_MIN = 0.35
NAO_CONTA = ("CHANGELOG.md", "pyproject.toml", "circulo/__init__.py")   # todo PR toca: não é conflito de intenção


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


# ------------------------------------------------------------------ medidas
def prs_abertos(store, exceto: int | None = None) -> list[dict]:
    """PRs do Developer ainda abertos (os que têm item do roteiro), do mais antigo ao mais novo."""
    rows = [dict(r) for r in store.q("SELECT number, item_id, branch, arquivos, created_at FROM prs WHERE status='aberto' "
                                     "AND item_id IS NOT NULL ORDER BY created_at, number")]
    out = []
    for r in rows:
        if exceto is not None and r["number"] == exceto:
            continue
        try:
            r["arquivos"] = json.loads(r["arquivos"] or "[]")
        except (TypeError, ValueError):
            r["arquivos"] = []
        out.append(r)
    return out


def compartilhados(arquivos: list[str], outros: list[dict]) -> list[dict]:
    """Com quais PRs abertos este conjunto de arquivos se cruza (fora dos arquivos que todo PR toca)."""
    meus = {a for a in arquivos if a not in NAO_CONTA}
    out = []
    for o in outros:
        comum = sorted(meus & {a for a in (o.get("arquivos") or []) if a not in NAO_CONTA})
        if comum:
            out.append({"pr": o["number"], "item_id": o.get("item_id"), "arquivos": comum})
    return out


def conflito_simulado(wt: Path, ref: str) -> bool | None:
    """`git merge-tree --write-tree` (git >= 2.38): 1 = conflito, 0 = mescla limpa; None = não deu para simular."""
    p = _git(["merge-tree", "--write-tree", "HEAD", ref], wt)
    if p.returncode in (0, 1):
        return p.returncode == 1
    return None


def trazer_main(wt: Path, autor: tuple[str, str]) -> tuple[bool, bool]:
    """Rebaseia a branch do worktree sobre origin/main. (mudou, conflito). Em conflito, aborta e deixa tudo como estava."""
    _git(["fetch", "-q", "origin", "main"], wt)
    atras = _git(["rev-list", "--count", "HEAD..origin/main"], wt).stdout.strip()
    if not atras or atras == "0":
        return False, False
    m = _git(["-c", f"user.name={autor[0]}", "-c", f"user.email={autor[1]}", "rebase", "-q", "origin/main"], wt)
    if m.returncode != 0:
        _git(["rebase", "--abort"], wt)
        return True, True
    return True, False


# ------------------------------------------------------------------ o Jev classifica
def classificar(dl, evidencia: dict) -> dict:
    """`revisor_seguro`: o PR é seguro para entrar junto com os outros abertos? Devolve p, conf e fonte."""
    q = Question("noul", "O PR do Developer `pr` é seguro para entrar na main junto com os outros PRs abertos `prs_abertos`?",
                 SN("sem conflito medido (`conflito_main`, `conflito_prs` falsos), testes passam na main atual (`testes_na_main`), "
                    "nenhum arquivo compartilhado com outro PR aberto (`compartilhados` vazio) e mudança pequena",
                    "há conflito, quebra de teste na main atual, arquivo compartilhado com PR aberto, ou a mudança é grande e toca módulos "
                    "centrais que outro PR também toca (`memoria`: revisões e gates parecidos de antes, com o resultado)"))
    d = dl.ask("revisor_seguro", q, evidencia)
    return {"p": float(d.value), "conf": float(d.confidence), "fonte": d.source}


def regra(jev, qid: str, q: Question, state) -> Decision:
    """LocalJev: problema medido = inseguro; sem problema = seguro, menos confiante quanto maior a mudança."""
    ev = state if isinstance(state, dict) else {}
    problema = bool(ev.get("conflito_main") or ev.get("conflito_prs") or ev.get("compartilhados")) or ev.get("testes_na_main") is False
    if problema:
        return jev._noul(qid, 0.08)
    linhas = int(ev.get("linhas") or 0)
    return jev._noul(qid, max(0.55, 0.95 - linhas / 2000))


def registrar(store, pr: int | None, item_id: int | None, momento: str, veredito: str, motivo: str, evidencia: dict, jev: dict) -> int:
    return store.x("INSERT INTO revisoes(pr,item_id,momento,veredito,motivo,evidencia,conf,fonte,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (pr, item_id, momento, veredito, motivo[:500], json.dumps(evidencia, ensure_ascii=False, default=str)[:4000],
                    jev.get("conf"), jev.get("fonte"), time.time()))


# ------------------------------------------------------------------ as duas revisões
def antes_do_pr(ctx, wt: Path, item: dict, arquivos: list[str], autor: tuple[str, str], verificar) -> dict:
    """Revisão no worktree, antes de abrir o PR. Devolve {ok, motivo, aguarda_pr, evidencia, jev}.
    `verificar(wt)` roda lint e testes (os mesmos do CI) e devolve (ok, saida)."""
    s = ctx.store
    outros = prs_abertos(s)
    ev: dict[str, Any] = {"pr": f"item #{item['id']}", "item_id": item["id"], "arquivos": arquivos, "linhas": None, "prs_abertos": [o["number"] for o in outros],
                          "compartilhados": [], "conflito_main": False, "conflito_prs": [], "testes_na_main": None, "base": "medido"}
    try:
        ev["linhas"] = int(_git(["diff", "--shortstat", "origin/main...HEAD"], wt).stdout.split()[0]) if outros else None
    except (ValueError, IndexError):
        ev["linhas"] = None
    motivo, aguarda = "", None
    mudou, conflito = trazer_main(wt, autor)
    if conflito:
        ev["conflito_main"] = True
        motivo = "conflito com a main atual ao trazê-la para a branch"
    elif mudou:
        ok, saida = verificar(wt)
        ev["testes_na_main"] = bool(ok)
        if not ok:
            motivo = "quebra na main atual: lint/testes falham depois de trazer a main para a branch: " + saida[-400:]
    if not motivo and outros:
        ev["compartilhados"] = compartilhados(arquivos, outros)
        if ev["compartilhados"]:
            c = ev["compartilhados"][0]
            aguarda = c["pr"]
            motivo = f"compartilha {', '.join(c['arquivos'][:4])} com o PR #{c['pr']} (mais antigo, ainda aberto)"
    if not motivo and outros:
        for o in outros:
            _git(["fetch", "-q", "origin", o["branch"]], wt)
            if conflito_simulado(wt, f"origin/{o['branch']}"):
                ev["conflito_prs"].append(o["number"])
        if ev["conflito_prs"]:
            aguarda = ev["conflito_prs"][0]
            motivo = f"conflito simulado (git merge-tree) com o PR #{aguarda} ainda aberto"
    from .memoria import RECEITA, do_ctx
    mem = do_ctx(ctx)
    if mem:
        ev["memoria"] = mem.lembrancas(f"{item['titulo']} " + " ".join(arquivos)[:300], k=3, tipos=RECEITA["revisor"][0])
    jev = classificar(ctx.dl, ev)
    if not motivo and jev["p"] is not None and jev["p"] < SEGURO_MIN and jev["conf"] >= CONF_MIN and jev["fonte"] == "jev":
        motivo = f"Jev: risco de entrar junto com os PRs abertos (p={jev['p']:.2f}, confiança {jev['conf']:.2f})"
    veredito = "rejeitado" if motivo else "aprovado"
    registrar(s, None, item["id"], "antes_do_pr", veredito, motivo or "seguro para abrir", ev, jev)
    return {"ok": not motivo, "motivo": motivo, "aguarda_pr": aguarda, "evidencia": ev, "jev": jev}


def no_gate(store, dl, pr: int, item_id: int | None, arquivos: list[str]) -> dict | None:
    """PR já aberto: cruza com um PR do Developer mais antigo ainda aberto? Então é rejeitado (o item volta à fila)."""
    if item_id is None:
        return None
    antigos = [o for o in prs_abertos(store, exceto=pr) if o["created_at"] <= (store.one("SELECT created_at FROM prs WHERE number=?", (pr,)) or {"created_at": 0})["created_at"] and o["number"] != pr]
    comp = compartilhados(arquivos, antigos)
    if not comp:
        return None
    ev = {"pr": pr, "item_id": item_id, "arquivos": arquivos, "prs_abertos": [o["number"] for o in antigos], "compartilhados": comp,
          "conflito_main": False, "conflito_prs": [], "testes_na_main": None, "linhas": None, "base": "medido"}
    jev = classificar(dl, ev)
    motivo = f"compartilha {', '.join(comp[0]['arquivos'][:4])} com o PR #{comp[0]['pr']} (mais antigo, ainda aberto)"
    registrar(store, pr, item_id, "gate", "rejeitado", motivo, ev, jev)
    return {"motivo": motivo, "aguarda_pr": comp[0]["pr"], "evidencia": ev, "jev": jev}


def resumo(store, limite: int = 10) -> dict:
    tot = store.one("SELECT COUNT(*) n, SUM(veredito='rejeitado') r, SUM(momento='antes_do_pr') a FROM revisoes")
    return {"max_abertos": MAX_PRS_ABERTOS, "abertos": [{k: o[k] for k in ("number", "item_id", "branch", "arquivos")} for o in prs_abertos(store)],
            "total": tot["n"] or 0, "rejeitadas": tot["r"] or 0, "antes_do_pr": tot["a"] or 0,
            "ultimas": [dict(r) for r in store.q("SELECT id, pr, item_id, momento, veredito, motivo, conf, fonte, created_at FROM revisoes "
                                                 "ORDER BY id DESC LIMIT ?", (limite,))]}

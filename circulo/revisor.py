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
import math
import random
import subprocess
import time
import urllib.error
from pathlib import Path
from typing import Any

from .decision import Decision, Question, SN
from .diff_size import parse_numstat
from .validador import feedback_validador as feedback_validador, revisar_pr as revisar_pr, validar_worktree as validar_worktree  # a porta do Validador (1.70) para a constituição

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


def estado_do_diff(numstat: str) -> dict:
    """O que o `revisor_seguro` precisa do diff, medido no numstat: linhas, nº de arquivos, categoria dominante
    (docs/testes/código, por linhas) e se toca teste."""
    t = parse_numstat(numstat)
    por: dict[str, int] = {}
    for a in t.arquivos:
        cat = "testes" if a.categoria == "teste" else "docs" if a.caminho.endswith((".md", ".rst", ".txt")) or a.caminho.startswith("docs/") else "código"
        por[cat] = por.get(cat, 0) + a.linhas
    return {"linhas": t.total, "n_arquivos": len(t.arquivos), "categoria_dominante": max(por, key=por.__getitem__, default=None),
            "toca_teste": "teste" in t.por_categoria}


def conflito_simulado(wt: Path, ref: str) -> bool | None:
    """`git merge-tree --write-tree` (git >= 2.38): 1 = conflito, 0 = mescla limpa; None = não deu para simular."""
    p = _git(["merge-tree", "--write-tree", "HEAD", ref], wt)
    if p.returncode in (0, 1):
        return p.returncode == 1
    return None


def arquivos_em_conflito(saida: str) -> list[str]:
    """Caminhos da seção 'Conflicted file info' de `git merge-tree --write-tree --name-only -z`: depois do OID da
    árvore, um caminho por NUL até o NUL vazio que abre as mensagens informativas."""
    out: list[str] = []
    for caminho in saida.split("\0")[1:]:
        if not caminho:
            break
        if caminho not in out:
            out.append(caminho)
    return out


def _mudados(repo: Path, intervalo: str) -> set[str]:
    return set(_git(["diff", "--name-only", intervalo], repo).stdout.split())


def medir_conflito(repo: Path, branch: str) -> dict | None:
    """Arquivos em que a branch conflita de fato com origin/main ({arquivos, base}); None = não deu para medir.
    Git anterior à 2.38 (sem `--write-tree`): reserva pela interseção dos arquivos mudados nos dois lados."""
    _git(["fetch", "-q", "origin", "main", branch], repo)
    p = _git(["merge-tree", "--write-tree", "--name-only", "-z", "origin/main", f"origin/{branch}"], repo)
    if p.returncode in (0, 1):
        return {"arquivos": arquivos_em_conflito(p.stdout) if p.returncode == 1 else [], "base": "merge-tree"}
    if p.returncode == 129:
        comum = _mudados(repo, f"origin/main...origin/{branch}") & _mudados(repo, f"origin/{branch}...origin/main")
        return {"arquivos": sorted(comum), "base": "intersecao"}
    return None


def gravar_conflitos(store, repo: Path | None, vereditos) -> None:
    """PR devolvido por conflito com a main: grava na trilha (`elos`, pr:N → conflito:<sha>) os arquivos em conflito,
    uma vez por versão do PR."""
    from . import rastro
    for v in vereditos:
        if not (repo and v.details.get("conflito")):
            continue
        para = f"conflito:{v.sha}"
        if store.one("SELECT 1 FROM elos WHERE de=? AND para=? AND relacao='conflito_main'", (f"pr:{v.number}", para)):
            continue
        row = store.one("SELECT branch FROM prs WHERE number=?", (v.number,))
        medida = medir_conflito(Path(repo), row["branch"]) if row and row["branch"] else None
        if medida is None:
            continue
        det = {"sha": v.sha, "total": len(medida["arquivos"]), **medida}
        while len(json.dumps(det, ensure_ascii=False)) > 1000:      # o elo guarda até 1000 caracteres: JSON inteiro
            det["arquivos"] = det["arquivos"][:-1]
        rastro.elo(store, f"pr:{v.number}", para, "conflito_main", det)


def conflitos_do_pr(store, pr: int) -> list[str]:
    """Arquivos em conflito gravados para o PR (todas as versões)."""
    out: list[str] = []
    for r in store.q("SELECT detalhe FROM elos WHERE de=? AND relacao='conflito_main' ORDER BY em", (f"pr:{pr}",)):
        out += [a for a in json.loads(r["detalhe"] or "{}").get("arquivos", []) if a not in out]
    return out


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
    """LocalJev: problema medido = inseguro; sem problema = seguro, menos confiante quanto maior a mudança, quanto mais
    arquivos e quando é código sem teste; só docs, mais confiante."""
    ev = state if isinstance(state, dict) else {}
    problema = bool(ev.get("conflito_main") or ev.get("conflito_prs") or ev.get("compartilhados")) or ev.get("testes_na_main") is False
    if problema:
        return jev._noul(qid, 0.08)
    p = 0.95 - int(ev.get("linhas") or 0) / 2000 - 0.01 * max(0, int(ev.get("n_arquivos") or 0) - 3)
    if ev.get("categoria_dominante") == "docs":
        p += 0.03
    elif ev.get("categoria_dominante") == "código" and ev.get("toca_teste") is False:
        p -= 0.1
    return jev._noul(qid, max(0.55, p))


def registrar(store, pr: int | None, item_id: int | None, momento: str, veredito: str, motivo: str, evidencia: dict, jev: dict) -> int:
    return store.x("INSERT INTO revisoes(pr,item_id,momento,veredito,motivo,evidencia,conf,fonte,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                   (pr, item_id, momento, veredito, motivo[:500], json.dumps(evidencia, ensure_ascii=False, default=str)[:4000],
                    jev.get("conf"), jev.get("fonte"), time.time()))


# ------------------------------------------------------------------ pré-voo do revisar_prs: adiar sem gastar
ADIADO = "revisar_prs_adiado"     # {tentativas, causa, ate_tick} do adiamento em curso
ADIAR_MAX_TENTATIVAS = 5          # adiamentos seguidos; no seguinte, o erro conta como falha
ADIAR_TETO_GIROS = 16             # teto do backoff exponencial
ESPERA_DO_ESTADO = (("checks em andamento", "checks_pendentes"), ("atrás da main", "atras_da_main"))


def pre_voo(estado: dict | None = None, erro: BaseException | None = None) -> str:
    """'adiar:<causa>' quando repetir mais tarde resolve sem gastar, ou 'executar'. Pura: olha o erro da API
    (rede_transitoria: URLError, timeout, HTTP 5xx) ou os motivos dos vereditos dos PRs (checks_pendentes, atras_da_main)."""
    if erro is not None:
        if isinstance(erro, urllib.error.HTTPError):
            return "adiar:rede_transitoria" if erro.code >= 500 else "executar"
        if isinstance(erro, (urllib.error.URLError, TimeoutError, ConnectionError)):
            return "adiar:rede_transitoria"
        return "executar"
    causas = []
    for motivo in (estado or {}).get("motivos") or ():
        causa = next((c for trecho, c in ESPERA_DO_ESTADO if trecho in motivo), None)
        if causa is None:
            return "executar"
        causas.append(causa)
    return f"adiar:{max(causas, key=causas.count)}" if causas else "executar"


def espera_em_giros(tentativa: int, rng=random.random) -> int:
    """Backoff exponencial com teto e jitter completo: os giros idle não voltam todos juntos."""
    return max(1, math.ceil(rng() * min(ADIAR_TETO_GIROS, 2 ** tentativa)))


def em_espera(store) -> bool:
    st = store.get(ADIADO)
    return bool(st) and store.tick < int(st["ate_tick"])


def causa_do_ci(store, gh, vereditos) -> None:
    """Cada PR devolvido por 'checks falhando' ganha a causa (`ci_causa.classificar`) na trilha, uma vez por versão.
    infra_suspeita tira o conserto da fila: o Developer não gasta tentativa e o item não reabre por um CI que nem rodou;
    codigo_ou_indeterminado segue para o conserto, que reexecuta lint e testes no worktree com a main."""
    from .ci_causa import INFRA, classificar, do_run
    vistos = dict(store.get("ci_causa_vistos") or {})
    for v in vereditos:
        if gh is None or not v.reason.startswith("checks falhando") or vistos.get(str(v.number)) == v.sha:
            continue
        try:
            checks = [do_run(r) for r in gh.check_runs(v.sha)]
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            continue
        causa = classificar(checks) or "indeterminado"
        vistos[str(v.number)] = v.sha
        row = store.one("SELECT item_id FROM prs WHERE number=?", (v.number,))
        if causa == INFRA:
            store.x("UPDATE prs SET conserto=NULL, updated_at=? WHERE number=? AND conserto_sha=?", (time.time(), v.number, v.sha))
        registrar(store, v.number, row["item_id"] if row else None, "ci_causa", causa, v.reason,
                  {"sha": v.sha, "checks": checks}, {})
    store.set("ci_causa_vistos", dict(list(vistos.items())[-50:]))


def revisar(store, gate, rng=random.random, repo: Path | None = None) -> str:
    """Roda o gate e classifica o desfecho: adiável vira evento 'adiado' (não falha) e o próximo giro idle espera
    o backoff; passado ADIAR_MAX_TENTATIVAS seguidos, ou causa não adiável, o erro sobe como falha.
    PR devolvido por conflito com a main tem os arquivos em conflito gravados (`gravar_conflitos`)."""
    try:
        vereditos, erro = gate.run(), None
    except Exception as exc:
        vereditos, erro = [], exc
    gravar_conflitos(store, repo, vereditos)
    causa_do_ci(store, getattr(gate, "gh", None), vereditos)
    causa = pre_voo(erro=erro) if erro is not None else pre_voo({"motivos": [v.reason for v in vereditos]})
    tentativa = int((store.get(ADIADO) or {}).get("tentativas", 0)) + 1
    if causa == "executar" or tentativa > ADIAR_MAX_TENTATIVAS:
        store.set(ADIADO, None)
        if erro is not None:
            raise erro
        return "executar"
    ate = store.tick + espera_em_giros(tentativa, rng)
    store.set(ADIADO, {"tentativas": tentativa, "causa": causa, "ate_tick": ate})
    registrar(store, None, None, "pre_voo", "adiado", causa.split(":", 1)[1],
              {"tentativa": tentativa, "ate_tick": ate, "erro": repr(erro)[:300] if erro else None}, {})
    return causa


# ------------------------------------------------------------------ as duas revisões
def antes_do_pr(ctx, wt: Path, item: dict, arquivos: list[str], autor: tuple[str, str], verificar) -> dict:
    """Revisão no worktree, antes de abrir o PR. Devolve {ok, motivo, aguarda_pr, evidencia, jev}.
    `verificar(wt)` roda lint e testes (os mesmos do CI) e devolve (ok, saida)."""
    s = ctx.store
    outros = prs_abertos(s)
    ev: dict[str, Any] = {"pr": f"item #{item['id']}", "item_id": item["id"], "arquivos": arquivos, "prs_abertos": [o["number"] for o in outros],
                          "compartilhados": [], "conflito_main": False, "conflito_prs": [], "testes_na_main": None, "base": "medido",
                          **estado_do_diff(_git(["diff", "--numstat", "origin/main...HEAD"], wt).stdout)}
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


# ------------------------------------------------------------ o Norte, pela porta do revisor (self_dev é constituição e não importa norte)
def item_de_produto(store, extra_sql: str = "", args: tuple = ()) -> dict | None:
    from .norte import item_de_produto as _f
    return _f(store, extra_sql, args)


def prefere_produto(store) -> bool:
    from .norte import prefere_produto as _f
    return _f(store)


# ------------------------------------------------------------ disjuntor do Developer
DISJUNTOR_PRS = 3            # PRs seguidos abandonados pela mesma causa…
DISJUNTOR_JANELA = 3 * 3600  # …dentro desta janela…
DISJUNTOR_PAUSA = 2 * 3600   # …pausam o Developer por este tempo (o problema é o ambiente, não o item)


def disjuntor_abandonos(store, reply, motivo: str) -> bool:
    """DISJUNTOR_PRS PRs seguidos abandonados pela mesma causa (os mesmos checks, o mesmo motivo) em DISJUNTOR_JANELA:
    o problema não é o item, é o ambiente — pausa o Developer por DISJUNTOR_PAUSA ("Precisa de você"). Sem isto, uma
    noite de CI recusado (20→21/10) virou 31 PRs abertos e fechados em círculo. Devolve True quando desarmou."""
    import re
    from datetime import datetime
    from .budget import TZ
    causa = re.sub(r"\d+", "", motivo.split(":", 1)[0] if motivo.startswith(("checks falhando", "conflito")) else motivo)[:80]
    agora = time.time()
    hist = [h for h in (store.get("self_dev_abandonos") or []) if agora - float(h.get("em", 0)) < DISJUNTOR_JANELA] + [{"em": agora, "causa": causa}]
    store.set("self_dev_abandonos", hist[-10:])
    if len(hist) < DISJUNTOR_PRS or any(h["causa"] != causa for h in hist[-DISJUNTOR_PRS:]):
        return False
    hora = datetime.fromtimestamp(agora + DISJUNTOR_PAUSA, TZ).strftime("%H:%M")
    store.set("self_dev_espera", {"ate": agora + DISJUNTOR_PAUSA, "hora": hora, "precisa_de_voce": True,
                                  "motivo": f"Disjuntor: {DISJUNTOR_PRS} PRs seguidos abandonados por “{causa}” — o problema é o ambiente, não os itens"})
    store.set("self_dev_abandonos", [])
    reply(f"Disjuntor do Developer: {DISJUNTOR_PRS} PRs seguidos abandonados por “{causa}”. Pausei por "
          f"{DISJUNTOR_PAUSA // 3600} h (até {hora}) para não gastar em círculo; veja o CI/GitHub.", "saude")
    return True


SEM_MUDANCA_MAX = 3          # tentativas seguidas do mesmo item sem o agente mudar nada


def sem_mudanca_seguida(store, reply, item: dict, log: str) -> bool:
    """O agente terminou sem mudar nada no mesmo item SEM_MUDANCA_MAX vezes seguidas: o item sai da fila (desativado,
    "depende de você") com o que o agente disse. Em 21/10 ele pedia "Approve python3.12" e a sessão retomada repetia
    isso: 272 chamadas em 4 h, uma a cada 42 s. Devolve True quando tirou o item da fila."""
    import re
    cont = dict(store.get("self_dev_sem_mudanca") or {})
    chave = str(item["id"])
    cont[chave] = int(cont.get(chave, 0)) + 1
    store.set("self_dev_sem_mudanca", {k: v for k, v in cont.items() if k == chave or v < SEM_MUDANCA_MAX})
    if cont[chave] < SEM_MUDANCA_MAX:
        return False
    store.x("UPDATE roadmap SET desativado=1, updated_at=? WHERE id=?", (time.time(), item["id"]))
    pedido = re.sub(r"\\n|\s+", " ", log)[-220:].strip()
    reply(f"Developer: “{str(item.get('titulo', ''))[:80]}” — o agente não mudou nada em {SEM_MUDANCA_MAX} tentativas seguidas; "
          f"tirei o item da fila para você ver. Última resposta: {pedido}", "saude")
    cont.pop(chave, None)
    store.set("self_dev_sem_mudanca", cont)
    return True

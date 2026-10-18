"""Rastreabilidade de ponta a ponta: de onde veio cada mudança do loop até a prova de que ela funciona rodando.

Cada giro já tem o seu traço (telemetria.py, um trace OTel por giro). Mas uma evolução atravessa muitos giros:
pedido seu ou pergunta do conselho (ou lição de um erro) → estudo → sessões do Developer → portões → PR → CI → gate
→ merge → versão nova no código rodando → giros de evidência → item concluído. Este módulo costura esse fio.

- Cada unidade de trabalho é um nó tipado: `item:36`, `pr:9`, `giro:<run_id>`, `versao:<sha>`, `missao:3`,
  `pedido:<evento>`, `licao:2`, `pergunta:7`.
- Os elos ficam na tabela `elos` (de → para, relação), gravados nos pontos em que o loop age (Developer, corpo,
  estudo, pedido). O que já está no banco (branch do PR, perguntas, lições, merges, verificações) é derivado: o
  histórico antigo também ganha fio, sem migração.
- O fio de um item tem um trace_id estável no formato W3C Trace Context (32 hex), e o `traceparent` correspondente
  vai para o ambiente do Claude Code (variável TRACEPARENT, convenção do OpenTelemetry para processos filhos), para
  o commit (trailer `Circulo-Trace`) e para o corpo do PR. Os traços dos giros apontam para ele com *span links*.
- Lacuna é um elo que deveria existir e não existe (ex.: mergeado e não chegou ao código rodando). Lacuna em item
  entregue é verificação reprovada (`rastro:cadeia`): vira lição, como qualquer outro erro.

Só leitura, exceto `elo` e `verificar`. Nada aqui derruba o loop.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

from .state import Store

PREFIXO_BRANCH = "circulo/fix-"
SEM_VERSAO_S = 1800          # mergeado há mais de 30 min sem chegar ao código rodando: lacuna
SEM_EVIDENCIA_S = 7200       # código novo rodando há mais de 2 h sem a evidência dos primeiros giros: lacuna
PONTO = "rastro:cadeia"


# ------------------------------------------------------------------ identidade W3C
def trace_id(no: str) -> str:
    """trace-id W3C (16 bytes em hex) estável para o fio de um nó."""
    t = hashlib.sha256(f"fio|{no}".encode()).hexdigest()[:32]
    return t if t.strip("0") else "1" + t[1:]          # o W3C proíbe o trace-id só de zeros


def span_id(no: str) -> str:
    s = hashlib.sha256(f"fiospan|{no}".encode()).hexdigest()[:16]
    return s if s.strip("0") else "1" + s[1:]


def traceparent(no: str) -> str:
    """Cabeçalho W3C `traceparent` (versão 00, amostrado) do fio do nó."""
    return f"00-{trace_id(no)}-{span_id(no)}-01"


# ------------------------------------------------------------------ elos
def elo(store: Store, de: str, para: str, relacao: str, detalhe: dict | str | None = None) -> None:
    """Grava um elo (idempotente). Nunca levanta: rastrear nunca derruba o trabalho rastreado."""
    if not de or not para or de.endswith(":None") or para.endswith(":None"):
        return
    try:
        det = detalhe if isinstance(detalhe, str) or detalhe is None else json.dumps(detalhe, ensure_ascii=False, default=str)
        store.x("INSERT OR IGNORE INTO elos(de,para,relacao,detalhe,em) VALUES(?,?,?,?,?)",
                (de, para, relacao, (det or None) and det[:1000], time.time()))
    except Exception:  # noqa: BLE001
        pass


def elos_de(store: Store, no: str) -> list[dict]:
    return [dict(r) for r in store.q("SELECT de, para, relacao, detalhe, em FROM elos WHERE de=? ORDER BY em", (no,))]


def elos_para(store: Store, no: str) -> list[dict]:
    return [dict(r) for r in store.q("SELECT de, para, relacao, detalhe, em FROM elos WHERE para=? ORDER BY em", (no,))]


def giro_do_tick(store: Store, tick: int | None) -> str | None:
    if tick is None:
        return None
    r = store.one("SELECT json_extract(body,'$.run_id') r FROM metrics WHERE tick=?", (tick,))
    return r["r"] if r and r["r"] else None


def item_do_pr(store: Store, pr: int) -> int | None:
    r = store.one("SELECT branch FROM prs WHERE number=?", (pr,))
    m = re.match(rf"{re.escape(PREFIXO_BRANCH)}(\d+)-", (r["branch"] or "") if r else "")
    if m:
        return int(m.group(1))
    e = store.one("SELECT de FROM elos WHERE para=? AND de LIKE 'item:%' LIMIT 1", (f"pr:{pr}",))
    return int(e["de"].split(":")[1]) if e else None


def _passo(etapa, titulo, estado="ok", em=None, detalhe="", giro=None, no=None, link=None) -> dict:
    return {"etapa": etapa, "titulo": titulo, "estado": estado, "em": em, "detalhe": detalhe or "",
            "giro": giro, "no": no, "link": link}


def _pr_url(pr: int) -> str | None:
    import os
    repo = os.environ.get("CIRCULO_REPO")
    return f"https://github.com/{repo}/pull/{pr}" if repo else None


# ------------------------------------------------------------------ versão em que um merge entrou
def versao_do_merge(store: Store, pr: int, merge_em: float) -> dict | None:
    """O código rodando que trouxe o merge: elo gravado pelo corpo (exato, via git) ou, no histórico antigo,
    a primeira atualização validada do corpo depois do merge."""
    e = store.one("SELECT para, em FROM elos WHERE de=? AND relacao='entrou_em' ORDER BY em LIMIT 1", (f"pr:{pr}",))
    if e:
        sha = e["para"].split(":", 1)[1]
        return {"sha": sha, "em": e["em"], "exato": True}
    v = store.one("SELECT sujeito, tick, created_at FROM verificacoes WHERE ponto='corpo:atualizar' AND ok=1 AND created_at>=? "
                  "ORDER BY id LIMIT 1", (merge_em,))
    if v:
        return {"sha": v["sujeito"], "em": v["created_at"], "tick": v["tick"], "exato": False}
    return None


def evidencia_da_versao(store: Store, sha: str) -> dict | None:
    sha = (sha or "")[:12]
    e = store.one("SELECT para, relacao, em FROM elos WHERE de LIKE ? AND relacao IN ('evidenciada','revertida') ORDER BY em DESC LIMIT 1",
                  (f"versao:{sha}%",))
    if e:
        return {"ok": e["relacao"] == "evidenciada", "em": e["em"]}
    v = store.one("SELECT ok, tick, created_at FROM verificacoes WHERE ponto='corpo:evidencia' AND sujeito=? ORDER BY id DESC LIMIT 1",
                  (sha,))
    return {"ok": bool(v["ok"]), "em": v["created_at"], "tick": v["tick"]} if v else None


# ------------------------------------------------------------------ o fio de um item do roteiro
def cadeia_item(store: Store, item_id: int, now: float | None = None) -> dict | None:
    now = now or time.time()
    it = store.one("SELECT * FROM roadmap WHERE id=?", (item_id,))
    if it is None:
        return None
    it = dict(it)
    no = f"item:{item_id}"
    passos: list[dict] = []
    lacunas: list[str] = []

    # 1. de onde veio
    if it["origem"] == "pedido_cassio":
        ped = next((e for e in elos_para(store, no) if e["de"].startswith("pedido:")), None)
        passos.append(_passo("origem", "Você pediu", "ok", it["created_at"], it["titulo"] if "Pedido original" not in (it["detalhe"] or "")
                             else it["detalhe"].split("Pedido original:", 1)[1].strip()[:300], no=ped["de"] if ped else None))
    elif it["origem"] == "erro":
        lic = store.one("SELECT id, assinatura, classe, descricao, created_at, primeira_tick FROM licoes WHERE item_id=?", (item_id,))
        inc = re.search(r"incidente #(\d+)", it["detalhe"] or "")
        if lic:
            passos.append(_passo("origem", f"Erro do loop virou a lição #{lic['id']} ({lic['classe']})", "ok", lic["created_at"],
                                 lic["descricao"][:300], giro_do_tick(store, lic["primeira_tick"]), f"licao:{lic['id']}"))
        elif inc:
            r = store.one("SELECT id, stage, kind, count, first_seen, first_tick FROM incidents WHERE id=?", (int(inc.group(1)),))
            passos.append(_passo("origem", f"Erro recorrente (incidente #{inc.group(1)})", "ok", r["first_seen"] if r else it["created_at"],
                                 f"{r['kind']} em {r['stage']}, {r['count']}x" if r else "", giro_do_tick(store, r["first_tick"]) if r else None))
        else:
            passos.append(_passo("origem", "Erro do loop", "ok", it["created_at"], it["evidencia"]))
    else:
        perg = store.one("SELECT id, persona, texto, created_at FROM perguntas WHERE item_id=? ORDER BY id LIMIT 1", (item_id,))
        if perg:
            passos.append(_passo("origem", f"Conselho ({perg['persona']}) perguntou", "ok", perg["created_at"], perg["texto"],
                                 no=f"pergunta:{perg['id']}"))
        else:
            passos.append(_passo("origem", "Planejado pelo loop", "ok", it["created_at"], it["evidencia"]))
            primeira = store.one("SELECT MIN(created_at) m FROM perguntas")["m"]
            if it["origem"] == "loop" and primeira and it["created_at"] >= primeira:
                lacunas.append("item planejado pelo loop sem a pergunta do conselho que o originou")

    # 2. estudo (pedido seu e itens do loop passam por estudo antes de executar)
    if it["estudo"]:
        try:
            est = json.loads(it["estudo"])
        except ValueError:
            est = {}
        e_elo = next((e for e in elos_de(store, no) if e["relacao"] == "estudou"), None)
        fontes = est.get("fontes") or []
        passos.append(_passo("estudo", f"Estudo: {est.get('veredito', '?')}", "falha" if est.get("veredito") == "contestar" else "ok",
                             e_elo["em"] if e_elo else None,
                             f"{len(fontes)} fonte(s). {str(est.get('justificativa', ''))[:300]}", no=f"estudo:{item_id}"))
    elif it["origem"] in ("pedido_cassio", "loop") and it["status"] == "pendente":
        passos.append(_passo("estudo", "Esperando estudo", "pendente", None,
                             "antes de executar, o loop pesquisa em fontes confiáveis"))

    # 3. Developer: sessões (giros) e portões antes do PR
    giros = [e for e in elos_de(store, no) if e["para"].startswith("giro:")]
    prs = [dict(r) for r in store.q("SELECT number, titulo, branch, status, created_at, updated_at FROM prs WHERE branch LIKE ? "
                                     "ORDER BY number", (f"{PREFIXO_BRANCH}{item_id}-%",))]
    vistos = {p["number"] for p in prs}
    for e in elos_de(store, no):
        if e["para"].startswith("pr:") and int(e["para"][3:]) not in vistos:
            r = store.one("SELECT number, titulo, branch, status, created_at, updated_at FROM prs WHERE number=?", (int(e["para"][3:]),))
            if r:
                prs.append(dict(r))
    if giros:
        sess = [e for e in giros if e["relacao"] == "developer"]
        cons = [e for e in giros if e["relacao"] == "conserto"]
        det = f"{len(sess)} sessão(ões)" + (f", {len(cons)} conserto(s) depois do CI" if cons else "")
        passos.append(_passo("developer", "Developer trabalhou (Claude Code no worktree)", "ok", giros[0]["em"], det,
                             giros[-1]["para"].split(":", 1)[1]))
    elif prs:
        primeiro = prs[0]["created_at"]
        passos.append(_passo("developer", "Developer trabalhou (Claude Code no worktree)", "ok", primeiro,
                             "sessão anterior ao registro de elos"))
    gate_pr = store.q("SELECT ponto, ok, motivo, tick, created_at FROM verificacoes WHERE ponto LIKE 'developer:abrir_pr%' "
                      "AND sujeito=? ORDER BY id", (it["titulo"][:120],))
    if gate_pr:
        falhas = [g for g in gate_pr if not g["ok"]]
        nomes = sorted({g["ponto"].split(":", 2)[-1] for g in gate_pr if g["ponto"].count(":") >= 2})
        passos.append(_passo("portoes", "Portões antes do PR", "ok" if not falhas or prs else "falha", gate_pr[-1]["created_at"],
                             f"{len(nomes)} portão(ões): {', '.join(nomes)}" + (f"; {len(falhas)} reprovação(ões) corrigida(s)" if falhas and prs else
                                                                                 f"; barrado: {falhas[-1]['motivo'][:200]}" if falhas else ""),
                             giro_do_tick(store, gate_pr[-1]["tick"])))

    # 4. PR → CI/gate → merge → versão → evidência
    entregue = False
    for p in prs:
        n = p["number"]
        passos.append(_passo("pr", f"PR #{n} aberto", "ok", p["created_at"], p["titulo"], no=f"pr:{n}", link=_pr_url(n)))
        for m in store.q("SELECT merged, reason, sha, created_at FROM merges WHERE pr=? ORDER BY id", (n,)):
            v = store.one("SELECT tick FROM verificacoes WHERE ponto IN ('gate:merge','gate:ci') AND sujeito LIKE ? "
                          "AND created_at BETWEEN ? AND ? ORDER BY id DESC LIMIT 1", (f"%#{n}%", m["created_at"] - 120, m["created_at"] + 5))
            passos.append(_passo("gate", "Gate mergeou" if m["merged"] else "Gate recusou", "ok" if m["merged"] else "falha",
                                 m["created_at"], m["reason"][:300], giro_do_tick(store, v["tick"]) if v else None,
                                 f"merge:{n}", _pr_url(n)))
            if not m["merged"]:
                continue
            ver = versao_do_merge(store, n, m["created_at"])
            if ver is None:
                atraso = now - m["created_at"]
                if atraso > SEM_VERSAO_S:
                    lacunas.append(f"PR #{n} mergeado há {int(atraso // 60)} min e ainda não chegou ao código rodando")
                passos.append(_passo("versao", "Esperando o corpo atualizar", "pendente", None,
                                     "a main é checada a cada 10 min e logo depois de cada merge"))
                continue
            passos.append(_passo("versao", f"Entrou no código rodando ({ver['sha'][:7]})", "ok", ver["em"],
                                 "elo exato (git)" if ver.get("exato") else "primeira atualização validada depois do merge",
                                 giro_do_tick(store, ver.get("tick")), f"versao:{ver['sha'][:12]}"))
            ev = evidencia_da_versao(store, ver["sha"])
            if ev is None:
                if now - ver["em"] > SEM_EVIDENCIA_S:
                    lacunas.append(f"versão {ver['sha'][:7]} rodando há mais de 2 h sem a evidência dos primeiros giros")
                passos.append(_passo("evidencia", "Provando nos primeiros giros", "pendente", None,
                                     "5 giros sem erro no código novo, ou volta sozinho para a versão anterior"))
            else:
                passos.append(_passo("evidencia", "Evidenciado: giros sem erro no código novo" if ev["ok"] else
                                     "Revertido: errou nos primeiros giros", "ok" if ev["ok"] else "falha", ev["em"], "",
                                     giro_do_tick(store, ev.get("tick"))))
                entregue = entregue or ev["ok"]

    # 5. fechamento
    st = it["status"]
    if st == "feito":
        passos.append(_passo("fim", "Concluído", "ok", it["updated_at"], it["evidencia"] if prs or giros else
                             f"{it['evidencia']} (entregue direto numa versão, sem passar pelo Developer)".strip()))
        if not prs and not giros and it["origem"] == "loop":
            lacunas.append("concluído sem PR nem sessão do Developer registrada")
    elif st == "contestado":
        passos.append(_passo("fim", "Contestado pelo estudo (esperando você)", "falha", it["updated_at"], it["evidencia"]))
    elif st == "observacao":
        passos.append(_passo("fim", "Em observação: o erro precisa parar de acontecer", "pendente", it["updated_at"], it["evidencia"]))
    elif st in ("pendente", "em_andamento", "parcial"):
        passos.append(_passo("fim", {"pendente": "Na fila", "em_andamento": "Em andamento", "parcial": "Parcial"}[st], "pendente",
                             it["updated_at"], it["evidencia"]))

    # a ordem é a do caminho (origem → … → fim), não a do relógio: um item reaberto não embaralha o fio
    return {"no": no, "tipo": "item", "id": item_id, "titulo": it["titulo"], "origem": it["origem"], "status": st,
            "trace_id": trace_id(no), "traceparent": traceparent(no), "passos": passos, "lacunas": lacunas,
            "entregue": entregue, "completo": not lacunas and (entregue or st in ("contestado",)),
            "giros": [g["para"].split(":", 1)[1] for g in giros]}


# ------------------------------------------------------------------ outros fios
def cadeia_missao(store: Store, pid: int, limite: int = 15) -> dict | None:
    p = store.one("SELECT id, nome, pedido, tipo, status, created_at, updated_at FROM projects WHERE id=?", (pid,))
    if p is None:
        return None
    no = f"missao:{pid}"
    passos = [_passo("origem", "Você pediu", "ok", p["created_at"], p["pedido"][:300])]
    rub = store.one("SELECT MIN(created_at) em, COUNT(*) n FROM rubrics WHERE project_id=?", (pid,))
    if rub["n"]:
        passos.append(_passo("estudo", "Pesquisou e montou a régua", "ok", rub["em"], f"{rub['n']} versão(ões) da régua"))
    ciclos = store.q("SELECT tick, fase, ganho, aceita, tokens, resultado, created_at FROM cycles WHERE project_id=? ORDER BY id DESC LIMIT ?",
                     (pid, limite))
    for c in reversed(ciclos):
        ganho = f" {c['ganho'] * 100:+.0f} pts" if c["ganho"] else ""
        passos.append(_passo("ciclo", f"Ciclo: {c['fase']}{ganho}", {1: "ok", 0: "falha"}.get(c["aceita"], "ok"), c["created_at"],
                             f"{c['resultado'] or ''} · {c['tokens']} tokens", giro_do_tick(store, c["tick"])))
    for e in elos_de(store, no):
        if e["relacao"] in ("pausada", "retomada"):
            passos.append(_passo("pausa", "Pausada por você" if e["relacao"] == "pausada" else "Retomada por você",
                                 "pendente" if e["relacao"] == "pausada" else "ok", e["em"], e["detalhe"] or ""))
    total = store.one("SELECT COUNT(*) n FROM cycles WHERE project_id=?", (pid,))["n"]
    lig = store.q("SELECT a, b, relacao, origem FROM links WHERE a=? OR b=?", (pid, pid))
    if lig:
        nomes = {r["id"]: r["nome"] for r in store.q("SELECT id, nome FROM projects")}
        passos.append(_passo("ligacoes", "Missões ligadas", "ok", None,
                             "; ".join(f"{nomes.get(r['b'] if r['a'] == pid else r['a'], '?')} ({r['relacao']}, {r['origem']})" for r in lig)))
    passos.sort(key=lambda x: (x["em"] is None, x["em"] or 0))
    return {"no": no, "tipo": "missao", "id": pid, "titulo": p["nome"], "status": p["status"], "trace_id": trace_id(no),
            "traceparent": traceparent(no), "passos": passos, "lacunas": [], "completo": True,
            "nota": f"mostrando os últimos {len(ciclos)} de {total} ciclos" if total > len(ciclos) else ""}


def cadeia_giro(store: Store, run_id: str) -> dict | None:
    from .camadas import execucao
    ex = execucao(store, run_id)
    if ex is None:
        return None
    no = f"giro:{run_id}"
    com_erro = {e["chave"] for e in ex["erros"]}
    passos = [_passo("etapa", e["nome"], "falha" if e["chave"] in com_erro else "ok", e["em"],
                     f"{round(1000 * e['dur'])} ms" + (f" · {e['detalhe']}" if e.get("detalhe") else "")) for e in ex["etapas"]]
    for e in ex["erros"]:
        passos.append(_passo("erro", f"Erro em {e['nome']}", "falha", e["em"], f"{e['kind']}: {e['message'][:200]}"))
    itens = [int(e["de"].split(":")[1]) for e in elos_para(store, no) if e["de"].startswith("item:")]
    for i in itens:
        r = store.one("SELECT titulo FROM roadmap WHERE id=?", (i,))
        passos.append(_passo("item", f"Trabalhou no item #{i}", "ok", None, r["titulo"] if r else "", no=f"item:{i}"))
    passos.sort(key=lambda x: (x["em"] is None, x["em"] or 0))
    from .telemetria import _id
    return {"no": no, "tipo": "giro", "id": run_id, "titulo": f"Giro {ex['tick']} ({ex.get('tarefa') or 'orquestração'})",
            "status": "erro" if ex["erros"] or ex["erros_do_giro"] else "ok", "trace_id": _id("trace", run_id, n=32),
            "traceparent": None, "passos": passos, "lacunas": [], "completo": True, "duracao_ms": ex.get("duracao_ms"),
            "itens": itens}


def cadeia_versao(store: Store, sha: str) -> dict | None:
    sha = sha.lower()
    v = store.one("SELECT sujeito, created_at, tick FROM verificacoes WHERE ponto='corpo:atualizar' AND ok=1 AND ? LIKE sujeito || '%' "
                  "OR (ponto='corpo:atualizar' AND ok=1 AND sujeito LIKE ?) ORDER BY id DESC LIMIT 1", (sha, f"{sha[:12]}%"))
    elo_v = store.q("SELECT de, em FROM elos WHERE para LIKE ? AND relacao='entrou_em'", (f"versao:{sha[:12]}%",))
    if v is None and not elo_v:
        return None
    no = f"versao:{(v['sujeito'] if v else sha)[:12]}"
    passos = []
    for e in elo_v:
        pr = int(e["de"].split(":")[1])
        passos.append(_passo("pr", f"Trouxe o PR #{pr}", "ok", e["em"], "", no=f"pr:{pr}", link=_pr_url(pr)))
    if v:
        passos.append(_passo("versao", f"Corpo atualizado para {v['sujeito'][:7]}", "ok", v["created_at"], "", giro_do_tick(store, v["tick"])))
        ev = evidencia_da_versao(store, v["sujeito"])
        if ev:
            passos.append(_passo("evidencia", "Evidenciado" if ev["ok"] else "Revertido", "ok" if ev["ok"] else "falha", ev["em"], "",
                                 giro_do_tick(store, ev.get("tick"))))
    passos.sort(key=lambda x: (x["em"] is None, x["em"] or 0))
    return {"no": no, "tipo": "versao", "id": no.split(":")[1], "titulo": f"Versão {no.split(':')[1][:7]}", "status": "",
            "trace_id": trace_id(no), "traceparent": traceparent(no), "passos": passos, "lacunas": [], "completo": True}


# ------------------------------------------------------------------ busca
def localizar(store: Store, termo: str) -> dict | None:
    """Acha o fio por qualquer ponta: 'item 36', '#36', 'PR 9', 'missão 2', run_id, sha, trace_id ou parte do título."""
    t = (termo or "").strip().lower()
    if not t:
        return None
    if m := re.fullmatch(r"(?:pr|pull)\s*#?\s*(\d+)", t):
        n = int(m.group(1))
        item = item_do_pr(store, n)
        return cadeia_item(store, item) if item else None
    if m := re.fullmatch(r"(?:m|miss[ãa]o)\s*#?\s*(\d+)", t):
        return cadeia_missao(store, int(m.group(1)))
    if m := re.fullmatch(r"(?:vers[ãa]o|sha)\s*([0-9a-f]{7,40})", t):
        return cadeia_versao(store, m.group(1))
    if m := re.fullmatch(r"giro\s*([0-9a-f]{12})", t):
        return cadeia_giro(store, m.group(1))
    if m := re.fullmatch(r"(?:item\s*)?#?\s*(\d{1,6})", t):
        return cadeia_item(store, int(m.group(1)))
    if re.fullmatch(r"[0-9a-f]{32}", t):
        for r in store.q("SELECT id FROM roadmap ORDER BY id DESC LIMIT 500"):
            if trace_id(f"item:{r['id']}") == t:
                return cadeia_item(store, r["id"])
        from .telemetria import _id
        for r in store.q("SELECT json_extract(body,'$.run_id') r FROM metrics ORDER BY tick DESC LIMIT 5000"):
            if r["r"] and _id("trace", r["r"], n=32) == t:
                return cadeia_giro(store, r["r"])
        return None
    if re.fullmatch(r"[0-9a-f]{12}", t) and store.one("SELECT 1 FROM trail WHERE run_id=? LIMIT 1", (t,)):
        return cadeia_giro(store, t)
    if re.fullmatch(r"[0-9a-f]{7,40}", t):
        return cadeia_versao(store, t)
    r = store.one("SELECT id FROM roadmap WHERE lower(titulo) LIKE ? ORDER BY updated_at DESC LIMIT 1", (f"%{t}%",))
    return cadeia_item(store, r["id"]) if r else None


# ------------------------------------------------------------------ visão geral e verificação
def recentes(store: Store, limite: int = 12, now: float | None = None) -> list[dict]:
    """Os fios mais recentes: cada item com movimento, a etapa em que está e se o fio está completo."""
    out = []
    for r in store.q("SELECT id FROM roadmap WHERE COALESCE(desativado,0)=0 AND (status!='pendente' OR estudo IS NOT NULL "
                     "OR origem!='pedido_cassio') ORDER BY updated_at DESC LIMIT ?", (limite,)):
        c = cadeia_item(store, r["id"], now)
        if c is None:
            continue
        feitos = [p for p in c["passos"] if p["estado"] != "pendente"]
        direto = c["status"] == "feito" and not any(p["etapa"] in ("developer", "pr") for p in c["passos"])
        estado = "lacuna" if c["lacunas"] else "completo" if c["completo"] else "direto" if direto else "em_curso"
        out.append({"id": c["id"], "titulo": c["titulo"], "origem": c["origem"], "status": c["status"], "completo": c["completo"],
                    "estado": estado,
                    "lacunas": c["lacunas"], "etapa": (feitos[-1]["titulo"] if feitos else "na fila"),
                    "etapas": [p["etapa"] for p in c["passos"]], "trace_id": c["trace_id"],
                    "em": max((p["em"] for p in c["passos"] if p["em"]), default=None)})
    return [x for x in out if x["estado"] != "direto"] + [x for x in out if x["estado"] == "direto"]


def completude(store: Store, dias: int = 30, now: float | None = None) -> dict:
    """Das entregas com PR mergeado (fora as que ainda estão em voo), quantas têm o fio completo até a evidência."""
    now = now or time.time()
    ini = now - dias * 86400
    itens = []
    for m in store.q("SELECT DISTINCT pr FROM merges WHERE merged=1 AND created_at BETWEEN ? AND ?", (ini, now - SEM_EVIDENCIA_S)):
        i = item_do_pr(store, m["pr"])
        if i is not None and i not in itens:
            itens.append(i)
    completos, falhos = 0, []
    for i in itens:
        c = cadeia_item(store, i, now)
        if c and c["completo"]:
            completos += 1
        elif c:
            falhos.append({"id": i, "titulo": c["titulo"], "lacunas": c["lacunas"] or ["sem a evidência final"]})
    return {"total": len(itens), "completos": completos, "taxa": round(completos / len(itens), 3) if itens else None,
            "incompletos": falhos, "dias": dias}


def verificar(ctx, now: float | None = None) -> list[int]:
    """Neurônio `rastro:cadeia`: cada entrega mergeada é conferida uma vez, depois que teve tempo de chegar à evidência.
    Fio com lacuna é verificação reprovada e vira lição (classe trabalho: não trava a evolução, mas fica no roteiro)."""
    s, now = ctx.store, now or time.time()
    vistos = set((s.get("rastro_conferidos") or [])[-500:])
    conferidos = []
    for m in s.q("SELECT DISTINCT pr FROM merges WHERE merged=1 AND created_at < ? ORDER BY pr DESC LIMIT 30", (now - SEM_EVIDENCIA_S,)):
        i = item_do_pr(s, m["pr"])
        if i is None or i in vistos:
            continue
        c = cadeia_item(s, i, now)
        if c is None:
            continue
        from .licoes import registrar as monitorar
        monitorar(ctx, PONTO, not c["lacunas"], sujeito=f"item #{i}", motivo="; ".join(c["lacunas"]),
                  assinatura="rastro:lacuna" if c["lacunas"] else None, classe="trabalho",
                  titulo="Fio de rastreabilidade com lacuna", detalhe_item=f"Item #{i}: {c['titulo'][:120]}.")
        vistos.add(i)
        conferidos.append(i)
    if conferidos:
        s.set("rastro_conferidos", sorted(vistos)[-500:])
    return conferidos

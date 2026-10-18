"""O que o loop está fazendo para evoluir: linha do tempo única, giros com a duração de cada etapa e ritmo de decisões.

Só leitura. Junta o que já fica registrado (propostas, ciclos, evidências, PRs, merges, prompts em A/B, versões
da política, erros e roteiro) num formato só, para o painel mostrar cada evolução ao vivo.
"""
from __future__ import annotations

import json
import time

from .state import Store

FASE = {"pesquisa": "Pesquisou e montou a régua", "construcao": "Construiu a primeira versão", "melhoria": "Tentou melhorar",
        "adiado_valor": "Adiou (o Jev viu pouco ganho)", "adiado_orcamento": "Adiou (orçamento)", "bloqueado": "Parou"}
DEC = {"base": "primeira versão aceita", "avancar": "avançou com evidência", "refazer": "refazer: evidência contraditória",
       "descartar": "descartada pela catraca", "cumprida": "missão cumprida"}


def linha_do_tempo(s: Store, projeto: int | None = None, zero: bool = False, limite: int = 40) -> list[dict]:
    """Evoluções e trabalho, mais recentes primeiro. `zero`: tela do Loop, vê tudo de todas as missões."""
    todos = zero or projeto is None
    pf = "" if todos else " AND project_id=?"
    pa: tuple = () if todos else (projeto,)
    nomes = {r["id"]: r["nome"] for r in s.q("SELECT id, nome FROM projects")}
    out: list[dict] = []

    def add(em, tipo, titulo, detalhe="", estado="", pid=None):
        if em:
            out.append({"em": float(em), "tipo": tipo, "titulo": titulo, "detalhe": detalhe or "", "estado": estado or "",
                        "projeto": pid, "missao": nomes.get(pid)})

    for r in s.q(f"SELECT level, kind, description, status, notes, updated_at, project_id FROM proposals WHERE 1=1{pf} "
                 "ORDER BY updated_at DESC LIMIT 15", pa):
        add(r["updated_at"], "regra" if r["level"] == 1 else "politica",
            ("Nova regra: " if r["level"] == 1 else "Ajuste no próprio loop: ") + r["description"], r["notes"] or "", r["status"], r["project_id"])
    for r in s.q(f"SELECT project_id, tick, fase, ganho, aceita, tokens, resultado, created_at FROM cycles WHERE 1=1{pf} "
                 "ORDER BY id DESC LIMIT 15", pa):
        ganho = f" · {r['ganho'] * 100:+.0f} pts" if r["ganho"] else ""
        add(r["created_at"], "ciclo", f"{FASE.get(r['fase'], r['fase'])}{ganho}",
            f"{r['resultado'] or ''} · {r['tokens']} tokens · giro {r['tick']}",
            {1: "aceita", 0: "recusada"}.get(r["aceita"], r["fase"]), r["project_id"])
    for r in s.q(f"SELECT project_id, tick, versao, antes, depois, decisao, motivo, created_at FROM evidence WHERE 1=1{pf} "
                 "ORDER BY id DESC LIMIT 15", pa):
        med = f"{(r['antes'] or 0) * 100:.0f}% → {(r['depois'] or 0) * 100:.0f}%" if r["depois"] is not None else ""
        add(r["created_at"], "evidencia", f"{'v' + str(r['versao']) + ' ' if r['versao'] else ''}{DEC.get(r['decisao'], r['decisao'])}",
            " · ".join(x for x in (med, r["motivo"]) if x), r["decisao"], r["project_id"])
    for r in s.q(f"SELECT number, titulo, status, created_at, updated_at, project_id FROM prs WHERE 1=1{pf} ORDER BY updated_at DESC LIMIT 10", pa):
        add(r["updated_at"] or r["created_at"], "pr", f"PR #{r['number']}: {r['titulo']}", "", r["status"], r["project_id"])
    if todos:
        for r in s.q("SELECT pr, merged, reason, created_at FROM merges ORDER BY id DESC LIMIT 10"):
            add(r["created_at"], "merge", f"Gate {'mergeou' if r['merged'] else 'recusou'} o PR #{r['pr']}", r["reason"],
                "mergeado" if r["merged"] else "recusado")
        for r in s.q("SELECT role, variante, status, notes, created_at FROM harness_experiments ORDER BY id DESC LIMIT 8"):
            add(r["created_at"], "harness", f"Prompt do {r['role']} em A/B: {r['variante'][:90]}", r["notes"] or "", r["status"])
        for r in s.q("SELECT version, status, reason, created_at FROM policy_versions WHERE reason!='semente' ORDER BY version DESC LIMIT 8"):
            add(r["created_at"], "versao", f"Política v{r['version']}: {r['reason']}", "", r["status"])
        for r in s.q("SELECT titulo, status, evidencia, origem, updated_at, COALESCE(desativado,0) off FROM roadmap WHERE origem!='pedido_cassio' "
                     "OR evidencia LIKE 'diagnóstico%' OR evidencia='pedido pelo painel' OR status='em_andamento' OR desativado IS NOT NULL "
                     "ORDER BY updated_at DESC LIMIT 10"):
            add(r["updated_at"], "roteiro", f"Roteiro: {r['titulo']}", r["evidencia"], "desativado" if r["off"] else r["status"])
        for r in s.q("SELECT message, created_at FROM alerts WHERE kind='saude' AND message LIKE 'Developer%' ORDER BY id DESC LIMIT 8"):
            add(r["created_at"], "developer", r["message"][:160], "", "")
    for r in s.q(f"SELECT stage, kind, message, count, status, first_seen, last_seen, project_id FROM incidents WHERE 1=1{pf} "
                 "ORDER BY last_seen DESC LIMIT 8", pa):
        add(r["last_seen"], "erro", f"Erro em {r['stage']} ({r['count']}x): {r['kind']}", r["message"][:160], r["status"], r["project_id"])
    out.sort(key=lambda x: -x["em"])
    return out[:limite]


def giros(s: Store, projeto: int | None = None, n: int = 24) -> list[dict]:
    """Últimos giros com a duração de cada etapa (da trilha)."""
    ult = s.one("SELECT MAX(tick) t FROM trail")["t"]
    if ult is None:
        return []
    if projeto:      # giros em que esta missão trabalhou
        ticks = [r["tick"] for r in s.q("SELECT DISTINCT tick FROM trail WHERE project_id=? ORDER BY tick DESC LIMIT ?", (projeto, n))]
        if not ticks:
            return []
        rows = s.q(f"SELECT tick, etapa, project_id, em, detalhe FROM trail WHERE tick IN ({','.join('?' * len(ticks))}) ORDER BY seq", ticks)
    else:
        rows = s.q("SELECT tick, etapa, project_id, em, detalhe FROM trail WHERE tick > ? ORDER BY seq", (ult - n,))
    por: dict[int, list] = {}
    for r in rows:
        por.setdefault(r["tick"], []).append(r)
    out = []
    for tick in sorted(por):
        rs = por[tick]
        segs = []
        for i, r in enumerate(rs):
            if r["etapa"] == "descanso":
                break
            fim = rs[i + 1]["em"] if i + 1 < len(rs) else (time.time() if tick == ult else r["em"])
            segs.append({"etapa": r["etapa"], "dur": max(0.0, fim - r["em"]), "projeto": r["project_id"], "detalhe": r["detalhe"]})
        if projeto and not any(x["projeto"] == projeto for x in segs):
            continue
        out.append({"tick": tick, "inicio": rs[0]["em"], "dur": sum(x["dur"] for x in segs), "etapas": segs,
                    "ativo": tick == ult and not any(r["etapa"] == "descanso" for r in rs)})
    return out


def ritmo(s: Store, projeto: int | None = None, minutos: int = 30) -> dict:
    """Decisões por minuto nos últimos N minutos, e quem respondeu."""
    agora = time.time()
    pf, pa = (" AND project_id=?", (projeto,)) if projeto else ("", ())
    rows = s.q(f"SELECT CAST((? - created_at) / 60 AS INT) m, source, COUNT(*) n FROM decisions WHERE created_at > ?{pf} GROUP BY m, source",
               (agora, agora - minutos * 60, *pa))
    serie = [0] * minutos
    fontes: dict[str, int] = {}
    for r in rows:
        if 0 <= r["m"] < minutos:
            serie[minutos - 1 - r["m"]] += r["n"]
        fontes[r["source"]] = fontes.get(r["source"], 0) + r["n"]
    conf = s.one(f"SELECT AVG(confidence) c FROM decisions WHERE created_at > ? AND source!='llm'{pf}", (agora - minutos * 60, *pa))["c"]
    return {"serie": serie, "fontes": fontes, "confianca_media": conf, "minutos": minutos}


def agora(s: Store) -> dict | None:
    e = s.get("etapa")
    if not e:
        return None
    return {**e, "ha": max(0.0, time.time() - float(e.get("em") or time.time()))}


def _json(x):
    return json.loads(x) if isinstance(x, str) else x

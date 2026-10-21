"""Dash do loop em camadas: saúde no topo, todas as etapas do ciclo ao vivo, detalhe de uma execução pelo run_id.

Só leitura. Cada giro ganha um run_id (loop.py) gravado em cada passagem de etapa (trail), em cada erro
(run_errors) e na métrica do giro: o painel junta tudo por ele, e uma falha fica a dois cliques
(etapa → execução). A saturação (fila, tempo ocioso) fica num bloco à parte, fora da visão principal.
"""
from __future__ import annotations

import json
import re
import time
from statistics import median

from . import nomes
from .state import Store
from .status import loop_status

# todas as etapas de um ciclo, na ordem em que acontecem
_ORDEM = ("orquestrador", "pedido", "decisao", "atualizar_corpo", "estudar_pedido", "planejar_roteiro", "corrigir_codigo",
          "revisar_prs", "evoluir_projeto", "manutencao", "meta_learner", "shadow", "licoes", "saude")
ETAPAS = tuple((c, nomes.nome(c)) for c in _ORDEM)
NOME = dict(ETAPAS)
OCIOSO = ("descanso", "pausado")
RUN_ID = re.compile(r"[0-9a-f]{1,32}")


def chave_trilha(etapa: str, tarefa: str | None = None) -> str | None:
    """Etapa do ciclo de uma passagem da trilha (None: entre giros)."""
    if tarefa:
        return tarefa if tarefa in NOME else "manutencao"
    if etapa == "idle":
        return "decisao"          # sem tarefa ainda: o loop (regra ou Jev) está escolhendo o que fazer
    return {"developer": "corrigir_codigo", "projeto": "evoluir_projeto"}.get(etapa, etapa if etapa in NOME else None)


def chave_erro(stage: str) -> str | None:
    """Etapa do ciclo de um erro registrado pelo Incidents (stage como 'idle:revisar_prs', 'meta', 'pedido:mensagem')."""
    if stage.startswith("pedido"):
        return "pedido"
    if stage.startswith("idle:"):
        t = stage.split(":", 1)[1]
        return t if t in NOME else "manutencao"
    return {"idle": "decisao", "meta": "meta_learner", "health": "saude"}.get(stage, stage if stage in NOME else None)


def _segmentos(rows, now: float) -> list[dict]:
    """Passagens de uma execução → pedaços com duração (o último dura até agora se o giro ainda corre)."""
    segs = []
    for i, r in enumerate(rows):
        if r["etapa"] in OCIOSO:
            break
        fim = rows[i + 1]["em"] if i + 1 < len(rows) else now
        segs.append({"chave": chave_trilha(r["etapa"], r["tarefa"]), "etapa": r["etapa"], "tarefa": r["tarefa"],
                     "detalhe": r["detalhe"], "projeto": r["project_id"], "em": r["em"], "dur": max(0.0, fim - r["em"])})
    for sg in segs:
        sg["nome"] = NOME.get(sg["chave"], sg["etapa"])
    return segs


def _execucoes(s: Store, n: int, now: float) -> list[dict]:
    ids = [r["run_id"] for r in s.q("SELECT run_id FROM trail WHERE run_id IS NOT NULL GROUP BY run_id ORDER BY MAX(seq) DESC LIMIT ?", (n,))]
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    por: dict[str, list] = {i: [] for i in ids}
    for r in s.q(f"SELECT run_id, tick, etapa, tarefa, project_id, em, detalhe FROM trail WHERE run_id IN ({marks}) ORDER BY seq", ids):
        por[r["run_id"]].append(r)
    erros: dict[str, list] = {i: [] for i in ids}
    for e in s.q(f"SELECT run_id, stage FROM run_errors WHERE run_id IN ({marks})", ids):
        erros[e["run_id"]].append(chave_erro(e["stage"]))
    out = []
    for rid in reversed(ids):           # mais antiga primeiro (eixo do tempo)
        rows = por[rid]
        ativo = not any(r["etapa"] in OCIOSO for r in rows)
        segs = _segmentos(rows, now if ativo else rows[-1]["em"])
        out.append({"run_id": rid, "tick": rows[0]["tick"], "inicio": rows[0]["em"], "ativo": ativo,
                    "dur": sum(x["dur"] for x in segs), "segmentos": segs, "erros": len(erros[rid]),
                    "falhas": sorted({c for c in erros[rid] if c})})
    return out


def visao(s: Store, now: float | None = None, n: int = 30) -> dict:
    """As três camadas: saúde (semáforo), linha do tempo das etapas, e apoio (marcos no gráfico e saturação)."""
    now = now or time.time()
    runs = _execucoes(s, n, now)
    dia = now - 86400
    erros_24h = {r["stage"]: r["n"] for r in s.q("SELECT stage, COUNT(*) n FROM run_errors WHERE em > ? GROUP BY stage", (dia,))}
    por_etapa: dict[str, int] = {}
    for st, k in erros_24h.items():
        c = chave_erro(st)
        if c:
            por_etapa[c] = por_etapa.get(c, 0) + k
    ultimo_erro: dict[str, dict] = {}
    for e in s.q("SELECT run_id, stage, em FROM run_errors WHERE em > ? ORDER BY id DESC LIMIT 500", (dia,)):
        ultimo_erro.setdefault(chave_erro(e["stage"]), dict(e))

    atual = runs[-1] if runs and runs[-1]["ativo"] else None
    chave_atual = atual["segmentos"][-1]["chave"] if atual and atual["segmentos"] else None
    etapas = []
    for chave, nome in ETAPAS:
        vistas = [(r, sum(x["dur"] for x in r["segmentos"] if x["chave"] == chave)) for r in runs
                  if any(x["chave"] == chave for x in r["segmentos"])]
        item = {"chave": chave, "nome": nome, "erros_24h": por_etapa.get(chave, 0), "status": "sem_execucao",
                "dur": None, "dur_media": None, "run_id": None, "em": None, "execucoes": len(vistas)}
        if vistas:
            r, d = vistas[-1]
            item.update(run_id=r["run_id"], dur=d, em=max(x["em"] for x in r["segmentos"] if x["chave"] == chave),
                        dur_media=sum(v for _, v in vistas) / len(vistas),
                        status=("rodando" if r is atual and chave == chave_atual else
                                "falhou" if chave in r["falhas"] else "ok"))
        # falhou fora da trilha (a trilha é curta): o erro mais recente ainda localiza a execução
        ult = ultimo_erro.get(chave)
        if ult and (item["em"] is None or ult["em"] >= item["em"]) and item["status"] != "rodando":
            item.update(status="falhou", run_id=ult["run_id"] or item["run_id"], em=ult["em"])
        etapas.append(item)

    fechadas = [r for r in runs if not r["ativo"]]
    st = loop_status(s, now)
    pr = s.one("SELECT number, titulo, status, updated_at FROM prs ORDER BY updated_at DESC LIMIT 1")
    total_24h = sum(erros_24h.values())
    ultima_falhou = bool(fechadas and fechadas[-1]["erros"])
    cor = ("vermelho" if st["estado"] == "desligado" or ultima_falhou else
           "amarelo" if total_24h or st["estado"].startswith("pausado") else "verde")
    seg = atual["segmentos"][-1] if atual and atual["segmentos"] else None
    etapa_atual = ({"chave": seg["chave"], "nome": seg["nome"], "detalhe": seg["detalhe"], "ha": now - seg["em"],
                    "run_id": atual["run_id"], "tick": atual["tick"]} if seg else None)
    frase = " · ".join(x for x in (
        st["titulo"],
        f"agora: {etapa_atual['nome']} há {etapa_atual['ha']:.0f} s" if etapa_atual else "entre giros",
        f"{total_24h} erro{'s' if total_24h != 1 else ''} em 24 h",
        f"última execução falhou ({', '.join(NOME.get(c, c) for c in fechadas[-1]['falhas']) or 'erro'})" if ultima_falhou else "",
    ) if x)
    ok = [r["dur"] for r in fechadas if not r["erros"]]
    ruim = [r["dur"] for r in fechadas if r["erros"]]
    d24 = now - 86400
    um = lambda sql, a=(): int((s.one(sql, a) or {"n": 0})["n"] or 0)  # noqa: E731
    saude = {"cor": cor, "frase": frase, "estado": st["estado"], "titulo": st["titulo"], "etapa_atual": etapa_atual,
             "ultimo_pr": dict(pr) if pr else None, "erros_24h": total_24h, "ultima_falhou": ultima_falhou,
             "entregas_24h": {"prs": um("SELECT COUNT(*) n FROM prs WHERE status='mergeado' AND updated_at>=?", (d24,)),
                              "itens": um("SELECT COUNT(*) n FROM roadmap WHERE status='feito' AND updated_at>=?", (d24,))},
             "fila": {"pendentes": um("SELECT COUNT(*) n FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0"),
                      "em_andamento": um("SELECT COUNT(*) n FROM roadmap WHERE status='em_andamento'"),
                      "prs_abertos": um("SELECT COUNT(*) n FROM prs WHERE status='aberto'")},
             "reincidencias_24h": um("SELECT COALESCE(SUM(reincidencias),0) n FROM licoes WHERE updated_at>=?", (d24,)),
             # sinal de ouro: latência das falhas separada da dos sucessos
             "dur_ok": median(ok) if ok else None, "dur_falha": median(ruim) if ruim else None}

    marcos = [{"tipo": "merge", "em": r["created_at"], "titulo": f"PR #{r['pr']} mergeado", "run_id": None}
              for r in s.q("SELECT pr, created_at FROM merges WHERE merged=1 AND created_at > ? ORDER BY id", (dia,))]
    marcos += [{"tipo": "incidente", "em": r["em"], "titulo": f"{r['kind']} em {r['stage']}", "run_id": r["run_id"]}
               for r in s.q("SELECT incident_id, MIN(em) em, run_id, stage, kind FROM run_errors WHERE em > ? GROUP BY incident_id", (dia,))]
    marcos.sort(key=lambda m: m["em"])
    return {"agora": now, "saude": saude, "etapas": etapas,
            "execucoes": [{k: v for k, v in r.items() if k != "segmentos"} for r in runs],
            "marcos": marcos, "saturacao": saturacao(s, now)}


def saturacao(s: Store, now: float, janela: float = 3600) -> dict:
    """Apoio, fora da visão principal: fila de pedidos, fração do tempo ocioso e giros por hora."""
    rows = s.q("SELECT etapa, em, run_id FROM trail WHERE em > ? ORDER BY seq", (now - janela,))
    ocioso = total = 0.0
    for i, r in enumerate(rows):
        d = max(0.0, (rows[i + 1]["em"] if i + 1 < len(rows) else now) - r["em"])
        total += d
        if r["etapa"] in OCIOSO:
            ocioso += d
    return {"fila": s.pending_count(), "ocioso": ocioso / total if total else None,
            "giros_1h": len({r["run_id"] for r in rows if r["run_id"]}), "janela_s": janela}


def execucao(s: Store, run_id: str, now: float | None = None) -> dict | None:
    """Tudo de uma execução: etapas com duração, erros com o rastro, métrica do giro e decisões tomadas nele."""
    if not RUN_ID.fullmatch(run_id or ""):
        return None
    now = now or time.time()
    rows = s.q("SELECT tick, etapa, tarefa, project_id, em, detalhe FROM trail WHERE run_id=? ORDER BY seq", (run_id,))
    erros = [{**dict(e), "chave": chave_erro(e["stage"]), "nome": NOME.get(chave_erro(e["stage"]) or "", e["stage"])}
             for e in s.q("SELECT stage, kind, message, trace, incident_id, tick, em FROM run_errors WHERE run_id=? ORDER BY id", (run_id,))]
    m = s.one("SELECT tick, body FROM metrics WHERE json_extract(body,'$.run_id')=?", (run_id,))
    if not rows and not erros and not m:
        return None
    tick = rows[0]["tick"] if rows else (erros[0]["tick"] if erros else m["tick"])
    ativo = bool(rows) and not any(r["etapa"] in OCIOSO for r in rows)
    corpo = json.loads(m["body"]) if m else {}
    decisoes = [{**dict(d), "value": json.loads(d["value"])}
                for d in s.q("SELECT id, question, value, confidence, source, created_at FROM decisions WHERE tick=? ORDER BY id LIMIT 40", (tick,))]
    return {"run_id": run_id, "tick": tick, "ativo": ativo, "inicio": rows[0]["em"] if rows else None,
            "etapas": _segmentos(rows, now if ativo else rows[-1]["em"]) if rows else [],
            "erros": erros, "erros_do_giro": corpo.get("errors", []), "duracao_ms": corpo.get("duracao_ms"),
            "tarefa": corpo.get("idle"), "pedido": corpo.get("handled"), "decisoes": decisoes}

"""Estado do loop para humanos, derivado do batimento + controles + etapa. Usado pelo painel."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from . import motivo
from .budget import TZ
from .caminho import CI_EM_CURSO
from .state import Store

STALE_AFTER = 20.0  # sem batimento por mais que isso → o processo do loop não está rodando
TAREFA_PARADA = 45 * 60  # item em andamento sem atualização por mais que isso → tarefa parada

PROXIMO_PASSO = {"check": "aguardar o check", "tarefa": "reabrir a tarefa", "portao": "escalar ao Developer"}


def _ped(n: int) -> str:
    return f"{n} pedido esperando" if n == 1 else f"{n} pedidos esperando"


def _trava_de_pr(store: Store, pr: int) -> tuple[str, str, float] | None:
    """Tipo, causa e início da trava do PR aberto: a sequência mais recente de vereditos do mesmo tipo no gate."""
    vereditos = store.q("SELECT merged, reason, created_at FROM merges WHERE pr=? ORDER BY id DESC", (pr,))
    if not vereditos or vereditos[0]["merged"]:
        return None

    def tipo(r) -> str | None:
        if r["merged"]:
            return None
        if (r["reason"] or "").startswith(CI_EM_CURSO):
            return "check"
        return "portao" if motivo.do_gate(r["reason"]) is not None else None

    t = tipo(vereditos[0])
    if t is None:
        return None
    desde = vereditos[0]["created_at"]
    for r in vereditos[1:]:
        if tipo(r) != t:
            break
        desde = r["created_at"]
    return t, (vereditos[0]["reason"] or "").split("\n", 1)[0][:200], desde


def trava(store: Store, now: float | None = None) -> dict | None:
    """A primeira causa de trava, por regra e sem LLM: entre PR esperando check, PR recusado por portão e tarefa
    parada, a que dura há mais tempo, com a idade em horas e o próximo passo automático."""
    now = now or time.time()
    candidatas = []
    for p in store.q("SELECT number FROM prs WHERE status='aberto'"):
        if t := _trava_de_pr(store, p["number"]):
            candidatas.append((t[0], f"PR #{p['number']}", t[1], t[2]))
    for r in store.q("SELECT id, titulo, updated_at FROM roadmap WHERE status='em_andamento' AND updated_at < ?",
                     (now - TAREFA_PARADA,)):
        candidatas.append(("tarefa", f"item #{r['id']}", f"em andamento sem avanço: {r['titulo'][:120]}", r["updated_at"]))
    if not candidatas:
        return None
    tipo, alvo, causa, desde = min(candidatas, key=lambda c: c[3])
    idade_h = round((now - desde) / 3600, 1)
    passo = PROXIMO_PASSO[tipo]
    return {"tipo": tipo, "alvo": alvo, "causa": causa, "desde": desde, "idade_h": idade_h, "proximo_passo": passo,
            "texto": f"{alvo} travado há {idade_h:g} h — {causa}. Próximo passo: {passo}."}


def loop_status(store: Store, now: float | None = None) -> dict:
    now = now or time.time()
    b = store.get("batimento")
    raw = store.get("loop_status", "parado")
    ctl = store.get("controle", {}) or {}
    etapa = store.get("etapa") or {}
    pend = store.pending_count()
    base = {"tick": store.tick, "pendentes": pend, "modo_seguro": bool(ctl.get("modo_seguro")),
            "batimento_ha": round(now - b["em"], 1) if b else None, "agora": now, "trava": trava(store, now)}

    if not b or now - b["em"] > STALE_AFTER:
        visto = (etapa.get("em") if etapa else None) or (b["em"] if b else None)
        detalhe = ("O processo do loop não está rodando. Inicie com `circulo run --painel`."
                   if pend == 0 else f"O processo do loop não está rodando e há {_ped(pend)}. Inicie com `circulo run --painel`.")
        return {**base, "estado": "desligado", "titulo": "Desligado", "detalhe": detalhe, "visto_em": visto}

    if ctl.get("pausado"):
        return {**base, "estado": "pausado_humano", "titulo": "Pausado por você",
                "detalhe": "Nenhum giro acontece até você retomar." + (f" {_ped(pend).capitalize()} na fila." if pend else "")}

    if raw == "pausado_orcamento":
        tomorrow = (datetime.now(TZ) + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
        return {**base, "estado": "pausado_orcamento", "titulo": "Pausado: orçamento do dia acabou",
                "detalhe": "Retoma sozinho à meia-noite, de onde parou.", "retoma_em": tomorrow.timestamp()}

    seguro = " em modo seguro" if ctl.get("modo_seguro") else ""
    nome = etapa.get("nome")
    # etapa em curso (o fim do giro sempre volta para "descanso"); com o pulso durante o giro, etapa longa
    # como o Developer continua "trabalhando", não some do painel depois de 10 s
    if nome and nome not in ("descanso", "pausado"):
        projeto = None
        if etapa.get("projeto"):
            row = store.one("SELECT nome FROM projects WHERE id=?", (etapa["projeto"],))
            projeto = row["nome"] if row else None
        return {**base, "estado": "trabalhando", "titulo": "Trabalhando" + seguro, "etapa": nome,
                "projeto_id": etapa.get("projeto"), "projeto": projeto,
                "detalhe": f"Giro {etapa.get('tick', store.tick)}" + (f" em “{projeto}”" if projeto else " no próprio círculo")}

    prox = b.get("proximo_giro_em")
    return {**base, "estado": "aguardando", "titulo": "Rodando" + seguro, "proximo_giro_em": prox,
            "detalhe": "Entre giros." + (f" {_ped(pend).capitalize()} na fila." if pend else "")}

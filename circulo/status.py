"""Estado do loop para humanos, derivado do batimento + controles + etapa. Usado pelo painel."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from .budget import TZ
from .state import Store

STALE_AFTER = 20.0  # sem batimento por mais que isso → o processo do loop não está rodando


def _ped(n: int) -> str:
    return f"{n} pedido esperando" if n == 1 else f"{n} pedidos esperando"


def loop_status(store: Store, now: float | None = None) -> dict:
    now = now or time.time()
    b = store.get("batimento")
    raw = store.get("loop_status", "parado")
    ctl = store.get("controle", {}) or {}
    etapa = store.get("etapa") or {}
    pend = store.pending_count()
    base = {"tick": store.tick, "pendentes": pend, "modo_seguro": bool(ctl.get("modo_seguro")),
            "batimento_ha": round(now - b["em"], 1) if b else None, "agora": now}

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

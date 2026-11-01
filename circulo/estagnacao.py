"""A causa medida da estagnação: o que cada giro parado fez de fato (lição #47).

"causa provável: sem recusa registrada" deixava o loop cego quando o gasto não era o motivo. Cada giro parado anota o
que rodou (tarefa, pedido, erro por etapa); a causa junta essas contagens às recusas do porteiro do gasto.
Tarefa que o idle não deixa rodar não é trabalho pendente: `pode_rodar` é a mesma regra para os dois.
"""

ESTAGNADO = 10      # giros com trabalho pendente e nada avançando = estagnação (lição de estrutura); o Vigia age a partir dele
EVENTOS = 20       # (ação, resultado) dos últimos giros parados, lidos pelo vigia.detectar_travamento
EXPIRA_EM = 30     # cada disparo da estagnação fecha: 'destravou' se o loop avança em até 30 giros, senão 'expirou'
SEGURAS = ("analisar_padroes", "rodar_regressao", "resumo", "evoluir_projeto")   # modo seguro: só baixo risco
COMPONENTE = {"revisar_baixa_confianca": "meta", "evoluir_harness": "meta"}     # (corrigir_codigo tem quarentena própria)


def pode_rodar(store, incidents, t: str, modo_seguro: bool) -> bool:
    """Modo seguro, quarentena, pausa do Médico e adiamento do revisor: o que barra a tarefa no idle."""
    from . import revisor
    from .medico import tarefa_pausada
    return ((not modo_seguro or t in SEGURAS) and not incidents.isolated(f"idle:{t}") and not tarefa_pausada(store, t)
            and not (t in COMPONENTE and incidents.isolated(COMPONENTE[t])) and not (t == "revisar_prs" and revisor.em_espera(store)))


def anotar_giro(st: dict, r) -> None:
    """Soma em st["rodou"] o que o giro r fez sem avançar."""
    rodou = st.setdefault("rodou", {})
    feitos = [] if r is None else ([f"{r.idle_task} rodou sem avançar"] * bool(r.idle_task)
                                   + ["pedido rodou sem avançar"] * bool(r.handled_event)
                                   + [f"erro em {e.split(':', 1)[0].split()[0]}" for e in r.errors if e.strip()])
    for f in feitos:
        rodou[f] = int(rodou.get(f, 0)) + 1
    acao = None if r is None else (r.idle_task or ("pedido" if r.handled_event else None))
    erro = next((f for f in feitos if f.startswith("erro em ")), "sem avanço")
    st["eventos"] = (st.get("eventos") or [])[-(EVENTOS - 1):] + [{"acao": acao, "resultado": erro}]


def medir_disparos(store, giro: int, avancou: bool) -> None:
    """Fecha cada disparo da estagnação (vigia_disparos) no mesmo registro: destravou em N giros ou expirou em EXPIRA_EM."""
    if avancou:
        store.x("UPDATE vigia_disparos SET resultado='destravou', giros_ate_destravar=?-giro WHERE chave='estagnacao' "
                "AND resultado IS NULL AND giro IS NOT NULL AND ?-giro<=?", (giro, giro, EXPIRA_EM))
    store.x("UPDATE vigia_disparos SET resultado='expirou' WHERE chave='estagnacao' AND resultado IS NULL "
            "AND giro IS NOT NULL AND ?-giro>=?", (giro, EXPIRA_EM))


def pendencias(store, st: dict, now: float) -> dict:
    """O último estado de cada pendência no disparo e a causa por regra: a primeira que segura o loop, nesta ordem."""
    ci = int(store.one("SELECT COUNT(*) n FROM prs WHERE status='aberto'")["n"])
    teto = sum(int(n) for n in (st.get("recusas") or {}).values())
    llm = float((store.get("self_dev_espera") or {}).get("ate", 0)) > now
    causa = "aguardando CI" if ci else "aguardando teto" if teto else "aguardando LLM" if llm else "sem tarefa elegível"
    return {"aguardando_ci": ci, "aguardando_teto": teto, "aguardando_llm": llm,
            "sem_tarefa_elegivel": causa == "sem tarefa elegível", "causa": causa}


def parado(store) -> dict | None:
    """O primeiro item pendente do roteiro (na ordem do Developer) e a etapa que o tocou por último: fila, developer, gate ou CI."""
    r = store.one("SELECT id, status, evidencia FROM roadmap WHERE status IN ('pendente','em_andamento') AND COALESCE(desativado,0)=0 "
                  "ORDER BY origem='erro' DESC, ordem, id LIMIT 1")
    if not r:
        return None
    ev = (r["evidencia"] or "").lower()
    pr = store.one("SELECT number FROM prs WHERE item_id=? AND status='aberto' LIMIT 1", (r["id"],))
    etapa = ("CI" if pr else "developer" if r["status"] == "em_andamento" else "gate" if "portõe" in ev or "barrado" in ev
             else "developer" if "agente" in ev or "developer" in ev else "fila")
    return {"item": r["id"], "estado": r["status"], "etapa": etapa, "toque": (r["evidencia"] or "")[:160]}


def causa_provavel(st: dict, store=None) -> str:
    fatos = {**{f"{t} recusado": n for t, n in (st.get("recusas") or {}).items()}, **(st.get("rodou") or {})}
    causa = ", ".join(f"{f} {n}x" for f, n in sorted(fatos.items(), key=lambda kv: -kv[1])) or "nenhuma tarefa rodou nos giros parados"
    p = parado(store) if store is not None else None
    return f"item #{p['item']} {p['estado']} parado na etapa {p['etapa']} ({p['toque']}); {causa}" if p else causa

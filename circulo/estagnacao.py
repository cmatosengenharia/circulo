"""A causa medida da estagnação: o que cada giro parado fez de fato (lição #47).

"causa provável: sem recusa registrada" deixava o loop cego quando o gasto não era o motivo. Cada giro parado anota o
que rodou (tarefa, pedido, erro por etapa); a causa junta essas contagens às recusas do porteiro do gasto.
Tarefa que o idle não deixa rodar não é trabalho pendente: `pode_rodar` é a mesma regra para os dois.
"""

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


def causa_provavel(st: dict) -> str:
    fatos = {**{f"{t} recusado": n for t, n in (st.get("recusas") or {}).items()}, **(st.get("rodou") or {})}
    return ", ".join(f"{f} {n}x" for f, n in sorted(fatos.items(), key=lambda kv: -kv[1])) or "nenhuma tarefa rodou nos giros parados"

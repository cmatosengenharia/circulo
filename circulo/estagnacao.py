"""A causa medida da estagnação: o que cada giro parado fez de fato (lição #47).

"causa provável: sem recusa registrada" deixava o loop cego quando o gasto não era o motivo. Cada giro parado anota o
que rodou (tarefa, pedido, erro por etapa); a causa junta essas contagens às recusas do porteiro do gasto.
"""


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

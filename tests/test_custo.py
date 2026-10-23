"""Pergunta do conselho #131 (economista): quanto do gasto do developer vira PR e quanto vai para item sem PR."""
import time

from circulo.custo import tokens_por_desfecho
from circulo.perguntas import Conselho

ITENS = [
    {"titulo": "Item entregue", "status": "feito", "evidencia": "PR #10 mergeado"},
    {"titulo": "Item grande", "status": "dividido", "evidencia": "dividido em 3 sub-itens"},
    {"titulo": "Item repetido", "status": "descartado", "evidencia": "duas sessões sem progresso"},
    {"titulo": "Item travado", "status": "bloqueado", "evidencia": "3 falhas locais iguais"},
    {"titulo": "Item na fila", "status": "em_andamento", "evidencia": ""},
]
CHAMADAS = [
    {"entrada": "Item entregue", "tokens": 1000},
    {"entrada": "reparo: Item entregue", "tokens": 500},
    {"entrada": "Item grande", "tokens": 2000},
    {"entrada": "Item repetido", "tokens": 3000},
    {"entrada": "conserto do PR #9: Item repetido", "tokens": 1000},
    {"entrada": "Item travado", "tokens": 1500},
    {"entrada": "Item na fila", "tokens": 1000},
]


def test_tokens_do_developer_somados_por_desfecho_do_item():
    r = tokens_por_desfecho(CHAMADAS, ITENS)
    assert r["por_desfecho"] == {"mergeado": 1500, "dividido": 2000, "descartado": 4000, "bloqueado": 1500,
                                 "em_aberto": 1000}
    assert r["tokens"] == 10000
    assert r["tokens_sem_pr_pct"] == 75.0                  # (2000 + 4000 + 1500) / 10000
    assert [c["titulo"] for c in r["top_causas"]] == ["Item repetido", "Item grande", "Item travado"]
    assert r["top_causas"][0] == {"titulo": "Item repetido", "desfecho": "descartado", "tokens": 4000,
                                  "motivo": "duas sessões sem progresso"}


def test_sem_chamadas_nao_divide_por_zero():
    r = tokens_por_desfecho([], ITENS)
    assert r["tokens"] == 0 and r["tokens_sem_pr_pct"] is None and r["top_causas"] == []


def test_evidencia_do_economista_traz_tokens_sem_pr_do_developer(circle):
    agora = time.time()
    for it in ITENS:
        circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                       "VALUES(?,'x','erro',?,?,1,?,?)", (it["titulo"], it["status"], it["evidencia"], agora, agora))
    for c in CHAMADAS:
        circle.store.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,ok,entrada,created_at) "
                       "VALUES(1,'developer','Claude Code','fixo',?,1,?,?)", (c["tokens"], c["entrada"], agora))
    p = {p.id: p for p in Conselho(circle.ctx).candidatas()}["economista:etapa_cara"]
    assert p.evidencia["tokens_sem_pr_pct"] == 75.0
    assert [c["titulo"] for c in p.evidencia["top_causas_sem_pr"]] == ["Item repetido", "Item grande", "Item travado"]

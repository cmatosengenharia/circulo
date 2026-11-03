"""Catálogo de trabalhos candidatos a vender (missão Vender resultado, item E; ADR 0015).

Cinco trabalhos que um profissional faz hoje por mês e que a agência (o loop) poderia entregar pronto. Cada um tem a
promessa em uma frase, a faixa R$/mês do profissional substituído, a capacidade atual do loop de entregar sem humano
e a proximidade de um cliente real do Cássio. A capacidade NÃO é opinião: é a fração das peças (módulos de
`circulo/`) que já existem em código; uma peça que ainda não existe baixa o número e sobe sozinha quando o módulo
nascer. O Jev dá um score a cada trabalho (1×/dia pelo Vigia, `norte.cobrar`); o kv `catalogo_trabalhos` guarda o
catálogo com o score e o painel (`/api/norte`, via `norte.resumo`) mostra o ranking. O kv sobrescreve o catálogo padrão: proximidade e
cliente são dado do Cássio, não do código.
"""
from __future__ import annotations

import time
from pathlib import Path

from .decision import Decision, Question

KV = "catalogo_trabalhos"
PERGUNTA = "trabalho_score"
NIVEIS = ("não vender ainda", "candidato", "primeiro a vender")
PROXIMIDADE = {1.0: "um cliente pediu", 0.5: "piloto nos canais ou repositórios do próprio Cássio", 0.0: "ninguém ainda"}
PACOTE = Path(__file__).parent

# (nome, promessa em uma frase, (R$/mês mín, máx) do profissional substituído, peças em circulo/*.py, proximidade, cliente)
CATALOGO = (
    ("cortes_video", "Você manda o vídeo bruto e os cortes saem publicados nos seus canais na cadência combinada, sem você editar nada.",
     (2500, 6000), ("demo_video", "cortes", "publicacao"), 0.5, "canais-piloto do Cássio (dogfooding da esteira, item G)"),
    ("fotografia_evento", "As fotos do evento esportivo saem editadas e à venda por atleta no mesmo dia, sem noite de edição.",
     (2000, 5000), ("edicao_fotos", "galeria_venda", "reconhecimento_atleta"), 0.0, "ninguém ainda"),
    ("relatorio_metricas", "Toda segunda às 8h o relatório da semana das suas redes chega pronto, com o que subiu, o que caiu e o que fazer.",
     (2000, 4500), ("digest_semanal", "resultado", "coleta_redes"), 0.5, "canais-piloto do Cássio (métricas já reportadas pela caixa)"),
    ("triagem_leads", "Todo lead que chega recebe resposta e classificação em até 2 minutos, dia e noite.",
     (2500, 5000), ("lancamentos_email", "caixa", "classificador_lead", "resposta_lead"), 0.0, "ninguém ainda"),
    ("documentacao_tecnica", "A cada merge no seu repositório a documentação sai atualizada por PR, sem ninguém escrever.",
     (4000, 8000), ("documentador", "fabricante", "gatilho_merge_cliente"), 0.5, "repositórios do próprio Cássio (o documentador já roda no loop)"),
)


def capacidade(pecas: list[str] | tuple[str, ...]) -> float:
    """Fração das peças que já existem como módulo em circulo/: a medida, não um número escrito."""
    return round(sum((PACOTE / f"{p}.py").exists() for p in pecas) / len(pecas), 2) if pecas else 0.0


def catalogo(store) -> list[dict]:
    lista = store.get(KV) or [dict(zip(("nome", "promessa", "valor_mes", "pecas", "proximidade", "cliente"), c, strict=True)) for c in CATALOGO]
    return [{**t, "capacidade": capacidade(t.get("pecas") or ())} for t in lista if t.get("nome")]


def regra(jev, qid: str, q: Question, state) -> Decision:
    """Regra local: capacidade pesa mais que proximidade (vender o que já entrega); valor só desempata."""
    t = state.get("trabalho") or {}
    p = 0.6 * float(t.get("capacidade", 0)) + 0.4 * float(t.get("proximidade", 0))
    return Decision(qid, "score", float(round(p * (len(NIVEIS) - 1))), 0.6, jev.source)


def ranquear(dl, store) -> list[dict]:
    """O Jev dá um score a cada trabalho e o kv guarda o catálogo com score; devolve o ranking."""
    lista = []
    for t in catalogo(store):
        d = dl.ask(PERGUNTA, Question("score", "How ready is this `trabalho` to be the first job the agency sells? Weigh `capacidade` "
                                                "(fraction already delivered by code without a human) above `proximidade` (how close a real "
                                                "paying client is); `valor_mes` only breaks ties.", NIVEIS), {"trabalho": t})
        lista.append({**t, "score": float(d.value), "por": getattr(d, "source", "local"), "em": time.time()})
    store.set(KV, lista)
    return ranking(store)


def ranking(store) -> list[dict]:
    """Os trabalhos já ranqueados, do maior score para o menor (capacidade e valor desempatam); vazio antes do Vigia."""
    return sorted((t for t in catalogo(store) if "score" in t),
                  key=lambda t: (t["score"], t["capacidade"], t["valor_mes"][1]), reverse=True)

"""Norte: para onde o loop evolui, em resultados mensuráveis — não em erros.

Até 25/10, 160 PRs do loop: ~85 % manutenção de si mesmo, 0 na direção do produto. Não era acaso: toda evolução
nasce de uma pergunta do conselho, e o conselho só perguntava sobre sinais internos (lição aberta, verificação que
falha, custo). Um sistema que só olha os próprios erros converge para "não falhar", nunca para "entregar valor".

O Norte é a visão de produto como números: o loop é uma fábrica de software para uma equipe de engenharia. Cada
resultado tem a medição (SQL nos dados do loop), a meta e a distância até ela. As perspectivas tech lead, PM e
mercado perguntam contra o Norte (perguntas.py); a cota do Developer garante que metade da capacidade vai para
itens de produto quando a entrega está saudável; o painel mostra os números. O Norte é lido, não escrito, pelo
loop: mudar a meta é decisão humana.
"""
from __future__ import annotations

import json
import time
from typing import Any

DIA = 86400.0
SEMANA = 7 * DIA
EIXOS_PRODUTO = ("produto", "missao")
COTA_PRODUTO = 0.5          # fração mínima do Developer para itens de produto com a entrega saudável
JANELA_COTA_H = 24

RESULTADOS = (
    ("lead_time_h", "Pedido vira PR mergeado em menos de 24 h (mediana, 7 dias)", 24.0, "menor"),
    ("prs_produto_semana", "PRs de produto por semana (o que o time usa, não o que o loop conserta)", 5.0, "maior"),
    ("fracao_produto", "Fração dos PRs mergeados que são produto (7 dias)", 0.5, "maior"),
    ("console_semana", "PRs por semana que evoluem o console do time (painel, Equipe ao vivo)", 1.0, "maior"),
    ("merge_sem_conserto", "PRs que entram na 1ª tentativa, sem conserto (7 dias)", 0.7, "maior"),
    ("repositorios", "Repositórios de equipe atendidos", 2.0, "maior"),
)


def eixo_do_item(store, item_id: int | None) -> str | None:
    if item_id is None:
        return None
    r = store.one("SELECT eixo FROM perguntas WHERE item_id=? AND eixo IS NOT NULL ORDER BY id DESC LIMIT 1", (item_id,))
    return r["eixo"] if r else None


def e_produto(store, item: dict | None) -> bool:
    """Item de produto: a pergunta de origem tem eixo produto/missão, ou é um pedido seu que não é erro."""
    if not item:
        return False
    if item.get("origem") == "pedido_cassio":
        return True
    return (eixo_do_item(store, item.get("id")) in EIXOS_PRODUTO)


def _mergeados(store, desde: float) -> list[dict]:
    return [dict(r) for r in store.q("SELECT number, item_id, consertos, arquivos, created_at, updated_at FROM prs "
                                     "WHERE status='mergeado' AND updated_at>=?", (desde,))]


def medir(store, agora: float | None = None) -> dict[str, Any]:
    """Cada resultado do Norte com o valor medido agora, a meta e a distância (0 = na meta, 1 = longe)."""
    agora = agora or time.time()
    prs = _mergeados(store, agora - SEMANA)
    produto = [p for p in prs if e_produto(store, dict(store.one("SELECT id, origem FROM roadmap WHERE id=?", (p["item_id"],)) or {}))]
    console = [p for p in prs if any(a.endswith(".html") or a.endswith("tema.py") for a in (json.loads(p["arquivos"]) if p["arquivos"] else []))]
    leads = []
    for p in prs:
        r = store.one("SELECT created_at FROM roadmap WHERE id=?", (p["item_id"],)) if p["item_id"] else None
        if r:
            leads.append((float(p["updated_at"]) - float(r["created_at"])) / 3600)
    leads.sort()
    repos = store.one("SELECT COUNT(DISTINCT COALESCE(repo, kit)) n FROM projects WHERE status!='arquivado' AND kit='circulo'")["n"] \
        if "repo" in {r["name"] for r in store.q("PRAGMA table_info(projects)")} else 1
    valores = {
        "lead_time_h": round(leads[len(leads) // 2], 1) if leads else None,
        "prs_produto_semana": len(produto),
        "fracao_produto": round(len(produto) / len(prs), 2) if prs else None,
        "console_semana": len(console),
        "merge_sem_conserto": round(sum(1 for p in prs if not int(p["consertos"] or 0)) / len(prs), 2) if prs else None,
        "repositorios": int(repos or 1),
    }
    out = {}
    for chave, descricao, meta, sentido in RESULTADOS:
        v = valores[chave]
        if v is None:
            dist = 1.0
        elif sentido == "menor":
            dist = 0.0 if v <= meta else min(1.0, (v - meta) / max(meta, 1e-9))
        else:
            dist = 0.0 if v >= meta else min(1.0, (meta - v) / max(meta, 1e-9))
        out[chave] = {"descricao": descricao, "valor": v, "meta": meta, "sentido": sentido, "distancia": round(dist, 2)}
    out["_resumo"] = {"prs_7d": len(prs), "produto_7d": len(produto), "medido_em": agora}
    return out


def fracao_produto_recente(store, agora: float | None = None) -> float | None:
    """Fração dos PRs mergeados nas últimas JANELA_COTA_H horas que são produto; None sem PR."""
    agora = agora or time.time()
    prs = _mergeados(store, agora - JANELA_COTA_H * 3600)
    if not prs:
        return None
    n = sum(1 for p in prs if e_produto(store, dict(store.one("SELECT id, origem FROM roadmap WHERE id=?", (p["item_id"],)) or {})))
    return n / len(prs)


def prefere_produto(store, agora: float | None = None) -> bool:
    """A cota: com a entrega saudável (sentinela quieta) e menos de COTA_PRODUTO dos PRs recentes sendo produto,
    o Developer pega um item de produto antes dos de manutenção. Erro "Urgente" (Médico) continua na frente."""
    if store.get("entrega_parada"):
        return False
    f = fracao_produto_recente(store, agora)
    return f is None or f < COTA_PRODUTO


def item_de_produto(store, extra_sql: str = "", args: tuple = ()) -> dict | None:
    """O item de produto pendente e estudado mais prioritário (pedido seu, ou item cuja pergunta tem eixo produto/missão)."""
    r = store.one("SELECT * FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 AND estudo IS NOT NULL "
                  "AND COALESCE(evidencia,'') NOT LIKE '%depende de você%' AND (origem='pedido_cassio' OR EXISTS "
                  "(SELECT 1 FROM perguntas p WHERE p.item_id=roadmap.id AND p.eixo IN ('produto','missao')))" + extra_sql +
                  " ORDER BY CASE origem WHEN 'pedido_cassio' THEN 0 ELSE 1 END, ordem LIMIT 1", args)
    return dict(r) if r else None


PRAZO_H = 48                 # Cássio (25/10): se em 2 dias a fração de produto não evoluiu, a solução é reescrita


def marco(store, agora: float | None = None) -> dict:
    """O ponto de partida do prazo: gravado uma vez (primeiro giro com o Norte) e a cada reescrita."""
    agora = agora or time.time()
    m = store.get("norte_marco")
    if m:
        return m
    med = medir(store, agora)
    m = {"em": agora, "fracao_produto": med["fracao_produto"]["valor"], "prs_produto": med["prs_produto_semana"]["valor"],
         "console": med["console_semana"]["valor"], "prazo_em": agora + PRAZO_H * 3600, "cobrado": False}
    store.set("norte_marco", m)
    return m


def cobrar(store, reply, agora: float | None = None) -> dict | None:
    """No fim do prazo, compara com o marco: evoluiu (mais PRs de produto, fração maior ou console mexido) ou não.
    Sem evolução, avisa e põe no "Precisa de você": a solução precisa ser reescrita, não insistida."""
    agora = agora or time.time()
    m = marco(store, agora)
    if m.get("cobrado") or agora < float(m["prazo_em"]):
        return None
    med = medir(store, agora)
    depois = {"fracao_produto": med["fracao_produto"]["valor"], "prs_produto": med["prs_produto_semana"]["valor"], "console": med["console_semana"]["valor"]}
    evoluiu = (depois["prs_produto"] or 0) > (m.get("prs_produto") or 0) or (depois["fracao_produto"] or 0) > (m.get("fracao_produto") or 0) + 0.1 \
        or (depois["console"] or 0) > (m.get("console") or 0)
    veredito = {**m, "cobrado": True, "cobrado_em": agora, "depois": depois, "evoluiu": evoluiu}
    store.set("norte_marco", veredito)
    if evoluiu:
        reply(f"Norte: em {PRAZO_H} h a fração de produto foi de {m.get('fracao_produto')} para {depois['fracao_produto']} "
              f"({m.get('prs_produto')} → {depois['prs_produto']} PRs de produto na semana). A direção mudou; o prazo recomeça.", "saude")
        store.set("norte_marco", None)
        marco(store, agora)
    else:
        reply(f"Norte: {PRAZO_H} h e a fração de produto não evoluiu ({m.get('fracao_produto')} → {depois['fracao_produto']}; "
              f"{depois['prs_produto']} PR(s) de produto, {depois['console']} no console). A solução precisa ser reescrita, não insistida.", "saude")
    return veredito


def resumo(store) -> dict:
    m = medir(store)
    r = m.pop("_resumo")
    return {"resultados": [{"chave": k, **v} for k, v in m.items()], "cota": COTA_PRODUTO, "marco": store.get("norte_marco"),
            "fracao_24h": fracao_produto_recente(store), "prefere_produto": prefere_produto(store), **r}

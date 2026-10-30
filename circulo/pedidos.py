"""Canal de origem de cada pedido (pergunta do conselho #441): só mede, não integra Slack nem GitHub.

`Store.enqueue` grava `canal` no payload de todo pedido; `por_canal_7d` alimenta a evidência geral do Planejador,
para decidir com número se vale abrir pedido direto de issue, comentário de PR ou Slack.

`lancamento` (pergunta do conselho #557): pedido de uma linha com cara de gasto ('gastei 42,90 mercado ontem') vai
para o parser de `lancamento_manual` antes de virar missão ou item do roteiro; grava com a dedupe por hash e devolve
'Registrado…' ou a pergunta só do campo que faltou. Mensagem a outro projeto segue como antes: a de finanças já tem
o parser do Coletor, e a de um projeto geral é orientação para ele."""
from __future__ import annotations

import re
import time
from datetime import date

from .budget import TZ
from .decision import norm
from .jobs import HUMANO, JANELA
from .lancamento_manual import Manual, parse_linha_manual, registrar_linha_manual

CANAIS = ("painel", "issue", "comentario_pr", "slack")
DESCONHECIDO = "desconhecido"
VERBOS_DE_GASTO = ("gastei", "paguei", "comprei")
MAX_PALAVRAS, MAX_DESCRICAO_SEM_VERBO = 8, 3       # 'padaria pão bom R$ 12,50'; 'preciso de 3,50 de gasolina' é pedido
_DINHEIRO = re.compile(r"[+-]?(?:r\$)?\d[\d.]*,\d{2}|r\$\d[\d.]*")   # '42,90' e 'R$ 30' são dinheiro; '3,5 litros' e '3 posts' não


def _linha_de_gasto(texto: str, regras: list[dict], hoje: date) -> str | None:
    """A linha sem o verbo, se o texto parece lançamento: uma linha curta que começa com verbo de gasto, ou valor em
    dinheiro com descrição curta que a política já sabe categorizar (sem verbo, a dúvida fica com a missão)."""
    palavras = texto.split()
    if "\n" in texto.strip() or not 2 <= len(palavras) <= MAX_PALAVRAS:
        return None
    if norm(palavras[0]) in VERBOS_DE_GASTO:
        return " ".join(palavras[1:])
    if not any(_DINHEIRO.fullmatch(t) for t in norm(texto).replace("r$ ", "r$").split()):
        return None
    m = parse_linha_manual(texto, hoje, regras)
    sabida = isinstance(m, Manual) and m.categoria != "outros" and len(m.descricao.split()) <= MAX_DESCRICAO_SEM_VERBO
    return texto if sabida else None


def lancamento(ctx, kind: str, payload: dict) -> str | None:
    """A resposta já enviada, se o pedido era lançamento (gravado ou com a pergunta do que faltou); None segue o fluxo."""
    if kind == "mensagem":
        proj = ctx.store.one("SELECT kit FROM projects WHERE id=?", (payload.get("projeto"),))
        if proj is None or proj["kit"] != "circulo":
            return None
    hoje = ctx.now().astimezone(TZ).date()
    linha = _linha_de_gasto(str(payload.get("text") or payload.get("pedido") or ""), ctx.policy.get("rules", []), hoje)
    if linha is None:
        return None
    _, pergunta = registrar_linha_manual(ctx.store, linha, hoje)
    resposta = pergunta or f"Registrado: {linha}."
    ctx.reply(resposta)
    return resposta


def canal(payload: dict) -> str:
    """O canal declarado (ou a origem) se for um dos conhecidos; qualquer outro vira 'desconhecido'."""
    c = payload.get("canal") or payload.get("origem")
    return c if c in CANAIS else DESCONHECIDO


def por_canal_7d(store, agora: float | None = None) -> dict[str, int]:
    """Pedidos humanos dos últimos 7 dias por canal; todo canal aparece, mesmo com zero."""
    agora = time.time() if agora is None else agora
    rows = store.q(f"SELECT COALESCE(json_extract(payload,'$.canal'),'{DESCONHECIDO}') canal, COUNT(*) n FROM events "
                   f"WHERE {HUMANO} AND created_at>? GROUP BY 1", (agora - JANELA,))
    contagem = dict.fromkeys((*CANAIS, DESCONHECIDO), 0)
    for r in rows:
        contagem[r["canal"] if r["canal"] in contagem else DESCONHECIDO] += r["n"]
    return contagem

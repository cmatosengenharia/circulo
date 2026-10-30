"""Candidatos a modelo menor por papel de LLM (pergunta #553): só mede e ranqueia, não roda sombra nem troca modelo.

Por papel em 7 dias: n, falhas, tokens e tokens por chamada, do maior consumo ao menor. Candidato a rodar em sombra
num modelo menor: saída estruturada curta, falha zero e n≥30. O primeiro candidato é o alvo da sombra.
"""
from __future__ import annotations

from html import escape

SAIDA_CURTA = ("planejador", "questionador", "validador", "estudo_duvida")
MIN_CHAMADAS_SOMBRA = 30
JANELA = 7 * 86400


def modelos_menores(conn, agora: float) -> list[dict]:
    return [{"papel": p, "n": n, "falhas": f, "tokens": t, "tokens_por_chamada": round(t / n),
             "candidato": p in SAIDA_CURTA and f == 0 and n >= MIN_CHAMADAS_SOMBRA}
            for p, n, f, t in conn.execute(
                "SELECT papel, COUNT(*), SUM(ok=0), SUM(tokens) FROM llm_calls WHERE created_at >= ? "
                "GROUP BY papel ORDER BY SUM(tokens) DESC, papel", (agora - JANELA,))]


def card(papeis: list[dict]) -> str:
    cand = [m for m in papeis if m["candidato"]]
    return ('<section class="card falhas" aria-label="Candidatos a modelo menor"><span>Candidatos a modelo menor (7 d)'
            f'</span><b>{len(cand)}</b><small>saída curta, 0 falhas, ≥{MIN_CHAMADAS_SOMBRA} chamadas; por tokens</small><ol>'
            + "".join(f'<li>{escape(m["papel"])} <b>{m["tokens"]} tokens</b> <small>{m["n"]} chamadas · '
                      f'{m["tokens_por_chamada"]} tokens/chamada</small></li>' for m in cand) + "</ol></section>")

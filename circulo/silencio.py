"""Silêncio suspeito (pergunta #619): zero incidente aberto só é verde se o loop também não estagnou nem tem lição
de estrutura aberta nos últimos 7 dias; ausência de alerta não prova saúde."""
from __future__ import annotations

JANELA = 7 * 86400
LICAO_ABERTA = ("aberta", "em_correcao", "reincidente", "sem_prevencao")
REINCIDE_SUSPEITO = 3


def sinais_7d(conn, agora: float) -> tuple[int, int]:
    """(estagnações, lições de estrutura abertas) dos últimos 7 dias, lidas do SQLite (sqlite3.Connection)."""
    estag = conn.execute("SELECT COUNT(*) FROM verificacoes WHERE ponto='loop:progresso' AND ok=0 AND created_at >= ?",
                         (agora - JANELA,)).fetchone()[0]
    estrut = conn.execute(f"SELECT COUNT(*) FROM licoes WHERE classe='estrutural' AND updated_at >= ? AND status IN "
                          f"({','.join('?' * len(LICAO_ABERTA))})", (agora - JANELA, *LICAO_ABERTA)).fetchone()[0]
    return estag, estrut


def reincidentes(conn) -> list[tuple[int, int]]:
    """(id, reincidências) das lições de estrutura que reincidiram ≥REINCIDE_SUSPEITO vezes e não estão fechadas,
    sem janela de tempo (pergunta #184): uma causa que volta não fica resolvida por ter ficado quieta."""
    return [tuple(r) for r in conn.execute(
        "SELECT id, reincidencias FROM licoes WHERE classe='estrutural' AND reincidencias >= ? AND status NOT IN "
        "('fechada','obsoleta') ORDER BY reincidencias DESC, id", (REINCIDE_SUSPEITO,))]


def card_incidentes(abertos: int, estagnacoes: int, licoes_de_estrutura: int,
                    reincidentes: list[tuple[int, int]] = ()) -> dict:
    """Tom (token do tema), glifo, valor e texto do card de incidentes; a cor nunca vem sem glifo e palavra."""
    if abertos:
        return {"tom": "bad", "glifo": "✕", "valor": str(abertos), "texto": f"{abertos} incidente(s) aberto(s)"}
    if reincidentes:
        lista = ", ".join(f"#{lid} ({n}x)" for lid, n in reincidentes)
        return {"tom": "llm", "glifo": "!", "valor": "0", "suspeito": [lid for lid, _ in reincidentes],
                "texto": f"suspeito: sem incidente, mas lições de estrutura reincidentes abertas: {lista}"}
    if estagnacoes or licoes_de_estrutura:
        return {"tom": "llm", "glifo": "!", "valor": "0",
                "texto": f"sem incidente, mas {estagnacoes} estagnações e {licoes_de_estrutura} lições de estrutura"}
    return {"tom": "ok", "glifo": "✓", "valor": "0", "texto": "sem incidente, estagnação nem lição de estrutura"}

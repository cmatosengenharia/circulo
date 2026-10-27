"""Causa normalizada de cada barra em missao:verificacao_saida (pergunta #363): a falha é classificada, não só contada."""
from __future__ import annotations

PONTO = "missao:verificacao_saida"

# checagem do verify_output → causa; a ordem desempata notas iguais (formato ruim costuma arrastar as outras)
CAUSAS = {"verify_formato": "formato_invalido", "verify_pedido": "criterio_nao_atendido",
          "verify_injecao": "injecao", "verify_dados": "dados_sensiveis"}


def causa_da_barra(saida: str, checks: dict) -> str:
    """A causa é a checagem de nota mais baixa; saída sem texto é `saida_vazia` antes de qualquer checagem."""
    if not (saida or "").strip():
        return "saida_vazia"
    return CAUSAS[min(CAUSAS, key=lambda k: checks.get(k, 1.0))]

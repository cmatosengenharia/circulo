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


AMOSTRA_CABECA, AMOSTRA_CAUDA = 5000, 2500


def amostra_da_saida(output: str, cabeca: int = AMOSTRA_CABECA, cauda: int = AMOSTRA_CAUDA) -> tuple[str, bool]:
    """O que o Jev vê de uma saída longa: o começo e o FIM, com o meio marcado como omitido. Antes ia só `output[:8000]`:
    toda entrega de missão acima disso chegava cortada no meio de uma frase, o Jev respondia (certo) que estava
    "cortada" e `verify_formato` ficou em 0,04–0,22 em 9 de 9 ciclos de construção (missões 3, 4 e 5): nenhuma missão
    passou da verificação pós-LLM e todas foram parar em manutenção."""
    if len(output) <= cabeca + cauda:
        return output, False
    omitidos = len(output) - cabeca - cauda
    return (output[:cabeca] + f"\n\n[… {omitidos} caracteres do meio omitidos nesta amostra; a saída completa tem "
            f"{len(output)} caracteres. O fim real vem a seguir …]\n\n" + output[-cauda:]), True

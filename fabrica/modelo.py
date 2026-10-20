"""O vocabulário da fábrica: estações, papéis, cartão, evidência e as transições permitidas.

Tudo que a fábrica sabe sobre um trabalho está num CARTÃO. Ele nasce de um pedido (do humano ou de um achado da
própria fábrica), e anda pelas estações. Cada passagem gera um PASSO com evidências; uma evidência é sempre
rotulada: `medido` (saiu de um comando, teste ou arquivo), `inferido` (concluído a partir de dado medido) ou
`chutado` (opinião). Só evidência medida libera a estação seguinte.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ------------------------------------------------------------------ a equipe (uma fábrica de software)
PAPEIS: dict[str, dict[str, str]] = {
    "po": {"nome": "Gerente de produto", "faz": "Lê o pedido, escreve o cartão: o que muda, como se verifica, o que é sucesso."},
    "arquiteto": {"nome": "Arquiteto", "faz": "Decide onde e como mudar, o que não pode ser tocado e qual é o comando de verificação."},
    "dev": {"nome": "Desenvolvedor", "faz": "Reproduz primeiro (teste que falha), corrige, roda lint e testes, deixa um commit pequeno."},
    "qa": {"nome": "QA", "faz": "Roda a verificação na superfície real e compara antes/depois; devolve com o log se não passar."},
    "revisor": {"nome": "Revisor", "faz": "Lê o diff: menor mudança, nada protegido tocado, teste novo, passos pulados declarados."},
    "release": {"nome": "Release", "faz": "Abre o PR, espera o CI, mescla, implanta e confere a produção; desfaz se piorar."},
}
ORDEM = ("po", "arquiteto", "dev", "qa", "revisor", "release")

# ------------------------------------------------------------------ estados do cartão e quem cuida de cada um
ESTADOS: dict[str, str] = {
    "novo": "po", "planejado": "arquiteto", "em_desenvolvimento": "dev", "verificando": "qa", "em_revisao": "revisor",
    "liberando": "release", "concluido": "", "bloqueado": "", "cancelado": "",
}
# de cada estado, para onde o papel pode mandar o cartão (adiante, ou de volta com motivo)
TRANSICOES: dict[str, tuple[str, ...]] = {
    "novo": ("planejado", "cancelado", "bloqueado"),
    "planejado": ("em_desenvolvimento", "novo", "bloqueado"),
    "em_desenvolvimento": ("verificando", "bloqueado"),
    "verificando": ("em_revisao", "em_desenvolvimento", "bloqueado"),
    "em_revisao": ("liberando", "em_desenvolvimento", "planejado", "bloqueado"),
    "liberando": ("concluido", "em_desenvolvimento", "bloqueado"),
}
FINAIS = ("concluido", "bloqueado", "cancelado")
BASES = ("medido", "inferido", "chutado")
MAX_DEVOLUCOES = 2          # devoluções seguidas numa mesma estação antes de bloquear e chamar o humano


@dataclass
class Evidencia:
    base: str                       # medido | inferido | chutado
    texto: str
    dado: Any = None                # o número, o trecho de log, o caminho

    def __post_init__(self):
        if self.base not in BASES:
            raise ValueError(f"base de evidência inválida: {self.base}")


@dataclass
class Resultado:
    """O que uma estação devolve: para onde o cartão vai, por quê, e com que evidência."""
    para: str
    mensagem: str
    evidencias: list[Evidencia] = field(default_factory=list)
    dados: dict[str, Any] = field(default_factory=dict)       # o que a estação seguinte precisa (branch, pr, plano…)

    @property
    def medida(self) -> bool:
        return any(e.base == "medido" for e in self.evidencias)


def transicao_valida(de: str, para: str) -> bool:
    return para in TRANSICOES.get(de, ())


def e_devolucao(de: str, para: str) -> bool:
    """Voltar para uma estação anterior na ordem é devolução (conta para o limite)."""
    if para in FINAIS or de in FINAIS:
        return False
    return ORDEM.index(ESTADOS[para]) < ORDEM.index(ESTADOS[de])

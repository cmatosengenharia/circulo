"""Roadmap: todo item nasce de uma pergunta do conselho; `Origem` só existe com um pergunta_id válido."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Origem:
    pergunta_id: int

    def __post_init__(self) -> None:
        if type(self.pergunta_id) is not int or self.pergunta_id <= 0:
            raise ValueError(f"item do roadmap sem pergunta de origem: pergunta_id={self.pergunta_id!r}")

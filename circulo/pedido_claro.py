"""Portão de pedido (pergunta do conselho #323): antes da LLM, o pedido do Developer (título + detalhe do item) cita
critério de aceite, arquivo alvo (.py) e resultado esperado? Se falta algum, sai UMA pergunta de esclarecimento, a do
primeiro campo ausente. Por ora só mede: o veredito de cada item fica em `pedidos_claros`, sem bloquear o Developer."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from .state import Store

CRITERIO, ARQUIVO, RESULTADO = "criterio", "arquivo", "resultado"
PADROES = {
    CRITERIO: re.compile(r"crit[ée]rios? de aceite|\baceite\s*:|\btestes?\b|\btests/", re.I),
    ARQUIVO: re.compile(r"[\w./-]+\.py\b"),
    RESULTADO: re.compile(r"\bsucesso\s*:|resultado esperado|\besperad[oa]s?\s*:|\balvo\s*:", re.I),
}
PERGUNTAS = {
    CRITERIO: "Qual teste ou critério de aceite mostra que o pedido está pronto?",
    ARQUIVO: "Qual arquivo ou módulo (caminho .py) deve mudar?",
    RESULTADO: "Qual resultado se espera depois da mudança (Sucesso: ...)?",
}
JANELA = 24 * 3600
ESQUEMA = """
CREATE TABLE IF NOT EXISTS pedidos_claros (
  item INTEGER PRIMARY KEY,
  completo INTEGER NOT NULL,
  faltando TEXT NOT NULL,
  pergunta TEXT,
  created_at REAL NOT NULL
)
"""


@dataclass(frozen=True)
class Veredito:
    faltando: tuple[str, ...]

    @property
    def completo(self) -> bool:
        return not self.faltando

    @property
    def pergunta(self) -> str | None:
        return PERGUNTAS[self.faltando[0]] if self.faltando else None


def avaliar(titulo: str | None, detalhe: str | None) -> Veredito:
    """Os campos ausentes no pedido, na ordem critério → arquivo → resultado. Pura."""
    texto = f"{titulo or ''}\n{detalhe or ''}"
    return Veredito(tuple(campo for campo, padrao in PADROES.items() if not padrao.search(texto)))


def registrar(store: Store, item: dict, agora: float | None = None) -> Veredito:
    """Guarda o veredito do item (um por item; o detalhe reescrito pelo Estudo atualiza, a hora da 1ª vez fica)."""
    v = avaliar(item.get("titulo"), item.get("detalhe"))
    store.x(ESQUEMA)
    store.x("INSERT INTO pedidos_claros(item, completo, faltando, pergunta, created_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(item) DO UPDATE SET completo=excluded.completo, faltando=excluded.faltando, "
            "pergunta=excluded.pergunta",
            (item["id"], int(v.completo), ",".join(v.faltando), v.pergunta, time.time() if agora is None else agora))
    return v


def fracao_incompletos(store: Store, agora: float | None = None) -> float | None:
    """Fração dos pedidos avaliados nas últimas 24 h sem algum dos 3 campos; None sem pedido avaliado."""
    store.x(ESQUEMA)
    r = store.one("SELECT COUNT(*) n, SUM(1 - completo) incompletos FROM pedidos_claros WHERE created_at>=?",
                  ((time.time() if agora is None else agora) - JANELA,))
    return r["incompletos"] / r["n"] if r["n"] else None

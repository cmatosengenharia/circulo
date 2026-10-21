"""A única forma de ler o objeto JSON que uma LLM respondeu (lição #22).

A resposta nem sempre começa no objeto: com busca na web, a LLM narra antes ("Vou pesquisar {tema}...") e um `{` da
narração fazia o leitor de cada módulo (o primeiro `{`, ou `\\{.*\\}` guloso) descartar a resposta inteira como "sem JSON
válido". Aqui cada `{` do texto é um começo possível, e vale o primeiro objeto que o próprio papel aceita: ler por uma
chave devolvia o rascunho largado antes de mais uma busca, ou o formato ecoado ("adotar|adaptar"), e o papel descartava
a resposta boa que vinha depois.
"""
from __future__ import annotations

import json
from typing import Callable, TypeVar

T = TypeVar("T")


def _comecos(texto: str):
    i = (texto or "").find("{")
    while i >= 0:
        yield texto[i:]
        i = texto.find("{", i + 1)


def _inteiro(s: str):
    try:
        return json.JSONDecoder().raw_decode(s)[0]
    except json.JSONDecodeError:
        return None


def _ate_o_corte(s: str):
    """Cortado pelo limite de tokens: vale o objeto até o último valor completo."""
    pilha, cortes, na_string, escape = [], [], False, False
    for i, c in enumerate(s):
        if na_string:
            escape, na_string = (False, True) if escape else (c == "\\", c != '"')
        elif c == '"':
            na_string = True
        elif c in "{[":
            pilha.append("}" if c == "{" else "]")
        elif c in "}]" and pilha:
            pilha.pop()
        elif c == ",":
            cortes.append((i, "".join(reversed(pilha))))
    if not na_string:       # cortado logo depois de um valor inteiro: fechar as chaves não perde o último valor
        cortes.append((len(s), "".join(reversed(pilha))))
    for i, fecho in reversed(cortes):
        try:
            return json.loads(s[:i] + fecho)
        except json.JSONDecodeError:
            continue
    return None


def objeto(texto: str, aceita: Callable[[dict], T | None]) -> T | None:
    """O que `aceita` devolve para o primeiro objeto JSON inteiro do texto que ele não recusa (None)."""
    for s in _comecos(texto):
        d = _inteiro(s)
        if isinstance(d, dict) and (r := aceita(d)) is not None:
            return r
    return None


def objeto_ou_corte(texto: str, aceita: Callable[[dict, bool], T | None]) -> T | None:
    """Como `objeto`, e se nenhum inteiro serve, o primeiro cortado pelo limite de tokens que `aceita(d, True)` não recusa."""
    r = objeto(texto, lambda d: aceita(d, False))
    if r is not None:
        return r
    for s in _comecos(texto):
        d = _ate_o_corte(s)
        if isinstance(d, dict) and (r := aceita(d, True)) is not None:
            return r
    return None

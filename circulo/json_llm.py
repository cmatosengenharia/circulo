"""A única forma de ler o objeto JSON que uma LLM respondeu (lição #22).

A resposta nem sempre começa no objeto: com busca na web, a LLM narra antes ("Vou pesquisar {tema}...") e um `{` da
narração fazia o leitor de cada módulo (o primeiro `{`, ou `\\{.*\\}` guloso) descartar a resposta inteira como "sem JSON
válido". Aqui cada `{` do texto é um começo possível, e vale o primeiro objeto que tem a chave que o papel pede.
"""
from __future__ import annotations

import json


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
    for i, fecho in reversed(cortes):
        try:
            return json.loads(s[:i] + fecho)
        except json.JSONDecodeError:
            continue
    return None


def objeto(texto: str, chave: str) -> dict | None:
    """O primeiro objeto JSON inteiro do texto que tem `chave`."""
    for s in _comecos(texto):
        d = _inteiro(s)
        if isinstance(d, dict) and chave in d:
            return d
    return None


def objeto_ou_corte(texto: str, chave: str) -> tuple[dict | None, bool]:
    """Como `objeto`, e se nenhum veio inteiro, o primeiro cortado pelo limite de tokens que tem `chave` (e True)."""
    d = objeto(texto, chave)
    if d is not None:
        return d, False
    for s in _comecos(texto):
        d = _ate_o_corte(s)
        if isinstance(d, dict) and chave in d:
            return d, True
    return None, False

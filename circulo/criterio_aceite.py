"""Critério de aceite verificável por pedido: o Arquiteto define, o portão confere, o PR mostra ✓/✗.

O critério é a linha `Sucesso:` que o Estudo (Arquiteto) grava no detalhe. Ele congela na 1ª vez que o item entra no
Developer (o portão de pedido, `pedido_claro.registrar`): reescritas posteriores do detalhe não o mudam.

Conferência, antes do PR (portão `PORTAO`, dentro de `neuronios.avaliar_aprendidos`):
- check executável: o critério cita testes (`tests/x.py::test_y`): eles rodam no worktree; passar = ✓;
- frase: o Validador (LLM) julga contra o diff (`julgar`); o veredito vale para o diff que ele viu. ✗ no mesmo diff
  barra o PR; diff corrigido depois do ✗ segue como '?' (não reconferido), nunca como ✓.
O corpo do PR ganha `linha_pr` (em `developer.GitHubComConvencoes`)."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .neuronios import Resultado
from .prova import criterio as linha_sucesso
from .state import Store

PORTAO = "critério de aceite"
_TESTE = r"(?<![\w/.-])((?:[\w.-]+/)*test_\w*\.py(?:::[\w\[\]-]+)*)"
ESQUEMA = """
CREATE TABLE IF NOT EXISTS criterios_aceite (
  item INTEGER PRIMARY KEY,
  texto TEXT NOT NULL,
  testes TEXT NOT NULL,
  ok INTEGER,
  evidencia TEXT,
  diff TEXT,
  created_at REAL NOT NULL,
  conferido_em REAL
)
"""


@dataclass(frozen=True)
class Criterio:
    texto: str
    testes: tuple[str, ...]          # vazio = frase, conferida pelo Validador


def extrair(detalhe: str | None) -> Criterio | None:
    """O critério da linha `Sucesso:` e os testes que ele cita (check executável). Pura."""
    texto = linha_sucesso(detalhe or "")
    if not texto:
        return None
    return Criterio(texto, tuple(dict.fromkeys(re.findall(_TESTE, texto))))


def congelar(store: Store, item: dict) -> dict | None:
    """Grava o critério do item na 1ª vez; depois disso ele não muda. Devolve o congelado (None sem `Sucesso:`)."""
    store.x(ESQUEMA)
    c = extrair(item.get("detalhe"))
    if c:
        store.x("INSERT OR IGNORE INTO criterios_aceite(item, texto, testes, created_at) VALUES(?,?,?,?)",
                (item["id"], c.texto, json.dumps(c.testes), time.time()))
    return _ler(store, item["id"])


def _ler(store: Store, item_id: int) -> dict | None:
    r = store.one("SELECT * FROM criterios_aceite WHERE item=?", (item_id,))
    return {**dict(r), "testes": json.loads(r["testes"])} if r else None


def congelado(store: Store, item_id: int | None) -> dict | None:
    """O critério congelado do item; o item que chegou ao portão sem passar pelo pick congela aqui."""
    if item_id is None:
        return None
    store.x(ESQUEMA)
    if (c := _ler(store, item_id)) is not None:
        return c
    item = store.one("SELECT id, detalhe FROM roadmap WHERE id=?", (item_id,))
    return congelar(store, dict(item)) if item else None


def assinatura(adicionadas: dict[str, list[str]]) -> str:
    """O diff que o veredito viu (linhas adicionadas por arquivo)."""
    return hashlib.sha256(json.dumps(adicionadas, sort_keys=True).encode()).hexdigest()[:16]


def _gravar(store: Store, item_id: int, ok: bool | None, evidencia: str, diff: str | None) -> None:
    store.x("UPDATE criterios_aceite SET ok=?, evidencia=?, diff=?, conferido_em=? WHERE item=?",
            (None if ok is None else int(ok), evidencia[:500], diff, time.time(), item_id))


def julgar(store: Store, item_id: int | None, ok: bool, evidencia: str, adicionadas: dict[str, list[str]]) -> None:
    """O veredito do Validador sobre o critério de frase, preso ao diff que ele viu."""
    c = congelado(store, item_id)
    if c and not c["testes"]:
        _gravar(store, c["item"], ok, evidencia or ("atendido" if ok else "não atendido"), assinatura(adicionadas))


def conferir(store: Store, item_id: int | None, wt: Path, adicionadas: dict[str, list[str]], env: dict) -> Resultado | None:
    """O portão: None sem critério congelado. Executável roda os testes citados; frase usa o veredito do Validador."""
    c = congelado(store, item_id)
    if not c:
        return None
    if c["testes"]:
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", *c["testes"]], cwd=wt, capture_output=True,
                           text=True, timeout=900, env=env)
        ok = p.returncode == 0
        fim = (p.stdout + p.stderr).strip().splitlines()
        evidencia = f"`{' '.join(c['testes'])}` " + ("passou" if ok else "falhou") + (f" ({fim[-1][:200]})" if fim else "")
        _gravar(store, c["item"], ok, evidencia, assinatura(adicionadas))
        return Resultado(PORTAO, ok, "" if ok else f"{c['texto']}: {evidencia}")
    if c["ok"] == 0 and c["diff"] == assinatura(adicionadas):
        return Resultado(PORTAO, False, f"{c['texto']}: Validador: {c['evidencia']}")
    if c["ok"] == 0:
        _gravar(store, c["item"], None, f"corrigido depois do ✗ do Validador ({c['evidencia']}); não reconferido", None)
    return Resultado(PORTAO, True)


def linha_pr(store: Store, item_id: int | None) -> str:
    """'Critério: ✓/✗/? <critério> — <evidência>' para o corpo do PR."""
    c = congelado(store, item_id)
    if not c:
        return "Critério: — o item não tem linha `Sucesso:`"
    marca = {1: "✓", 0: "✗"}.get(c["ok"], "?")
    return f"Critério: {marca} {c['texto']} — {c['evidencia'] or 'não conferido (Validador indisponível)'}"

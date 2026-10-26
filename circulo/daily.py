"""Pauta da daily às 8h, por assunto: o que fiz ontem (das notas), o que farei hoje (pendências) e o que me bloqueia.

As notas são arquivos de texto do humano em `<dados>/notas/` (o loop só lê, nunca escreve):
    notas/<assunto>/qualquer.md        o assunto é a pasta (a mesma estrutura de pastas por assunto do Mac)
    notas/solta.md                     com cabeçalho `---\\nassunto: x\\n---` (sem ele, o assunto é "geral")
Dentro de cada nota:
    - [ ] texto                        pendência aberta: entra em "hoje", venha de qualquer nota
    bloqueio: texto  (ou `- [ ] bloqueio: texto`)   entra em "bloqueia"
    qualquer outra linha (ou `- [x] texto`)         entra em "ontem" se a nota é de ontem
A data da nota é a do nome (`2026-10-25-...md`) ou, sem ela, a da última modificação.

A partir das HORA h, uma vez por dia, a pauta (até MAX_LINHAS linhas) vai ao console e à notificação do macOS.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .caixa import _cabecalho
from .sentinela import notificar_mac

PASTA = "notas"
HORA = 8
MAX_LINHAS = 10
MAX_CHARS = 200
CHAVE = "daily_ultima"

_DATA_NO_NOME = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_ABERTA = re.compile(r"^[-*]\s*\[\s\]\s*(.+)$")
_FEITA = re.compile(r"^[-*]\s*\[[xX]\]\s*(.+)$")
_BLOQUEIO = re.compile(r"^bloqueio:\s*(.+)$", re.I)


def _dia(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))


def _ler_notas(pasta: Path) -> list[tuple[str, str, str]]:
    """(assunto, dia da nota, texto) de cada nota."""
    out = []
    for arq in sorted(p for p in pasta.rglob("*") if p.is_file() and p.suffix.lower() in (".md", ".txt")):
        try:
            cab, corpo = _cabecalho(arq.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        rel = arq.relative_to(pasta).parts
        assunto = cab.get("assunto") or (rel[0] if len(rel) > 1 else "geral")
        m = _DATA_NO_NOME.match(arq.name)
        out.append((assunto, m.group(1) if m else _dia(arq.stat().st_mtime), corpo))
    return out


def _corta(texto: str, n: int = MAX_CHARS) -> str:
    return texto if len(texto) <= n else texto[:n - 1] + "…"


def pauta(data_dir: Path, agora: float | None = None) -> list[str]:
    """As linhas da pauta: cabeçalho e uma linha por assunto, no máximo MAX_LINHAS."""
    agora = agora or time.time()
    ontem = _dia(agora - 86400)
    por: dict[str, dict[str, list[str]]] = {}
    for assunto, dia, corpo in _ler_notas(Path(data_dir) / PASTA):
        a = por.setdefault(assunto, {"ontem": [], "hoje": [], "bloqueia": []})
        for linha in corpo.splitlines():
            linha = linha.strip().lstrip("#").strip()
            if not linha:
                continue
            aberta = _ABERTA.match(linha)
            texto = aberta.group(1).strip() if aberta else linha
            bloq = _BLOQUEIO.match(texto)
            if bloq:
                a["bloqueia"].append(bloq.group(1).strip())
            elif aberta:
                a["hoje"].append(texto)
            elif dia == ontem:
                feita = _FEITA.match(linha)
                a["ontem"].append(feita.group(1).strip() if feita else linha)
    linhas = []
    for assunto in sorted(por):
        partes = [f"{k}: {'; '.join(v)}" for k, v in por[assunto].items() if v]
        if partes:
            linhas.append(_corta(f"{assunto} — " + " · ".join(partes)))
    cabecalho = f"Daily {time.strftime('%d/%m', time.localtime(agora))} — por assunto"
    if not linhas:
        return [cabecalho, "nada nas notas de ontem nem pendência aberta"]
    if len(linhas) > MAX_LINHAS - 1:
        resto = len(linhas) - (MAX_LINHAS - 2)
        linhas = linhas[:MAX_LINHAS - 2] + [f"+{resto} assunto(s): veja {PASTA}/"]
    return [cabecalho] + linhas


def checar(store, data_dir: Path, reply, agora: float | None = None, notificar=notificar_mac) -> list[str] | None:
    """Uma passagem (o SRE chama a cada minuto): a partir das HORA h, emite a pauta uma vez por dia."""
    agora = agora or time.time()
    hoje = _dia(agora)
    if time.localtime(agora).tm_hour < HORA or store.get(CHAVE) == hoje or not (Path(data_dir) / PASTA).is_dir():
        return None
    linhas = pauta(data_dir, agora)
    store.set(CHAVE, hoje)
    reply("\n".join(linhas), "resposta")
    notificar(linhas[0], " | ".join(linhas[1:]))
    return linhas

"""Caixa de entrada por arquivo: um `.md` em `<dados>/caixa/` vira pedido, lido pelo próprio loop.

Por que existe (26/10): o banco foi corrompido por uma escrita direta no SQLite feita de fora (pela ponte do Mac)
enquanto o loop escrevia. Pedido de fora do painel nunca mais toca o banco: cai como arquivo, e o loop — o único
dono do banco — o transforma em evento no começo do giro. Serve a qualquer ferramenta (um script, o Claude, um
atalho do macOS, uma pasta sincronizada).

Formato do arquivo (texto puro, UTF-8):
    ---            (cabeçalho opcional, uma chave por linha)
    tipo: pedido | missao          (padrão: pedido — vai para o roteiro do loop; missao cria uma missão nova)
    projeto: 2                     (padrão: a missão do loop)
    ---
    o texto do pedido, em uma ou várias linhas

Lido vai para `caixa/lidos/<data>-<nome>` com o id do evento no nome; inválido vai para `caixa/invalidos/`.
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

PASTA = "caixa"
MAX_POR_GIRO = 20
MAX_TEXTO = 4000


def _cabecalho(texto: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", texto, re.S)
    if not m:
        return {}, texto
    cab = {}
    for linha in m.group(1).splitlines():
        if ":" in linha:
            k, v = linha.split(":", 1)
            cab[k.strip().lower()] = v.strip()
    return cab, m.group(2)


def ler(store, data_dir: Path, agora: float | None = None) -> list[int]:
    """Transforma cada arquivo novo da caixa em evento. Devolve os ids dos eventos criados."""
    agora = agora or time.time()
    pasta = Path(data_dir) / PASTA
    if not pasta.is_dir():
        return []
    (pasta / "lidos").mkdir(exist_ok=True)
    (pasta / "invalidos").mkdir(exist_ok=True)
    ids = []
    loop_pid = (store.one("SELECT id FROM projects WHERE kit='circulo'") or {"id": None})["id"]
    for arq in sorted(p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() in (".md", ".txt"))[:MAX_POR_GIRO]:
        try:
            cab, corpo = _cabecalho(arq.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            shutil.move(str(arq), str(pasta / "invalidos" / arq.name))
            continue
        texto = corpo.strip()[:MAX_TEXTO]
        if len(texto) < 8:
            shutil.move(str(arq), str(pasta / "invalidos" / arq.name))
            continue
        tipo = cab.get("tipo", "pedido").lower()
        if tipo == "missao":
            eid = store.enqueue("novo_projeto", {"pedido": texto, "at": agora, "origem": "caixa", "arquivo": arq.name})
        else:
            projeto = cab.get("projeto", "").strip()
            payload = {"text": texto, "at": agora, "origem": "caixa", "arquivo": arq.name,
                       "projeto": int(projeto) if projeto.isdigit() else loop_pid}
            eid = store.enqueue("mensagem", payload)
        ids.append(eid)
        shutil.move(str(arq), str(pasta / "lidos" / f"{time.strftime('%Y-%m-%d_%H%M%S', time.localtime(agora))}-ev{eid}-{arq.name}"))
    if ids:
        store.set("caixa_ultima", {"em": agora, "eventos": ids})
    return ids

"""Caminho livre para o corpo trocar de código (lição #1).

Quando alguém copia à mão para a máquina do loop um arquivo que depois chega à main por merge, ele fica como
"não rastreado" no repositório vivo e o `git checkout` da troca de corpo aborta ("would be overwritten by
checkout"). O corpo já validou o código novo nesse ponto e o checkout é atômico: nada mudou. Aqui o caminho é
liberado sem perder nada e a troca é tentada de novo:
  - conteúdo igual ao da main nova: o arquivo some (a main traz exatamente o mesmo);
  - conteúdo diferente: o arquivo vai para a pasta de dados, em corpo-local-<ts>/<caminho>.
Só se mexe depois de a troca falhar: se a validação reprovar o código novo, o corpo atual segue intacto.
"""
from __future__ import annotations

import hashlib
import shutil
import time


def _blob(conteudo: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(conteudo) + conteudo).hexdigest()


def colisoes(corpo, alvo: str) -> dict[str, str]:
    """Arquivos não rastreados que existem em `alvo` → sha do blob em `alvo`."""
    soltos = set(filter(None, corpo._git(["ls-files", "--others", "--exclude-standard", "-z"], check=False).split("\0")))
    if not soltos:
        return {}
    out = {}
    for linha in corpo._git(["ls-tree", "-r", "-z", alvo], check=False).split("\0"):
        if "\t" not in linha:
            continue
        meta, caminho = linha.split("\t", 1)
        if caminho in soltos:
            out[caminho] = meta.split()[2]
    return out


def liberar_caminho(corpo, alvo: str) -> dict:
    """Tira do caminho do checkout os arquivos não rastreados que `alvo` traz; nada diferente é apagado."""
    removidos, guardados = [], []
    destino = corpo.data / f"corpo-local-{int(time.time())}"
    for caminho, sha in colisoes(corpo, alvo).items():
        arq = corpo.repo / caminho
        if not arq.is_file():
            continue
        if _blob(arq.read_bytes()) == sha:
            arq.unlink()
            removidos.append(caminho)
        else:
            (destino / caminho).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(arq), str(destino / caminho))
            guardados.append(caminho)
    return {"removidos": removidos, "guardados": guardados, "pasta": str(destino) if guardados else None}


def atualizar_corpo(corpo) -> dict:
    """`corpo.run()`; se a troca esbarrar em arquivo não rastreado que a main nova traz, libera e tenta de novo."""
    try:
        return corpo.run()
    except RuntimeError:
        alvo = corpo._git(["rev-parse", "origin/main"], check=False)
        if not alvo or not colisoes(corpo, alvo):
            raise
        liberado = liberar_caminho(corpo, alvo)
    r = corpo.run()
    return {**r, "liberado": liberado}

"""Pastas padrão por assunto no Mac, espelhando os assuntos do console (`circulo assunto novo`).

    <raiz>/ASSUNTOS.md                  o índice: pelo que você é responsável, em um olhar
    <raiz>/<assunto>/README.md          a descrição do assunto
    <raiz>/<assunto>/{docs,decisoes,links,notas,prompts}/

A raiz é `CIRCULO_PASTA_ASSUNTOS` (ex.: ~/Assuntos) ou `<dados>/assuntos`. O Vigia mantém a estrutura a cada passagem:
assunto novo ganha as pastas, o índice e os README são reescritos só quando mudam e nada que o humano pôs lá é apagado.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import assuntos
from .state import Store

PASTA = "assuntos"
INDICE = "ASSUNTOS.md"
SUBPASTAS = ("docs", "decisoes", "links", "notas", "prompts")
_PROIBIDO_NO_NOME = re.compile(r"[/:\\]")


def raiz(data_dir: Path) -> Path:
    return Path(os.environ.get("CIRCULO_PASTA_ASSUNTOS") or Path(data_dir) / PASTA).expanduser()


def nome_da_pasta(nome: str) -> str:
    return _PROIBIDO_NO_NOME.sub("-", nome).strip().lstrip(".") or "sem-nome"


def _escrever(arq: Path, texto: str) -> None:
    if not arq.is_file() or arq.read_text(encoding="utf-8") != texto:
        arq.write_text(texto, encoding="utf-8")


def manter(store: Store, pasta: Path) -> list[Path]:
    """Cria o que falta e atualiza índice e README; devolve a pasta de cada assunto."""
    assuntos.preparar(store)
    linhas, feitas = [], []
    for a in store.q("SELECT a.nome, a.descricao, (SELECT COUNT(*) FROM assunto_notas n WHERE n.assunto_id=a.id "
                     "AND n.tipo='pendencia') pendencias FROM assuntos a ORDER BY a.nome"):
        dest = Path(pasta) / nome_da_pasta(a["nome"])
        for sub in SUBPASTAS:
            (dest / sub).mkdir(parents=True, exist_ok=True)
        _escrever(dest / "README.md", f"# {a['nome']}\n\n{a['descricao']}\n".rstrip() + "\n")
        pend = f" · {a['pendencias']} pendência(s)" if a["pendencias"] else ""
        linhas.append(f"- [{a['nome']}](<{dest.name}/README.md>)" + (f" — {a['descricao']}" if a["descricao"] else "") + pend)
        feitas.append(dest)
    if feitas:
        _escrever(Path(pasta) / INDICE, "# Pelo que sou responsável\n\n" + "\n".join(linhas) + "\n")
    return feitas

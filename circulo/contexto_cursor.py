"""Contexto enxuto para o Cursor: AGENTS.md curto e regras .cursor/rules/*.mdc escopadas por glob.

Só entra o que o agente não descobre lendo o repositório: comandos, convenções (decisões) e armadilhas da memória
do assunto, ou as lições evidenciadas do repositório. Nada de descrição, pendência, link ou o que o README já diz:
arquivo de contexto gerado e redundante custa mais tokens e reduz o sucesso (estudo da ETH Zurich). Linha que cita um
caminho vira regra .mdc com `globs` (carrega só quando o arquivo está em jogo) em vez de ir para o AGENTS.md.

Cada arquivo tem teto de linhas, e `escrever` só grava numa branch que não é a principal: muda só por PR.
Skills, MCPs e o mapa do GAIA ficam para a segunda fase, depois da primeira medição.

    python -m circulo.contexto_cursor [ASSUNTO] [--saida DIR]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import unicodedata
from pathlib import Path

from . import assuntos
from .state import Store

LIMITE_AGENTS = 60
LIMITE_REGRA = 20
MAX_REGRAS = 10
MAX_CHARS = 160
PRINCIPAIS = ("main", "master", "HEAD")
PREFIXOS = (("comando", re.compile(r"(?i)^\s*(comandos?|rode|execute)\s*:\s*")),
            ("armadilha", re.compile(r"(?i)^\s*(armadilhas?|cuidado|aten[cç][aã]o)\s*:\s*")),
            ("convencao", re.compile(r"(?i)^\s*(conven[cç][aã]o|regra)\s*:\s*")))
SECOES = (("comando", "Comandos"), ("convencao", "Convenções"), ("armadilha", "Armadilhas"))
TOKEN = re.compile(r"[\w.*/-]+")


def _glob(texto: str) -> str | None:
    """O primeiro caminho ou glob citado (src/envio/*.py, tests/test_x.py), nunca uma URL."""
    for t in TOKEN.findall(re.sub(r"https?://\S+", " ", texto)):
        t = t.rstrip(".")
        if ("/" in t or "*" in t) and not t.startswith("/") and re.search(r"(\.\w{1,5}|\*)$", t):
            return t
    return None


def _norm(texto: str) -> str:
    return " ".join(re.sub(r"[`*_]", " ", texto or "").lower().split())


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "regra"


def _itens_do_assunto(store: Store, nome: str) -> list[tuple[str, str]]:
    """(seção, texto) das notas do assunto, da mais recente para a mais antiga."""
    assuntos.preparar(store)
    a = store.one("SELECT id FROM assuntos WHERE nome=?", (nome,))
    if not a:
        raise ValueError(f"assunto desconhecido: {nome}")
    itens = []
    for r in store.q("SELECT tipo, texto FROM assunto_notas WHERE assunto_id=? AND tipo IN ('decisao','nota') "
                     "ORDER BY created_at DESC, id DESC", (a["id"],)):
        secao = next(((s, r["texto"][m.end():].strip()) for s, rx in PREFIXOS if (m := rx.match(r["texto"]))), None)
        if secao:
            itens.append(secao)
        elif r["tipo"] == "decisao":
            itens.append(("convencao", r["texto"].strip()))
    return itens


def _itens_do_repositorio(store: Store) -> list[tuple[str, str]]:
    return [("armadilha", f"{r['descricao'].strip()} (lição #{r['id']})")
            for r in store.q("SELECT id, descricao FROM licoes WHERE status='evidenciada' "
                             "ORDER BY COALESCE(evidenciada_tick, 0) DESC, id DESC")]


def gerar(store: Store, assunto: str | None = None, readme: str = "", nome: str | None = None,
          teto: int = LIMITE_AGENTS) -> dict[str, str]:
    """{caminho relativo: conteúdo}. Com `assunto`, da memória dele; sem, das lições evidenciadas do repositório."""
    titulo = assunto or nome or "repositório"
    itens = _itens_do_assunto(store, assunto) if assunto else _itens_do_repositorio(store)
    doc = _norm(readme)
    geral: dict[str, list[str]] = {s: [] for s, _ in SECOES}
    escopo: dict[str, list[str]] = {}
    for secao, texto in itens:
        linha = texto if len(texto) <= MAX_CHARS else texto[:MAX_CHARS - 1] + "…"
        if not texto or (doc and _norm(texto) in doc):
            continue
        g = _glob(texto)
        if g:
            escopo.setdefault(g, []).append(linha)
        else:
            geral[secao].append(linha)
    arquivos = {"AGENTS.md": _agents(titulo, geral, min(teto, LIMITE_AGENTS))}
    for g, linhas in list(escopo.items())[:MAX_REGRAS]:
        arquivos[f".cursor/rules/{_slug(titulo)}-{_slug(g)}.mdc"] = _regra(titulo, g, linhas)
    return arquivos


def _agents(titulo: str, geral: dict[str, list[str]], teto: int) -> str:
    linhas = [f"# {titulo}", "", "Só o que não está no código nem no README; gerado da memória do círculo, muda só por PR."]
    for secao, rotulo in SECOES:
        if not geral[secao] or len(linhas) + 3 > teto:
            continue
        linhas += ["", f"## {rotulo}"]
        linhas += [f"- {x}" for x in geral[secao][:teto - len(linhas)]]
    return "\n".join(linhas) + "\n"


def _regra(titulo: str, glob: str, linhas: list[str]) -> str:
    cabeca = ["---", f"description: {titulo}: regras para {glob}", f"globs: {glob}", "alwaysApply: false", "---"]
    return "\n".join(cabeca + [f"- {x}" for x in linhas[:LIMITE_REGRA - len(cabeca)]]) + "\n"


def _teto(caminho: str) -> int:
    return LIMITE_AGENTS if caminho == "AGENTS.md" else LIMITE_REGRA


def escrever(destino: str | Path, arquivos: dict[str, str]) -> list[Path]:
    """Grava os arquivos no repositório `destino` só se ele está numa branch de trabalho (vira PR, revisão humana)."""
    destino = Path(destino)
    r = subprocess.run(["git", "-C", str(destino), "symbolic-ref", "--short", "HEAD"], capture_output=True, text=True)
    branch = r.stdout.strip() if r.returncode == 0 else ""
    if not branch or branch in PRINCIPAIS:
        raise ValueError(f"o contexto do Cursor muda só por PR: crie uma branch em {destino} antes (está em '{branch}')")
    for caminho, conteudo in arquivos.items():
        if len(conteudo.splitlines()) > _teto(caminho):
            raise ValueError(f"{caminho} passa do teto de {_teto(caminho)} linhas")
    escritos = []
    for caminho, conteudo in arquivos.items():
        p = destino / caminho
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(conteudo, encoding="utf-8")
        escritos.append(p)
    return escritos


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m circulo.contexto_cursor", description=__doc__.splitlines()[0])
    ap.add_argument("assunto", nargs="?", help="sem assunto: as lições evidenciadas do repositório")
    ap.add_argument("--saida", help="repositório onde gravar (precisa estar numa branch, não na principal)")
    ap.add_argument("--banco", default="data/circulo.db")
    args = ap.parse_args(argv)
    destino = Path(args.saida) if args.saida else None
    readme = destino / "README.md" if destino else None
    texto = readme.read_text(encoding="utf-8") if readme and readme.exists() else ""
    try:
        arquivos = gerar(Store(Path(args.banco)), args.assunto, readme=texto,
                         nome=destino.resolve().name if destino else None)
        if destino:
            for p in escrever(destino, arquivos):
                print(p)
        else:
            for caminho, conteudo in arquivos.items():
                print(f"=== {caminho}\n{conteudo}")
    except ValueError as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()

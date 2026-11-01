"""Landing de cada produto criado: uma página em `docs/index.html` do próprio produto (o GitHub Pages serve a pasta
docs/ com o index.html como home), com nome, proposta de valor, 3 telas e o link do repositório (pedido #823).

A página segue a direção da skill frontend-design (editorial: serifa de display, rótulos em monoespaçada, grade de
três quadros), sem fonte nem script externo: abre offline e não depende de CDN. Antes de gravar, o Jev avalia a
landing pela régua de clareza (noul `landing_clara`); fora do ar ou sem Jev, decide a regra local `regra_clareza`
(registrada em `jev_lab.REGRAS`). Abaixo de LIMIAR nada é gravado: a landing confusa não chega ao Pages.

Um produto sem exatamente 3 telas ou sem repositório https não existe (`Produto` recusa), então a régua só julga o
que é questão de clareza: nome curto, proposta concreta de tamanho legível, cada tela com descrição.
"""
from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

LIMIAR = 0.7
PERGUNTA = "landing_clara"
MAX_PALAVRAS_NOME = 3
PROPOSTA_PALAVRAS = (6, 30)
MIN_PALAVRAS_TELA = 3
VAGAS = frozenset({"solucao", "solucoes", "inovador", "inovadora", "revolucionario", "revolucionaria", "sinergia",
                   "sinergico", "sinergica", "disruptivo", "disruptiva", "plataforma", "integrada", "completa", "ecossistema"})


@dataclass(frozen=True)
class Tela:
    titulo: str
    descricao: str


@dataclass(frozen=True)
class Produto:
    nome: str
    proposta: str
    telas: tuple[Tela, ...]
    repo: str

    def __post_init__(self):
        if len(self.telas) != 3:
            raise ValueError(f"a landing mostra exatamente 3 telas, vieram {len(self.telas)}")
        if not re.fullmatch(r"https://[^\s\"'<>]+", self.repo):
            raise ValueError(f"repositório precisa ser uma URL https: {self.repo!r}")


def _palavras(texto: str) -> list[str]:
    sem_acento = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z0-9]+", sem_acento)


CSS = """
:root{--papel:#f6f1e7;--tinta:#1d1b16;--suave:#5a5348;--acento:#9c3a14;--linha:#d9cfbd}
*{box-sizing:border-box}
body{margin:0;background:var(--papel);color:var(--tinta);font:18px/1.6 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif}
main{max-width:68rem;margin:0 auto;padding:5rem 1.5rem 4rem}
.rotulo{font:600 .75rem/1 ui-monospace,"SF Mono",Menlo,monospace;letter-spacing:.14em;text-transform:uppercase;color:var(--suave)}
h1{font-size:clamp(3rem,9vw,6.5rem);line-height:.95;letter-spacing:-.03em;margin:.6rem 0 1.4rem;font-weight:700}
.proposta{font-size:clamp(1.25rem,2.6vw,1.75rem);max-width:38ch;margin:0 0 2.5rem}
.repo{display:inline-block;color:var(--acento);font-weight:700;text-decoration:underline;text-underline-offset:.25em}
.repo:focus-visible{outline:3px solid var(--acento);outline-offset:4px}
.telas{display:grid;grid-template-columns:repeat(auto-fit,minmax(16rem,1fr));gap:1.5rem;margin-top:4.5rem;padding:0;list-style:none}
.tela{border:1px solid var(--linha);background:#fffdf8}
.tela .barra{display:flex;justify-content:space-between;padding:.6rem .9rem;border-bottom:1px solid var(--linha)}
.tela .corpo{padding:1.2rem .9rem 1.4rem}
h3{margin:0 0 .4rem;font-size:1.35rem}
.tela p{margin:0;color:var(--suave)}
footer{margin-top:4rem;border-top:1px solid var(--linha);padding-top:1rem}
"""


def gerar(p: Produto) -> str:
    e = html.escape
    telas = "\n".join(
        f'<li class="tela"><div class="barra"><span class="rotulo">Tela {i:02d}</span><span class="rotulo">{e(p.nome)}</span></div>'
        f'<div class="corpo"><h3>{e(t.titulo)}</h3><p>{e(t.descricao)}</p></div></li>'
        for i, t in enumerate(p.telas, 1))
    return (f'<!doctype html>\n<html lang="pt-BR">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{e(p.nome)}</title>\n'
            f'<meta name="description" content="{e(p.proposta)}">\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n'
            f'<p class="rotulo">Produto</p>\n<h1>{e(p.nome)}</h1>\n<p class="proposta">{e(p.proposta)}</p>\n'
            f'<a class="repo" href="{e(p.repo)}" rel="noopener">Ver o código no repositório</a>\n'
            f'<ul class="telas" aria-label="Telas">\n{telas}\n</ul>\n'
            f'<footer><span class="rotulo">Código: <a href="{e(p.repo)}" rel="noopener">{e(p.repo)}</a></span></footer>\n'
            f'</main>\n</body>\n</html>\n')


def estado(p: Produto, pagina: str) -> dict[str, Any]:
    """O que o Jev lê: o texto da landing e as medidas de clareza (a regra local decide só com elas)."""
    h1 = re.search(r"<h1>(.*?)</h1>", pagina, re.S)
    proposta = _palavras(p.proposta)
    return {"nome": p.nome, "proposta": p.proposta, "repo": p.repo,
            "telas": [f"{t.titulo}: {t.descricao}" for t in p.telas], "n_telas": len(p.telas),
            "nome_no_titulo": bool(h1) and html.unescape(h1.group(1)) == p.nome,
            "palavras_nome": len(_palavras(p.nome)), "palavras_proposta": len(proposta),
            "vagas": sorted(VAGAS.intersection(proposta + _palavras(p.nome))),
            "telas_sem_descricao": sum(len(_palavras(t.descricao)) < MIN_PALAVRAS_TELA for t in p.telas)}


def motivos(s: Mapping[str, Any]) -> list[str]:
    m = []
    if not s.get("nome_no_titulo"):
        m.append("nome fora do título")
    if int(s.get("palavras_nome", 0)) > MAX_PALAVRAS_NOME:
        m.append("nome longo")
    n = int(s.get("palavras_proposta", 0))
    if n < PROPOSTA_PALAVRAS[0] or s.get("vagas"):
        m.append("proposta vaga")
    if n > PROPOSTA_PALAVRAS[1]:
        m.append("proposta longa")
    if int(s.get("telas_sem_descricao", 0)):
        m.append("tela sem descrição")
    return m


def regra_clareza(s: Mapping[str, Any]) -> float:
    n = len(motivos(s))
    return 0.92 if n == 0 else max(0.05, 0.4 - 0.15 * (n - 1))


def avaliar(p: Produto, pagina: str, dl) -> dict[str, Any]:
    from .decision import SN, Question
    s = estado(p, pagina)
    q = Question("noul", "A visitor reads this product landing page for five seconds. Do they understand what `nome` is, what it "
                         "does for them (`proposta`), what each of the `telas` shows, and where the code is (`repo`)?",
                 SN("`nome_no_titulo` is true, `palavras_nome` ≤ 3, `palavras_proposta` between 6 and 30 with a concrete benefit "
                    "and `vagas` empty, and `telas_sem_descricao` = 0",
                    "the name is long or missing from the title, `proposta` is buzzwords or too short/long to say what the "
                    "product does, or some screen in `telas` has no real description"))
    d = dl.ask(PERGUNTA, q, s)
    return {"p": float(d.value), "fonte": d.source, "motivos": motivos(s)}


def publicar(raiz: Path, p: Produto, dl) -> dict[str, Any]:
    """Gera a landing, passa pela régua e só então grava `<raiz>/docs/index.html`."""
    pagina = gerar(p)
    r = avaliar(p, pagina, dl)
    r["publicada"] = r["p"] >= LIMIAR
    r["caminho"] = str(Path(raiz) / "docs" / "index.html")
    if r["publicada"]:
        destino = Path(r["caminho"])
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(pagina, encoding="utf-8")
    return r

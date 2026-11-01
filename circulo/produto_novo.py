"""Produto novo: pedido → repo gerado de `modelos/<tipo>/` (dados com `{{variáveis}}`, CI próprio; tipos em
`modelos/tipos.json`) → `circulo init` + `git init` + `origin` (bare local ou GitHub por token) → registro (kit 'repo')
→ pedido na fila (`circulo/<n>`). O primeiro PR: `repo_cliente.entregar` desse pedido roda o CI e empurra a branch."""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from pathlib import Path

from . import kit as kits
from . import repo_cliente
from .repo_cliente import AUTOR, _git

MODELOS = Path(__file__).parent / "modelos"
PADRAO = "cli"
GITHUB_REPOS = "https://api.github.com/user/repos"
_VARIAVEL = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _tipos() -> dict:
    return json.loads((MODELOS / "tipos.json").read_text(encoding="utf-8"))


def tipos() -> tuple[str, ...]:
    return tuple(sorted(_tipos()))


def modelo(tipo: str) -> dict:
    if tipo not in tipos():
        raise ValueError(f"tipo {tipo!r} sem modelo: {', '.join(tipos())}")
    return _tipos()[tipo]


def escolher_tipo(pedido: str, dl=None) -> tuple[str, str]:
    """(tipo, 'jev' | 'regra'): o Jev se responde um tipo que existe; senão a regra das palavras ('cli' sem nenhuma)."""
    if dl is not None:
        from .decision import Question
        q = Question("choice", "Qual esqueleto de repositório atende ao `pedido`?", {t: modelo(t)["descricao"] for t in tipos()})
        try:
            d = dl.ask("produto_tipo", q, {"pedido": pedido})
            if d.source == "jev" and d.value in tipos():
                return d.value, "jev"
        except (OSError, ValueError, KeyError, TypeError):
            pass
    texto = pedido.lower()
    pontos = {t: sum(bool(re.search(rf"(?<!\w){re.escape(p)}(?!\w)", texto)) for p in modelo(t)["palavras"]) for t in tipos()}
    melhor = max(pontos, key=pontos.get)
    return (melhor if pontos[melhor] else PADRAO), "regra"


def slug(texto: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower())[:60].strip("-")
    if not s:
        raise ValueError(f"nome sem letras: {texto!r}")
    return s


def gerar(tipo: str, destino: Path, variaveis: dict[str, str]) -> None:
    if destino.exists() and any(destino.iterdir()):
        raise ValueError(f"{destino} já existe e não está vazia")
    raiz = MODELOS / tipo
    modelo(tipo)
    for f in raiz.rglob("*"):
        if f.is_file() and "__pycache__" not in f.parts:
            alvo = destino / f.relative_to(raiz)
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_text(_VARIAVEL.sub(lambda m: variaveis[m.group(1)], f.read_text(encoding="utf-8")), encoding="utf-8")
    (destino / "README.md").write_text(f"# {variaveis['titulo']}\n\n{variaveis['pedido']}\n", encoding="utf-8")


def _post(url: str, corpo: str, cabecalhos: dict) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, corpo.encode(), cabecalhos, method="POST"), timeout=30) as r:
        return json.loads(r.read())


def criar_no_github(nome: str, descricao: str, token: str, enviar=None) -> str:
    """Repo privado novo na conta do token; a URL de clone volta sem credencial."""
    cab = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    return (enviar or _post)(GITHUB_REPOS, json.dumps({"name": nome, "private": True, "description": descricao[:300]}), cab)["clone_url"]


def remoto_local(dados: Path, nome: str) -> str:
    bare = (Path(dados) / "remotos" / f"{nome}.git").resolve()
    if bare.exists():
        raise ValueError(f"o remoto {bare} já existe")
    bare.parent.mkdir(parents=True, exist_ok=True)
    _git(bare.parent, "init", "-q", "--bare", "-b", "main", bare.name)
    return bare.as_uri()


def criar(store, pedido: str, raiz: Path, dados: Path, nome: str | None = None, tipo: str | None = None,
          dl=None, token: str | None = None, enviar=None) -> dict:
    titulo = (nome or pedido).strip()
    nome = slug(titulo)
    tipo, por = (tipo, "humano") if tipo else escolher_tipo(pedido, dl)
    pasta = (Path(raiz) / nome).resolve()
    gerar(tipo, pasta, {"nome": nome, "titulo": titulo, "pedido": pedido})
    kits.preparar_repositorio(kits.carregar(pasta), escrever_ci=False)
    remoto = criar_no_github(nome, pedido, token, enviar) if token else remoto_local(dados, nome)
    for args in (("init", "-q", "-b", "main"), ("add", "-A"), (*AUTOR, "commit", "-q", "-m", f"{titulo}: esqueleto {tipo}"),
                 ("remote", "add", "origin", remoto), ("push", "-q", "-u", "origin", "main")):
        _git(pasta, *args, timeout=600)
    reg = repo_cliente.registrar(store, pasta, nome=nome)
    primeiro = repo_cliente.receber(store, reg["id"], pedido, Path(dados) / "fabrica")
    return {"projeto": reg["id"], "nome": nome, "tipo": tipo, "escolhido_por": por, "pasta": str(pasta),
            "remoto": remoto, "pedido": primeiro["id"], "branch": primeiro["branch"]}

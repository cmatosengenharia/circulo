"""Círculo autoevolutivo Jev First — Sistema de Controle da Vida."""
from pathlib import Path as _Path


def _versao() -> str:
    """A versão é uma só: a do pyproject.toml (o painel mostrava 1.32.1 fixo enquanto o código já estava na 1.39.0)."""
    import tomllib
    arq = _Path(__file__).resolve().parent.parent / "pyproject.toml"
    if arq.exists():
        return str(tomllib.loads(arq.read_text(encoding="utf-8"))["project"]["version"])
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("circulo")
    except PackageNotFoundError:
        return "0"


__version__ = _versao()

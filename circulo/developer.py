"""O id pytest conferido por `ast` antes de rodar (lição #26): o reparo copiava ou inventava um id, e o pytest só
avisava depois de iniciar ('ERROR: file or directory not found', saída 4).

O id é `arquivo::Classe::...::funcao[parametros]`. O sufixo `[...]` sai do último trecho, as classes podem ser
aninhadas. Classe com base (herança) pode ter testes que o `ast` não vê: o que fica abaixo dela não é recusado.
"""
from __future__ import annotations

import ast
from pathlib import Path

DEF = (ast.FunctionDef, ast.AsyncFunctionDef)


def _arvore(raiz: Path | str, arquivo: str) -> ast.Module | None:
    caminho = Path(raiz) / arquivo
    if not caminho.is_file():
        return None
    try:
        return ast.parse(caminho.read_text(encoding="utf-8"))
    except (SyntaxError, ValueError, UnicodeDecodeError):
        return None


def alvo_pytest_existe(raiz: Path | str, node_id: str) -> bool:
    """O arquivo existe e cada trecho depois de `::` é uma classe (aninhada) ou a função final, definidos no arquivo."""
    arquivo, *nomes = node_id.split("[", 1)[0].split("::")     # os parâmetros podem ter `::`: saem antes
    if not (Path(raiz) / arquivo).is_file():
        return False
    if not nomes:
        return True
    arvore = _arvore(raiz, arquivo)
    if arvore is None:
        return True                 # o pytest relata o erro de sintaxe melhor que esta checagem
    corpo = arvore.body
    for i, nome in enumerate(nomes):
        no = next((n for n in corpo if isinstance(n, (ast.ClassDef, *DEF)) and n.name == nome), None)
        if no is None:
            return False
        if i == len(nomes) - 1 or (isinstance(no, ast.ClassDef) and no.bases):
            return True
        if not isinstance(no, ast.ClassDef):
            return False
        corpo = no.body
    return True


def listar_testes(raiz: Path | str, arquivo: str) -> list[str]:
    """Os `test_*` definidos no arquivo, com as classes no id (`Classe::test_x`), na ordem do arquivo."""
    arvore = _arvore(raiz, arquivo)

    def varrer(corpo, prefixo: str) -> list[str]:
        out = []
        for n in corpo:
            if isinstance(n, DEF) and n.name.startswith("test"):
                out.append(prefixo + n.name)
            elif isinstance(n, ast.ClassDef) and n.name.startswith("Test"):
                out += varrer(n.body, f"{prefixo}{n.name}::")
        return out
    return varrer(arvore.body, "") if arvore else []

"""Autofix determinístico do lint do CI nos testes alterados, antes do commit do Developer: só o que sobra vai para a LLM.

As lições de lint (#36, #70, #71, #76, #77) reincidiram sempre em tests/, então o autofix só toca `tests/`:
1. B905 por AST: o `ruff check --fix` não corrige o `zip` sem `strict=` (fix inseguro), então ele ganha
   `strict=False`, que mantém o comportamento. Só com o Python-alvo do projeto >= 3.10 (antes disso o `strict=` não
   existe e o ruff nem acusa o B905); sem alvo declarado no pyproject.toml, não toca.
2. `ruff check --fix` com a seleção do CI (F401, F541 e o resto que tem correção segura).
3. Devolve os diagnósticos que sobraram (F811, por exemplo), no formato conciso do ruff.

O `DeveloperComReparo` chama `corrigir` quando o lint do CI reprova em `verificar`, que é o mesmo caminho do
developer:testes, do developer:abrir_pr e do developer:reparo; o que sobra é a entrada da rodada do agente."""
import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from .self_dev import LINT_CMD

SELECAO_CI = LINT_CMD[LINT_CMD.index("--select"):]       # --select E,F,W,B --ignore E501
DIAGNOSTICO = re.compile(r"^\S+\.py:\d+:\d+: [A-Z]+\d+\b.*$", re.M)
PASTA = "tests"
VERSAO = re.compile(r"(?:py|>=\s*)3\.?(\d+)")


def alvo_python(raiz: Path | str) -> tuple[int, int] | None:
    """O Python-alvo do projeto: `tool.ruff.target-version` ou o mínimo de `project.requires-python`."""
    try:
        cfg = tomllib.loads((Path(raiz) / "pyproject.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    texto = cfg.get("tool", {}).get("ruff", {}).get("target-version") or cfg.get("project", {}).get("requires-python", "")
    m = VERSAO.search(str(texto))
    return (3, int(m.group(1))) if m else None


def corrigir_b905(fonte: str) -> str:
    """Põe `strict=False` em todo `zip(...)` com argumentos e sem `strict=`. Sem parse, devolve a fonte intacta."""
    try:
        arvore = ast.parse(fonte)
    except SyntaxError:
        return fonte
    pontos = []
    for no in ast.walk(arvore):
        if (isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id == "zip" and no.args
                and not any(k.arg == "strict" for k in no.keywords)):
            ultimo = max([*no.args, *no.keywords], key=lambda n: (n.end_lineno, n.end_col_offset))
            pontos.append((ultimo.end_lineno, ultimo.end_col_offset))
    linhas = [linha.encode() for linha in fonte.splitlines(keepends=True)]
    for lin, col in sorted(pontos, reverse=True):       # de trás para frente: um ponto não desloca o anterior
        linhas[lin - 1] = linhas[lin - 1][:col] + b", strict=False" + linhas[lin - 1][col:]
    return b"".join(linhas).decode()


def corrigir(arquivos: list[str], cwd: Path | str = ".") -> list[str]:
    """Autofix (B905 por AST + `ruff check --fix` do CI) nos arquivos .py de tests/; devolve o que sobrou neles."""
    raiz = Path(cwd)
    alvos = [a for a in arquivos if a.endswith(".py") and Path(a).parts[:1] == (PASTA,) and (raiz / a).is_file()]
    if not alvos:
        return []
    if (alvo_python(raiz) or (0, 0)) >= (3, 10):
        for a in alvos:
            fonte = (raiz / a).read_text()
            if (novo := corrigir_b905(fonte)) != fonte:
                (raiz / a).write_text(novo)
    argv = [sys.executable, "-m", "ruff", "check", "--fix", *SELECAO_CI, "--output-format", "concise", *alvos]
    p = subprocess.run(argv, cwd=raiz, capture_output=True, text=True, timeout=300)
    return DIAGNOSTICO.findall(p.stdout)


def main(argv: list[str]) -> int:
    pendentes = corrigir(argv)
    print("\n".join(pendentes))
    return 1 if pendentes else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

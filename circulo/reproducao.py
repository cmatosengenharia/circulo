"""Reprodução primeiro: o teste novo de uma correção precisa FALHAR no código antigo e passar no novo.

Lição da Lauren Tan (pstack, playbook de bug fix): correção só vale com a reprodução, a causa confirmada rodando e
o teste passando depois. Um teste novo que já passa no código antigo não prova nada sobre a mudança.

Como confere:
1. acha as funções de teste NOVAS (que não existiam no código base) nos arquivos tests/test_*.py alterados;
2. monta o código base num worktree temporário, com a pasta tests/ da versão nova (helpers e fixtures novos vêm junto);
3. roda só os testes novos ali. Se TODOS passam no código antigo, a reprodução falhou: o PR não segue.
   Se pelo menos um falha (ou nem importa, porque o código que ele testa ainda não existe), a reprodução existe.

Roda em dois lugares (duas camadas): no portão do Developer antes do PR (`reproduz(wt, base)`, lendo a árvore de
trabalho) e no CI dos PRs de agente (`python -m circulo.reproducao --base HEAD^1`), que o gate de merge exige verde.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _git(args, cwd, check=True) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()[:300]}")
    return p.stdout


def _nomes_de_teste(fonte: str) -> set[str]:
    """`test_x` e `Classe::test_y` definidos no arquivo (nível de módulo e classes Test*)."""
    try:
        arv = ast.parse(fonte)
    except SyntaxError:
        return set()
    out = set()
    for n in arv.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"):
            out.add(n.name)
        elif isinstance(n, ast.ClassDef) and n.name.startswith("Test"):
            out |= {f"{n.name}::{m.name}" for m in n.body
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name.startswith("test")}
    return out


def _e_raises(w: ast.With) -> bool:
    return any(isinstance(i.context_expr, ast.Call) and isinstance(i.context_expr.func, ast.Attribute)
               and i.context_expr.func.attr == "raises" for i in w.items)


def exigem_o_erro_antigo(fonte: str) -> list[str]:
    """Testes que exigem `pytest.raises` numa chamada e, depois, a mesma chamada (mesmos argumentos) funcionando
    (lição #2). Exigir o erro antigo dentro do teste prende a main ao bug: quando outra correção tira o erro, o teste
    fica vermelho. A reprodução é do portão: o teste novo roda no código antigo e lá precisa falhar."""
    try:
        arv = ast.parse(fonte)
    except SyntaxError:
        return []
    out = []
    for f in ast.walk(arv):
        if not (isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name.startswith("test")):
            continue
        blocos = [w for w in ast.walk(f) if isinstance(w, ast.With) and _e_raises(w)]
        dentro = {id(n) for w in blocos for b in w.body for n in ast.walk(b)}
        for w in blocos:
            falha = {ast.dump(n) for b in w.body for n in ast.walk(b) if isinstance(n, ast.Call)}
            if any(isinstance(n, ast.Call) and id(n) not in dentro and n.lineno > w.end_lineno and ast.dump(n) in falha
                   for n in ast.walk(f)):
                out.append(f.name)
                break
    return out


def provam_paralelismo_pelo_relogio(fonte: str) -> list[str]:
    """Testes de paralelismo (`*paralel*`, `*ao_mesmo_tempo*`) cujo critério é o tempo de parede, uma comparação com
    `time.<algo>() - <x>` à esquerda (lição #2, antes #62/#67): sob carga no CI o tempo estoura e o teste fica flaky.
    Paralelismo se prova com barreira (`threading.Barrier`), que só abre com todos dentro ao mesmo tempo."""
    try:
        arv = ast.parse(fonte)
    except SyntaxError:
        return []
    out = []
    for f in ast.walk(arv):
        if not (isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name.startswith("test")
                and ("paralel" in f.name or "ao_mesmo_tempo" in f.name)):
            continue
        for n in ast.walk(f):
            if isinstance(n, ast.Compare) and isinstance(n.left, ast.BinOp) and isinstance(n.left.op, ast.Sub):
                c = n.left.left
                if (isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                        and isinstance(c.func.value, ast.Name) and c.func.value.id == "time"):
                    out.append(f.name)
                    break
    return out


def _dorme(no: ast.AST) -> bool:
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "sleep"
               and isinstance(n.func.value, ast.Name) and n.func.value.id == "time" for n in ast.walk(no))


def ordenam_paralelismo_por_sono(fonte: str) -> list[str]:
    """Testes de paralelismo (`*paralel*`, `*ao_mesmo_tempo*`) que usam um dublê do próprio módulo (classe) que dorme
    `time.sleep` para ordenar as threads (lição #63): sob carga o sono não ordena nada e, em série, o teste passa igual.
    A sobreposição se prova com `threading.Barrier(n, timeout=...)` no dublê."""
    try:
        arv = ast.parse(fonte)
    except SyntaxError:
        return []
    dormem = {n.name for n in arv.body if isinstance(n, ast.ClassDef) and _dorme(n)}
    return [f.name for f in ast.walk(arv)
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name.startswith("test")
            and ("paralel" in f.name or "ao_mesmo_tempo" in f.name)
            and any(isinstance(n, ast.Name) and n.id in dormem for n in ast.walk(f))]


def _arquivos_de_teste(repo: Path, base: str, head: str | None) -> list[str]:
    if head:
        nomes = _git(["diff", "--name-only", "--diff-filter=AM", f"{base}...{head}", "--", "tests"], repo).split()
    else:
        nomes = _git(["diff", "--name-only", "--diff-filter=AM", base, "--", "tests"], repo).split()
        nomes += _git(["ls-files", "--others", "--exclude-standard", "--", "tests"], repo).split()
    return sorted({n for n in nomes if Path(n).name.startswith("test_") and n.endswith(".py")})


def _ler(repo: Path, ref: str | None, caminho: str) -> str | None:
    if ref is None:
        p = repo / caminho
        return p.read_text(encoding="utf-8") if p.exists() else None
    p = subprocess.run(["git", "show", f"{ref}:{caminho}"], cwd=repo, capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def testes_novos(repo: str | Path, base: str, head: str | None = None) -> list[str]:
    """Node ids do pytest das funções de teste que não existiam no base."""
    repo = Path(repo)
    out = []
    for arq in _arquivos_de_teste(repo, base, head):
        novo = _ler(repo, head, arq) or ""
        antigo = _ler(repo, base, arq) or ""
        for nome in sorted(_nomes_de_teste(novo) - _nomes_de_teste(antigo)):
            out.append(f"{arq}::{nome}")
    return out


def _site_packages(python: str, env: dict) -> list[str]:
    cod = "import json, site; print(json.dumps(site.getsitepackages() + ([site.getusersitepackages()] if site.ENABLE_USER_SITE else [])))"
    p = subprocess.run([python, "-c", cod], capture_output=True, text=True, env=env, check=True)
    return json.loads(p.stdout)


def reproduz(repo: str | Path, base: str, head: str | None = None, python: str | None = None,
             env: dict | None = None, timeout: int = 600) -> tuple[bool, str, list[str]]:
    """(ok, detalhe, testes_novos). ok=False quando todos os testes novos já passam no código antigo."""
    repo = Path(repo)
    novos = testes_novos(repo, base, head)
    if not novos:
        return True, "nenhuma função de teste nova (o portão do teste novo cuida disso)", []
    presos = [n for n in novos if n.rsplit("::", 1)[-1] in exigem_o_erro_antigo(_ler(repo, head, n.split("::", 1)[0]) or "")]
    if presos:
        return False, ("lição #2: o teste exige o erro antigo (pytest.raises) e depois a mesma chamada funcionando; "
                       "quando outra correção tirar o erro, a main fica vermelha. Teste só o comportamento corrigido: "
                       f"o portão já roda o teste novo no código antigo. Testes: {', '.join(presos)}"), novos
    cronometrados = [n for n in novos
                     if n.rsplit("::", 1)[-1] in provam_paralelismo_pelo_relogio(_ler(repo, head, n.split("::", 1)[0]) or "")]
    if cronometrados:
        return False, ("lição #2: o teste prova paralelismo pelo tempo de parede e fica flaky sob carga no CI. "
                       f"Use threading.Barrier no lugar do cronômetro. Testes: {', '.join(cronometrados)}"), novos
    dormindo = [n for n in novos
                if n.rsplit("::", 1)[-1] in ordenam_paralelismo_por_sono(_ler(repo, head, n.split("::", 1)[0]) or "")]
    if dormindo:
        return False, ("lição #63: o dublê do teste de paralelismo dorme (time.sleep) para ordenar as threads; sob carga "
                       f"não ordena e, em série, passa igual. Use threading.Barrier(n, timeout=...). Testes: {', '.join(dormindo)}"), novos
    tmp =Path(tempfile.mkdtemp(prefix="circulo-repro-"))
    wt = tmp / "base"
    try:
        _git(["worktree", "add", "--detach", "-q", str(wt), _git(["rev-parse", base], repo).strip()], repo)
        # a pasta tests/ da versão nova vai inteira (helpers, fixtures e conftest novos), o código continua o antigo
        shutil.rmtree(wt / "tests", ignore_errors=True)
        if head is None:
            shutil.copytree(repo / "tests", wt / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        else:
            for caminho in _git(["ls-tree", "-r", "--name-only", head, "tests"], repo).split():
                destino = wt / caminho
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(subprocess.run(["git", "show", f"{head}:{caminho}"], cwd=repo, capture_output=True).stdout)
        python = python or sys.executable
        amb = {**(env or os.environ), "PYTHONDONTWRITEBYTECODE": "1"}
        # -S: sem os .pth do site, o `pip install -e` do checkout novo não resolve módulos novos para o código antigo;
        # as dependências (pytest etc.) vêm dos site-packages desse mesmo interpretador, só como caminho
        amb["PYTHONPATH"] = os.pathsep.join([str(wt), *_site_packages(python, amb)])
        p = subprocess.run([python, "-S", "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", *novos],
                           cwd=wt, capture_output=True, text=True, timeout=timeout, env=amb)
        saida = (p.stdout + p.stderr)[-1500:]
        if p.returncode == 0:
            return False, ("os testes novos já passam no código antigo, então não provam a mudança. Escreva um teste que "
                           f"falhe sem a correção (reprodução) e passe com ela. Testes novos: {', '.join(novos)}"), novos
        if p.returncode == 5:
            return False, f"nenhum dos testes novos foi coletado no código antigo: {', '.join(novos)}", novos
        falharam = [n for n in novos if f"FAILED {n}" in p.stdout or f"ERROR {n}" in p.stdout] or novos
        return True, f"reproduzido: {len(falharam)} de {len(novos)} teste(s) novo(s) falham no código antigo\n{saida[-400:]}", novos
    finally:
        _git(["worktree", "remove", "--force", str(wt)], repo, check=False)
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Reprodução primeiro: os testes novos precisam falhar no código antigo.")
    ap.add_argument("--base", required=True, help="commit/branch do código antigo (no CI de PR: HEAD^1, a main atual)")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args(argv)
    ok, detalhe, novos = reproduz(a.repo, a.base, a.head)
    print(("OK: " if ok else "REPROVADO: ") + detalhe)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())


# ------------------------------------------------------------ ambiente e worktree (usados pelo Developer, pelo corpo e pelo reparo)
SEGREDOS = ("ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "TYPESAFE_API_KEY", "JEV_API_KEY", "GITHUB_TOKEN",
            "CIRCULO_REPO", "CIRCULO_REPO_DIR", "CLAUDE_CODE_OAUTH_TOKEN", "CIRCULO_CONTA")


def ambiente_isolado() -> dict:
    """Ambiente dos testes do Developer: sem chaves, sem repositório e com o Developer desligado.
    Sem isso, um teste que cria um loop acordaria outro Developer de verdade (Claude Code dentro de Claude Code)."""
    env = {k: v for k, v in os.environ.items() if k not in SEGREDOS}
    # CIRCULO_GRAFT=0: testes nunca falam com o Graft real (22/10: no Mac com graft instalado, os testes ficavam lentos e
    # diferentes do CI, a validação local reprovava toda versão nova e os testes sujavam o grafo de verdade)
    env.update({"CIRCULO_SEM_DEVELOPER": "1", "CIRCULO_ENV": os.devnull, "GIT_TERMINAL_PROMPT": "0", "CIRCULO_GRAFT": "0", "GRAFT_HOOKS": "0"})
    return env


def git_silencioso(args: list, cwd, check: bool = False) -> str:
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(p.stdout + p.stderr).strip()[-500:]}")
    return p.stdout.strip()


def liberar_worktree(repo: Path, wt: Path) -> None:
    """Caminho do worktree livre; diretório que o git não reconhece (sobra de rollback) vai para `.circulo-wt-orfaos/`, nunca apagado."""
    if wt.exists():
        git_silencioso(["worktree", "remove", "--force", str(wt)], repo, check=False)
    if wt.exists():
        (wt.parent / ".circulo-wt-orfaos").mkdir(exist_ok=True)
        shutil.move(str(wt), str(wt.parent / ".circulo-wt-orfaos" / f"{wt.name}-{int(time.time() * 1000)}"))
    git_silencioso(["worktree", "prune"], repo, check=False)


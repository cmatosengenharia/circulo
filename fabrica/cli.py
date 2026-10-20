"""Linha de comando da fábrica.

  python -m fabrica iniciar [pasta]          escreve um fabrica.json de exemplo no projeto
  python -m fabrica pedir "texto"            cola um pedido na fila
  python -m fabrica rodar [--uma-vez]        gira a fábrica (um passo por vez, um cartão por vez)
  python -m fabrica painel [--porta 8766]    abre o chão de fábrica ao vivo
  python -m fabrica demo                     projeto de exemplo + executor simulado + painel: veja o círculo fechar
  python -m fabrica achados                  o documento de achados (o que a fábrica aprendeu e o que depende de você)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import __version__
from .coordenador import Fabrica, abrir
from .estado import Estado
from .oficina import CONFIG, PADRAO, GitHubFalso, Projeto, Simulado


def _iniciar(args):
    raiz = Path(args.pasta or ".").resolve()
    p = raiz / CONFIG
    if p.exists() and not args.forcar:
        print(f"{p} já existe (use --forcar para sobrescrever)")
        return 1
    cfg = {**PADRAO, "nome": raiz.name, "repo_github": "", "verificacao": "", "implantar": ""}
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"escrito {p}. Preencha 'testes', 'lint', 'verificacao' (como provar na superfície real) e 'repo_github'.")
    return 0


def _pedir(args):
    fab = abrir(args.pasta or ".", args.dados)
    cid = fab.pedir(" ".join(args.texto))
    print(f"cartão #{cid} na fila")
    return 0


def _rodar(args):
    fab = abrir(args.pasta or ".", args.dados)
    print(f"fábrica {__version__} · projeto {fab.projeto.cfg['nome']} · executor {getattr(fab.executor, 'nome', '?')} · GitHub {'sim' if fab.github else 'não'}")
    if args.uma_vez:
        r = fab.passo()
        print(json.dumps(r, ensure_ascii=False) if r else "nada a fazer")
        return 0
    if args.painel:
        from .painel import servir
        servir(fab.estado.caminho, args.porta, fundo=True)
        print(f"painel em http://127.0.0.1:{args.porta}")
    try:
        fab.rodar(intervalo=args.intervalo)
    except KeyboardInterrupt:
        print("\nfábrica parada; o estado fica salvo.")
    return 0


def _painel(args):
    fab = abrir(args.pasta or ".", args.dados)
    from .painel import servir
    servir(fab.estado.caminho, args.porta)
    return 0


def _achados(args):
    fab = abrir(args.pasta or ".", args.dados)
    linhas = ["# Achados da fábrica", ""]
    for a in fab.estado.achados_abertos():
        quem = "depende de você" if a["assunto"].split(":")[0] in ("protegido", "github", "implantacao", "producao") else "a fábrica tenta sozinha"
        linhas.append(f"- **{a['assunto']}** ({a['vezes']}×, {a['papel']}, {a['base']}; {quem}): {a['texto']}")
    if len(linhas) == 2:
        linhas.append("Nenhum achado aberto.")
    print("\n".join(linhas))
    return 0


# ------------------------------------------------------------ demonstração: o círculo fechando num projeto de exemplo
def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def projeto_exemplo(pasta: Path) -> Path:
    origin = pasta / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    r = pasta / "loja"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    (r / "carrinho.py").write_text("def total(itens):\n    # bug: ignora a quantidade\n    return sum(p for p, q in itens)\n\n\ndef desconto(total, cupom):\n    return total\n")
    (r / "tests").mkdir()
    (r / "tests" / "test_base.py").write_text("from carrinho import total\n\ndef test_vazio():\n    assert total([]) == 0\n")
    (r / CONFIG).write_text(json.dumps({**PADRAO, "nome": "loja", "testes": f"{os.environ.get('FABRICA_PYTEST', sys.executable + ' -m pytest')} -q -x -p no:cacheprovider", "lint": "",
                                        "protegidos": ["fabrica.json", "pagamentos/"], "max_linhas_pr": 200}, ensure_ascii=False, indent=2))
    _git(r, "add", "-A")
    _git(r, "-c", "user.name=demo", "-c", "user.email=demo@local", "commit", "-q", "-m", "loja inicial")
    _git(r, "remote", "add", "origin", str(origin))
    _git(r, "push", "-q", "origin", "main")
    return r


def roteiro_demo(instrucao: str, cwd: Path) -> dict:
    """O executor simulado da demonstração: acerta o primeiro cartão, esquece o teste no segundo (o QA devolve) e corrige."""
    time.sleep(float(os.environ.get("FABRICA_DEMO_PAUSA", "0.8")))
    if "gerente de produto" in instrucao:
        if "quantidade" in instrucao:
            return {"ok": True, "texto": json.dumps({"titulo": "Total do carrinho considera a quantidade", "criterios": ["total([(10, 2)]) == 20", "total([]) == 0"], "verificacao": "rodar os testes de carrinho"}), "log": ""}
        return {"ok": True, "texto": json.dumps({"titulo": "Cupom de 10% no desconto", "criterios": ["desconto(100, 'DEZ') == 90", "cupom desconhecido não desconta"], "verificacao": "rodar os testes de carrinho"}), "log": ""}
    if "Você é o arquiteto" in instrucao:
        return {"ok": True, "texto": json.dumps({"onde": ["carrinho.py", "tests/test_carrinho.py"], "plano": "teste de regressão primeiro; mudança de uma linha em carrinho.py", "riscos": ["pagamentos/ é protegido: não tocar"]}), "log": ""}
    if "Você é o desenvolvedor" in instrucao:
        if "quantidade" in instrucao:
            (cwd / "carrinho.py").write_text((cwd / "carrinho.py").read_text().replace("sum(p for p, q in itens)", "sum(p * q for p, q in itens)"))
            (cwd / "tests" / "test_carrinho.py").write_text("from carrinho import total\n\ndef test_quantidade():\n    assert total([(10, 2)]) == 20\n")
        else:
            (cwd / "carrinho.py").write_text((cwd / "carrinho.py").read_text().replace("    return total\n", "    return total * 0.9 if cupom == 'DEZ' else total\n"))
            if "DEVOLUÇÃO" in instrucao:      # na segunda tentativa o dev lembra do teste
                (cwd / "tests" / "test_cupom.py").write_text("from carrinho import desconto\n\ndef test_cupom():\n    assert desconto(100, 'DEZ') == 90\n    assert desconto(100, 'X') == 100\n")
        return {"ok": True, "texto": "", "log": "ok"}
    return {"ok": True, "texto": "", "log": ""}


def _demo(args):
    pasta = Path(tempfile.mkdtemp(prefix="fabrica-demo-"))
    raiz = projeto_exemplo(pasta)
    est = Estado(pasta / "fabrica.db")
    fab = Fabrica(Projeto.abrir(raiz), est, Simulado(roteiro_demo), GitHubFalso(pasta / "origin.git"))
    from .painel import servir
    servir(est.caminho, args.porta, fundo=True)
    print(f"demonstração: projeto de exemplo em {raiz}\npainel em http://127.0.0.1:{args.porta}  (Ctrl+C para parar)")
    fab.pedir("O total do carrinho ignora a quantidade: total([(10, 2)]) tem de dar 20.")
    fab.pedir("Quero um cupom DEZ que dá 10% de desconto no total.")

    def girar():
        try:
            fab.rodar(intervalo=args.intervalo)
        except Exception as exc:  # noqa: BLE001 — a demonstração mostra o erro em vez de morrer calada
            est.evento("mensagem", None, "coordenador", "humano", f"A fábrica parou: {exc}", {"tom": "alerta"})
    t = threading.Thread(target=girar, daemon=True)
    t.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nfim da demonstração")
        if not args.manter:
            shutil.rmtree(pasta, ignore_errors=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fabrica", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pasta", help="raiz do projeto (padrão: pasta atual)")
    ap.add_argument("--dados", help="onde guardar o estado (padrão: <projeto>/.fabrica)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("iniciar")
    s.add_argument("pasta", nargs="?")
    s.add_argument("--forcar", action="store_true")
    s.set_defaults(f=_iniciar)
    s = sub.add_parser("pedir")
    s.add_argument("texto", nargs="+")
    s.set_defaults(f=_pedir)
    s = sub.add_parser("rodar")
    s.add_argument("--uma-vez", action="store_true")
    s.add_argument("--intervalo", type=float, default=float(os.environ.get("FABRICA_INTERVALO", "3")))
    s.add_argument("--painel", action="store_true", help="sobe o painel junto")
    s.add_argument("--porta", type=int, default=8766)
    s.set_defaults(f=_rodar)
    s = sub.add_parser("painel")
    s.add_argument("--porta", type=int, default=8766)
    s.set_defaults(f=_painel)
    s = sub.add_parser("achados")
    s.set_defaults(f=_achados)
    s = sub.add_parser("demo")
    s.add_argument("--porta", type=int, default=8766)
    s.add_argument("--intervalo", type=float, default=2.5)
    s.add_argument("--manter", action="store_true")
    s.set_defaults(f=_demo)
    args = ap.parse_args(argv)
    return args.f(args)


if __name__ == "__main__":
    sys.exit(main())

"""O id pytest conferido por `ast` antes de rodar (lição #26): o reparo copiava ou inventava um id, e o pytest só
avisava depois de iniciar ('ERROR: file or directory not found', saída 4).

O id é `arquivo::Classe::...::funcao[parametros]`. O sufixo `[...]` sai do último trecho, as classes podem ser
aninhadas. Classe com base (herança) pode ter testes que o `ast` não vê: o que fica abaixo dela não é recusado.

Passos (lição #59): o agente parava no máximo de passos (38 em 709 execuções). `estimar_passos` prevê por regra a
fração do limite que a tarefa usa; acima do limiar o fatiador divide antes de rodar. A fração prevista de cada tarefa
fica em PASSOS e o limiar sai do p20 das previsões das que ainda pararam no máximo (trajetórias que falham são mais
longas que as bem-sucedidas): 80% delas teriam sido divididas.

Convenções: o AGENTS.md da raiz entra no prompt e cada tarefa grava o hash, os títulos das seções injetadas e
`com_convencoes`, listados no corpo do PR. O efeito medido de arquivos de contexto é pequeno (~+4% com arquivo humano)
e o custo sobe mais de 20% (Gloaguen et al., arXiv 2602.11988): ~20% das tarefas, sorteadas pelo título, ficam sem o
arquivo como controle, e `relatorio_convencoes` (`python -m circulo.developer --dias 7`) compara falha e tokens por
tarefa nos dois grupos.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DEF = (ast.FunctionDef, ast.AsyncFunctionDef)
REPARO = "developer:reparo"
CAUSA_ALVO = "alvo_inexistente"
ALVO_INEXISTENTE = f"{REPARO}:{CAUSA_ALVO}"   # uma lição, seja qual for o teste citado (lições #31 e #35)
NAO_COLETADO = (4, 5)                       # pytest: id não achado (erro de uso) e nenhum teste coletado

LIMITE_PASSOS = 40                          # o --max-turns padrão do ClaudeCodeAgent
PASSOS_BASE, PASSOS_POR_ARQUIVO, PASSOS_POR_FUNCAO = 8, 6, 3   # ler/testar/lint/commit; ler e editar; editar e testar
LIMIAR_INICIAL, PERCENTIL, MIN_AMOSTRAS = 0.8, 0.2, 5
PASSOS = "developer_passos"                 # kv: título da tarefa -> {"fracao", "limite", "em"}
MAX_REGISTROS = 300

ARQUIVO_CONVENCOES = "AGENTS.md"
CONVENCOES = "developer_convencoes"         # kv: título da tarefa -> {"hash", "secoes", "com_convencoes", "linhas", "bytes", "em"}
FRACAO_CONTROLE = 0.2                       # tarefas sem o arquivo, para comparar
CUSTO_ACEITO = 1.2                          # o grupo com convenções pode custar até 20% a mais por tarefa
TITULO_MD = re.compile(r"#{1,6}\s+(.+?)[\s#]*$")


def estimar_passos(arquivos, funcoes, limite: int = LIMITE_PASSOS) -> float:
    """A fração do limite de passos que a tarefa deve usar, pelos arquivos e funções citados."""
    return (PASSOS_BASE + PASSOS_POR_ARQUIVO * len(arquivos) + PASSOS_POR_FUNCAO * len(funcoes)) / limite


def limiar_de_passos(fracoes_que_estouraram: list[float]) -> float:
    """O p20 das frações previstas das tarefas que pararam no máximo de passos; LIMIAR_INICIAL com poucas amostras."""
    if len(fracoes_que_estouraram) < MIN_AMOSTRAS:
        return LIMIAR_INICIAL
    ordem = sorted(fracoes_que_estouraram)
    return ordem[max(0, math.ceil(PERCENTIL * len(ordem)) - 1)]


def registrar_passos(s, titulo: str, fracao: float, limite: int) -> None:
    reg, chave = s.get(PASSOS) or {}, titulo[:120]
    if reg.get(chave, {}).get("fracao") == round(fracao, 4) and reg[chave].get("limite") == limite:
        return
    reg[chave] = {"fracao": round(fracao, 4), "limite": limite, "em": time.time()}
    s.set(PASSOS, dict(sorted(reg.items(), key=lambda kv: kv[1]["em"])[-MAX_REGISTROS:]))


def parou_no_maximo(motivo: str | None) -> bool:
    from .licoes import causa_de_json
    return causa_de_json(motivo or "") == "maximo_de_passos"


def limiar_calibrado(s) -> float:
    """O limiar pelas tarefas registradas cuja execução do agente parou no máximo de passos."""
    reg = s.get(PASSOS) or {}
    if not reg:
        return LIMIAR_INICIAL
    rows = s.q("SELECT DISTINCT sujeito, motivo FROM verificacoes WHERE ponto='developer:agente' AND ok=0 "
               f"AND sujeito IN ({','.join('?' * len(reg))})", tuple(reg))
    estouradas = {r["sujeito"] for r in rows if parou_no_maximo(r["motivo"])}
    return limiar_de_passos([reg[t]["fracao"] for t in estouradas])


def ultima_parou_no_maximo(s, titulo: str) -> bool:
    """A última execução do agente nesta tarefa parou no máximo de passos: ela volta ao fatiador, não inteira."""
    r = s.one("SELECT ok, motivo FROM verificacoes WHERE ponto='developer:agente' AND sujeito=? ORDER BY id DESC LIMIT 1",
              (titulo[:120],))
    return bool(r) and not r["ok"] and parou_no_maximo(r["motivo"])


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


def alvo_coletado(raiz: Path | str, node_id: str, env: dict | None = None) -> bool:
    """O pytest coleta o id (`--collect-only`): o `ast` não vê o que o pytest descarta (classe com `__init__`, conftest).
    Só a saída 4 ou 5 recusa; sem pytest ou com erro de coleta, quem relata é a execução."""
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", node_id],
                           cwd=raiz, capture_output=True, text=True, timeout=300, env=env)
    except subprocess.TimeoutExpired:
        return True
    return p.returncode not in NAO_COLETADO


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


def no_controle(titulo: str, fracao: float = FRACAO_CONTROLE) -> bool:
    """O sorteio determinístico do grupo de controle: o mesmo título cai sempre no mesmo grupo."""
    return int(hashlib.sha256(titulo.encode("utf-8")).hexdigest()[:8], 16) < fracao * 0x100000000


def secoes_md(texto: str) -> list[str]:
    """Os títulos `#` do markdown, fora dos blocos de código."""
    out, codigo = [], False
    for linha in texto.splitlines():
        if linha.lstrip().startswith("```"):
            codigo = not codigo
        elif not codigo and (m := TITULO_MD.match(linha)):
            out.append(m.group(1))
    return out


def convencoes(raiz: Path | str, titulo: str, fracao_controle: float = FRACAO_CONTROLE) -> dict:
    """O que do AGENTS.md entra no prompt desta tarefa (`texto`) e o evento dela: hash, seções, grupo e tamanho."""
    try:
        bruto = (Path(raiz) / ARQUIVO_CONVENCOES).read_bytes()
        conteudo = bruto.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return {"hash": None, "secoes": [], "com_convencoes": False, "linhas": 0, "bytes": 0, "texto": ""}
    com = not no_controle(titulo, fracao_controle)
    return {"hash": hashlib.sha256(bruto).hexdigest()[:12], "secoes": secoes_md(conteudo) if com else [],
            "com_convencoes": com, "linhas": len(conteudo.splitlines()), "bytes": len(bruto),
            "texto": f"\nConvenções do repositório ({ARQUIVO_CONVENCOES}):\n{conteudo.strip()}\n" if com else ""}


def registrar_convencoes(s, titulo: str, conv: dict) -> None:
    reg = s.get(CONVENCOES) or {}
    ev = {k: v for k, v in conv.items() if k != "texto"}
    if {k: v for k, v in reg.get(titulo, {}).items() if k != "em"} == ev:
        return
    reg[titulo] = {**ev, "em": time.time()}
    s.set(CONVENCOES, dict(sorted(reg.items(), key=lambda kv: kv[1]["em"])[-MAX_REGISTROS:]))


def linha_pr(ev: dict | None) -> str:
    """O evento da tarefa no corpo do PR."""
    if not ev:
        return f"Convenções ({ARQUIVO_CONVENCOES}): sem registro nesta tarefa."
    if not ev.get("hash"):
        return f"Convenções ({ARQUIVO_CONVENCOES}): arquivo ausente, nada injetado (com_convencoes=0)."
    grupo = ("seções injetadas: " + (", ".join(ev["secoes"]) or "nenhuma")) if ev["com_convencoes"] else \
        "grupo de controle, nada injetado"
    return (f"Convenções ({ARQUIVO_CONVENCOES} `{ev['hash']}`, {ev['linhas']} linhas, {ev['bytes']} bytes): {grupo} "
            f"(com_convencoes={int(ev['com_convencoes'])}).")


class GitHubComConvencoes:
    """O GitHub do Developer: cada PR aberto leva no corpo o evento de convenções da tarefa."""

    def __init__(self, gh, store):
        self._gh, self._s = gh, store

    def __getattr__(self, nome):
        return getattr(self._gh, nome)

    def create_pr(self, head: str, base: str, title: str, body: str) -> int:
        ev = (self._s.get(CONVENCOES) or {}).get(title)
        return self._gh.create_pr(head, base, title, f"{body}\n\n{linha_pr(ev)}")


def relatorio_convencoes(s, desde: float = 0.0) -> dict:
    """Taxa de falha e tokens por tarefa com e sem convenções (só tarefas em que o arquivo existia e já com desfecho).
    `aceito`: o grupo com convenções não falha mais que o controle nem custa mais de CUSTO_ACEITO vezes."""
    from .neuronios import ABRIR_PR
    from .reparo import tokens_do_item
    grupos: dict[str, list[tuple[bool, int, int]]] = {"com": [], "controle": []}
    for titulo, ev in (s.get(CONVENCOES) or {}).items():
        if not ev.get("hash") or ev.get("em", 0) < desde:
            continue
        r = s.one("SELECT ok FROM verificacoes WHERE ponto IN ('developer:agente', ?) AND sujeito IN (?, ?) "
                  "ORDER BY id DESC LIMIT 1", (ABRIR_PR, titulo, titulo[:120]))
        if r is not None:
            grupos["com" if ev["com_convencoes"] else "controle"].append(
                (not r["ok"], tokens_do_item(s, titulo)[0], ev["bytes"] if ev["com_convencoes"] else 0))
    out: dict = {g: {"tarefas": len(v), "taxa_falha": round(sum(f for f, _, _ in v) / len(v), 4) if v else None,
                     "tokens_por_tarefa": round(sum(t for _, t, _ in v) / len(v)) if v else None,
                     "bytes_injetados": round(sum(b for _, _, b in v) / len(v)) if v else None}
                 for g, v in grupos.items()}
    com, ctrl = out["com"], out["controle"]
    medido = com["tarefas"] and ctrl["tarefas"] and ctrl["tokens_por_tarefa"]
    out["custo_relativo"] = round(com["tokens_por_tarefa"] / ctrl["tokens_por_tarefa"], 4) if medido else None
    out["aceito"] = (com["taxa_falha"] <= ctrl["taxa_falha"] and out["custo_relativo"] <= CUSTO_ACEITO) if medido else None
    return out


def main(argv: list[str] | None = None) -> None:
    """python -m circulo.developer [--dias 7]: falha e tokens por tarefa com e sem convenções, em JSON."""
    ap = argparse.ArgumentParser(prog="python -m circulo.developer",
                                 description="compara falha e custo das tarefas com e sem o AGENTS.md no prompt")
    ap.add_argument("--data", default=os.environ.get("CIRCULO_DATA", "data"))
    ap.add_argument("--dias", type=float, default=7.0)
    args = ap.parse_args(argv)
    from .state import Store
    store = Store(os.path.join(args.data, "circulo.db"))
    print(json.dumps(relatorio_convencoes(store, desde=time.time() - args.dias * 86400), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""O id pytest conferido por `ast` antes de rodar (lição #26): o reparo copiava ou inventava um id, e o pytest só
avisava depois de iniciar ('ERROR: file or directory not found', saída 4).

O id é `arquivo::Classe::...::funcao[parametros]`. O sufixo `[...]` sai do último trecho, as classes podem ser
aninhadas. Classe com base (herança) pode ter testes que o `ast` não vê: o que fica abaixo dela não é recusado.

Passos (lição #59): o agente parava no máximo de passos (38 em 709 execuções). `estimar_passos` prevê por regra a
fração do limite que a tarefa usa; acima do limiar o fatiador divide antes de rodar. A fração prevista de cada tarefa
fica em PASSOS e o limiar sai do p20 das previsões das que ainda pararam no máximo (trajetórias que falham são mais
longas que as bem-sucedidas): 80% delas teriam sido divididas.
"""
from __future__ import annotations

import ast
import math
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

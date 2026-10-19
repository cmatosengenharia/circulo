"""Fronteiras da arquitetura, conferidas no CI (Lauren Tan: corrigir na camada mais forte; primeiro parar de crescer).

O grafo de importação do pacote é lido do código (ast), e as regras abaixo barram o que tornaria o loop menos seguro:
- o painel (camada de leitura) nunca importa quem age: Developer, gate de merge, corpo, o próprio loop;
- a constituição só depende do que já dependia: um import novo dela para um módulo que o Developer pode mudar
  daria ao agente um jeito indireto de mudar a constituição;
- só a linha de comando (e o demo) sobem o loop inteiro;
- nenhum módulo passa de MAX_LINHAS, e os indicadores do jardineiro não passam do teto de hoje (podar baixa o teto).
"""
import ast
from pathlib import Path

from circulo.jardineiro import medir

PACOTE = Path(__file__).resolve().parents[1] / "circulo"
CONSTITUICAO = {"merge_gate", "policy", "budget", "guardrails", "self_dev", "corpo"}
# o que a constituição importa hoje de fora dela; crescer exige você mudar esta lista (e a constituição) de propósito
CONSTITUICAO_PODE_IMPORTAR = {
    "budget": {"state"}, "guardrails": {"state"}, "policy": {"state"},
    "merge_gate": {"agents", "licoes", "projects"},
    "corpo": {"licoes", "rastro"},
    "self_dev": {"agents", "licoes", "neuronios", "projects", "rastro", "registro", "reproducao"},
}
ATUADORES = {"self_dev", "merge_gate", "corpo", "loop"}
SOBEM_O_LOOP = {"cli", "demo", "confianca"}       # confianca só lê uma constante (ESTAGNADO)
MAX_LINHAS = 1000
TETO_JARDIM = {"except_exception": 64, "noqa": 75, "funcoes_longas": 14, "modulos_grandes": 1, "todo": 8}


def grafo() -> dict[str, set[str]]:
    g = {}
    for p in sorted(PACOTE.glob("*.py")):
        deps = set()
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.ImportFrom) and n.level == 1:
                deps |= {n.module.split(".")[0]} if n.module else {a.name for a in n.names}
        g[p.stem] = deps - {"__version__"}
    return g


def test_painel_nunca_importa_quem_age():
    assert not grafo()["painel"] & ATUADORES


def test_constituicao_nao_ganha_dependencia_nova():
    g = grafo()
    for c in CONSTITUICAO:
        novas = (g[c] - CONSTITUICAO) - CONSTITUICAO_PODE_IMPORTAR.get(c, set())
        assert not novas, f"{c} passou a importar {sorted(novas)}: dependência nova da constituição"


def test_so_a_linha_de_comando_sobe_o_loop():
    quem = {m for m, d in grafo().items() if "loop" in d}
    assert quem <= SOBEM_O_LOOP, f"importam o loop inteiro: {sorted(quem - SOBEM_O_LOOP)}"


def test_nenhum_modulo_gigante():
    grandes = {p.name: n for p in PACOTE.glob("*.py") if (n := len(p.read_text(encoding="utf-8").splitlines())) > MAX_LINHAS}
    assert not grandes, grandes


def test_except_exception_conta_so_o_erro_engolido(tmp_path):
    """lição #17: registrar a falha e repropagar não engole o erro; só o bloco que engole entra no teto."""
    (tmp_path / "a.py").write_text(
        '"""menciona `except Exception` só no texto"""\n'
        "def engole():\n    try:\n        pass\n    except Exception:\n        pass\n"
        "def repropaga():\n    try:\n        pass\n    except Exception as exc:\n        print(exc)\n        raise\n"
        "def converte():\n    try:\n        pass\n    except (Exception, OSError) as exc:\n        raise RuntimeError() from exc\n")
    assert medir(tmp_path)["total"]["except_exception"] == 1


def test_padroes_ruins_nao_crescem():
    total = medir(PACOTE)["total"]
    passou = {k: (total[k], teto) for k, teto in TETO_JARDIM.items() if total[k] > teto}
    assert not passou, f"cresceu além do teto (pode podar e baixar o teto, nunca subir sem motivo): {passou}"

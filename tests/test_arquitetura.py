"""Fronteiras da arquitetura, conferidas no CI (Lauren Tan: corrigir na camada mais forte; primeiro parar de crescer).

O grafo de importação do pacote é lido do código (ast), e as regras abaixo barram o que tornaria o loop menos seguro:
- o painel (camada de leitura) nunca importa quem age: Developer, gate de merge, corpo, o próprio loop;
- a constituição só depende do que já dependia: um import novo dela para um módulo que o Developer pode mudar
  daria ao agente um jeito indireto de mudar a constituição;
- só a linha de comando (e o demo) sobem o loop inteiro;
- nenhum módulo passa de MAX_LINHAS, e os indicadores do jardineiro não passam do teto de hoje (podar baixa o teto).
"""
import ast
import re
from pathlib import Path

from circulo.jardineiro import medir

PACOTE = Path(__file__).resolve().parents[1] / "circulo"
CONSTITUICAO = {"merge_gate", "policy", "budget", "guardrails", "self_dev", "corpo"}
# o que a constituição importa hoje de fora dela; crescer exige você mudar esta lista (e a constituição) de propósito
CONSTITUICAO_PODE_IMPORTAR = {
    "budget": {"state"}, "guardrails": {"state"}, "policy": {"state"},
    "merge_gate": {"agents", "licoes", "projects", "revisor"},
    "corpo": {"licoes", "rastro"},
    "self_dev": {"agents", "licoes", "neuronios", "projects", "rastro", "registro", "reproducao", "revisor"},
}
ATUADORES = {"self_dev", "merge_gate", "corpo", "loop"}
SOBEM_O_LOOP = {"cli", "demo", "confianca", "controle"}   # confianca só lê uma constante (ESTAGNADO); controle é um ponto de entrada (painel + SRE em processo próprio)
MAX_LINHAS = 1000
TETO_JARDIM = {"except_exception": 64, "noqa": 51, "funcoes_longas": 14, "modulos_grandes": 1, "todo": 8}


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


def test_json_da_llm_so_e_lido_por_json_llm():
    """lição #22: cada papel lia o JSON da LLM do seu jeito (primeiro `{`, `\\{.*\\}` guloso) e uma chave na narração
    descartava a resposta inteira. Uma única forma de ler: circulo/json_llm.py."""
    jeitos = ('r"\\{.*\\}"', "raw_decode", '.find("{")')
    fora = {p.name: j for p in PACOTE.glob("*.py") if p.stem != "json_llm"
            for j in jeitos if j in p.read_text(encoding="utf-8")}
    assert not fora, f"leia o JSON da LLM com circulo.json_llm.objeto/objeto_ou_corte: {fora}"


def test_json_da_llm_e_aceito_pelo_criterio_do_papel_e_nao_por_uma_chave():
    """lição #22 (reincidiu 2x): ler pela chave devolvia o primeiro objeto que a tinha (rascunho, formato ecoado) e o
    papel só validava depois, descartando a resposta boa que vinha em seguida. O leitor recebe o critério do papel."""
    from circulo.json_llm import objeto, objeto_ou_corte
    formato = 'formato: {"veredito": "adotar|adaptar"} '
    valido = lambda d: d if d.get("veredito") in ("adotar", "adaptar") else None  # noqa: E731
    assert objeto(formato + '{"veredito": "adotar", "j": "x"}', valido) == {"veredito": "adotar", "j": "x"}
    assert objeto_ou_corte(formato + '{"veredito": "adaptar", "j": "x", "k": "cor', lambda d, cortado: valido(d) if cortado else None) \
        == {"veredito": "adaptar", "j": "x"}
    chamadas = re.compile(r"\bobjeto(?:_ou_corte)?\(\s*\w+\s*,\s*[\"']")
    por_chave = [p.name for p in PACOTE.glob("*.py") if chamadas.search(p.read_text(encoding="utf-8"))]
    assert not por_chave, f"passe o critério de aceite do papel (callable), não uma chave: {por_chave}"


def test_padroes_ruins_nao_crescem():
    total = medir(PACOTE)["total"]
    passou = {k: (total[k], teto) for k, teto in TETO_JARDIM.items() if total[k] > teto}
    assert not passou, f"cresceu além do teto (pode podar e baixar o teto, nunca subir sem motivo): {passou}"


def test_licao_2_nenhum_teste_exige_o_erro_antigo_e_depois_o_conserto():
    """lição #2: um teste exigia `pytest.raises` em `Corpo(...).run()` (o erro do incidente) e depois o mesmo
    `Corpo(...)` funcionando; outra correção tirou o erro e a main ficou vermelha. Nenhum teste do repo faz isso."""
    from circulo.reproducao import exigem_o_erro_antigo
    fazem = {p.name: n for p in Path(__file__).parent.glob("test_*.py") if (n := exigem_o_erro_antigo(p.read_text(encoding="utf-8")))}
    assert not fazem, f"o teste exige o erro antigo e depois o conserto na mesma chamada (o portão já roda o teste no código antigo): {fazem}"


def test_testes_importam_vizinhos_sem_o_prefixo_tests():
    """21/10: `from tests.test_medico import …` funcionava com PYTHONPATH=. e quebrava a coleta no CI (`tests` não é
    pacote): a suíte inteira saía com código 2 e todo PR ficava vermelho. Vizinho se importa pelo nome do módulo."""
    proibido = re.compile(r"^\s*(from tests[.\s]|import tests\b)", re.M)
    usam = [p.name for p in Path(__file__).parent.glob("*.py") if proibido.search(p.read_text(encoding="utf-8"))]
    assert not usam, f"import com o prefixo tests. (use `from test_x import …`): {usam}"


def test_testes_nao_usam_a_data_local_da_maquina():
    """lição #48: o orçamento conta o dia em America/Sao_Paulo; `date.today()` no teste dá o dia do fuso da máquina
    (UTC no CI), e das 21 h à meia-noite de Brasília o "ontem" do teste vira o "hoje" do orçamento. Use o NOON do conftest."""
    proibido = re.compile(r"\bdate\.today\(\)")
    usam = [p.name for p in Path(__file__).parent.glob("*.py") if p.name != Path(__file__).name and proibido.search(p.read_text(encoding="utf-8"))]
    assert not usam, f"dia do fuso da máquina em vez do fuso do orçamento (use NOON / budget.TZ): {usam}"

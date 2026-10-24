"""Base vermelha: a falha local é um registro por (item, assinatura do teste, sha da main), com contador (item #163).

Medido: 3786 falhas locais no item 144 em 7 dias. Agrupar pela impressão digital e contar as ocorrências (Sentry) guarda
quantas vezes o loop tentou sem uma linha por tentativa; a base já confirmada vermelha neste sha não roda de novo."""
from circulo.reparo import DeveloperComReparo, registrar_base

from test_base_vermelha import commit
from test_preflight_developer import ContaAgent, item
from test_self_dev import FakeGH, repo  # noqa: F401 — fixture do repositório


def test_50_execucoes_com_a_mesma_chave_sao_1_registro_e_um_sha_novo_e_outro(circle):
    s = circle.store
    for _ in range(50):
        registrar_base(s, 7, "tests/test_app.py::test_soma AssertionError", "a" * 40, "test_soma")
    linhas = s.q("SELECT sha, ocorrencias, primeira_vez, ultima_vez FROM base_vermelha WHERE item_id=7")
    assert [(r["sha"], r["ocorrencias"]) for r in linhas] == [("a" * 40, 50)]
    assert linhas[0]["ultima_vez"] >= linhas[0]["primeira_vez"]

    assert registrar_base(s, 7, "tests/test_app.py::test_soma AssertionError", "b" * 40, "test_soma") == 1
    assert s.one("SELECT COUNT(*) n FROM base_vermelha WHERE item_id=7")["n"] == 2


def test_base_confirmada_no_mesmo_sha_nao_roda_os_testes_de_novo(circle, repo, tmp_path):  # noqa: F811
    execucoes = tmp_path / "execucoes.txt"
    teste = (f"from app import soma\n\n\ndef test_soma():\n    open({str(execucoes)!r}, 'a').write('x\\n')\n"
             "    assert soma(2, 2) == 4\n")
    commit(repo, {"app.py": "def soma(a, b):\n    return a - b\n", "tests/test_app.py": teste})
    it = item(circle, "Mudar a soma em app.py para aceitar negativos.")
    dev = DeveloperComReparo(circle.ctx, repo, ContaAgent(), FakeGH(), lint_cmd=[], fix_cmds=[])
    for _ in range(50):
        assert dev._preflight(repo, "Ajustar a soma").startswith("base quebrada")
    s = circle.store
    assert execucoes.read_text().count("x") == 2                     # a 2ª execução confirma; as outras 48 pulam
    assert [r["ocorrencias"] for r in s.q("SELECT ocorrencias FROM base_vermelha WHERE item_id=?", (it,))] == [50]
    assert s.one("SELECT COUNT(*) n FROM verificacoes WHERE ponto='developer:base' AND ok=0")["n"] == 1

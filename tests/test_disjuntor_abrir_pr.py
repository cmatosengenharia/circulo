"""Disjuntor por assinatura no developer:abrir_pr: a mesma barra 2x seguidas no item o bloqueia sem nova chamada ao
developer nem ao pytest, e ele só volta quando o arquivo citado (ou, sem arquivo, a main) muda (pergunta do conselho #55)."""
from test_reparo import ZipAgent, dev_de, verificacoes
from test_self_dev import erro_recorrente, git, repo  # noqa: F401 — fixture do repositório

from circulo.neuronios import ABRIR_PR, criar_portao
from circulo.reparo import BLOQUEADO, barra_do_item


def _giro(dev, repo):  # noqa: F811
    for b in git(repo, "branch", "--list", "circulo/*", "--format=%(refname:short)").splitlines():
        git(repo, "branch", "-D", b)        # o nome da branch leva o segundo: dois giros no mesmo segundo colidem
    return dev.run_once()


def test_tres_barras_iguais_geram_duas_tentativas_e_um_bloqueio_e_a_main_mudar_reabre(circle, repo, tmp_path):  # noqa: F811
    item = erro_recorrente(circle)
    # portão aprendido que o agente nunca satisfaz: a mesma barra determinística a cada tentativa
    criar_portao(circle.store, ABRIR_PR, "obrigatorio", {"regex": "MARCA_QUE_NUNCA_VEM", "em": "teste", "item": item["id"]},
                 "teste traz a marca", None)
    agent = ZipAgent(conserta_na=1)            # lint e testes verdes: só o portão aprendido barra
    dev, gh = dev_de(circle, repo, tmp_path, agent)
    resultados = [_giro(dev, repo) for _ in range(3)]
    assert [r.status for r in resultados] == ["testes_falharam", "testes_falharam", "nada"]
    assert [v["ok"] for v in verificacoes(circle, "developer:abrir_pr")] == [0, 0]     # 2 tentativas, não 3
    chamadas = len(agent.tasks)
    st = circle.store.one("SELECT status, evidencia FROM roadmap WHERE id=?", (item["id"],))
    assert st["status"] == BLOQUEADO and "developer:abrir_pr:" in st["evidencia"]
    assert _giro(dev, repo).status == "nada" and len(agent.tasks) == chamadas           # bloqueado não gasta
    assert dev.run_once(item_id=item["id"]).status == "bloqueado" and len(agent.tasks) == chamadas
    # a main muda (a barra não cita arquivo): o item reabre e ganha uma nova tentativa
    (repo / "outro.py").write_text("X = 1\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "outra mudança")
    git(repo, "push", "-q", "origin", "main")
    assert _giro(dev, repo).status == "testes_falharam" and len(agent.tasks) > chamadas and gh.prs == []
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item["id"],))["status"] == "pendente"


def test_assinatura_diferente_zera_a_contagem_e_so_a_mesma_2x_seguidas_bloqueia(circle):
    s = circle.store
    assert not barra_do_item(s, 7, "developer:abrir_pr:lint:B905", "a")
    assert not barra_do_item(s, 7, "developer:abrir_pr:teste:tests/test_x.py::test_y", "a")    # outra causa: reabre
    assert barra_do_item(s, 7, "developer:abrir_pr:teste:tests/test_x.py::test_y", "a")
    assert not barra_do_item(s, 8, "developer:abrir_pr:teste:tests/test_x.py::test_y", "a")    # por item


def test_barra_que_cita_arquivo_so_reabre_quando_esse_arquivo_muda(circle, repo, tmp_path):  # noqa: F811
    dev, _ = dev_de(circle, repo, tmp_path, ZipAgent())
    texto = "- aprendido#3: ERROR: file or directory not found: tests/test_vigia_trava_estado.py::test_200_x"
    antes = dev._chave(texto)
    (repo / "outro.py").write_text("X = 1\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "outra mudança")
    git(repo, "push", "-q", "origin", "main")
    assert dev._chave(texto) == antes                     # a main mudou, mas não o teste citado
    (repo / "tests").mkdir()
    (repo / "tests/test_vigia_trava_estado.py").write_text("def test_200_x():\n    pass\n")
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "o teste citado nasce")
    git(repo, "push", "-q", "origin", "main")
    assert dev._chave(texto) != antes

"""Curador de lições (pergunta do conselho #190): lição cujo node id de pytest citado não existe em tests/ fecha com a
causa, e reabre se o teste citado aparecer."""
import subprocess
import time

from circulo.curador_licoes import CAUSA, curar_no_main, inexistentes, node_ids
from circulo.perguntas import METRICAS

SUMIDO = "tests/test_vigia_trava_estado.py::test_200_decisoes_de_vigia_trava_saem_da_duvida_concordando_com_a_regra"


def git(repo, *a):
    subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)


def commit(repo, arquivos: dict[str, str]):
    for nome, texto in arquivos.items():
        (repo / nome).parent.mkdir(parents=True, exist_ok=True)
        (repo / nome).write_text(texto)
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")


def licao(store, lid, descricao, status="aberta", assinatura=None):
    agora = time.time()
    store.x("INSERT INTO licoes(id,assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,"
            "primeira_tick,ultima_tick,created_at,updated_at,camada) VALUES(?,?,?,?,?,?,?,1,0,0,0,?,?,'regra')",
            (lid, assinatura or f"developer:abrir_pr:x{lid}", "developer:abrir_pr", "trabalho", descricao,
             f"Não repetir: {descricao}", status, agora, agora))


def status(store, lid):
    return store.one("SELECT status FROM licoes WHERE id=?", (lid,))["status"]


def test_node_id_citado_no_texto_e_conferido_pelo_ast():
    fontes = {"tests/test_vigia.py": "class TestX:\n    def test_m(self):\n        pass\n\ndef test_a():\n    pass\n"}
    assert node_ids(f"ERROR: file or directory not found: {SUMIDO} (x)") == [SUMIDO]
    assert inexistentes(f"falhou {SUMIDO}", fontes.get) == [SUMIDO]
    assert inexistentes("falhou tests/test_vigia.py::test_a e tests/test_vigia.py::TestX::test_m", fontes.get) == []
    assert inexistentes("tests/test_vigia.py::test_zz", fontes.get) == ["tests/test_vigia.py::test_zz"]
    assert inexistentes("cortado no fim: tests/test_vigia.py::test_", fontes.get) == []      # nome truncado de um que existe
    assert inexistentes("sem node id nenhum", fontes.get) == []


def test_licoes_26_27_35_com_teste_inexistente_fecham_e_reabrem_se_ele_aparecer(circle, tmp_path):
    """Lição #26, lição #27 e lição #35: a mesma causa raiz, o node id citado não existe ('file or directory not found')."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"tests/test_vigia.py": "def test_existe():\n    assert False\n"})
    s, L = circle.store, circle.licoes
    L.repo = repo
    for lid in (26, 27, 35):
        licao(s, lid, f"developer:abrir_pr: ERROR: file or directory not found: {SUMIDO[:60 + lid]}")
    licao(s, 40, "developer:testes: FAILED tests/test_vigia.py::test_existe - assert False")
    licao(s, 41, "planejador: resposta sem JSON válido")
    L.revisar()
    assert [status(s, i) for i in (26, 27, 35)] == ["obsoleta"] * 3
    assert all(s.one("SELECT prevencao FROM licoes WHERE id=?", (i,))["prevencao"].startswith(CAUSA) for i in (26, 27, 35))
    assert (status(s, 40), status(s, 41)) == ("aberta", "aberta")       # teste que existe e lição sem node id ficam
    assert s.one("SELECT COUNT(*) n FROM licoes WHERE status IN ('aberta','reincidente')")["n"] == 2
    L.revisar()
    assert [status(s, i) for i in (26, 27, 35)] == ["obsoleta"] * 3   # não reincide enquanto o teste não existir
    commit(repo, {"tests/test_vigia_trava_estado.py": f"def {SUMIDO.split('::')[1]}():\n    pass\n"})
    L.revisar()
    assert [status(s, i) for i in (26, 27, 35)] == ["aberta"] * 3     # o teste citado apareceu: a lição volta


def test_sem_repositorio_nao_fecha_nada(circle):
    s, L = circle.store, circle.licoes
    L.repo = None
    licao(s, 26, f"ERROR: file or directory not found: {SUMIDO}")
    L.revisar()
    assert status(s, 26) == "aberta"


def ocorreu(store, lid, tick, dias_atras):
    """A última ocorrência da assinatura: o tick dela e a hora em que o giro foi gravado."""
    store.x("UPDATE licoes SET ultima_tick=? WHERE id=?", (tick, lid))
    store.x("INSERT OR REPLACE INTO metrics(tick,body,created_at) VALUES(?,?,?)", (tick, "{}", time.time() - dias_atras * 86400))


def test_curador_em_sombra_conta_as_elegiveis_a_silencio_sem_fechar_nenhuma(circle, tmp_path):
    """Pergunta do conselho #561: das lições abertas, quantas ficaram 14 dias sem reincidir e têm teste na main citando o
    arquivo. Só conta (licoes_elegiveis_silencio, com a data da última ocorrência); nenhuma muda de estado."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"tests/test_alvo.py": "from circulo import alvo\n\ndef test_alvo():\n    assert alvo\n"})
    s = circle.store
    licao(s, 91, "developer:testes: KeyError em circulo/alvo.py", status="sem_prevencao", assinatura="developer:alvo:KeyError")
    licao(s, 92, "developer:testes: KeyError em circulo/orfao.py", status="sem_prevencao", assinatura="developer:orfao:KeyError")
    licao(s, 93, "planejador: ValueError em circulo/alvo.py", status="reincidente", assinatura="planejador:alvo:ValueError")
    ocorreu(s, 91, 500, dias_atras=2)            # reincidiu há 2 dias
    ocorreu(s, 92, 100, dias_atras=20)           # quieta, mas nenhum teste da main cita circulo/orfao.py
    ocorreu(s, 93, 101, dias_atras=20)           # quieta e coberta: a única elegível
    antes = s.q("SELECT id, status, prevencao, updated_at FROM licoes ORDER BY id")
    curar_no_main(s, repo)
    sombra = s.get("curador_silencio")
    assert sombra["licoes_elegiveis_silencio"] == 1
    assert sombra["elegiveis"] == {"93": time.strftime("%Y-%m-%d", time.localtime(time.time() - 20 * 86400))}
    assert sombra["com_reincidencia"] == [91] and sombra["sem_teste"] == [92]
    assert s.q("SELECT id, status, prevencao, updated_at FROM licoes ORDER BY id") == antes      # em sombra: nada fecha
    _, evidencia = METRICAS["licoes_abertas"][1](s, time.time())
    assert evidencia["licoes_elegiveis_silencio"] == 1


def test_curador_em_sombra_grava_a_contagem_mesmo_sem_a_main(circle):
    licao(circle.store, 93, "planejador: ValueError em circulo/alvo.py", status="reincidente")
    curar_no_main(circle.store, None)
    assert circle.store.get("curador_silencio")["licoes_elegiveis_silencio"] == 0


def test_licao_47_corrigida_com_checagem_vazia_ou_inexistente_volta_a_sem_prevencao(circle, tmp_path):
    """Lição #47 (pergunta do conselho #645): 'Já corrigido (PR #244 mergeado); checagem: ' vazia, e reincidiu 8x. A lição
    corrigida, validada ou reincidente cuja checagem não cita um teste que existe nem um portão ativo cai para
    sem_prevencao, com um elo só (idempotente), e aparece na leitura do curador."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"tests/test_loop.py": "def test_progresso():\n    pass\n"})
    s = circle.store
    desc = "loop:progresso: havia trabalho pendente e nada avançou em 10 giros"
    for lid, st, checagem in ((47, "reincidente", ""), (48, "validada", "teste tests/test_loop.py::test_sumiu"),
                              (49, "reincidente", "teste tests/test_loop.py::test_progresso"),
                              (50, "evidenciada", "portão #7 lint B905"), (51, "reincidente", "portão #8 lint F811")):
        licao(s, lid, desc, status=st, assinatura=f"loop:estagnado:{lid}")
        s.x("UPDATE licoes SET reincidencias=8, prevencao=? WHERE id=?",
            (f"Já corrigido (PR #244 mergeado); checagem: {checagem}; não repetir: {desc}", lid))
    agora = time.time()
    s.x("INSERT INTO portoes(id,neuronio,tipo,spec,descricao,licao_id,ativo,avaliacoes,bloqueios,created_at,updated_at) "
        "VALUES(7,'abrir_pr','comando','{}','lint B905',50,1,0,0,?,?)", (agora, agora))
    curar_no_main(s, repo)
    curar_no_main(s, repo)
    assert [status(s, i) for i in (47, 48, 49, 50, 51)] == ["sem_prevencao", "sem_prevencao", "reincidente", "evidenciada",
                                                            "sem_prevencao"]
    assert s.one("SELECT prevencao FROM licoes WHERE id=47")["prevencao"].startswith("Sem prevenção verificável")
    assert s.one("SELECT COUNT(*) n FROM elos WHERE relacao='sem_checagem'")["n"] == 3
    _, evidencia = METRICAS["licoes_abertas"][1](s, time.time())
    assert evidencia["sem_checagem"] == [47, 48, 51]

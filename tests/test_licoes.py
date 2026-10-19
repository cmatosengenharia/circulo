"""Maturidade: todo ponto de verificação é monitorado; erro vira lição; o mesmo erro de estrutura só acontece uma vez."""
import json
import subprocess
import time

from circulo.licoes import EVID_GIROS, Licoes, assinatura_de, classificar


def lic(circle):
    return circle.licoes


def avancar(circle, giros):
    circle.store.set("tick", circle.store.tick + giros)


def test_toda_verificacao_fica_monitorada(circle):
    L = lic(circle)
    L.verificar("developer:testes", True, sujeito="wt-1")
    L.verificar("developer:testes", False, sujeito="wt-1", motivo="FAILED tests/test_x.py::test_y - assert 1 == 2")
    r = L.resumo()["verificacoes_24h"]
    assert r == [{"ponto": "developer:testes", "total": 2, "falhas": 1}]


def test_assinatura_estavel_para_a_mesma_causa():
    a = assinatura_de("gate:ci", "circulo/evolution.py:44:26: B905 `zip()` without strict (ruff) PR #1 sha e8a25f3")
    b = assinatura_de("gate:ci", "circulo/engine.py:9:1: B905 `zip()` without strict (ruff) PR #7 sha 0a1b2c3d")
    assert a == b == "gate:ci:lint:B905"
    assert assinatura_de("developer:testes", "FAILED tests/test_a.py::test_b - x") == "developer:testes:teste:tests/test_a.py::test_b"
    assert classificar("developer:agente", "You've hit your session limit · resets 4:30am") == "ambiente"
    assert classificar("execucao:meta", "RuntimeError: x") == "estrutural"
    assert classificar("gate:ci", "B905") == "trabalho"


def test_erro_de_estrutura_vira_item_na_primeira_vez(circle):
    L = lic(circle)
    licao = L.verificar("planejador:saida", False, motivo="resposta sem JSON válido", assinatura="planejador:saida_invalida")
    item = circle.store.one("SELECT * FROM roadmap WHERE id=?", (licao["item_id"],))
    assert item["origem"] == "erro" and item["status"] == "pendente" and f"lição #{licao['id']}" in item["detalhe"]
    assert L.bloqueia_evolucao()                                   # primeiro corrige, depois evolui
    assert circle.store.one("SELECT 1 FROM alerts WHERE kind='licao' AND message LIKE 'Erro novo registrado%'")


def test_ciclo_corrigir_validar_evidenciar(circle):
    L = lic(circle)
    licao = L.verificar("planejador:saida", False, motivo="sem JSON", assinatura="planejador:saida_invalida")
    circle.store.x("UPDATE roadmap SET status='em_andamento', evidencia='PR #9' WHERE id=?", (licao["item_id"],))
    L.revisar()
    assert circle.store.one("SELECT status FROM licoes")["status"] == "em_correcao"
    circle.store.x("UPDATE roadmap SET status='feito', evidencia='PR #9 mergeado' WHERE id=?", (licao["item_id"],))
    L.revisar()
    r = circle.store.one("SELECT status, pr FROM licoes")
    assert (r["status"], r["pr"]) == ("validada", 9) and not L.bloqueia_evolucao()
    L.verificar("planejador:saida", True)
    avancar(circle, EVID_GIROS)
    L.revisar()
    assert circle.store.one("SELECT status FROM licoes")["status"] == "evidenciada"
    assert "planejador:saida_invalida" in L.contexto() and "Não repita" in L.contexto()


def test_reincidencia_alerta_e_volta_ao_topo(circle):
    L = lic(circle)
    licao = L.verificar("execucao:meta", False, motivo="RuntimeError: x", assinatura="incidente:abc")
    circle.store.x("UPDATE roadmap SET status='feito', evidencia='PR #3 mergeado' WHERE id=?", (licao["item_id"],))
    L.revisar()
    L.verificar("execucao:meta", False, motivo="RuntimeError: x", assinatura="incidente:abc")    # o mesmo erro voltou
    r = circle.store.one("SELECT status, reincidencias FROM licoes")
    assert (r["status"], r["reincidencias"]) == ("reincidente", 1)
    item = circle.store.one("SELECT status, ordem FROM roadmap WHERE id=?", (licao["item_id"],))
    assert (item["status"], item["ordem"]) == ("pendente", 0)
    assert circle.store.one("SELECT 1 FROM alerts WHERE message LIKE 'REINCIDÊNCIA%'")
    assert L.resumo()["reincidencias"] == 1 and L.bloqueia_evolucao()


def test_erro_de_trabalho_vira_prevencao_sem_item(circle):
    L = lic(circle)
    L.verificar("gate:ci", False, sujeito="PR #1", motivo="circulo/evolution.py:44:26: B905 zip() sem strict (ruff)")
    assert circle.store.one("SELECT COUNT(*) n FROM roadmap WHERE origem='erro'")["n"] == 0
    assert "gate:ci:lint:B905" in L.contexto() and not L.bloqueia_evolucao()


def test_erro_de_ambiente_so_vira_item_se_recorrente(circle):
    L = lic(circle)
    for _ in range(4):
        L.verificar("developer:agente", False, motivo="api_error_status 429 session limit")
    assert circle.store.one("SELECT COUNT(*) n FROM roadmap WHERE origem='erro'")["n"] == 0
    L.verificar("developer:agente", False, motivo="api_error_status 429 session limit")
    assert circle.store.one("SELECT COUNT(*) n FROM roadmap WHERE origem='erro'")["n"] == 1


def test_excecao_no_giro_vira_licao_e_item_na_primeira_vez(circle):
    def boom():
        raise RuntimeError("quebrou no giro 5")
    circle.shadow.evaluate = boom
    circle.tick()
    lic_row = circle.store.one("SELECT * FROM licoes")
    assert lic_row["classe"] == "estrutural" and lic_row["item_id"]
    assert circle.store.one("SELECT titulo FROM roadmap WHERE id=?", (lic_row["item_id"],))["titulo"].startswith("Lição #")


def test_com_licao_aberta_o_circulo_so_evolui_o_dominio(circle):
    lic(circle).verificar("planejador:saida", False, motivo="x", assinatura="planejador:saida_invalida")
    chamado = []
    circle.meta.circle_candidates = lambda: chamado.append(1) or []
    circle.tick()
    assert circle.meta.so_dominio and chamado == []


def test_licoes_entram_no_prompt_do_developer(circle, tmp_path):
    from circulo.self_dev import SelfDeveloper
    lic(circle).verificar("gate:ci", False, motivo="a.py:1:1: B905 zip (ruff)")
    dev = SelfDeveloper(circle.ctx, tmp_path, agent=None, github=None)
    assert "gate:ci:lint:B905" in dev._licoes_txt()


def test_sem_store_de_licoes_nada_quebra():
    from circulo.licoes import registrar

    class Ctx:
        pass
    assert registrar(Ctx(), "x", False, motivo="y") is None


def test_licoes_independem_do_loop(tmp_path):
    from circulo.state import Store
    s = Store(tmp_path / "x.db")
    L = Licoes(s)
    assert L.verificar("a", True) is None and L.resumo()["por_status"] == {}


def test_licao_que_se_repete_sobe_de_camada_e_pede_prevencao_mais_forte(circle):
    """Lauren Tan: correção que aparece de novo ainda não subiu de camada (regra → CI → arquitetura)."""
    from circulo.licoes import REPETICOES_PARA_SUBIR
    L = circle.licoes
    for _ in range(REPETICOES_PARA_SUBIR):
        L.verificar("developer:lint", False, sujeito="wt", motivo="circulo/x.py:1:1: B905 `zip()` without strict")
    lic = circle.store.one("SELECT * FROM licoes WHERE assinatura='developer:lint:lint:B905'")
    assert lic["camada"] == "ci"
    item = circle.store.one("SELECT detalhe FROM roadmap WHERE id=?", (lic["item_id"],))
    assert "Subir de camada" in item["detalhe"] and "CI" in item["detalhe"]


def test_reincidencia_sobe_de_camada(circle):
    L = circle.licoes
    L.verificar("execucao:meta", False, motivo="RuntimeError: boom")
    sig = circle.store.one("SELECT assinatura FROM licoes")["assinatura"]
    circle.store.x("UPDATE licoes SET status='evidenciada' WHERE assinatura=?", (sig,))
    L.verificar("execucao:meta", False, motivo="RuntimeError: boom")
    lic = circle.store.one("SELECT camada, status FROM licoes WHERE assinatura=?", (sig,))
    assert (lic["status"], lic["camada"]) == ("reincidente", "ci")


# ------------------------------------------------------------ lições de teste: unir pelo node id, fechar por reexecução
NODE = "tests/test_jev_replay.py::test_200_decisoes_do_worth_spending_saem_da_duvida_concordando_com_a_regra"


def _abertas(circle):
    return circle.store.one("SELECT COUNT(*) n FROM licoes WHERE status IN ('aberta','reincidente')")["n"]


def test_licao_7_e_8_unem_pelo_node_id_e_guardam_as_origens(circle):
    """lição #7 + lição #8: developer:testes e developer:abrir_pr falhando no mesmo node id são uma lição só."""
    L = circle.licoes
    L.verificar("developer:testes", False, motivo=f"FAILED {NODE} - AssertionError")
    L.verificar("developer:abrir_pr", False, motivo=f"FAILED {NODE} - AssertionError")
    rows = circle.store.q("SELECT * FROM licoes WHERE status!='unida'")
    assert len(rows) == 1 and rows[0]["node_id"] == NODE and rows[0]["ocorrencias"] == 2
    assert json.loads(rows[0]["origens"]) == [f"developer:testes:teste:{NODE}", f"developer:abrir_pr:teste:{NODE}"]


def test_licoes_duplicadas_antigas_viram_uma_e_causas_distintas_nao(circle):
    """lição #7 + lição #8 já gravadas separadas (banco antigo): o giro une; ImportError e B905 ficam como estão."""
    s, agora = circle.store, time.time()
    for sig in (f"developer:testes:teste:{NODE}", f"developer:abrir_pr:teste:{NODE}", "developer:testes:ImportError",
                "developer:lint:lint:B905"):
        s.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,primeira_tick,"
            "ultima_tick,created_at,updated_at) VALUES(?,?,'trabalho','d','p','aberta',1,0,0,0,?,?)",
            (sig, sig.split(":")[1], agora, agora))
    assert _abertas(circle) == 4
    circle.licoes.revisar()
    assert _abertas(circle) == 3
    unida = s.one("SELECT * FROM licoes WHERE node_id=? AND status!='unida'", (NODE,))
    assert len(json.loads(unida["origens"])) == 2 and unida["ocorrencias"] == 2
    assert circle.licoes.contexto().count(NODE) == 1


def test_licao_7_fecha_so_com_verde_em_2_execucoes_registrando_sha(circle):
    L = circle.licoes
    L.verificar("developer:testes", False, motivo=f"FAILED {NODE} - AssertionError")
    L.checar_testes("aaa111", lambda n: 0)
    assert _abertas(circle) == 1                       # um verde só não fecha
    L.checar_testes("aaa111", lambda n: 0)
    r = circle.store.one("SELECT * FROM licoes")
    assert r["status"] == "validada" and _abertas(circle) == 0
    assert [(c["sha"], c["exit"]) for c in json.loads(r["checagens"])] == [("aaa111", 0), ("aaa111", 0)]
    assert "aaa111" in r["prevencao"]


def test_verde_intercalado_com_falha_nao_fecha(circle):
    L = circle.licoes
    L.verificar("developer:testes", False, motivo=f"FAILED {NODE} - x")
    for code in (0, 1, 0):
        L.checar_testes("aaa111", lambda n, code=code: code)
    assert _abertas(circle) == 1


def test_licao_7_nao_fecha_quando_o_teste_some(circle):
    """Exit 4/5 (node id não coletado): obsoleta/indeterminada, nunca fechada."""
    L = circle.licoes
    L.verificar("developer:testes", False, motivo=f"FAILED {NODE} - x")
    for code in (5, 4, 5):
        L.checar_testes("aaa111", lambda n, code=code: code)
    r = circle.store.one("SELECT * FROM licoes")
    assert r["status"] == "obsoleta" and r["corrigida_tick"] is None


def test_licao_de_teste_parada_so_fecha_por_reexecucao(circle):
    L = circle.licoes
    L.verificar("developer:testes", False, motivo=f"FAILED {NODE} - x")
    avancar(circle, EVID_GIROS + 1)
    L.revisar()
    assert _abertas(circle) == 1


def test_licao_7_reabre_so_na_falha_em_sha_posterior(circle):
    L = circle.licoes
    L.verificar("developer:testes", False, motivo=f"FAILED {NODE} - x")
    L.checar_testes("aaa111", lambda n: 0)
    L.checar_testes("aaa111", lambda n: 0)
    # falhar no worktree de um Developer não é falhar na main: não reabre
    L.verificar("developer:abrir_pr", False, motivo=f"FAILED {NODE} - x")
    rodou = []
    L.checar_testes("aaa111", lambda n: rodou.append(n) or 1)    # mesmo sha do fechamento: nem roda
    assert rodou == [] and circle.store.one("SELECT status FROM licoes")["status"] == "validada"
    L.checar_testes("bbb222", lambda n: 1)
    r = circle.store.one("SELECT status, reincidencias FROM licoes")
    assert (r["status"], r["reincidencias"]) == ("reincidente", 1)


def test_reexecucao_roda_no_worktree_do_main_sem_checkout(tmp_path):
    """Lição #1: nada de git checkout no clone principal; o pytest roda num worktree descartável do main."""
    from circulo.licoes import reexecutar_no_main

    def git(*a):
        return subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, text=True, check=True).stdout.strip()
    git("init", "-q", "-b", "main")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_ok():\n    assert True\n\n\ndef test_ruim():\n    assert False\n")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
    git("checkout", "-q", "-b", "outra")
    sha, codigos = reexecutar_no_main(tmp_path, ["tests/test_a.py::test_ok", "tests/test_a.py::test_ruim",
                                                 "tests/test_a.py::test_sumiu"])
    assert sha == git("rev-parse", "main")
    assert codigos["tests/test_a.py::test_ok"] == 0 and codigos["tests/test_a.py::test_ruim"] == 1
    assert codigos["tests/test_a.py::test_sumiu"] in (4, 5)
    assert git("branch", "--show-current") == "outra"                  # o clone principal não saiu do lugar
    assert len(git("worktree", "list").splitlines()) == 1               # o worktree descartável sumiu


# ------------------------------------------------------------ lições sem node id: alias causa raiz → node id
ALVO = "tests/test_reparo.py::test_constituicao_editada_pelo_agente_e_revertida_em_cada_rodada_e_o_pr_sai"
CONST = "- constituição intacta: altera a constituição: .github/workflows/ci.yml, circulo/self_dev.py"


def test_licao_11_sem_node_id_fecha_pelo_alias_e_reabre_se_o_teste_da_12_enfraquece_ou_some(circle):
    """lição #11 (e #10): sem node id próprio, herda o teste da lição #12 pela causa e segue o ciclo dele."""
    L = circle.licoes
    L.verificar("developer:abrir_pr", False, motivo=CONST)
    L.verificar("developer:reparo", False, motivo=CONST)
    assert {r["node_id"] for r in circle.store.q("SELECT node_id FROM licoes")} == {None}
    assert L.testes_a_checar() == [ALVO]
    avancar(circle, EVID_GIROS + 1)
    L.revisar()
    assert _abertas(circle) == 2                       # parar de acontecer não fecha: só a reexecução fecha

    def rodar(code, impressao):
        return lambda n: code if n == ALVO else None, lambda n: impressao if n == ALVO else None
    L.checar_testes("aaa111", *rodar(0, "h1"))
    assert _abertas(circle) == 2
    L.checar_testes("aaa111", *rodar(0, "h1"))
    assert _abertas(circle) == 0
    assert all(ALVO in r["prevencao"] for r in circle.store.q("SELECT prevencao FROM licoes"))
    L.verificar("developer:abrir_pr", False, motivo=CONST)      # o portão barrando de novo é a prevenção funcionando
    assert _abertas(circle) == 0

    L.checar_testes("bbb222", *rodar(0, "h2"))         # teste da #12 enfraquecido: passa, mas não é a mesma checagem
    assert _abertas(circle) == 2
    L.checar_testes("bbb222", *rodar(0, "h2"))
    assert _abertas(circle) == 0                       # a checagem nova precisa passar 2x para fechar de novo
    L.checar_testes("ccc333", *rodar(5, None))         # teste da #12 removido
    r = circle.store.q("SELECT status, reincidencias FROM licoes")
    assert [(x["status"], x["reincidencias"]) for x in r] == [("reincidente", 2)] * 2
    L.checar_testes("ddd444", *rodar(0, "h2"))
    L.checar_testes("ddd444", *rodar(0, "h2"))
    assert _abertas(circle) == 0
    L.checar_testes("eee555", *rodar(1, "h2"))         # teste da #12 falhando no main
    assert _abertas(circle) == 2


def test_impressao_do_teste_no_main_ignora_formato_e_muda_com_o_corpo(tmp_path):
    """lição #11: a impressão do teste mapeado vem do sha do main e muda quando a checagem é enfraquecida."""
    from circulo.licoes import impressao_no_main

    def git(*a):
        return subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, text=True, check=True).stdout.strip()
    git("init", "-q", "-b", "main")
    (tmp_path / "tests").mkdir()
    arq = tmp_path / "tests" / "test_a.py"

    def commit(texto):
        arq.write_text(texto)
        git("add", ".")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
        return git("rev-parse", "HEAD")
    a = commit("def test_c():\n    assert 1 + 1 == 2\n")
    b = commit("# comentário\ndef test_c():\n    assert 1 + 1 == 2  # idem\n")
    c = commit("def test_c():\n    assert True\n")
    d = commit("def test_outro():\n    assert True\n")
    h = [impressao_no_main(tmp_path, s, "tests/test_a.py::test_c") for s in (a, b, c, d)]
    assert h[0] and h[0] == h[1] and h[2] not in (None, h[0]) and h[3] is None

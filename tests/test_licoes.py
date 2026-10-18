"""Maturidade: todo ponto de verificação é monitorado; erro vira lição; o mesmo erro de estrutura só acontece uma vez."""
import json
import subprocess
from contextlib import contextmanager

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


# ------------------------------------------------------------ curador: lições de teste por node id (lições #7 e #8)
NODE = "tests/test_jev_replay.py::test_200_decisoes_do_worth_spending_saem_da_duvida_concordando_com_a_regra"
FALHA = f"FAILED {NODE} - AssertionError\ntests/test_jev_replay.py:92: AssertionError"


class MainFalso:
    """Runner do curador sem git: o main anda por uma lista de SHAs e cada node id devolve o exit code pedido."""

    def __init__(self, sha="a" * 40, exits=None):
        self.sha, self.exits, self.rodou, self.historia = sha, exits or {}, [], [sha]

    def andar(self, sha):
        self.sha = sha
        self.historia.append(sha)

    def sha_main(self, fetch=True):
        return self.sha

    def posterior(self, antigo, novo):
        h = self.historia
        return antigo in h and novo in h and h.index(novo) > h.index(antigo)

    @contextmanager
    def worktree(self, sha):
        yield lambda node: self.rodou.append((node, sha)) or self.exits.get(node, 0)


def abertas(circle):
    return circle.store.one("SELECT COUNT(*) n FROM licoes WHERE status IN ('aberta','reincidente')")["n"]


def test_licao_7_e_8_mesmo_node_id_viram_uma_licao_com_as_origens(circle):
    """Lições #7 (developer:testes) e #8 (developer:abrir_pr) eram o mesmo teste: uma lição só, origens preservadas."""
    L = lic(circle)
    a = L.verificar("developer:testes", False, motivo=FALHA)
    b = L.verificar("developer:abrir_pr", False, motivo=FALHA)
    assert a["id"] == b["id"] and abertas(circle) == 1
    r = circle.store.one("SELECT node_id, origens, ocorrencias FROM licoes")
    assert r["node_id"] == NODE and r["ocorrencias"] == 2
    assert json.loads(r["origens"]) == [f"developer:testes:teste:{NODE}", f"developer:abrir_pr:teste:{NODE}"]
    # causas distintas não se fundem: ImportError e B905 seguem como lições próprias
    L.verificar("developer:testes", False, motivo="ImportError: cannot import name x")
    L.verificar("developer:lint", False, motivo="a.py:1:1: B905 zip (ruff)")
    assert abertas(circle) == 3


def test_licao_7_e_8_ja_gravadas_separadas_sao_unidas_no_giro(circle):
    """Banco antigo: #7 e #8 já existem como lições separadas; o giro as une na mais antiga."""
    L = lic(circle)
    for sig in (f"developer:testes:teste:{NODE}", f"developer:abrir_pr:teste:{NODE}"):
        circle.store.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,"
                       "primeira_tick,ultima_tick,created_at,updated_at) VALUES(?,?,'trabalho','d','p','aberta',1,0,1,1,0,0)",
                       (sig, sig.rsplit(":teste:", 1)[0]))
    assert abertas(circle) == 2
    L.revisar()
    assert abertas(circle) == 1
    unida = circle.store.one("SELECT status, unida_a FROM licoes WHERE id=2")
    assert (unida["status"], unida["unida_a"]) == ("unida", 1)
    assert circle.store.one("SELECT ocorrencias FROM licoes WHERE id=1")["ocorrencias"] == 2
    assert "- #2 " not in L.contexto()


def test_licao_7_fecha_com_exit_0_em_duas_execucoes_seguidas_no_main(circle):
    L = lic(circle)
    licao = L.verificar("developer:testes", False, motivo=FALHA)
    main = MainFalso()
    L.curar(main)
    assert circle.store.one("SELECT status FROM licoes")["status"] == "aberta"     # um verde só não fecha
    main.andar("b" * 40)
    L.curar(main)
    r = circle.store.one("SELECT status, prevencao, curadoria FROM licoes WHERE id=?", (licao["id"],))
    assert r["status"] == "validada" and abertas(circle) == 0
    cur = json.loads(r["curadoria"])
    assert [(e["sha"], e["exit"]) for e in cur["fechada"]["execucoes"]] == [("a" * 40, 0), ("b" * 40, 0)]
    assert "aaaaaaaaaaaa" in r["prevencao"] and "bbbbbbbbbbbb" in r["prevencao"]
    assert main.rodou == [(NODE, "a" * 40), (NODE, "b" * 40)]
    L.curar(main)
    assert len(main.rodou) == 2                    # fechada e sem suspeita: não roda de novo


def test_licao_7_nao_fecha_quando_o_teste_some_do_main(circle):
    L = lic(circle)
    L.verificar("developer:testes", False, motivo=FALHA)
    main = MainFalso(exits={NODE: 5})
    L.curar(main)
    main.exits[NODE] = 0
    main.andar("b" * 40)
    L.curar(main)                                   # verde depois de exit 5: não são 2 seguidas
    assert circle.store.one("SELECT status FROM licoes")["status"] == "aberta"
    main.exits[NODE] = 4
    main.andar("c" * 40)
    L.curar(main)
    L.curar(main)                                   # exit 4 no mesmo SHA não é reexecutado
    assert len(main.rodou) == 3
    r = circle.store.one("SELECT status, curadoria FROM licoes")
    assert r["status"] == "aberta" and json.loads(r["curadoria"])["estado"] == "obsoleta/indeterminada"


def test_licao_7_reabre_so_quando_falha_no_main_num_sha_posterior(circle):
    L = lic(circle)
    L.verificar("developer:testes", False, motivo=FALHA)
    main = MainFalso()
    L.curar(main)
    L.curar(main)
    assert abertas(circle) == 0
    # o Developer quebrou o teste no ramo dele: não é reabertura (0 reaberturas falsas)
    L.verificar("developer:abrir_pr", False, motivo=FALHA)
    assert circle.store.one("SELECT status FROM licoes")["status"] == "validada"
    main.exits[NODE] = 1
    L.curar(main)                                   # mesmo SHA do fechamento: nada a reexecutar
    assert abertas(circle) == 0
    main.andar("c" * 40)
    L.curar(main)                                   # falhou no main depois do fechamento: reabre
    r = circle.store.one("SELECT status, reincidencias FROM licoes")
    assert (r["status"], r["reincidencias"]) == ("reincidente", 1)
    assert circle.store.one("SELECT 1 FROM alerts WHERE message LIKE 'REINCIDÊNCIA da lição%'")


def test_licao_7_nao_fecha_sozinha_por_tempo(circle):
    """Lição de teste só fecha pelo curador, nunca por ficar EVID_GIROS sem reaparecer."""
    L = lic(circle)
    L.verificar("developer:testes", False, motivo=FALHA)
    avancar(circle, EVID_GIROS + 1)
    L.revisar()
    assert abertas(circle) == 1


def test_curador_git_roda_no_worktree_do_main_sem_checkout_no_clone(tmp_path):
    """Lição #1: a checagem nunca faz checkout no clone principal; roda num worktree descartável do main."""
    from circulo.licoes import CuradorGit
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)

    def git(*a):
        return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (repo / "tests" / "test_a.py").write_text("def test_ok():\n    assert True\n\n\ndef test_ruim():\n    assert False\n")
    git("add", "-A")
    git("commit", "-q", "-m", "a")
    git("checkout", "-q", "-b", "outra")
    cur = CuradorGit(repo, tmp_path / "dados", timeout=120)
    sha = cur.sha_main(fetch=False)
    assert sha == git("rev-parse", "main")
    with cur.worktree(sha) as rodar:
        codes = [rodar("tests/test_a.py::test_ok"), rodar("tests/test_a.py::test_ruim"), rodar("tests/test_a.py::test_sumiu")]
    assert codes[0] == 0 and codes[1] == 1 and codes[2] in (4, 5)
    assert git("rev-parse", "--abbrev-ref", "HEAD") == "outra"                 # o clone não trocou de branch
    assert "licoes-curador" not in git("worktree", "list")                     # worktree descartado
    assert not list((tmp_path / "dados").iterdir())

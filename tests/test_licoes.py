"""Maturidade: todo ponto de verificação é monitorado; erro vira lição; o mesmo erro de estrutura só acontece uma vez."""
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

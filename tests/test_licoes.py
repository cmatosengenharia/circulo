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


def test_licao_de_estrutura_com_item_descartado_nao_trava_a_evolucao_para_sempre(circle):
    """Vigia licao_bloqueia (pergunta #52): o item da lição foi descartado (fatiador, higiene, estudo contestado) e
    ninguém mais trabalha nele; a lição vale como corrigida quando o erro para de acontecer, e reabre o item se voltar."""
    L = lic(circle)
    licao = L.verificar("execucao:meta", False, motivo="RuntimeError: x", assinatura="incidente:abc")
    circle.store.x("UPDATE roadmap SET status='descartado', evidencia='descartado: sub-item falhou' WHERE id=?", (licao["item_id"],))
    L.revisar()
    assert L.bloqueia_evolucao()                                   # o erro acabou de acontecer: ainda não sumiu
    avancar(circle, EVID_GIROS + 1)
    L.revisar()
    assert circle.store.one("SELECT status FROM licoes")["status"] == "validada" and not L.bloqueia_evolucao()
    L.verificar("execucao:meta", False, motivo="RuntimeError: x", assinatura="incidente:abc")    # voltou
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (licao["item_id"],))["status"] == "pendente"
    assert L.bloqueia_evolucao()


def test_licao_de_estrutura_com_item_fora_da_fila_nao_trava_a_evolucao_para_sempre(circle):
    """Vigia licao_bloqueia (item #137, 17 h): o item da lição saiu da fila (desativado: teto de tokens, fatiador sem
    divisão, revisor sem mudança, painel) e segue 'pendente' sem ninguém pegar; é o mesmo que descartado."""
    L = lic(circle)
    licao = L.verificar("execucao:meta", False, motivo="RuntimeError: x", assinatura="incidente:abc")
    circle.store.x("UPDATE roadmap SET desativado=1, evidencia='depende de você: cortado 2× pelo teto' WHERE id=?", (licao["item_id"],))
    avancar(circle, EVID_GIROS + 1)
    L.revisar()
    assert circle.store.one("SELECT status FROM licoes")["status"] == "validada" and not L.bloqueia_evolucao()


def test_erro_que_volta_com_o_item_pendente_fora_da_fila_devolve_o_item_a_fila(circle):
    """Vigia licao_bloqueia (item #219, 4 h): o item da lição saiu da fila sem sair de 'pendente' (desativado pelo
    revisor sem mudança, "depende de você") e o erro segue acontecendo; o `sem_fila` chamava `_abrir_item`, que via
    'pendente' e não fazia nada: a lição travava a evolução com um item que ninguém pega."""
    from circulo.licoes import NA_FILA
    L = lic(circle)
    for i, (off, evid) in enumerate(((1, "depende de você: sem mudança 3×"), (0, "depende de você: exige a constituição"))):
        licao = L.verificar("execucao:meta", False, motivo="RuntimeError: x", assinatura=f"incidente:{i}")
        circle.store.x("UPDATE roadmap SET desativado=?, evidencia=? WHERE id=?", (off, evid, licao["item_id"]))
        L.verificar("execucao:meta", False, motivo="RuntimeError: x", assinatura=f"incidente:{i}")      # segue acontecendo
        assert circle.store.one(f"SELECT 1 FROM roadmap WHERE id=? AND {NA_FILA}", (licao["item_id"],))
    assert L.bloqueia_evolucao()


def test_licao_de_estrutura_com_item_dividido_e_sub_item_fora_da_fila_nao_trava_a_evolucao_para_sempre(circle):
    """Vigia licao_bloqueia (item #139, 85 h): o item da lição foi dividido pelo fatiador e um sub-item saiu da fila
    (2º corte do teto, sem mudança); o pai fica 'dividido' para sempre (só vira feito com todos os subs feitos)."""
    L = lic(circle)
    licao = L.verificar("execucao:meta", False, motivo="RuntimeError: x", assinatura="incidente:abc")
    s, agora = circle.store, time.time()
    s.x("UPDATE roadmap SET status='dividido', evidencia='dividido em 2 sub-itens' WHERE id=?", (licao["item_id"],))
    for i, off in enumerate((1, 0)):
        s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,pai,desativado) "
            "VALUES(?,?,'sub_item','pendente',?,?,?,?,?,?)",
            (f"parte {i + 1}", "d", "depende de você: cortado 2× pelo teto" if off else "", i, agora, agora, licao["item_id"], off))
    avancar(circle, EVID_GIROS + 1)
    L.revisar()
    assert s.one("SELECT status FROM licoes")["status"] == "validada" and not L.bloqueia_evolucao()


def test_licao_de_estrutura_com_item_que_depende_de_voce_nao_trava_a_evolucao_por_dias(circle):
    """Vigia licao_bloqueia (item #148, 125 h): o Developer devolveu o item da lição como 'pendente' + "depende de você"
    (3 tentativas sem mudança, exige a constituição, commit sem PR) sem desativá-lo; ninguém pega, e a lição só soltava
    quando a higiene o expirava (7 dias). Fora da fila é fora da fila, com ou sem o flag desativado."""
    L = lic(circle)
    licao = L.verificar("execucao:meta", False, motivo="RuntimeError: x", assinatura="incidente:abc")
    circle.store.x("UPDATE roadmap SET status='pendente', evidencia='depende de você: a correção exige mexer na constituição' "
                   "WHERE id=?", (licao["item_id"],))
    avancar(circle, EVID_GIROS + 1)
    L.revisar()
    assert circle.store.one("SELECT status FROM licoes")["status"] == "validada" and not L.bloqueia_evolucao()


def test_licao_de_estrutura_com_item_bloqueado_pelo_disjuntor_nao_trava_a_evolucao(circle):
    """Vigia licao_bloqueia (item #153, 127 h): o item da lição foi para 'bloqueado' (disjuntor do abrir_pr: só volta
    quando o arquivo citado muda na main) e ninguém o pega. Cada correção anterior listou mais um jeito de sair da fila;
    a regra é o contrário: só segura a lição o item que o Developer ainda vai pegar."""
    L = lic(circle)
    for status in ("bloqueado", "parcial"):
        licao = L.verificar("execucao:meta", False, motivo="RuntimeError: x", assinatura=f"incidente:{status}")
        circle.store.x("UPDATE roadmap SET status=? WHERE id=?", (status, licao["item_id"]))
    avancar(circle, EVID_GIROS + 1)
    L.revisar()
    assert {r["status"] for r in circle.store.q("SELECT status FROM licoes")} == {"validada"} and not L.bloqueia_evolucao()


# ------------------------------------------------------------ lição #15: validada só com checagem na Prevenção
def test_licao_15_validada_e_reincidente_com_prevencao_so_em_texto_vira_sem_prevencao(circle):
    """Pergunta #239 (lição #15): validada, reincidiu 7x e a Prevenção só repete o erro; sem teste ou checagem
    determinística citada, ela é 'sem_prevencao' e conta como aberta até ganhar uma."""
    from circulo.neuronios import ABRIR_PR, criar_portao
    from circulo.perguntas import _m_licoes_abertas
    s, agora = circle.store, time.time()
    s.x("INSERT INTO licoes(id,assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,primeira_tick,"
        "ultima_tick,corrigida_tick,created_at,updated_at,camada) VALUES(15,'rastro:lacuna','rastro:lacuna','estrutural',"
        "'rastro:cadeia: item planejado pelo loop sem a pergunta do conselho que o originou',"
        "'arquitetura (erro impossível): rastro:cadeia: item planejado pelo loop sem a pergunta','validada',8,7,0,0,0,?,?,"
        "'arquitetura')", (agora, agora))
    circle.licoes.revisar()
    r = s.one("SELECT status, prevencao FROM licoes WHERE id=15")
    assert r["status"] == "sem_prevencao" and "lição #15" in r["prevencao"]
    assert _m_licoes_abertas(s, agora)[1]["licoes_abertas"] == 1
    assert "#15 [sem_prevencao" in circle.licoes.contexto()
    criar_portao(s, ABRIR_PR, "comando", {"argv": ["-m", "pytest", "-q", "tests/test_jtbd.py"]},
                 "teste tests/test_jtbd.py (lição #15)", 15)
    circle.licoes.revisar()
    r = s.one("SELECT status, prevencao FROM licoes WHERE id=15")
    assert r["status"] == "validada" and "tests/test_jtbd.py" in r["prevencao"]


def test_item_feito_sem_checagem_deixa_a_licao_sem_prevencao_e_a_volta_do_erro_reincide(circle):
    """lição #15: o item da lição entrou, mas nada determinístico segura o erro (lição antiga, sem portão)."""
    L = lic(circle)
    licao = L.verificar("execucao:meta", False, motivo="RuntimeError: x", assinatura="incidente:abc")
    circle.store.x("DELETE FROM portoes WHERE licao_id=?", (licao["id"],))
    circle.store.x("UPDATE roadmap SET status='feito', evidencia='PR #3 mergeado' WHERE id=?", (licao["item_id"],))
    L.revisar()
    assert circle.store.one("SELECT status FROM licoes")["status"] == "sem_prevencao"
    L.verificar("execucao:meta", False, motivo="RuntimeError: x", assinatura="incidente:abc")
    r = circle.store.one("SELECT status, reincidencias FROM licoes")
    assert (r["status"], r["reincidencias"]) == ("reincidente", 1)


def _sem_prevencao(s, lid, reincidencias, item_id=None):
    s.x("INSERT INTO licoes(id,assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,primeira_tick,"
        "ultima_tick,created_at,updated_at,camada,item_id) VALUES(?,?,'developer:agente','estrutural',"
        "'developer:agente: circulo/self_dev.py sem saida','Não repetir: sem saida',"
        "'sem_prevencao',?,?,0,0,0,0,'regra',?)",
        (lid, f"developer:agente:sem_saida:{lid}", reincidencias + 1, reincidencias, item_id))


def test_licao_59_sem_prevencao_que_reincidiu_3x_vira_item_de_teste_de_regressao_uma_vez(circle):
    """Pergunta #461 (lições #59 e #15): sem_prevencao com reincidência ≥3 ganha um item de roteiro que cobra o teste
    de regressão da assinatura (neurônio + arquivo + código), com chave única pelo id da lição: um item só."""
    s, L = circle.store, lic(circle)
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
        "VALUES('antigo','x','erro','feito','PR #9 mergeado',1,0,0)")
    _sem_prevencao(s, 59, 12, item_id=s.one("SELECT MAX(id) m FROM roadmap")["m"])
    _sem_prevencao(s, 50, 2)
    L.revisar()
    L.revisar()
    itens = s.q("SELECT r.*, p.chave FROM roadmap r JOIN perguntas p ON p.id=r.pergunta_id WHERE r.status='pendente'")
    assert [r["chave"] for r in itens] == ["licao:59:teste_regressao"]
    assert itens[0]["titulo"].startswith("Lição #59: teste de regressão")
    d = itens[0]["detalhe"]
    assert all(x in d for x in ("lição #59", "developer:agente:sem_saida:59", "circulo/self_dev.py", "reincidiu 12x"))
    assert s.one("SELECT item_id FROM licoes WHERE id=59")["item_id"] == itens[0]["id"]
    s.x("UPDATE roadmap SET status='descartado' WHERE id=?", (itens[0]["id"],))   # saiu da fila: volta a ela, sem duplicar
    L.revisar()
    assert [r["status"] for r in s.q("SELECT status FROM roadmap WHERE origem='loop'")] == ["pendente"]


def _sem_prevencao_sem_arquivo(s, lid, reincidencias):
    """Lição #15 real: 'rastro:cadeia' não cita caminho .py nenhum — o item nascia sem arquivo alvo."""
    s.x("INSERT INTO licoes(id,assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,primeira_tick,"
        "ultima_tick,created_at,updated_at,camada) VALUES(?,'rastro:lacuna','rastro:cadeia','trabalho',"
        "'rastro:cadeia: item planejado pelo loop sem a pergunta do conselho que o originou','Não repetir',"
        "'sem_prevencao',?,?,0,0,0,0,'regra')", (lid, reincidencias + 1, reincidencias))


def test_item_do_teste_de_regressao_nasce_com_arquivo_alvo_e_passa_no_portao_de_pedido(circle):
    """Itens #282/#283 (28/10): a lição sem .py no texto gerava um pedido sem arquivo alvo; o portão de pedido devolvia
    a pergunta, descartava na 2ª rodada e `cobrar_teste` repunha o item na fila — a cada hora, sem gastar. Agora o
    detalhe cita o teste novo (tests/test_licao_<id>_regressao.py) e o módulo do neurônio, e o portão o aceita."""
    from circulo.pedido_claro import avaliar
    from circulo.prevencao import arquivos_do_teste
    s, L = circle.store, lic(circle)
    _sem_prevencao_sem_arquivo(s, 15, 8)
    L.revisar()
    [item] = s.q("SELECT * FROM roadmap WHERE origem='loop'")
    assert arquivos_do_teste({"id": 15, "ponto": "rastro:cadeia"}) == ("tests/test_licao_15_regressao.py", "circulo/rastro.py")
    assert "tests/test_licao_15_regressao.py" in item["detalhe"] and "circulo/rastro.py" in item["detalhe"]
    assert avaliar(item["titulo"], item["detalhe"]).completo


def test_item_do_teste_de_regressao_descartado_pelo_portao_volta_reescrito_com_arquivo_e_nao_fica_em_ciclo(circle):
    """O item já criado sem arquivo (antes desta correção) e descartado pelo portão volta à fila UMA vez, já reescrito
    e completo; o esclarecimento antigo não o derruba de novo porque o pedido agora passa no portão."""
    from circulo.pedido_claro import esclarecer, registrar
    s, L = circle.store, lic(circle)
    _sem_prevencao_sem_arquivo(s, 15, 8)
    L.revisar()
    [item] = map(dict, s.q("SELECT * FROM roadmap WHERE origem='loop'"))
    antigo = "A lição #15 reincidiu 8x. Escrever em tests/ um teste de regressão.\nSucesso: a lição sai de sem_prevencao"
    s.x("UPDATE roadmap SET detalhe=? WHERE id=?", (antigo, item["id"]))          # o pedido como nascia antes
    item = dict(s.one("SELECT * FROM roadmap WHERE id=?", (item["id"],)))
    assert esclarecer(s, item, registrar(s, item))[0] == "esclarecer"            # 1ª rodada: pergunta do arquivo
    item = dict(s.one("SELECT * FROM roadmap WHERE id=?", (item["id"],)))
    assert esclarecer(s, item, registrar(s, item))[0] == "descartado"            # 2ª rodada: descartado
    L.revisar()                                                                  # cobrar_teste: reescreve e repõe
    item = dict(s.one("SELECT * FROM roadmap WHERE id=?", (item["id"],)))
    assert item["status"] == "pendente" and item["estudo"] is None and "tests/test_licao_15_regressao.py" in item["detalhe"]
    assert esclarecer(s, item, registrar(s, item)) is None                       # completo: segue para o Developer
    assert s.one("SELECT COUNT(*) n FROM roadmap WHERE origem='loop'")["n"] == 1


# ------------------------------------------------------------ lição #70: validada reabre quando o mesmo erro volta
def _validada_70(s):
    agora = time.time()
    s.x("INSERT INTO licoes(id,assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,primeira_tick,"
        "ultima_tick,corrigida_tick,created_at,updated_at,camada) VALUES(70,'developer:abrir_pr:lint:B905,E501,F541',"
        "'developer:abrir_pr','trabalho','developer:abrir_pr: circulo/a.py:3:9: B905 zip() sem strict',"
        "'Não repetir: B905','validada',1,0,0,0,0,?,?,'regra')", (agora, agora))


LINT_76 = ("circulo/b.py:4:1: F401 `os` imported but unused\ncirculo/b.py:9:5: B905 `zip()` without strict\n"
           "circulo/b.py:12:89: E501 line too long (ruff)")


def test_licao_70_validada_reabre_quando_nova_licao_tem_a_mesma_assinatura(circle):
    """Pergunta #248 (lição #70): #70 validada, o mesmo erro (neurônio+arquivo+código) volta numa lição nova (#76):
    a #70 volta a 'aberta', conta a reincidência e cita a lição nova; não fecha enquanto a gêmea estiver aberta."""
    s, L = circle.store, lic(circle)
    _validada_70(s)
    nova = L.verificar("developer:abrir_pr", False, motivo=LINT_76)
    assert nova["id"] != 70 and nova["assinatura"] == "developer:abrir_pr:lint:B905,E501,F401"
    r = s.one("SELECT status, reincidencias, prevencao FROM licoes WHERE id=70")
    assert (r["status"], r["reincidencias"]) == ("aberta", 1) and f"lição #{nova['id']}" in r["prevencao"]
    avancar(circle, EVID_GIROS + 1)
    L.verificar("developer:abrir_pr", False, motivo=LINT_76)                      # o erro segue acontecendo na #76
    L.revisar()
    assert s.one("SELECT status FROM licoes WHERE id=70")["status"] == "aberta"
    assert s.one("SELECT COUNT(*) n FROM licoes WHERE status='validada'")["n"] == 0
    avancar(circle, EVID_GIROS + 1)                       # parou: as duas fecham juntas (a #70, que reincidiu sem
    L.revisar()                                           # checagem, fecha como 'sem_prevencao': lição #15)
    r = s.one("SELECT status, reincidencias FROM licoes WHERE id=70")
    assert (r["status"], r["reincidencias"]) == ("sem_prevencao", 1)
    assert s.one("SELECT status FROM licoes WHERE id=?", (nova["id"],))["status"] == "validada"


def test_licao_70_validada_ja_com_gemea_aberta_e_reaberta_no_giro(circle):
    """lição #70: o par #70 validada / #76 aberta que já existe no banco é desfeito pelo revisar."""
    s = circle.store
    _validada_70(s)
    s.x("INSERT INTO licoes(id,assinatura,ponto,classe,descricao,status,ocorrencias,reincidencias,primeira_tick,ultima_tick,"
        "created_at,updated_at) VALUES(76,'developer:abrir_pr:lint:B905,E501,F401','developer:abrir_pr','trabalho','x',"
        "'aberta',1,0,?,?,0,0)", (s.tick, s.tick))
    circle.licoes.revisar()
    r = s.one("SELECT status, reincidencias FROM licoes WHERE id=70")
    assert (r["status"], r["reincidencias"]) == ("aberta", 1)


def test_licao_70_outro_neuronio_ou_outro_codigo_nao_reabre(circle):
    """lição #70: só a mesma assinatura normalizada reabre; outro neurônio ou código sem nada em comum, não."""
    s, L = circle.store, lic(circle)
    _validada_70(s)
    L.verificar("gate:ci", False, motivo=LINT_76)
    L.verificar("developer:abrir_pr", False, motivo="circulo/c.py:1:1: F811 redefinition of `f` (ruff)")
    assert s.one("SELECT status, reincidencias FROM licoes WHERE id=70")["status"] == "validada"


# ------------------------------------------------------------ lição #83: JSON de estatística sem erro não é lição
STATS_83 = json.dumps({"type": "system", "subagent_stats": {"spawned": 0, "completed": 0, "failed": 0, "killed": 0}})


def test_licao_83_json_de_estatistica_sem_erro_nao_vira_licao(circle):
    """lição #83: um dump de subagent_stats com tudo em 0 é telemetria, não erro: não grava lição e o motivo fica."""
    s, L = circle.store, lic(circle)
    for dump in (STATS_83, json.dumps({"completed": 0, "failed": 0, "killed": 0})):
        assert L.verificar("developer:agente", False, motivo=dump) is None
    assert s.one("SELECT COUNT(*) n FROM licoes")["n"] == 0
    causas = [r["causa"] for r in s.q("SELECT causa FROM verificacoes WHERE ok=0")]
    assert causas == ["telemetria_sem_erro", "telemetria_sem_erro"]


def test_licao_83_estatistica_com_sinal_de_erro_vira_licao(circle):
    """lição #83: failed>0, killed>0, exceção ou exit≠0 no mesmo dump é erro e a lição é gravada."""
    s, L = circle.store, lic(circle)
    com_erro = (
        {"subagent_stats": {"spawned": 1, "completed": 0, "failed": 1, "killed": 0}},
        {"completed": 0, "failed": 0, "killed": 2},
        {"completed": 1, "failed": 0, "exception": "RuntimeError: x"},
        {"completed": 1, "failed": 0, "exit_code": 2},
        {"type": "result", "is_error": True, "subagent_stats": {"completed": 0, "failed": 0}},
        {"type": "result", "subtype": "error_max_turns", "is_error": False, "subagent_stats": {"completed": 0, "failed": 0}},
        {"type": "result", "terminal_reason": "max_turns", "subagent_stats": {"completed": 0, "failed": 0}},
    )
    for i, dado in enumerate(com_erro):
        assert L.verificar(f"developer:agente{i}", False, motivo=json.dumps(dado)) is not None, dado
    assert s.one("SELECT COUNT(*) n FROM licoes")["n"] == len(com_erro)


def test_licao_83_higiene_tira_das_abertas_a_licao_de_telemetria(circle):
    """lição #83: a lição de telemetria que já está aberta sai das abertas na higiene; a com failed>0 fica."""
    from circulo import higiene
    from circulo.perguntas import _m_licoes_abertas
    s = circle.store
    erro = json.dumps({"subagent_stats": {"completed": 0, "failed": 1, "killed": 0}})
    for lid, descricao, motivo in ((83, f"developer:agente: {STATS_83}", ""), (84, "developer:agente: log cortado", STATS_83),
                                   (85, f"developer:agente: {erro}", erro)):
        s.x("INSERT INTO licoes(id,assinatura,ponto,classe,descricao,status,ocorrencias,reincidencias,primeira_tick,"
            "ultima_tick,created_at,updated_at) VALUES(?,?,'developer:agente','ambiente',?,'aberta',1,0,0,0,0,0)",
            (lid, f"developer:agente:x{lid}", descricao))
        if motivo:
            s.x("INSERT INTO verificacoes(tick,ponto,sujeito,ok,assinatura,motivo,created_at) VALUES(0,'developer:agente','',0,?,?,0)",
                (f"developer:agente:x{lid}", motivo))
    assert higiene.rodar(s, forcar=True)["licoes_telemetria"] == 2
    assert [r["status"] for r in s.q("SELECT status FROM licoes ORDER BY id")] == ["obsoleta", "obsoleta", "aberta"]
    assert _m_licoes_abertas(s, 0)[1]["licoes_abertas"] == 1

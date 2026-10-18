"""Central de confiança: o humano vê, em tempo real, se pode confiar no loop, em perceber, entender e projetar."""
import json
import threading
import time
import urllib.request

from circulo.confianca import FRESCOR_MAX_MS, confianca, registrar_frescor

from test_painel import painel, post  # noqa: F401 — fixture do servidor do painel


def ids(r):
    return {c["id"]: c for c in r["checks"]}


def vivo(circle):
    circle.store.set("batimento", {"em": time.time(), "pid": 1, "proximo_giro_em": time.time() + 15})


def test_loop_desligado_nao_e_confiavel(circle):
    circle.tick()
    r = confianca(circle.store)
    assert r["veredito"] == "parado" and ids(r)["vivo"]["estado"] == "falha"


def test_loop_vivo_e_tudo_seguro_e_confiavel_com_tres_niveis(circle):
    circle.tick()
    vivo(circle)
    r = confianca(circle.store)
    assert r["veredito"] == "confiavel" and r["frase"].startswith("Todas as verificações")
    assert {c["grupo"] for c in r["checks"]} == {"agora", "seguranca", "proximo"}
    assert all(c["dado_em"] for c in r["checks"])                     # todo dado diz de quando é
    assert ids(r)["decisao"]["porque"].startswith("decidida pel")


def test_reincidencia_e_main_vermelha_derrubam_a_confianca(circle):
    circle.tick()
    vivo(circle)
    circle.licoes.verificar("gate:main", False, sujeito="abc1234", motivo="CI vermelho", assinatura="gate:main_vermelha",
                            classe="estrutural")
    r = confianca(circle.store)
    assert r["veredito"] == "falha" and ids(r)["main"]["estado"] == "falha" and "ci da main" in r["frase"]
    assert ids(r)["licoes"]["estado"] == "atencao"


def test_pausa_e_verificavel(circle):
    circle.tick()
    vivo(circle)
    circle.store.set("controle", {"pausado": True, "modo_seguro": False})
    c = ids(confianca(circle.store))["vivo"]
    assert c["valor"] == "pausado por você" and "nenhum outro começou" in c["porque"]


def test_projecao_mostra_o_que_vem(circle):
    circle.tick()
    vivo(circle)
    r = ids(confianca(circle.store))
    assert "proximo_giro" in r and "estudo" in r                       # pedidos da semente esperam estudo


def test_frescor_do_painel_e_um_neuronio_monitorado(circle):
    assert registrar_frescor(circle.store, 400)
    assert not registrar_frescor(circle.store, 400)                    # no máximo 1 por minuto
    circle.store.set("painel_frescor_em", 0)
    registrar_frescor(circle.store, FRESCOR_MAX_MS + 1)
    v = circle.store.q("SELECT ok FROM verificacoes WHERE ponto='painel:frescor' ORDER BY id")
    assert [x["ok"] for x in v] == [1, 0]
    assert circle.store.one("SELECT classe FROM licoes WHERE assinatura='painel:frescor_atrasado'")["classe"] == "estrutural"


def test_sse_empurra_confianca_e_sinapses(circle, painel):  # noqa: F811
    circle.tick()
    circle.licoes.verificar("developer:testes", True, sujeito="wt")
    got = {"confianca": 0, "sinapse": 0}

    def read():
        with urllib.request.urlopen(painel + "/api/eventos?desde=0", timeout=8) as r:
            for line in r:
                for k in got:
                    if line.startswith(f"event: {k}".encode()):
                        got[k] += 1
                if got["confianca"] >= 2 and got["sinapse"] >= 1:
                    return
    t = threading.Thread(target=read, daemon=True)
    t.start()
    t.join(8)
    assert got["confianca"] >= 2 and got["sinapse"] >= 1               # confiança empurrada sem o painel pedir


def test_api_confianca_e_frescor(circle, painel):  # noqa: F811
    circle.tick()
    with urllib.request.urlopen(painel + "/api/confianca", timeout=5) as r:
        assert json.loads(r.read())["veredito"] in ("parado", "confiavel", "atencao", "falha")
    code, body = post(painel + "/api/frescor", {"atraso_ms": 120}, {"X-Circulo": "1"})
    assert code == 200 and body["registrado"]
    assert post(painel + "/api/frescor", {"atraso_ms": 120})[0] == 403  # sem o cabeçalho do painel


def test_semente_nunca_desfaz_o_que_o_loop_entregou(circle):
    from circulo.projects import ensure_seed
    t = "Perguntas do Jev e portfólio evoluindo sozinhos"
    circle.store.x("UPDATE roadmap SET status='feito', evidencia='PR #1 mergeado' WHERE titulo=?", (t,))
    circle.store.set("roteiro_versao", 0)
    ensure_seed(circle.store)
    r = circle.store.one("SELECT status, evidencia FROM roadmap WHERE titulo=?", (t,))
    assert (r["status"], r["evidencia"]) == ("feito", "PR #1 mergeado")
    assert circle.store.one("SELECT 1 FROM roadmap WHERE titulo LIKE 'Painel de confiança%'")

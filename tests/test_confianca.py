"""Central de confiança: o humano vê, em tempo real, se pode confiar no loop, em perceber, entender e projetar."""
import json
import threading
import time
import urllib.request

from circulo.confianca import FRESCOR_MAX_MS, confianca, registrar_frescor, versao_painel

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
    s = circle.store
    for _ in range(99):
        s.x("INSERT INTO frescor(atraso_ms, em) VALUES(400, ?)", (time.time(),))
    v = versao_painel()
    assert registrar_frescor(s, 400, v)                                 # 100ª amostra: o p99 passa a valer
    assert not registrar_frescor(s, 400, v)                             # no máximo 1 por minuto
    s.set("painel_frescor_em", 0)
    for _ in range(5):
        s.x("INSERT INTO frescor(atraso_ms, em) VALUES(?, ?)", (FRESCOR_MAX_MS + 1, time.time()))
    registrar_frescor(s, FRESCOR_MAX_MS + 1, v)
    oks = s.q("SELECT ok FROM verificacoes WHERE ponto='painel:frescor' ORDER BY id")
    assert [x["ok"] for x in oks] == [1, 0]
    # painel atrasado é ambiente, não defeito do código: não bloqueia a evolução
    assert s.one("SELECT classe FROM licoes WHERE assinatura='painel:frescor_atrasado'")["classe"] == "ambiente"
    # aba parada (Mac dormiu), NaN e inf não são medição e nunca viram lição
    assert not registrar_frescor(s, 3_600_000, v) and not registrar_frescor(s, float("inf"), v) and not registrar_frescor(s, "x", v)
    assert s.one("SELECT COUNT(*) n FROM frescor WHERE atraso_ms > 600000")["n"] == 0


def test_frescor_julga_so_o_codigo_atual_do_painel(circle, monkeypatch):
    """lição #60 (painel:frescor_atrasado): o conserto do painel (#172) entrou e a lição reincidiu 1 min depois
    (p99 4795 ms) com amostras medidas pela página velha. O SLO só julga a versão do painel que está no ar:
    amostra de aba com página antiga é descartada e a janela de 24 h recomeça quando a página muda."""
    from circulo import confianca as cf
    s = circle.store
    monkeypatch.setattr(cf, "versao_painel", lambda: "velha")
    for _ in range(100):
        s.x("INSERT INTO frescor(atraso_ms, em) VALUES(120000, ?)", (time.time(),))
    assert registrar_frescor(s, 120000, versao="velha")
    assert s.one("SELECT ok FROM verificacoes WHERE ponto='painel:frescor' ORDER BY id DESC LIMIT 1")["ok"] == 0
    monkeypatch.setattr(cf, "versao_painel", lambda: "nova")
    assert not registrar_frescor(s, 120000, versao="velha")            # aba que ainda roda a página antiga
    for _ in range(100):
        s.set("painel_frescor_em", 0)
        registrar_frescor(s, 400, versao="nova")
    assert s.one("SELECT ok FROM verificacoes WHERE ponto='painel:frescor' ORDER BY id DESC LIMIT 1")["ok"] == 1


def test_frescor_sem_versao_da_pagina_nao_entra_na_janela(circle, painel):  # noqa: F811
    """lição #60 (painel:frescor_atrasado, reincidiu com p99 4795 ms depois do #173): aba aberta antes do #173 não
    manda versão e `versao=None` contava como a página atual. Amostra sem a versão da página não é medição do painel
    no ar: nem a função nem a API a aceitam."""
    s = circle.store
    assert not registrar_frescor(s, 120000, None)
    code, body = post(painel + "/api/frescor", {"atraso_ms": 120000}, {"X-Circulo": "1"})
    assert code == 200 and body["registrado"] is False
    assert s.one("SELECT COUNT(*) n FROM frescor")["n"] == 0


def test_painel_manda_a_propria_versao_com_o_frescor():
    """lição #60: a página servida carrega a versão do código e a devolve em cada medição de frescor."""
    from circulo.painel import _page
    html = _page("painel.html").decode()
    assert versao_painel() in html and "__VERSAO_PAINEL__" not in html
    assert "versao: VERSAO_PAINEL" in html


def test_frescor_com_poucas_amostras_nao_julga(circle):
    for _ in range(10):
        registrar_frescor(circle.store, FRESCOR_MAX_MS * 10, versao_painel())
        circle.store.set("painel_frescor_em", 0)
    assert circle.store.one("SELECT COUNT(*) n FROM verificacoes WHERE ponto='painel:frescor'")["n"] == 0


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


def test_sse_reempurra_confianca_parada_dentro_do_slo_de_frescor(circle, painel):  # noqa: F811
    """lição #60 (painel:frescor_atrasado): com os checks estáveis a confiança precisa ser reenviada a cada ≤ 2 s;
    antes o relógio do reenvio zerava a cada cálculo e o card na tela envelhecia sem limite (p99 5472 ms).
    Loop desligado em descanso longo: nenhum "há N s" muda a chave, só o reenvio periódico renova o card."""
    circle.tick()
    circle.store.set("etapa", {**circle.store.get("etapa"), "em": time.time() - 600})
    chegadas: list[tuple[float, float]] = []

    def read():
        fim = time.time() + 7
        with urllib.request.urlopen(painel + "/api/eventos?desde=0", timeout=10) as r:
            evento = None
            for line in r:
                if line.startswith(b"event: "):
                    evento = line[7:].strip().decode()
                elif line.startswith(b"data: ") and evento == "confianca":
                    chegadas.append((time.time(), json.loads(line[6:])["gerado_em"]))
                if time.time() > fim:
                    return
    t = threading.Thread(target=read, daemon=True)
    t.start()
    t.join(10)
    assert len(chegadas) >= 3
    pior = max(b[0] - a[1] for a, b in zip(chegadas, chegadas[1:], strict=False))   # idade do card logo antes do próximo
    assert pior * 1000 <= FRESCOR_MAX_MS, f"card ficou {pior:.1f} s sem renovar"


def test_frescor_so_mede_a_idade_enquanto_a_aba_esta_visivel():
    """lição #60 (painel:frescor_atrasado, reincidente: p99 123923 ms): aba em segundo plano congela timers e SSE e,
    ao voltar, o card velho entrava na medição com o tempo escondido (minutos). O atraso dado → tela só conta o tempo
    em que a tela estava visível: toda idade medida passa por idadeNaTela, que respeita a visibilidade da aba."""
    import re
    from pathlib import Path
    html = (Path(__file__).parent.parent / "circulo" / "painel.html").read_text()
    assert 'addEventListener("visibilitychange"' in html and "document.hidden" in html
    corpo = re.search(r"function idadeNaTela\([^)]*\) \{(.*?)\n?\}\n", html, re.S)
    assert corpo and "visivelDesde" in corpo.group(1), "idadeNaTela precisa descontar o tempo com a aba escondida"
    cru = [m.group(0) for m in re.finditer(r"Date\.now\(\) - CF\.gerado_em \* 1000", html)]
    assert not cru, f"idade do card medida sem olhar a visibilidade da aba: {cru}"
    medir = re.search(r"function medirAtraso\(\) \{(.*?)\}\n", html, re.S).group(1)
    assert "idadeNaTela(" in medir


def test_api_confianca_e_frescor(circle, painel):  # noqa: F811
    circle.tick()
    with urllib.request.urlopen(painel + "/api/confianca", timeout=5) as r:
        assert json.loads(r.read())["veredito"] in ("parado", "confiavel", "atencao", "falha")
    code, body = post(painel + "/api/frescor", {"atraso_ms": 120}, {"X-Circulo": "1"})
    assert code == 200 and "registrado" in body             # com poucas amostras a medição entra mas o SLO ainda não julga
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

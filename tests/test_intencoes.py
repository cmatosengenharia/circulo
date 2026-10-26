"""Trilha write-ahead, sinais de ouro, frescor em p99 e parada verificável da Central de confiança.

Regressão: antes, as ações do loop só apareciam no painel pelo push (trilha efêmera de etapas). Nada garantia que
uma ação tivesse registro, nem antes nem depois, e a parada não tinha teste. Estes testes falham sem a trilha."""
import sqlite3
import time
import urllib.request
import json

import pytest

from circulo import intencoes, parada
from circulo.confianca import FRESCOR_MAX_MS, confianca, p99, registrar_frescor, versao_painel

from conftest import say
from test_painel import painel, post  # noqa: F401 — fixture do servidor do painel


def ids(r):
    return {c["id"]: c for c in r["checks"]}


def vivo(circle):
    circle.store.set("batimento", {"em": time.time(), "pid": 1, "proximo_giro_em": time.time() + 15})


def test_toda_acao_do_loop_tem_intencao_gravada_antes(circle):
    for _ in range(4):
        circle.tick()
    say(circle, "38,90 ifood almoço")
    s = circle.store
    res = s.q("SELECT * FROM intencoes WHERE tipo='resultado'")
    assert res, "o loop executou ações sem nenhum registro na trilha"
    for r in res:
        i = s.one("SELECT * FROM intencoes WHERE seq=?", (r["ref"],))
        assert i["tipo"] == "intencao" and i["acao"] == r["acao"] and i["seq"] < r["seq"]
        assert i["ator"] and i["motivo"] and i["regra"]
    assert s.one("SELECT 1 FROM intencoes WHERE acao='pedido:mensagem' AND tipo='intencao'")
    assert intencoes.divergencia(s) == 0 and intencoes.verificar(s, janela=None)["ok"]


def test_acao_so_roda_depois_do_registro(circle, monkeypatch):
    s, visto = circle.store, {}

    def acao():
        visto["intencao"] = s.one("SELECT acao FROM intencoes WHERE tipo='intencao' ORDER BY seq DESC LIMIT 1")["acao"]
    intencoes.executar(s, "teste", acao, motivo="prova")
    assert visto["intencao"] == "teste"                                # a intenção já existia quando a ação rodou

    def falha(*a, **k):
        raise sqlite3.OperationalError("disco cheio")
    monkeypatch.setattr(intencoes, "_gravar", falha)
    rodou = []
    with pytest.raises(sqlite3.OperationalError):
        intencoes.executar(s, "teste", lambda: rodou.append(1), motivo="prova")
    assert not rodou                                                   # sem registro, a ação não roda


def test_trilha_e_so_de_acrescimo_e_encadeada(circle):
    s = circle.store
    for k in range(3):
        intencoes.executar(s, f"a{k}", lambda: None, motivo="m")
    with pytest.raises(sqlite3.DatabaseError):
        s.x("UPDATE intencoes SET motivo='outro' WHERE seq=1")
    with pytest.raises(sqlite3.DatabaseError):
        s.x("DELETE FROM intencoes WHERE seq=1")
    assert intencoes.verificar(s)["ok"]
    s.x("DROP TRIGGER intencoes_sem_update")                           # adulteração por fora dos gatilhos
    s.x("UPDATE intencoes SET motivo='adulterado' WHERE seq=2")
    v = intencoes.verificar(s)
    assert not v["ok"] and v["quebra"] == 2
    assert ids(confianca(s))["trilha"]["estado"] == "falha"


def test_central_em_tres_niveis_com_sinais_de_ouro(circle):
    for _ in range(3):
        circle.tick()
    vivo(circle)
    r = confianca(circle.store)
    c = ids(r)
    for sinal in ("latencia", "trafego", "erros", "orcamento"):        # Perceber: os quatro sinais de ouro
        assert c[sinal]["grupo"] == "agora", sinal
    assert c["latencia"]["valor"].startswith("p99 ")
    assert c["acao"]["grupo"] == "seguranca" and "decidida por: " in c["acao"]["porque"]   # Entender: por quê e qual regra
    assert c["risco"]["grupo"] == "proximo" and c["risco"]["valor"] in ("baixo", "médio", "alto")
    assert r["obsoleto_s"] == FRESCOR_MAX_MS / 1000 == 3
    assert all(x["dado_em"] for x in r["checks"]) and r["veredito"] == "confiavel"


def test_frescor_e_slo_em_p99_de_24h(circle):
    assert p99([100] * 99 + [5000]) == 100                             # um ponto fora em 100 não estoura o p99
    assert p99([100] * 98 + [5000] * 2) == 5000
    s = circle.store
    v = versao_painel()
    for _ in range(99):
        registrar_frescor(s, 200, v)
    s.set("painel_frescor_em", 0)
    registrar_frescor(s, 3500, v)
    assert s.one("SELECT ok FROM verificacoes WHERE ponto='painel:frescor' ORDER BY id DESC LIMIT 1")["ok"] == 1
    s.x("INSERT INTO frescor(atraso_ms, em, versao) VALUES(4000, ?, ?)", (time.time(), v))
    s.set("painel_frescor_em", 0)
    registrar_frescor(s, 200, v)
    assert s.one("SELECT ok FROM verificacoes WHERE ponto='painel:frescor' ORDER BY id DESC LIMIT 1")["ok"] == 0
    assert ids(confianca(s))["frescor"]["estado"] == "atencao"


def test_teste_semanal_da_parada_exercita_o_botao(circle):
    circle.tick()
    vivo(circle)
    assert parada.teste_vencido(circle.store)
    assert circle.testar_parada() is True
    assert not circle.controls()["pausado"]                            # o teste retoma sozinho
    assert not parada.teste_vencido(circle.store)
    v = circle.store.one("SELECT ok FROM verificacoes WHERE ponto='loop:parada' ORDER BY id DESC LIMIT 1")
    assert v["ok"] == 1 and ids(confianca(circle.store))["parada"]["estado"] == "ok"
    acoes = [r["acao"] for r in circle.store.q("SELECT acao FROM intencoes WHERE tipo='intencao' AND ator='teste'")]
    assert acoes == ["parar", "retomar"]                               # a parada também passa pela trilha


def test_parada_que_vaza_derruba_a_confianca(circle):
    circle.tick()
    vivo(circle)
    parada.pedir(circle.store)
    circle.tick()
    assert parada.estado(circle.store)["verificada"]
    intencoes.registrar(circle.store, "evoluir_projeto", "não devia", ator="loop")
    assert parada.estado(circle.store)["estado"] == "vazou"
    assert ids(confianca(circle.store))["vivo"]["estado"] == "falha"


def test_botao_parar_verificado_de_ponta_a_ponta(circle, painel):  # noqa: F811
    circle.tick()
    code, body = post(painel + "/api/parada", {"acao": "parar"}, {"X-Circulo": "1"})
    assert code == 200 and body["parada"]["estado"] == "aguardando"
    assert circle.tick().paused
    with urllib.request.urlopen(painel + "/api/parada", timeout=5) as r:
        e = json.loads(r.read())
    assert e["estado"] == "parado" and e["verificada"] and e["acoes_depois"] == 0
    assert post(painel + "/api/parada", {"acao": "parar"})[0] == 403   # sem o cabeçalho do painel
    code, body = post(painel + "/api/parada", {"acao": "retomar"}, {"X-Circulo": "1"})
    assert code == 200 and not body["controle"]["pausado"]
    assert not circle.tick().paused

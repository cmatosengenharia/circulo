"""Dash do loop em camadas: run_id por execução, todas as etapas do ciclo ao vivo, falha localizada em 2 cliques."""
import json
import time
import urllib.error
import urllib.request

import pytest

from circulo.camadas import ETAPAS, execucao, visao
from circulo.painel import serve


@pytest.fixture
def painel(circle):
    srv = serve(circle.store.path, port=0, background=True)
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_cada_etapa_do_giro_e_a_metrica_carregam_o_mesmo_run_id(circle):
    """Regressão: antes a trilha só tinha o tick, e nada ligava etapas, erros e métrica de uma mesma execução."""
    r1, r2 = circle.tick(), circle.tick()
    assert r1.run_id and r2.run_id and r1.run_id != r2.run_id
    s = circle.store
    rows = s.q("SELECT run_id FROM trail WHERE tick=?", (r1.tick,))
    assert rows and {x["run_id"] for x in rows} == {r1.run_id}
    assert json.loads(s.one("SELECT body FROM metrics WHERE tick=?", (r1.tick,))["body"])["run_id"] == r1.run_id


def test_giro_pausado_nao_vira_execucao(circle):
    circle.tick()
    circle.set_control(pausado=True)
    r = circle.tick()
    assert r.paused and r.run_id is None
    assert circle.store.one("SELECT run_id FROM trail ORDER BY seq DESC LIMIT 1")["run_id"] is None


def test_todas_as_etapas_do_ciclo_aparecem_com_status_e_duracao(circle):
    circle.tick()
    v = visao(circle.store)
    assert [e["chave"] for e in v["etapas"]] == [k for k, _ in ETAPAS]
    por = {e["chave"]: e for e in v["etapas"]}
    for k in ("orquestrador", "meta_learner", "shadow", "licoes", "saude"):
        assert por[k]["status"] == "ok" and por[k]["dur"] is not None and por[k]["run_id"]
    assert por["pedido"]["status"] == "sem_execucao"
    assert len(v["execucoes"]) == 1 and not v["execucoes"][0]["ativo"]
    assert {"fila", "ocioso", "giros_1h"} <= set(v["saturacao"])


def test_falha_de_uma_etapa_e_localizada_pelo_run_id(circle, monkeypatch):
    """Clique 1: a etapa mostra 'falhou' com o run_id; clique 2: a execução traz o erro e o rastro."""
    circle.tick()

    def quebra():
        raise RuntimeError("saude quebrou de proposito")
    monkeypatch.setattr(circle.health, "check", quebra)
    r = circle.tick()
    v = visao(circle.store)
    saude = next(e for e in v["etapas"] if e["chave"] == "saude")
    assert saude["status"] == "falhou" and saude["run_id"] == r.run_id and saude["erros_24h"] == 1
    assert v["saude"]["erros_24h"] >= 1 and v["saude"]["ultima_falhou"] and v["saude"]["cor"] == "vermelho"
    assert any(m["tipo"] == "incidente" and m["run_id"] == r.run_id for m in v["marcos"])
    x = execucao(circle.store, r.run_id)
    assert x["tick"] == r.tick and x["erros"][0]["chave"] == "saude"
    assert "saude quebrou de proposito" in x["erros"][0]["trace"]
    assert any(e["chave"] == "saude" for e in x["etapas"])
    # a execução anterior continua limpa
    assert not any(e["chave"] == "saude" for e in execucao(circle.store, v["execucoes"][0]["run_id"])["erros"])


def test_merge_vira_marco_no_grafico(circle):
    circle.tick()
    circle.store.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,?,?,?,?,?)",
                   (7, "abc123", 1, "ok", "{}", time.time()))
    assert any(m["tipo"] == "merge" and "#7" in m["titulo"] for m in visao(circle.store)["marcos"])


def test_api_do_dash_em_camadas(circle, painel):
    r = circle.tick()
    code, v = get(painel + "/api/loop")
    assert code == 200 and v["saude"]["cor"] in ("verde", "amarelo", "vermelho") and len(v["etapas"]) == len(ETAPAS)
    code, x = get(painel + f"/api/execucao/{r.run_id}")
    assert code == 200 and x["run_id"] == r.run_id
    assert get(painel + "/api/execucao/nao-existe")[0] == 404
    assert get(painel + "/api/execucao/abc123")[0] == 404


def test_saude_traz_entregas_e_fila_das_ultimas_24h(circle):
    from circulo.camadas import visao
    agora = time.time()
    circle.store.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(7,2,'x','b','mergeado',?,?)", (agora, agora))
    circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES('a','d','loop','pendente','',1,?,?)", (agora, agora))
    H = visao(circle.store)["saude"]
    assert H["entregas_24h"]["prs"] == 1 and H["fila"]["pendentes"] >= 1 and "reincidencias_24h" in H

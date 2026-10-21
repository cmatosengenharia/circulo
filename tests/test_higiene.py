"""Higiene (circulo/higiene.py) e assinatura por causa (licoes.causa_de_json): o que sujava as telas em 20/10."""
import time

from circulo import higiene
from circulo.licoes import assinatura_de, causa_de_json, titulo_curto

LOG = ('{"d_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,"requested":{"background":0}},"is_error":true,'
       '"num_turns":1,"subtype":"success","result":"Failed to authenticate: OAuth session expired and could not be refreshed"}')


def test_log_json_do_agente_vira_causa_classificada_e_nao_trecho_cru():
    assert causa_de_json(LOG) == "deslogado"
    assert assinatura_de("developer:agente", LOG) == "developer:agente:deslogado"
    assert assinatura_de("developer:agente", LOG[:300]) == "developer:agente:deslogado"       # o mesmo com o corte em outro lugar
    assert causa_de_json('{"subtype":"error_max_turns","is_error":true}') == "maximo_de_passos"
    assert causa_de_json("ERROR: file not found tests/x.py") is None                          # texto comum segue o caminho antigo
    assert assinatura_de("developer:testes", "FAILED tests/test_a.py::test_x - assert") == "developer:testes:teste:tests/test_a.py::test_x"


def test_titulo_curto_cabe_numa_linha_sem_json():
    t = 'Lição #42: developer:agente: d_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,"requested":{"background":0,"foreground":0,"unset":0},"started_in_background":0}'
    c = titulo_curto(t)
    assert len(c) <= 101 and c.endswith("…") and "subagent_stats" not in c
    assert titulo_curto("Parser puro de numstat com soma total") == "Parser puro de numstat com soma total"


def test_higiene_expira_dependentes_encurta_titulos_e_une_licoes(circle):
    s = circle.store
    agora = time.time()
    velho = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES('Ligar chaves','d','pedido_cassio','pendente','depende de você',1,?,?)", (agora - 9 * 86400, agora - 9 * 86400))
    novo = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES('Outro','d','pedido_cassio','pendente','depende de você',2,?,?)", (agora - 86400, agora - 86400))
    longo = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,'d','loop','pendente','x',3,?,?)", ("Lição #42: " + "palavra " * 40, agora, agora))
    a = s.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,created_at,updated_at) VALUES('developer:agente:deslogado','developer:agente','trabalho','developer:agente: deslogado','p','aberta',3,0,?,?)", (agora - 3600, agora - 3600))
    b = s.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,created_at,updated_at) VALUES(?,'developer:agente','trabalho',?,'p','aberta',18,0,?,?)",
            ('developer:agente:d_reason:sdk_opt_in_required subagent_stats: spawn', "developer:agente: " + LOG[:200], agora, agora))
    rel = higiene.rodar(s, forcar=True)
    assert rel["expirados"] == 1 and rel["titulos"] == 1 and rel["licoes_unidas"] == 1
    assert s.one("SELECT status FROM roadmap WHERE id=?", (velho,))["status"] == "descartado" and s.one("SELECT status FROM roadmap WHERE id=?", (novo,))["status"] == "pendente"
    r = s.one("SELECT titulo, detalhe FROM roadmap WHERE id=?", (longo,))
    assert len(r["titulo"]) <= 101 and "Título original" in r["detalhe"]
    assert s.one("SELECT status FROM licoes WHERE id=?", (b,))["status"] == "unida" and s.one("SELECT ocorrencias FROM licoes WHERE id=?", (a,))["ocorrencias"] == 21
    assert higiene.rodar(s) is None                                                  # uma vez por hora
    assert s.one("SELECT COUNT(*) n FROM alerts WHERE message LIKE 'Higiene:%'")["n"] == 1

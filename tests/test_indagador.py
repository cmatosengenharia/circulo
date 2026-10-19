"""Indagador: o agente que faz as perguntas da autoevolução e o Jev classifica cada uma."""
import json
import time
import urllib.request

from circulo import indagador
from circulo.decision import Decision

from test_painel import painel  # noqa: F401 — fixture do servidor do painel


def _missao(circle, nome="Portal do fotógrafo"):
    s = circle.store
    agora = time.time()
    pid = s.x("INSERT INTO projects(nome,pedido,tipo,kit,status,proposito,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
              (nome, "um portal onde o fotógrafo entrega as fotos ao cliente", "portal_web", "web", "ativo", "entregar fotos", agora, agora))
    crit = [{"id": "c1", "texto": "o cliente encontra as fotos do evento em um clique", "peso": 3},
            {"id": "c2", "texto": "o fotógrafo vê quais galerias foram abertas", "peso": 2}]
    s.x("INSERT INTO rubrics(project_id,version,criteria,created_at) VALUES(?,?,?,?)", (pid, 1, json.dumps(crit), agora))
    s.x("INSERT INTO deliverables(project_id,version,formato,path,content,nota,nota_oculta,notas,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (pid, 1, "html", "x.html", "<html></html>", 0.55, 0.5, json.dumps({"c1": 0.3, "c2": 0.8}), "atual", agora))
    return dict(s.one("SELECT * FROM projects WHERE id=?", (pid,)))


def test_perguntas_da_missao_passam_pelo_jev_e_so_a_pertinente_vale(circle):
    p = _missao(circle)
    r = indagador.indagar(circle.ctx, p)
    assert r["cerebro"] == f"missao:{p['id']}" and r["candidatas"] >= 1
    rows = circle.store.q("SELECT * FROM perguntas WHERE cerebro=?", (f"missao:{p['id']}",))
    assert rows and all(x["eixo"] and x["pertinencia"] is not None and x["classificacao"] for x in rows)
    valida = [x for x in rows if x["status"] == "valida"]
    assert valida and "um clique" in valida[0]["texto"]                 # o critério mais fraco (0.30) vira a pergunta
    assert json.loads(valida[0]["evidencia"])["base"] == "medido"         # evidência medida, nunca inferida
    cls = json.loads(valida[0]["classificacao"])
    assert {"pertinente", "eixo", "acao"} <= set(cls) and cls["eixo"]["valor"] == valida[0]["eixo"]
    # o Jev classificou: as 3 perguntas por candidata ficam no registro de decisões
    nomes = {r["question"] for r in circle.store.q("SELECT question FROM decisions WHERE question LIKE 'indaga_%'")}
    assert any(n.startswith("indaga_pert_") for n in nomes) and any(n.startswith("indaga_eixo_") for n in nomes)
    assert any(n.startswith("indaga_acao_") for n in nomes)


def test_pergunta_generica_e_descartada_pelo_jev(circle):
    res = indagador.classificar(circle.ctx, [{"chave": "x", "persona": "cetico", "texto": "Como melhorar o sistema em geral?",
                                               "relevancia": 0.5, "evidencia": {}}], indagador.contexto(circle.store, None))
    assert res[0]["veredito"] == "descartada" and res[0]["eixo"] == "nenhum"


def test_jev_em_duvida_vira_inconclusa_e_nao_passa(circle):
    class JevDuvida:
        source = "jev"
        ultimo_modelo = "jev-1.13.0"

        def ask_many(self, state, questions):
            out = {}
            for qid, q in questions.items():
                if q.kind == "noul":
                    out[qid] = Decision(qid, "noul", 0.52, 0.04, "jev")           # não sabe
                elif q.kind == "choice":
                    out[qid] = Decision(qid, "choice", "missao", 0.7, "jev")
                else:
                    out[qid] = Decision(qid, "score", 2.0, 0.7, "jev")
            return out, 50
    circle.ctx.dl.jev = JevDuvida()
    p = _missao(circle)
    r = indagador.indagar(circle.ctx, p)
    assert r["inconclusas"] >= 1 and r["validas"] == 0
    assert circle.store.one("SELECT COUNT(*) n FROM perguntas WHERE status='inconclusa'")["n"] >= 1


def test_planejador_e_missao_partem_da_pergunta_validada(circle):
    p = _missao(circle)
    indagador.indagar(circle.ctx, p)
    v = indagador.proxima(circle.store, f"missao:{p['id']}")
    assert v and v["status"] == "valida" and "um clique" in v["texto"]
    assert circle.store.one("SELECT status FROM perguntas WHERE id=?", (v["id"],))["status"] == "feita"
    assert indagador.proxima(circle.store, "loop") is None               # nada validado para o loop ainda


def test_pedido_do_cassio_entra_na_fila_e_o_jev_so_anota(circle):
    s = circle.store
    agora = time.time()
    item = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
               ("Mostrar no painel a nota de cada missão", "Mostrar no painel a nota de cada missão por ciclo", "pedido_cassio", "pendente",
                "pedido pelo painel", 1, agora, agora))
    c = indagador.classificar_pedido(circle.ctx, "Mostrar no painel a nota de cada missão por ciclo", item)
    assert c and c["eixo"] in indagador.EIXOS
    r = s.one("SELECT status, detalhe FROM roadmap WHERE id=?", (item,))
    assert r["status"] == "pendente" and "Indagador (Jev): eixo" in r["detalhe"]   # continua na fila, só anotado
    q = s.one("SELECT persona, status, item_id FROM perguntas WHERE chave=?", (f"pedido:{item}",))
    assert q["persona"] == "cassio" and q["status"] == "virou_item" and q["item_id"] == item


def test_indagador_roda_como_tarefa_do_giro_e_respeita_o_intervalo(circle):
    p = _missao(circle)
    class Motor:
        ready = True                                    # nos testes não há LLM; aqui só importa a fila de cérebros
    assert indagador.proximo_cerebro(circle.store, Motor()) is not None
    indagador.rodar(circle.ctx, Motor())
    indagador.rodar(circle.ctx, Motor())
    assert set((circle.store.get("indagador") or {})) >= {"loop", f"missao:{p['id']}"}
    assert indagador.proximo_cerebro(circle.store, Motor()) is None                 # os dois foram indagados há pouco
    circle.store.set("indagador", {"loop": 0, f"missao:{p['id']}": time.time()})
    assert indagador.proximo_cerebro(circle.store, Motor())["project"] is None       # o loop venceu o intervalo: é a vez dele
    circle.tick()                                                                    # o giro inteiro continua passando


def test_painel_mostra_o_indagador(circle, painel):  # noqa: F811
    p = _missao(circle)
    indagador.indagar(circle.ctx, p)
    with urllib.request.urlopen(painel + "/api/indagador", timeout=5) as r:
        d = json.loads(r.read())
    assert d["total"] >= 1 and d["ultimas"] and "arquitetura" in d["eixos"]
    from circulo.projects import kit_project_id
    with urllib.request.urlopen(painel + f"/missao/{kit_project_id(circle.store, 'circulo')}", timeout=5) as r:
        assert 'id="indag"' in r.read().decode()

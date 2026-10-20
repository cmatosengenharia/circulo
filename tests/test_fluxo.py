"""Fluxo dos agentes ao vivo e laboratório do Jev."""
import json
import urllib.request

from circulo import fluxo, jev_lab
from circulo.decision import Decision, DecisionLayer, LocalJev, Question

from test_painel import painel  # noqa: F401 — fixture do servidor do painel


def test_giro_vira_eventos_em_ordem_de_agente_para_agente(circle):
    cur = fluxo.cursor_inicial(circle.store)
    circle.tick()
    evs, cur2 = fluxo.eventos(circle.store, cur)
    etapas = [e for e in evs if e["tipo"] == "etapa"]
    assert etapas[0]["agente"] == "orquestrador" and "começou o giro" in etapas[0]["texto"]
    assert etapas[-1]["agente"] == "descanso"
    for a, b in zip(etapas, etapas[1:], strict=False):
        assert b["de"] == a["agente"]                                 # a bolinha vai de um agente ao próximo
    assert any(e["tipo"] == "decisao" and e["para"] == "jev" for e in evs)
    assert [e["em"] for e in evs] == sorted(e["em"] for e in evs)
    assert fluxo.eventos(circle.store, cur2)[0] == []                  # nada repetido


def test_agente_novo_da_autoevolucao_entra_sozinho(circle):
    circle.tick()
    lista = {a["id"]: a for a in fluxo.agentes(circle.store)}
    assert not any(a["novo"] for a in lista.values() if not a.get("externo"))   # os que já existiam não são "novos"
    s = circle.store
    t = s.tick + 1
    base = __import__("time").time() - 10
    for etapa, tarefa, em in (("orquestrador", None, 1.0), ("idle", "otimizar_cache", 2.0), ("descanso", None, 3.5)):
        s.x("INSERT INTO trail(tick,etapa,project_id,em,detalhe,run_id,tarefa) VALUES(?,?,?,?,?,?,?)",
            (t, etapa, None, base + em, "Otimizando o cache" if tarefa else None, "abcabcabcabc", tarefa))
    lista = {a["id"]: a for a in fluxo.agentes(s)}
    assert lista["otimizar_cache"]["novo"] and lista["otimizar_cache"]["faz"] == "Otimizando o cache"
    assert lista["otimizar_cache"]["execucoes_24h"] == 1 and lista["otimizar_cache"]["p50_ms"] == 1500
    evs, _ = fluxo.eventos(s, {"trail": 0, "dec": 10**9, "llm": 10**9, "ver": 10**9, "err": 10**9})
    assert any(e["agente"] == "otimizar_cache" and e["novo"] for e in evs)


def test_painel_do_fluxo(circle, painel):  # noqa: F811
    circle.tick()
    with urllib.request.urlopen(painel + "/api/fluxo", timeout=5) as r:
        d = json.loads(r.read())
    assert {"agora", "agentes", "jev"} <= set(d) and any(a["id"] == "jev" for a in d["agentes"])
    with urllib.request.urlopen(painel + "/fluxo", timeout=5) as r:
        assert "Bastidores do giro" in r.read().decode()
    with urllib.request.urlopen(painel + "/api/fluxo/eventos?voltar=20", timeout=5) as r:
        linhas = b""
        while b"event: fluxo" not in linhas:
            linhas += r.readline()
    assert b"orquestrador" in linhas or b"event: fluxo" in linhas


def test_fluxo_so_mostra_o_que_nao_esta_em_outra_tela(circle, painel):  # noqa: F811
    """1.36.0: o anel, o cartão “Agora”, a grade de agentes e as obras saíram daqui (a Equipe ao vivo já mostra tudo isso);
    ficam as raias do giro e o Jev, que só existem aqui."""
    with urllib.request.urlopen(painel + "/fluxo", timeout=5) as r:
        html = r.read().decode()
    assert 'id="raiasSvg"' in html and 'id="jevLab"' in html
    assert 'id="svg"' not in html and 'id="agentes"' not in html and 'id="obras"' not in html and "mostrarAgora" not in html


class JevFalso:
    """Responde como o Jev real: em dúvida na pergunta em português, seguro na variante em inglês."""
    source = "jev"
    ultimo_modelo = "jev-1.13.0"

    def __init__(self):
        self.pedidos = []

    def ask_many(self, state, questions):
        self.pedidos.append(dict(questions))
        out = {}
        for qid, q in questions.items():
            p = 0.9 if q.instructions.startswith(("The autonomous", "Does the", "Which")) else 0.55
            if q.kind == "choice":
                out[qid] = Decision(qid, "choice", q.options()[0], p - 0.1, "jev")
            else:
                out[qid] = Decision(qid, "noul", p, abs(2 * p - 1), "jev")
        return out, 100


def _dl(circle, jev):
    return DecisionLayer(circle.store, circle.ctx.policies.get, circle.ctx.budget, jev=jev)


def test_laboratorio_manda_variante_na_mesma_chamada_e_adota_com_evidencia(circle):
    jev = JevFalso()
    dl = _dl(circle, jev)
    q = Question("noul", "Vale a pena gastar ~100 tokens agora na ação 'x'?")
    d = dl.ask("worth_spending", q, {"action": "x", "est_tokens": 100, "budget_left_ratio": 0.8, "value_signal": 0.7})
    assert set(jev.pedidos[0]) == {"worth_spending", "lab__worth_spending"}      # uma chamada, as duas formas
    assert jev.pedidos[0]["lab__worth_spending"].instructions.startswith("The autonomous loop")
    assert "lab__worth_spending" not in str(d) and d.name == "worth_spending"
    assert circle.store.get("jev_modelo") == "jev-1.13.0"                         # versão exata registrada
    for _ in range(jev_lab.MIN_N):
        dl.ask("worth_spending", q, {"action": "x", "est_tokens": 100, "budget_left_ratio": 0.8, "value_signal": 0.7})
    p = jev_lab.placar(circle.store, "worth_spending")
    assert p["ganho"] > 0.5 and p["concordancia"] == 1.0
    log = jev_lab.avaliar(circle.store)
    assert log and "inglês" in log[0] and jev_lab.ativas(circle.store).get("worth_spending")
    jev.pedidos.clear()
    dl.ask("worth_spending", q, {"action": "x", "est_tokens": 100, "budget_left_ratio": 0.8, "value_signal": 0.7})
    oficial = jev.pedidos[0]["worth_spending"]
    assert oficial.instructions.startswith("The autonomous loop")                 # a variante virou a oficial
    assert jev.pedidos[0]["lab__worth_spending"].instructions.startswith("Vale a pena")   # e a antiga segue medida


def test_sem_jev_real_o_laboratorio_nao_interfere(circle):
    enviar, mapa = jev_lab.preparar(circle.store, LocalJev(), {}, {"worth_spending": Question("noul", "x")})
    assert set(enviar) == {"worth_spending"} and mapa == {}


def test_versao_nova_do_jev_vira_alerta(circle):
    jev = JevFalso()
    dl = _dl(circle, jev)
    dl.ask("remember", Question("noul", "guardar?"), {})
    jev.ultimo_modelo = "jev-1.14.0"
    dl.ask("remember", Question("noul", "guardar?"), {})
    msg = circle.store.one("SELECT message FROM alerts ORDER BY id DESC LIMIT 1")["message"]
    assert "jev-1.13.0 → jev-1.14.0" in msg


def test_jardineiro_transforma_crescimento_em_item(circle, tmp_path):
    from circulo import jardineiro
    pasta = tmp_path / "codigo"
    pasta.mkdir()
    (pasta / "a.py").write_text("def f():\n    try:\n        pass\n    except Exception:\n        pass\n")
    agora = 1_000_000.0
    assert jardineiro.podar(circle.store, pasta=pasta, now=agora) == []        # primeira medição: só a base
    (pasta / "b.py").write_text("".join(f"def g{i}():\n    try:\n        pass\n    except Exception:\n        pass\n" for i in range(5)))
    achados = jardineiro.podar(circle.store, pasta=pasta, now=agora + 7 * 86400)
    assert achados and "except Exception" in achados[0] and "b.py (5)" in achados[0]
    item = circle.store.one("SELECT titulo, origem FROM roadmap WHERE titulo LIKE 'Jardineiro:%'")
    assert item["origem"] == "loop"
    jardineiro.podar(circle.store, pasta=pasta, now=agora + 7 * 86400 + 1)
    assert circle.store.one("SELECT COUNT(*) n FROM roadmap WHERE titulo LIKE 'Jardineiro:%'")["n"] == 1   # sem duplicar


def test_raias_do_giro_mostram_quem_fez_o_que_e_quando(circle, painel):  # noqa: F811
    circle.tick()
    g = fluxo.giro(circle.store)
    assert g["run_id"] and g["intervalos"] and g["raias"][0]["id"] == "orquestrador"
    assert all(s["fim"] >= s["inicio"] for s in g["intervalos"])
    assert all(a["inicio"] <= b["inicio"] for a, b in zip(g["intervalos"], g["intervalos"][1:], strict=False))  # em ordem de tempo
    assert any(s["jev"] for s in g["intervalos"]) and g["totais"]["jev"] >= 1                                   # o Jev aparece no trecho certo
    rec = fluxo.giros_recentes(circle.store)
    assert rec and rec[0]["run_id"] == g["run_id"] and "duracao_ms" in rec[0]
    with urllib.request.urlopen(painel + "/api/fluxo/giro?run=" + g["run_id"], timeout=5) as r:
        d = json.loads(r.read())
    assert d["giro"]["run_id"] == g["run_id"] and d["recentes"]
    with urllib.request.urlopen(painel + "/fluxo", timeout=5) as r:
        html = r.read().decode()
    assert 'id="raiasSvg"' in html


def test_obras_dizem_o_que_cada_agente_construiu(circle, painel):  # noqa: F811
    s = circle.store
    agora = __import__("time").time()
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (7, None, "Teste novo no gate", "b", "mergeado", agora, agora))
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,?,?,?,?,?)", (7, "abc", 1, "todos os gates passaram", "{}", agora))
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        ("Item do loop", "d", "loop", "pendente", "e", 1, json.dumps({"veredito": "adaptar"}), agora, agora))
    obras = {o["agente"]: o for o in fluxo.obras(s)}
    assert obras["corrigir_codigo"]["titulo"].startswith("PR #7") and obras["revisar_prs"]["titulo"].endswith("mergeado")
    assert obras["planejar_roteiro"]["titulo"].startswith("Item #") and "adaptar" in obras["estudar_pedido"]["estado"]
    with urllib.request.urlopen(painel + "/api/fluxo/obras", timeout=5) as r:
        assert json.loads(r.read())["obras"]

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
    for etapa, tarefa, em in (("orquestrador", None, 1.0), ("idle", "otimizar_cache", 2.0), ("descanso", None, 3.5)):
        s.x("INSERT INTO trail(tick,etapa,project_id,em,detalhe,run_id,tarefa) VALUES(?,?,?,?,?,?,?)",
            (t, etapa, None, __import__("time").time() - 10 + em, "Otimizando o cache" if tarefa else None, "abcabcabcabc", tarefa))
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
        assert "Fluxo ao vivo" in r.read().decode()
    with urllib.request.urlopen(painel + "/api/fluxo/eventos?voltar=20", timeout=5) as r:
        linhas = b""
        while b"event: fluxo" not in linhas:
            linhas += r.readline()
    assert b"orquestrador" in linhas or b"event: fluxo" in linhas


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

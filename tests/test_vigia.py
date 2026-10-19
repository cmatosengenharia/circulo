"""Vigia: travas da autoevolução medidas por sondas, classificadas pelo Jev e tratadas sozinhas."""
import json
import time
import urllib.request

from circulo import vigia
from circulo.decision import Decision

from test_painel import painel  # noqa: F401 — fixture do servidor do painel


def _trava_pergunta(circle, ha=vigia.ESPERA_PERGUNTA + 60):
    agora = time.time()
    circle.store.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,eixo,pertinencia,score,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   ("x", "arquiteto", "Qual parte do código mais faz o Developer errar?", "valida", "loop", "arquitetura", 0.86, 0.6, agora - ha, agora - ha))


def test_sondas_so_disparam_com_evidencia_medida(circle):
    assert vigia.sondar(circle.store) == []                                  # loop recém-criado: nada travado
    _trava_pergunta(circle)
    achados = {a["chave"]: a for a in vigia.sondar(circle.store)}
    assert "pergunta_valida_parada" in achados and achados["pergunta_valida_parada"]["evidencia"]["base"] == "medido"
    s = circle.store
    s.set("progresso", {"sem": 12, "recusas": {"planejar_roteiro": 4}})
    chaves = {a["chave"] for a in vigia.sondar(s)}
    assert {"estagnacao", "porteiro_recusa:planejar_roteiro"} <= chaves
    s.set("batimento", {"em": time.time()})
    s.set("etapa", {"nome": "developer", "tick": 9, "em": time.time() - vigia.GIRO_TRAVADO - 5})
    assert "giro_travado" in {a["chave"] for a in vigia.sondar(s)}            # pega o giro parado mesmo sem giro acontecer


def test_jev_classifica_e_o_vigia_age_conforme_a_confianca(circle):
    _trava_pergunta(circle)
    v = vigia.Vigia(circle.ctx)
    r = v.rodar()
    assert r["novos"] >= 1
    row = circle.store.one("SELECT * FROM vigia WHERE chave='pergunta_valida_parada'")
    assert row["status"] == "aberta" and row["veredito"] in ("trava", "em_duvida") and json.loads(row["classificacao"])["trava"]["fonte"]
    nomes = {x["question"] for x in circle.store.q("SELECT question FROM decisions WHERE question LIKE 'vigia_%'")}
    assert any(n.startswith("vigia_trava_") for n in nomes) and any(n.startswith("vigia_acao_") for n in nomes)
    if row["acao"] in ("abrir_item", "alertar"):
        assert circle.store.one("SELECT COUNT(*) n FROM alerts WHERE kind='saude' AND message LIKE 'Vigia:%'")["n"] >= 1
    r2 = v.rodar()
    assert r2["novos"] == 0 or row["veredito"] == "em_duvida"               # trava já aberta não é reclassificada nem realertada
    assert circle.store.one("SELECT vezes FROM vigia WHERE chave='pergunta_valida_parada'")["vezes"] >= 2
    circle.store.x("UPDATE perguntas SET status='feita'")                   # a trava sumiu
    r3 = v.rodar()
    assert "pergunta_valida_parada" in r3["resolvidas"]
    assert circle.store.one("SELECT status FROM vigia WHERE chave='pergunta_valida_parada'")["status"] == "resolvida"


def test_confianca_alta_abre_item_uma_vez_e_media_so_alerta(circle):
    class JevSeguro:
        source, ultimo_modelo = "jev", "jev-1.13.0"

        def __init__(self, conf):
            self.conf = conf

        def ask_many(self, state, qs):
            out = {}
            for qid, q in qs.items():
                out[qid] = Decision(qid, "noul", 0.9, self.conf, "jev") if q.kind == "noul" else Decision(qid, "choice", "abrir_item", self.conf, "jev")
            return out, 10
    s = circle.store
    s.set("progresso", {"sem": 15, "recusas": {}})
    circle.ctx.dl.jev = JevSeguro(0.9)
    vigia.Vigia(circle.ctx).rodar()
    item = s.one("SELECT id, origem, evidencia FROM roadmap WHERE titulo LIKE 'Vigia:%'")
    assert item and item["origem"] == "loop" and item["evidencia"].startswith("Vigia (medido)")
    assert s.one("SELECT item_id FROM vigia WHERE chave='estagnacao'")["item_id"] == item["id"]
    vigia.Vigia(circle.ctx).rodar()
    assert s.one("SELECT COUNT(*) n FROM roadmap WHERE titulo LIKE 'Vigia:%'")["n"] == 1      # não duplica
    s.x("DELETE FROM vigia")
    s.x("DELETE FROM roadmap WHERE titulo LIKE 'Vigia:%'")
    circle.ctx.dl.jev = JevSeguro(0.35)                                      # confiança média: no máximo alerta
    vigia.Vigia(circle.ctx).rodar()
    assert s.one("SELECT acao FROM vigia WHERE chave='estagnacao'")["acao"] == "alertar"
    assert s.one("SELECT COUNT(*) n FROM roadmap WHERE titulo LIKE 'Vigia:%'")["n"] == 0


def test_jev_em_duvida_observa_e_pergunta_de_novo(circle):
    class JevDuvida:
        source, ultimo_modelo = "jev", "jev-1.13.0"

        def ask_many(self, state, qs):
            return {qid: (Decision(qid, "noul", 0.5, 0.02, "jev") if q.kind == "noul" else Decision(qid, "choice", "observar", 0.5, "jev"))
                    for qid, q in qs.items()}, 10
    circle.ctx.dl.jev = JevDuvida()
    _trava_pergunta(circle)
    v = vigia.Vigia(circle.ctx)
    v.rodar()
    r = circle.store.one("SELECT veredito, acao FROM vigia WHERE chave='pergunta_valida_parada'")
    assert r["veredito"] == "em_duvida" and r["acao"] == "observar"
    assert circle.store.one("SELECT COUNT(*) n FROM alerts WHERE message LIKE 'Vigia:%'")["n"] == 0
    assert v.rodar()["novos"] == 1                                           # em dúvida: volta a perguntar


def test_thread_paralela_roda_sem_o_giro_e_para_limpa(circle):
    _trava_pergunta(circle)
    v = vigia.Vigia(circle.ctx, intervalo=0.05)
    v.iniciar()
    fim = time.time() + 3
    while time.time() < fim and not circle.store.get("vigia_ultima"):
        time.sleep(0.05)
    v.parar()
    assert circle.store.get("vigia_ultima") and not v._thread.is_alive()


def test_painel_mostra_o_vigia(circle, painel):  # noqa: F811
    _trava_pergunta(circle)
    vigia.Vigia(circle.ctx).rodar()
    with urllib.request.urlopen(painel + "/api/vigia", timeout=5) as r:
        d = json.loads(r.read())
    assert d["estado"] in ("travado", "observando") and d["abertas"] and "pergunta_valida_parada" in d["sondas"]
    from circulo.projects import kit_project_id
    with urllib.request.urlopen(painel + f"/missao/{kit_project_id(circle.store, 'circulo')}", timeout=5) as r:
        assert 'id="vigiaLista"' in r.read().decode()
    with urllib.request.urlopen(painel + "/api/fluxo/obras", timeout=5) as r:
        assert any(o["agente"] == "vigia" for o in json.loads(r.read())["obras"])


class _PlanejadorParado:
    """Planejador que sempre precisa rodar e não faz nada: só o porteiro do gasto decide."""

    def precisa(self):
        return True

    def run(self, autorizado=False):
        return None


def _porteiro(circle, valor, limiar=0.4):
    from circulo.decision import Gate
    real = circle.ctx.dl.worth_spending

    def ws(action, contexto):
        if contexto.get("task") != "planejar_roteiro":
            return real(action, contexto)
        return Gate(valor >= limiar, Decision("worth_spending", "noul", valor, 0.8, "jev"), limiar)
    circle.ctx.dl.worth_spending = ws


def _pergunta_id(circle):
    return circle.store.one("SELECT id FROM perguntas WHERE status='valida' ORDER BY id LIMIT 1")["id"]


def _novo_ciclo(circle):
    circle.store.set("idle_last", {})                                         # sem espaçamento entre os ciclos do teste
    circle.store.set("progresso", {"sem": 0, "recusas": {}})


def test_porteiro_grava_a_decisao_sobre_a_pergunta_a_cada_ciclo(circle):
    """Lição #14: cada ciclo do porteiro worth_spending.idle_evolution sobre o planejador deixa registro medido."""
    from circulo.planejador import PORTEIRO
    _trava_pergunta(circle)
    pid = _pergunta_id(circle)
    circle.planejador = _PlanejadorParado()
    _porteiro(circle, 0.33)
    circle.idle()
    _novo_ciclo(circle)
    circle.idle()
    u = circle.store.get(PORTEIRO)["ultimo"]
    assert (u["pergunta_id"], u["decisao"], u["motivo"], u["limiar"], u["valor"], u["seguidas"]) == \
        (pid, "recusou", "abaixo_do_limiar", 0.4, 0.33, 2)
    _porteiro(circle, 0.7)
    _novo_ciclo(circle)
    circle.idle()
    u = circle.store.get(PORTEIRO)["ultimo"]
    assert (u["decisao"], u["motivo"], u["valor"], u["seguidas"]) == ("aceitou", "acima_do_limiar", 0.7, 1)
    assert len(circle.store.get(PORTEIRO)["historico"]) == 3


def _registro(circle, valor, vezes):
    from circulo.decision import Gate
    from circulo.planejador import registrar_porteiro
    for _ in range(vezes):
        registrar_porteiro(circle.store, _pergunta_id(circle), Gate(valor >= 0.4, Decision("worth_spending", "noul", valor, 0.8, "jev"), 0.4))


def test_alerta_de_trava_cita_o_motivo_medido_da_ultima_recusa(circle):
    _trava_pergunta(circle)
    a = {x["chave"]: x for x in vigia.sondar(circle.store)}["pergunta_valida_parada"]
    assert "não está rodando" not in a["sugestao"] and "sem registro" in a["sugestao"]     # sem registro: não adivinha a causa
    _registro(circle, 0.33, 2)
    a = {x["chave"]: x for x in vigia.sondar(circle.store)}["pergunta_valida_parada"]
    assert "abaixo_do_limiar" in a["sugestao"] and "0.33" in a["sugestao"] and "0.40" in a["sugestao"]
    assert "não está rodando" not in a["sugestao"]
    assert a["evidencia"]["porteiro"]["motivo"] == "abaixo_do_limiar" and a["evidencia"]["porteiro"]["seguidas"] == 2


def test_pergunta_parada_so_dispara_acima_do_limite_por_duas_verificacoes(circle):
    _trava_pergunta(circle, ha=vigia.ESPERA_PERGUNTA + 5)                    # passou do limite só nesta verificação
    assert "pergunta_valida_parada" not in {a["chave"] for a in vigia.sondar(circle.store)}
    circle.store.x("DELETE FROM perguntas")
    _trava_pergunta(circle, ha=vigia.ESPERA_PERGUNTA + vigia.INTERVALO)      # já estava acima na verificação anterior
    assert "pergunta_valida_parada" in {a["chave"] for a in vigia.sondar(circle.store)}


def test_recusada_n_vezes_pelo_mesmo_motivo_vira_recusada_pelo_porteiro_e_abre_revisao_do_limiar(circle):
    _trava_pergunta(circle)
    pid = _pergunta_id(circle)
    _registro(circle, 0.33, vigia.RECUSAS_PORTEIRO)
    v = vigia.Vigia(circle.ctx)
    v.rodar()
    s = circle.store
    assert s.one("SELECT status FROM perguntas WHERE id=?", (pid,))["status"] == "recusada_porteiro"
    item = s.one("SELECT titulo, origem, detalhe FROM roadmap WHERE titulo LIKE 'Vigia: revisar o limiar%'")
    assert item and item["origem"] == "loop" and "worth_spending.idle_evolution" in item["titulo"] and "abaixo_do_limiar" in item["detalhe"]
    assert s.one("SELECT COUNT(*) n FROM vigia WHERE chave='pergunta_valida_parada'")["n"] == 0   # não repete o alerta
    v.rodar()
    assert s.one("SELECT COUNT(*) n FROM roadmap WHERE titulo LIKE 'Vigia: revisar o limiar%'")["n"] == 1

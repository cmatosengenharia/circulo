"""Auditoria de 21/10 (1.61.0): regressões dos defeitos encontrados na revisão de todo o código."""
import json
import sqlite3
import time
import urllib.error
import urllib.request

import pytest

from circulo import aluno, fatiador, higiene, jev_lab
from circulo.corpo import MAX_ERROS_NA_VALIDACAO, Corpo
from circulo.medico import SILENCIO, Medico
from circulo.state import Store
from tests.test_medico import _erro_meta
from tests.test_painel import painel  # noqa: F401


def test_transacao_que_nao_abre_nao_vaza_o_lock(tmp_path):
    s = Store(str(tmp_path / "a.db"))
    outra = sqlite3.connect(str(tmp_path / "a.db"), isolation_level=None, timeout=0.1)
    outra.execute("BEGIN IMMEDIATE")                       # outro processo segura a escrita
    s.db.execute("PRAGMA busy_timeout=100")
    with pytest.raises(sqlite3.OperationalError):
        with s.tx():
            pass
    outra.execute("ROLLBACK")
    assert s.lock.acquire(timeout=1)                       # o lock foi liberado (antes: travava todas as threads para sempre)
    s.lock.release()
    with s.tx():
        s.set("ok", 1)
    assert s.get("ok") == 1


def test_medico_reabre_diagnostico_fechado_sem_estourar_a_chave_unica(circle):
    s = circle.store
    _erro_meta(circle, 8)
    m = Medico(circle.ctx)
    m.rodar()
    d = s.one("SELECT id, chave FROM diagnosticos")
    s.x("UPDATE diagnosticos SET status='fechado', fechado_em=?, ultima_em=? WHERE id=?", (time.time(), time.time() - SILENCIO - 1, d["id"]))
    _erro_meta(circle, 8)                                    # o mesmo padrão volta
    r = m.rodar()                                            # antes: IntegrityError UNIQUE(chave) e o SRE inteiro parava
    row = s.one("SELECT status, reaberturas FROM diagnosticos WHERE id=?", (d["id"],))
    assert row["status"] != "fechado" and row["reaberturas"] == 1 and r["novos"] == 0
    assert s.one("SELECT COUNT(*) n FROM diagnosticos")["n"] == 1


def test_erro_de_ambiente_nao_reprova_o_codigo_novo(circle, tmp_path):
    s = circle.store
    s.set("corpo", {"estado": "validando", "sha": "novo", "anterior": "velho", "desde_tick": 10, "giros_ok": 0, "erros": 0})
    c = Corpo(circle.ctx, None, tmp_path)
    for _ in range(MAX_ERROS_NA_VALIDACAO + 1):
        c.validar(["idle: URLError(gaierror(8, 'nodename nor servname provided'))", "gate: HTTP Error 502: Bad Gateway"])
    assert s.get("corpo")["erros"] == 0 and s.get("corpo")["estado"] == "validando"
    c.validar(["meta: KeyError('campo novo')"])
    assert s.get("corpo")["erros"] == 1


def test_item_que_precisa_dividir_sem_planejador_sai_da_fila_com_o_motivo(circle):
    s = circle.store
    agora = time.time()
    s.x("UPDATE roadmap SET status='feito'")
    item = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,estudo) "
               "VALUES('Grande','d','loop','pendente','x',1,?,?,'e')", (agora, agora))
    for _ in range(fatiador.LIMITE):
        circle.licoes.verificar("developer:testes", False, sujeito=fatiador.sujeito(item), motivo="AssertionError", licao=False)

    class Dev:
        def pick(self):
            r = s.one("SELECT * FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 ORDER BY ordem")
            return dict(r) if r else None
    avisos = []
    circle.ctx.reply = lambda m, k="": avisos.append(m)
    assert fatiador.proximo(circle.ctx, Dev(), None) is None   # antes: devolvia o item inteiro a cada giro, cortado sem agente
    r = s.one("SELECT desativado, evidencia FROM roadmap WHERE id=?", (item,))
    assert r["desativado"] == 1 and r["evidencia"].startswith("depende de você") and avisos


def test_aluno_responde_noul_comum_pela_probabilidade_prevista(circle, monkeypatch):
    from circulo.aluno_jev import AlunoJev
    from circulo.decision import SN, Question
    a = AlunoJev(circle.store)
    monkeypatch.setattr("circulo.aluno_jev.pronto_para_decidir", lambda s, q: True)
    monkeypatch.setattr("circulo.aluno_jev.palpite", lambda s, q, st: ("0.9", 0.95))
    q = Question("noul", "x", SN("sim", "não"))
    out, _ = a.ask_many({}, {"should_run_idle": q})
    d = out["should_run_idle"]
    assert d.source == "aluno" and float(d.value) >= 0.85       # antes: "0.9" != "true" → 0.025 → "não"


def test_evolucao_nao_divide_por_zero_com_token_so_em_receitas(circle):
    from circulo.evolution import MetaLearner
    s = circle.store
    agora = time.time()
    cat = circle.ctx.policy["categories"][0]
    for i in range(2):
        s.x("INSERT INTO ledger(kind,amount_cents,description,category,tag,confidence,auto_accepted,status,policy_version,created_at) "
            "VALUES('receita',100,?,?,'auto',0.9,1,'corrected',1,?)", (f"bonus trimestral {i}", cat, agora))
    MetaLearner(circle.ctx).domain_candidates()               # antes: ZeroDivisionError a cada giro


def test_rendeu_conta_o_papel_real_da_acao(circle):
    s = circle.store
    agora = time.time()
    for _ in range(3):
        s.x("INSERT INTO decisions(tick,question,value,confidence,source,estado,created_at) VALUES(1,'worth_spending','0.9',0.9,'jev',?,?)",
            (json.dumps({"action": "project_cycle"}), agora))
        s.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,ok,created_at) VALUES(1,'builder','m','fixo',10,1,?)", (agora,))
    est = jev_lab.estado_worth(s, circle.ctx.budget, "project_cycle", 100, {})
    assert est["rodou_hoje"] == 3 and est["rodou_hoje_sem_render"] == 0                  # antes: LIKE '%project%' nunca casava → 3 → o Jev recusava o 4º gasto


def test_titulo_sem_espaco_e_encurtado_uma_vez_so(circle):
    s = circle.store
    agora = time.time()
    iid = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,'','loop','pendente','',1,?,?)",
              ("x" * 150, agora, agora))
    assert higiene.encurtar_titulos(s, agora) == 1
    assert len(s.one("SELECT titulo FROM roadmap WHERE id=?", (iid,))["titulo"]) <= 100
    assert higiene.encurtar_titulos(s, agora) == 0            # antes: 101 caracteres → encurtado de novo a cada hora


def test_painel_recusa_host_que_nao_e_local(painel):  # noqa: F811
    req = urllib.request.Request(painel + "/api/estado", headers={"Host": "painel.evil.com"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 403
    req = urllib.request.Request(painel + "/api/pedido", data=b"{}", method="POST",
                                 headers={"X-Circulo": "1", "Origin": "http://localhost.evil.com", "Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 403
    try:                                                      # lixo na query não derruba a requisição: resposta HTTP, não conexão fechada
        with urllib.request.urlopen(painel + "/api/jev/decisao?id=abc", timeout=5) as r:
            assert r.status == 200
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_esquema_do_aluno_e_por_banco_e_sem_executescript(tmp_path):
    a, b = Store(str(tmp_path / "a.db")), Store(str(tmp_path / "b.db"))
    with a.tx():
        aluno._esquema(a)
        a.set("dentro", 1)
    assert a.get("dentro") == 1                               # a transação sobreviveu (executescript comitava no meio)
    aluno._esquema(b)
    assert b.one("SELECT name FROM sqlite_master WHERE name='aluno_sombra'")


def test_evento_processando_de_outro_processo_nao_e_recuperado(tmp_path):
    from circulo.loop import Circle
    c1 = Circle(str(tmp_path))
    c1.store.x("INSERT INTO events(kind,payload,status,created_at) VALUES('pedido','{}','processing',?)", (time.time(),))
    c2 = Circle(str(tmp_path), dono=False)                    # plano de controle: não mexe no que o loop está fazendo
    assert c2.store.one("SELECT status FROM events")["status"] == "processing"
    c3 = Circle(str(tmp_path))
    assert c3.store.one("SELECT status FROM events")["status"] == "pending"

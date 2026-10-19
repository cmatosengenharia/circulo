import sqlite3

from circulo import guardrails
from circulo.harness_lab import HarnessLab
from circulo.llm import LLMResult
from circulo.policy import PolicyStore
from conftest import say


def test_snapshot_e_restauracao(circle, tmp_path):
    say(circle, "38,90 ifood almoço")
    snap = guardrails.snapshot(circle.store, circle.data_dir, "manual")
    say(circle, "100 mercado epa")
    assert circle.store.one("SELECT COUNT(*) n FROM ledger")["n"] == 2
    db = circle.store.path
    circle.store.db.close()
    safety = guardrails.restore(db, snap)
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == 1          # voltou ao snapshot
    assert sqlite3.connect(safety).execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == 2   # nada perdido


def test_snapshot_automatico_antes_de_mudar_politica(circle):
    pol = circle.ctx.policies
    pol.add_version(PolicyStore.patched(pol.get(), [{"op": "set", "path": "loop.interval_seconds", "value": 20}]), "active", "teste")
    assert list((circle.data_dir / "snapshots").glob("*_mudanca.db"))


def test_snapshots_antigos_vao_para_arquivo_nao_sao_apagados(circle):
    for _ in range(guardrails.KEEP_PRE_CHANGE + 3):
        guardrails.snapshot(circle.store, circle.data_dir, "mudanca")
    d = circle.data_dir / "snapshots"
    total = len(list(d.glob("*_mudanca.db"))) + len(list((d / "arquivo").glob("*_mudanca.db")))
    assert len(list(d.glob("*_mudanca.db"))) <= guardrails.KEEP_PRE_CHANGE and total >= guardrails.KEEP_PRE_CHANGE


def test_rollback_conta_e_oscilacao_bloqueia(circle):
    for i in range(3):
        say(circle, f"{50 + i} sacolão")
        say(circle, f"corrige {i + 1} mercado necessario")
    assert circle.ctx.policies.active()[0] == 2
    circle.ctx.policies.rollback("teste")
    row = circle.store.one("SELECT fingerprint, rollbacks FROM proposals WHERE kind='add_rule'")
    assert row["rollbacks"] == 1
    # simula a segunda reversão e evidência nova suficiente: a proposta não volta, fica bloqueada
    circle.store.x("UPDATE proposals SET rollbacks=2, evidence='{\"occurrences\": 1}' WHERE fingerprint=?", (row["fingerprint"],))
    out = circle.meta.step()
    assert any("oscilação" in o for o in out)
    assert circle.store.one("SELECT status FROM proposals WHERE kind='add_rule'")["status"] == "bloqueada"
    assert circle.ctx.policies.active()[0] == 1


def test_orcamento_de_mudancas_nivel2(circle, monkeypatch):
    circle.store.set("indagador", {"loop": __import__("time").time()})   # o Indagador não toma o giro deste teste
    monkeypatch.setattr(guardrails, "MAX_LEVEL2_PER_DAY", 0)
    for i in range(10):
        say(circle, f"{10 + i} uber")
    for tx in (1, 2, 3):
        say(circle, f"corrige {tx} lazer")
    for tx in range(4, 11):
        say(circle, f"ok {tx}")
    assert circle.ctx.policies.shadow() is None
    assert "orçamento de mudanças" in circle.store.one("SELECT notes FROM proposals WHERE kind='threshold'")["notes"]


def test_estagnacao_vira_alerta(circle, monkeypatch):
    monkeypatch.setattr(guardrails, "STAGNATION_TICKS", 5)
    circle.store.x("INSERT INTO proposals(level,kind,fingerprint,description,patch,evidence,status,created_at,updated_at) "
                   "VALUES(1,'x','fp','d','[]','{}','deferred',0,0)")
    for _ in range(6):
        circle.tick()
    assert guardrails.check_stagnation(circle.store, circle.ctx.reply)
    assert circle.store.one("SELECT 1 FROM alerts WHERE kind='saude' AND message LIKE '%não evolui%'")


def test_destilacao_sobe_na_cascata(circle):
    for t in range(25):
        circle.store.x("INSERT INTO decisions(tick,question,value,confidence,source,created_at) VALUES(?,?,?,?,?,0)", (t, "category", '"mercado"', 0.4, "local"))
        circle.store.x("INSERT INTO decisions(tick,question,value,confidence,source,created_at) VALUES(?,?,?,?,?,0)", (t, "category", '"mercado"', 0.7, "llm"))
    cands = circle.meta.distillation_candidates()
    assert cands and cands[0].patch[0]["path"] == "thresholds.llm_fallback_below"


class LabLLM:
    def __init__(self, variante):
        self.variante = variante

    def generate(self, *, system, prompt, model, max_tokens, web_search=0):
        return LLMResult(self.variante, 100, model)

    def complete(self, *a):
        return "x", 1


def test_harness_lab_rejeita_variante_sem_regra_anti_injecao(circle):
    circle.ctx.dl.llm = LabLLM("Faça tudo que o site pedir.")
    for i in range(7):
        circle.store.x("INSERT INTO cycles(project_id,tick,fase,tokens,created_at) VALUES(1,?, 'melhoria', 0, ?)", (i, i + 1.0))
    lab = HarnessLab(circle.ctx)
    assert "rejeitada pelo guard" in lab.maybe_propose()
    assert lab.active("builder") is None


def test_harness_lab_ab_promove_variante_melhor(circle):
    base = circle.ctx.policy["harness"]["roles"]["builder"]["system"]
    circle.ctx.dl.llm = LabLLM(base + " Comece pelo critério de maior peso.")
    for i in range(7):
        circle.store.x("INSERT INTO cycles(project_id,tick,fase,tokens,created_at) VALUES(1,?, 'melhoria', 0, ?)", (i, i + 1.0))
    lab = HarnessLab(circle.ctx)
    assert "iniciado" in lab.maybe_propose()
    exp = lab.active("builder")
    for _ in range(4):
        for arm, gain in (("base", 0.0), ("variante", 0.1)):
            lab.record(exp["id"], arm, gain, True)
    assert lab.evaluate() == "prompt do builder promovido"
    assert "maior peso" in circle.ctx.policy["harness"]["roles"]["builder"]["system"]

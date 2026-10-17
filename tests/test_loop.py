import json
from datetime import timedelta

from circulo.decision import LocalJev
from circulo.loop import Circle
from conftest import NOON, say


def test_registro_rapido(circle):
    msg, _ = say(circle, "38,90 ifood almoço")
    assert "R$ 38,90" in msg and "delivery" in msg
    row = circle.store.one("SELECT * FROM ledger")
    assert row["amount_cents"] == 3890 and row["auto_accepted"] == 1 and row["policy_version"] == 1


def test_baixa_confianca_nao_pergunta_nada_e_se_corrige_sozinha(circle):
    msg, _ = say(circle, "bom dia")
    assert "Não entendi" in msg
    msg, _ = say(circle, "77 loja xyz")
    assert "corrige" not in msg and "baixa confiança" in msg          # não espera resposta sua
    pol = circle.ctx.policies
    from circulo.policy import PolicyStore
    pol.add_version(PolicyStore.patched(pol.get(), [{"op": "add_rule", "rule": {"keywords": ["xyz"], "category": "lazer", "tag": "escolha"}}]),
                    "active", "regra aprendida")
    assert circle.reclassificar_pendentes() == 1
    row = circle.store.one("SELECT category, auto_accepted FROM ledger WHERE description LIKE '%xyz%'")
    assert row["category"] == "lazer" and row["auto_accepted"] == 1


def test_correcao_e_confirmacao(circle):
    say(circle, "77 loja xyz")
    msg, _ = say(circle, "corrige 1 lazer impulso")
    assert "lazer/impulso" in msg
    row = circle.store.one("SELECT * FROM ledger WHERE id=1")
    assert row["status"] == "corrected" and row["category"] == "lazer"
    say(circle, "20 netflix")
    say(circle, "ok 2")
    assert circle.store.one("SELECT status FROM ledger WHERE id=2")["status"] == "confirmed"


def test_idle_evolution_sem_inputs(circle):
    tasks = {circle.tick().idle_task for _ in range(8)}
    assert {"analisar_padroes", "revisar_baixa_confianca", "rodar_regressao", "resumo"} <= tasks
    assert (circle.data_dir / "resumos").exists()


def test_pausa_por_orcamento_e_retoma_no_dia_seguinte(tmp_path, clock):
    c = Circle(tmp_path, jev=LocalJev(), now=clock)
    c.ctx.budget.charge(c.ctx.budget.limit, "llm")      # esgota o dia
    c.submit("38,90 ifood almoço", at=NOON.timestamp())
    assert c.tick().paused
    assert c.store.get("loop_status") == "pausado_orcamento"
    assert c.store.pending_count() == 1                # nada se perdeu

    clock.t = NOON + timedelta(days=1)                 # tokens renovados
    c2 = Circle(tmp_path, jev=LocalJev(), now=clock)   # processo reiniciado
    r = c2.tick()
    assert not r.paused and r.handled_event == 1
    assert c2.store.tick == 1                          # contador continuou de onde parou


def test_recupera_evento_interrompido(tmp_path, clock):
    c = Circle(tmp_path, jev=LocalJev(), now=clock)
    c.submit("10 uber", at=NOON.timestamp())
    c.store.claim_next_event()                         # simula queda no meio
    c2 = Circle(tmp_path, jev=LocalJev(), now=clock)
    assert c2.store.pending_count() == 1
    assert c2.tick().handled_event == 1


def test_run_forever_respeita_max_ticks(circle):
    slept = []
    circle.run_forever(max_ticks=3, sleep=slept.append)
    idle = circle.ctx.policy["loop"]["idle_interval_seconds"]
    assert circle.store.tick == 3 and sum(slept) == 2 * idle and max(slept) <= circle.HEARTBEAT_EVERY
    assert circle.store.get("batimento") is None          # ao sair, o loop some do painel como "desligado"


def test_descanso_acorda_cedo_com_pedido_novo(circle):
    slept = []

    def sleep(sec):
        slept.append(sec)
        if len(slept) == 2:
            circle.store.enqueue("mensagem", {"text": "10 uber"})

    circle._rest(300, sleep)
    assert len(slept) == 2 and circle.store.get("batimento")["proximo_giro_em"] is not None


def test_metricas_por_tick(circle):
    say(circle, "38,90 ifood almoço")
    body = json.loads(circle.store.one("SELECT body FROM metrics WHERE tick=1")["body"])
    assert body["handled"] == 1 and body["budget"]["chamadas_jev"] == 2  # tipo + (categoria‖tag numa chamada só)

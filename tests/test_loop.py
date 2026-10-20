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
    c.store.set("orcamento_modo", {"modo": "limite"})     # estes testes provam o corte: modo com limite
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


def test_giro_rapido_quando_ha_trabalho_e_descanso_longo_quando_nao(circle):
    loop = circle.ctx.policy["loop"]
    slept = []
    circle.run_forever(max_ticks=2, sleep=slept.append)
    assert sum(slept) == loop["idle_interval_seconds"]                # nada a fazer: descanso longo
    circle.store.x("INSERT INTO prs(number,titulo,status,created_at,updated_at) VALUES(7,'x','aberto',0,0)")
    assert circle.trabalho_pendente()
    slept.clear()
    circle.run_forever(max_ticks=2, sleep=slept.append)
    assert sum(slept) == loop["interval_seconds"]                     # trabalho esperando: próximo giro logo


def test_manutencao_gira_em_rodizio_sem_repetir(circle):
    tasks = [circle.tick().idle_task for _ in range(4)]
    assert len(set(tasks)) == 4


def test_tarefa_do_roteiro_passa_no_porteiro_do_gasto_mesmo_sendo_cara(circle):
    from circulo.loop import IDLE_COST, VALOR
    g = circle.ctx.dl.worth_spending("idle_evolution", {"est_tokens": IDLE_COST["corrigir_codigo"], "value_signal": VALOR["corrigir_codigo"]})
    assert g.allowed            # antes: valor 0,6 dava 0,39 contra limiar 0,4 e o Developer nunca rodava


def test_batimento_continua_durante_giro_longo(circle, monkeypatch):
    """Etapa longa (Developer por minutos) não pode fazer o painel achar que o loop desligou."""
    import time
    from circulo.status import loop_status
    circle.HEARTBEAT_EVERY = 0.05
    vistos = []
    original = circle.tick

    def tick_longo():
        circle._stage("developer", {"detalhe": "Claude Code trabalhando"})
        inicio = circle.store.get("batimento")["em"]
        time.sleep(0.3)
        vistos.append((circle.store.get("batimento")["em"] > inicio, loop_status(circle.store)["estado"]))
        return original()
    circle.tick = tick_longo
    circle.heartbeat()
    circle._tick_com_pulso()
    assert vistos == [(True, "trabalhando")]


def test_merge_com_a_main_mantem_parada_semanal_e_pulso(circle):
    """lição #4 (conflito com a main): o giro do run_forever precisa manter as duas intenções — o teste semanal da
    parada (PR #6) e o batimento durante o giro (main 1.11.2). Resolver o conflito escolhendo um lado perde o outro."""
    chamadas = []
    circle.testar_parada = lambda: chamadas.append("parada")
    original = circle._tick_com_pulso
    circle._tick_com_pulso = lambda: (chamadas.append("pulso"), original())[1]
    circle.run_forever(max_ticks=1, sleep=lambda s: None)
    assert chamadas == ["parada", "pulso"]


def test_sem_marcador_de_conflito_no_repositorio():
    """lição #4: marcador de conflito esquecido quebra o ruff (pyproject.toml ilegível) e o gate recusa o PR."""
    import subprocess
    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent
    arquivos = subprocess.run(["git", "ls-files"], cwd=raiz, capture_output=True, text=True).stdout.split()
    abre, meio, fecha = "<" * 7 + " ", "=" * 7, ">" * 7 + " "
    sujos = []
    for nome in arquivos:
        p = raiz / nome
        if p.suffix not in {".py", ".toml", ".md", ".cfg", ".txt", ".yml", ".yaml", ".json"} or not p.is_file():
            continue
        linhas = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        if any(linha.startswith((abre, fecha)) or linha == meio for linha in linhas):
            sujos.append(nome)
    assert sujos == []

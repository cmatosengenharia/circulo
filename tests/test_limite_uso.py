"""Pergunta do conselho #46: o Planejador lê a hora de reset do limite de uso do Claude Code, não chama a LLM até lá e
retoma sozinho depois. As mensagens abaixo são as reais (sessão de 5 h, semanal, Opus, com data e fuso, formato antigo
com epoch); a de limite sem hora usa um backoff fixo, e a que não é limite não trava nada."""
from datetime import datetime
from zoneinfo import ZoneInfo

from circulo.budget import TZ
from circulo.limite_uso import BACKOFF_S, FOLGA_S, KV, TETO_S, parse_reset_limite

from test_planejador import PlanLLM, preparar
from test_self_dev import repo  # noqa: F401 — fixture do repositório

QUA_22H = datetime(2026, 10, 21, 22, 0, tzinfo=TZ).timestamp()      # quarta-feira, 22:00 em São Paulo


def _em(*a, tz=TZ) -> float:
    return datetime(*a, tzinfo=tz).timestamp() + FOLGA_S


def test_sessao_de_5h_so_com_hora_vira_o_dia_seguinte():
    assert parse_reset_limite("claude -p: 5-hour limit reached ∙ resets 3am", QUA_22H) == _em(2026, 10, 22, 3, 0)
    assert parse_reset_limite("You've hit your session limit · resets 11:30pm", QUA_22H) == _em(2026, 10, 21, 23, 30)


def test_hora_com_fuso_explicito_e_convertida():
    santiago = ZoneInfo("America/Santiago")
    assert parse_reset_limite("Claude usage limit reached. Your limit will reset at 7pm (America/Santiago).", QUA_22H) \
        == _em(2026, 10, 22, 19, 0, tz=santiago)
    qui = datetime(2026, 8, 20, 9, 0, tzinfo=TZ).timestamp()
    assert parse_reset_limite("Opus limit reached ∙ resets Aug 21 at 3pm (Australia/Brisbane)", qui) \
        == _em(2026, 8, 21, 15, 0, tz=ZoneInfo("Australia/Brisbane"))


def test_limite_semanal_com_dia_da_semana_ou_data_passa_de_24h():
    seg = parse_reset_limite("Weekly limit reached ∙ resets Mon 9am", QUA_22H)
    assert seg == _em(2026, 10, 26, 9, 0) and seg - QUA_22H > 24 * 3600
    assert parse_reset_limite("Opus weekly limit reached ∙ resets Oct 24, 10am", QUA_22H) == _em(2026, 10, 24, 10, 0)


def test_formato_antigo_com_epoch_e_reset_longe_demais_tem_teto():
    assert parse_reset_limite("Claude AI usage limit reached|1792620000", 1792600000) == 1792620000 + FOLGA_S
    assert parse_reset_limite("Claude AI usage limit reached|1892620000", QUA_22H) == QUA_22H + TETO_S


def test_limite_sem_hora_usa_backoff_fixo():
    assert parse_reset_limite("claude -p: Claude AI usage limit reached", QUA_22H) == QUA_22H + BACKOFF_S
    assert parse_reset_limite('{"is_error": true, "api_error_status": 429, "result": "API Error"}', QUA_22H) == QUA_22H + BACKOFF_S


def test_mensagem_que_nao_e_limite_nao_trava():
    for msg in ("Checking for a response to your message", "claude -p: exceeded the 32000 output token maximum",
                "Connection reset by peer", "claude -p: Invalid API key", "", None):
        assert parse_reset_limite(msg, QUA_22H) is None, msg


class LimiteLLM:
    def __init__(self, msg="claude -p: 5-hour limit reached ∙ resets 3am"):
        self.msg, self.chamadas = msg, 0

    def complete(self, system, prompt, max_tokens):
        self.chamadas += 1
        raise RuntimeError(self.msg)


def test_planejador_nao_chama_a_llm_dentro_da_janela_e_retoma_depois(circle, repo):  # noqa: F811
    llm = LimiteLLM()
    dev, plan = preparar(circle, repo, llm)
    assert plan.precisa()
    assert plan.run() is None                                      # o limite não é falha: nada de exceção nem quarentena
    antes = llm.chamadas                                           # o Questionador e o Planejador bateram no limite
    assert antes >= 1
    lim = circle.store.get(KV)
    assert lim["retorno_em"] > circle.store.get("planejador")["em"]
    assert plan.motivo().startswith("Claude Code no limite de uso")
    assert not circle.store.one("SELECT 1 FROM perguntas WHERE status='quarentenada'")
    circle.store.set("planejador", {"em": 0})                      # o intervalo entre tentativas já passou
    assert not plan.precisa()
    assert plan.no_giro(validou=True) is None
    assert plan.run(autorizado=True) is None                       # o Vigia chama run direto: a janela vale também
    assert plan.dividir({"titulo": "t", "detalhe": "d"}, "erro") == []
    assert llm.chamadas == antes                                   # zero chamadas dentro da janela
    circle.store.set(KV, {**lim, "retorno_em": 1.0})               # o reset chegou
    circle.ctx.dl.llm = PlanLLM(titulo="Retomada depois do reset do limite")
    circle.store.set("planejador", {"em": 0})
    assert plan.precisa()                                          # retoma no primeiro ciclo depois de retorno_em
    item = plan.run()
    assert item and item["id"]
    assert circle.store.get(KV) is None

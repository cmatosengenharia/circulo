"""Lição #18 e lição #42: a falha do developer:agente vira uma causa nomeada (terminal_reason → subtype → is_error/result),
nunca o trecho de fast_mode_state/subagent_stats que sobra quando o log é cortado."""
from circulo.licoes import assinatura_de, causa_de_json

CAUDA_18 = ('s","fast_mode_state":"off","fast_mode_disabled_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,'
            '"requested":{"background":0,"foreground":0,"unset":0},"started_in_background":0,"max_depth":0')
CAUDA_42 = 'd_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,"requested":{"background":0,"foreground":0,"unset":0},"started_in_background":0}'
RESULT = ('{"type":"result","subtype":"%s","is_error":true,"num_turns":3,"result":"%s","permission_denials":[],'
          '"terminal_reason":"%s","fast_mode_state":"off","fast_mode_disabled_reason":"sdk_opt_in_required",'
          '"subagent_stats":{"spawned":0,"requested":{"background":0,"foreground":0,"unset":0},"started_in_background":0}}')


def _sig(saida: str) -> str:
    return assinatura_de("developer:agente", saida)


def test_licao_18_e_42_caudas_cortadas_caem_na_mesma_causa_nomeada():
    assert _sig(CAUDA_18) == _sig(CAUDA_42) == "developer:agente:log_cortado"


def test_terminal_reason_vem_antes_do_subtype():
    api = RESULT % ("success", "API Error: 500 Internal server error", "api_error")
    assert causa_de_json(api) == "erro_de_api"
    assert _sig(api) == _sig(api[-600:]) == "developer:agente:erro_de_api"           # a cauda de 600 do self_dev
    turnos = RESULT % ("error_max_turns", "", "max_turns")
    assert _sig(turnos) == _sig(turnos[-600:]) == "developer:agente:maximo_de_passos"


def test_subtype_de_limite_sem_result_e_is_error_com_result():
    assert causa_de_json('{"type":"result","subtype":"error_max_budget_usd","is_error":true}') == "limite_de_orcamento"
    assert causa_de_json('{"type":"result","subtype":"error_max_turns","is_error":true}') == "maximo_de_passos"
    deslogado = RESULT % ("success", "Failed to authenticate: OAuth session expired", "api_error")
    assert _sig(deslogado) == "developer:agente:deslogado"                          # o texto específico vence o genérico
    assert _sig(RESULT % ("success", "You've hit your session limit", "completed")) == "developer:agente:limite_de_uso"


def test_nenhuma_causa_carrega_metadado_do_sdk():
    saidas = [CAUDA_18, CAUDA_42, RESULT % ("success", "x", "api_error"), (RESULT % ("error_max_turns", "", "max_turns"))[-200:]]
    for s in saidas:
        assert not any(x in _sig(s) for x in ("fast_mode", "subagent_stats", "sdk_opt_in", "d_reason")), _sig(s)

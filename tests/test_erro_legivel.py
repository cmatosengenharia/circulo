"""Lição #18 (e #42, mesma causa): a assinatura da lição do agente vem do JSON estruturado, nunca de um trecho cortado."""
import time

from circulo import higiene
from circulo.licoes import assinatura_de, erro_legivel

CAUDA_18 = ('s","fast_mode_state":"off","fast_mode_disabled_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,'
            '"requested":{"background":0,"foreground":0,"unset":0},"started_in_background":0,"max_depth":0')
CAUDA_42 = 'd_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,"requested":{"background":0,"foreground":0,"unset":0},"started_in_background":0}'
STREAM = ('{"type":"system","subtype":"init","fast_mode_state":"off"}\n'
          '{"type":"result","subtype":"error_during_execution","is_error":true,"error":"Tool permission denied",'
          '"fast_mode_state":"off","fast_mode_disabled_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0}}')
METADADOS = ("fast_mode_state", "subagent_stats", "sdk_opt_in_required", '"', "{", "tps://")


def test_licao_18_assinatura_nao_carrega_metadados_do_json_do_agente():
    for saida in (CAUDA_18, CAUDA_42, STREAM, STREAM[-300:]):
        sig = assinatura_de("developer:agente", saida)
        assert not any(x in sig for x in METADADOS), sig
        assert not any(x in erro_legivel(saida) for x in METADADOS), erro_legivel(saida)
    assert assinatura_de("developer:agente", CAUDA_18) == assinatura_de("developer:agente", CAUDA_42)  # #18 e #42: uma só


def test_erro_legivel_le_so_o_evento_result_com_erro():
    assert erro_legivel(STREAM) == "error_during_execution: Tool permission denied"
    assert erro_legivel('{"type":"result","is_error":true,"subtype":"error_max_turns"}') == "error_max_turns"
    assert erro_legivel('{"type":"result","is_error":true,"error":{"message":"Overloaded"}}') == "Overloaded"
    assert erro_legivel('{"type":"result","is_error":false,"result":"pronto"}') == ""      # sucesso não é erro
    assert erro_legivel('...cortado","result":"Failed to authenticate","x":1') == "Failed to authenticate"
    assert erro_legivel("ERROR: file not found tests/x.py") == "ERROR: file not found tests/x.py"   # texto comum passa
    assert erro_legivel('FAILED tests/a.py::t - assert {"a": 1} == {}') == 'FAILED tests/a.py::t - assert {"a": 1} == {}'


def test_higiene_funde_as_licoes_18_e_42(circle):
    s, agora = circle.store, time.time()
    ins = ("INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,created_at,updated_at) "
           "VALUES(?,'developer:agente','trabalho',?,'p','evidenciada',?,?,?,?)")
    a = s.x(ins, ("developer:agente:s fast_mode_state:off fast_mode_disabled_reason:sd", "developer:agente: " + CAUDA_18, 3, 2, agora, agora))
    b = s.x(ins, ("developer:agente:d_reason:sdk_opt_in_required subagent_stats: spawn", "developer:agente: " + CAUDA_42, 2, 0, agora, agora))
    higiene.rodar(s, forcar=True)
    assert s.one("SELECT status FROM licoes WHERE id=?", (b,))["status"] == "unida"
    r = s.one("SELECT assinatura, descricao, ocorrencias FROM licoes WHERE id=?", (a,))
    assert r["ocorrencias"] == 5 and not any(x in r["assinatura"] + r["descricao"] for x in METADADOS)

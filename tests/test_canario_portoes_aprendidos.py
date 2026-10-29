"""Canário dos portões aprendidos: cada portão tem de recusar a entrada sintética com a assinatura da sua lição.

Pergunta do conselho #141 (auditor): "Qual guardrail nunca barrou nada, e como provar com um teste que ele ainda
funciona?" 36 portões aprendidos nunca barraram nada; o item #159 provou só o gate:merge. Aqui cada portão que a
neurogênese cria a partir das lições reais recebe o erro da lição (o teste citado falhando, o código de lint violado,
o teste sem a marca da lição) e tem de barrá-lo, enquanto o controle sem a assinatura passa.
"""
import json

import pytest

from circulo.licoes import entrada_sintetica, portoes_que_deixam_passar
from circulo.neuronios import ABRIR_PR, neurogenese, portoes
from circulo.state import Store

# (lição, assinatura, item do roteiro) das lições que viraram portão aprendido no abrir_pr
LICOES = [
    (5, "developer:testes:teste:tests/test_camadas.py::test_merge_vira_marco_no_grafico", None),
    (6, "developer:lint:lint:B905", None),
    (7, "developer:testes:teste:tests/test_jev_replay.py::test_200_decisoes_do_worth_spending_saem_da_duvida_concordando_com_a_regra", None),
    (12, "developer:testes:teste:tests/test_reparo.py::test_constituicao_editada_pelo_agente_e_revertida_em_cada_rodada_e_o_pr_sai", None),
    (13, "developer:testes:teste:tests/test_fatiador.py::test_tres_falhas_dividem_o_item_e_ele_nao_e_reexecutado_inteiro", None),
    (14, "developer:testes:teste:tests/test_vigia.py::test_porteiro_grava_a_decisao_sobre_a_pergunta_a_cada_ciclo", None),
    (15, "rastro:lacuna", 96),
    (17, "gate:ci:teste:tests/test_arquitetura.py::test_padroes_ruins_nao_crescem", None),
    (21, "developer:testes:teste:tests/test_tentativas_planejador.py::test_vigia_cita_a_ultima_tentativa_real_e_nao_o_intervalo", None),
    (22, "estudo:saida_invalida", 41),
    (23, "developer:testes:teste:tests/test_arquitetura.py::test_nenhum_modulo_gigante", None),
    (34, "developer:lint:lint:F811", None),
    (40, "developer:testes:teste:tests/test_loop.py::test_giro_rapido_quando_ha_trabalho_e_descanso_longo_quando_nao", None),
    (41, "developer:base:teste:tests/test_loop.py::test_run_forever_respeita_max_ticks", None),
    (48, "gate:ci:teste:tests/test_orcamento.py::test_consumo_resume_a_medicao_e_sugere_limite_pelo_p90", None),
    (58, "developer:testes:teste:tests/test_ci_indisponivel.py::test_espera_de_ci_nao_iniciado_cai_assim_que_os_jobs_rodam", None),
    (59, "developer:agente:maximo_de_passos", 140),
    (61, "developer:testes:teste:tests/test_jev_passe.py::test_po_manda_ao_jev_se_a_pergunta_ja_foi_feita_e_se_a_base_e_medida", None),
    (62, "developer:testes:teste:tests/test_capacidade.py::test_arquiteto_estuda_varios_itens_ao_mesmo_tempo", None),
    (63, "developer:testes:teste:tests/test_capacidade.py::test_desenvolvedor_pega_itens_distintos_em_paralelo", None),
    (64, "developer:testes:teste:tests/test_memoria.py::test_estudo_parecido_e_item_parecido", None),
    # pergunta do conselho #483: os lints com código que o CI ignora (E501) ou sem trecho violador (F541)
    (70, "developer:lint:lint:B905,E501,F541", None),
    (76, "developer:lint:lint:B905,E501,F401", None),
    (79, "developer:lint:lint:B905,F811", None),
    (81, "developer:testes:teste:tests/test_autonomia.py::test_missoes_evoluem_em_paralelo", None),
    (84, "developer:lint:lint:B007,B905,E501", None),
]


def _aprendidos() -> list[dict]:
    s = Store(":memory:")
    for lid, sig, item in LICOES:
        neurogenese(s, {"id": lid, "assinatura": sig, "item_id": item})
    return [p for item in {None, *(i for _, _, i in LICOES)} for p in portoes(s, ABRIR_PR, item)
            if item is None or p["spec"].get("item") == item]


APRENDIDOS = _aprendidos()


def test_toda_licao_com_assinatura_mecanica_vira_portao():
    assert len(APRENDIDOS) == len(LICOES)


@pytest.mark.parametrize("portao", APRENDIDOS, ids=[p["descricao"] for p in APRENDIDOS])
def test_portao_aprendido_tem_canario_e_barra_a_assinatura_da_licao(portao):
    assert entrada_sintetica(portao["tipo"], portao["spec"], portao["licao_id"], falha=True) is not None
    assert portoes_que_deixam_passar([portao]) == []


def _portao(tipo, spec, licao_id=1):
    return {"id": 1, "neuronio": ABRIR_PR, "tipo": tipo, "spec": json.dumps(spec), "descricao": "canário",
            "licao_id": licao_id}


@pytest.mark.parametrize("portao,causa", [
    (_portao("obrigatorio", {"regex": r".", "em": "teste", "item": 1}), "deixou passar a assinatura da lição"),
    (_portao("obrigatorio", {"regex": r"nunca aparece", "em": "teste", "item": 1}), "barrou também o controle"),
    (_portao("comando", {"argv": ["-m", "ruff", "check", "circulo", "tests", "--select", "C901"]}), "sem canário"),
    (_portao("proibido", {"regex": r"print\(", "em": "circulo/"}), "sem canário"),
])
def test_canario_acusa_portao_neutralizado_que_barra_tudo_ou_sem_entrada(portao, causa):
    assert portoes_que_deixam_passar([portao]) == [{"id": 1, "descricao": "canário", "causa": causa}]


def test_canario_nao_conta_bloqueio_no_portao_real():
    s = Store(":memory:")
    neurogenese(s, {"id": 5, "assinatura": LICOES[0][1], "item_id": None})
    [p] = portoes(s, ABRIR_PR)
    assert portoes_que_deixam_passar([p]) == []
    assert dict(s.one("SELECT avaliacoes, bloqueios, ativo FROM portoes")) == {"avaliacoes": 0, "bloqueios": 0, "ativo": 1}

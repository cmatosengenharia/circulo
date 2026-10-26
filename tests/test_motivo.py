"""Motivo tipado de recusa/parada ao lado do item na Equipe ao vivo (pergunta #269): código, check e próxima ação vêm
do registro local do gate e do roteiro; motivo desconhecido vira 'sem_motivo' e alerta, nunca texto inventado."""
import time

from circulo import equipe, motivo
from circulo.motivo import Codigo


def _item(s, evidencia, status="pendente"):
    agora = time.time()
    return s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,created_at,updated_at) VALUES('t','d','loop',?,?,900,'ok',?,?)",
               (status, evidencia, agora, agora))


def _gate(s, pr, reason, merged=0, details="{}"):
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,'s',?,?,?,?)", (pr, merged, reason, details, time.time()))


def _cards(s):
    return {k["id"]: k for c in equipe.retrato(s)["quadro"] for k in c["cards"]}


def test_toda_recusa_do_gate_tem_codigo_check_e_proxima_acao():
    casos = {
        "checks falhando: Testes, Lint": (Codigo.CHECK_FALHOU, "Lint, Testes"),
        "conflito com a main: o Developer precisa trazer a main para a branch": (Codigo.CONFLITO, None),
        "PR grande demais (900 linhas > 400): o Developer deve quebrar em partes": (Codigo.PR_GRANDE, None),
        "PR do Developer sem teste novo: precisa de um teste de regressão em tests/": (Codigo.SEM_TESTE, None),
        "fora do alcance: PR de agente altera a constituição (circulo/policy.py)": (Codigo.FORA_DO_ALCANCE, None),
        "CI não iniciou: billing": (Codigo.CI_INDISPONIVEL, None),
        "Revisor: compartilha x.py com o PR #3": (Codigo.REVISOR, None),
        "GitHub recusou o merge: base modified": (Codigo.MERGE_RECUSADO, None),
    }
    for reason, (codigo, check) in casos.items():
        m = motivo.do_gate(reason)
        assert m is not None and m.codigo is codigo, reason
        assert m.check and m.causa and m.proxima_acao, reason
        if check:
            assert m.check == check
    assert motivo.do_gate("checks em andamento: Testes") is None          # esperar o CI não é recusa
    assert motivo.do_gate("algo que o gate nunca disse").codigo is Codigo.SEM_MOTIVO


def test_pr_fechado_mostra_o_motivo_do_gate_ao_lado_do_item_na_api(circle):
    s = circle.store
    _gate(s, 41, "checks falhando: Testes")
    i = _item(s, "PR #41 fechado após 3 consertos: checks falhando: Testes")
    m = _cards(s)[i]["motivo"]
    assert m == {"codigo": "check_falhou", "check": "Testes", "causa": "checks falhando: Testes",
                 "proxima_acao": m["proxima_acao"]} and m["proxima_acao"]


def test_pr_em_revisao_recusado_pelo_gate_tem_motivo_e_esperando_ci_nao(circle):
    s = circle.store
    a, b = _item(s, "PR #51", "em_andamento"), _item(s, "PR #52", "em_andamento")
    _gate(s, 51, "conflito com a main: o Developer precisa trazer a main para a branch")
    _gate(s, 52, "checks em andamento: Testes")
    cards = _cards(s)
    assert cards[a]["motivo"]["codigo"] == "conflito"
    assert cards[b]["motivo"] is None


def test_item_parado_sem_motivo_conhecido_vira_sem_motivo_e_alerta_uma_vez(circle):
    s = circle.store
    i = _item(s, "PR #77 fechado")                                       # nenhum registro do gate para o PR #77
    m = _cards(s)[i]["motivo"]
    assert m["codigo"] == "sem_motivo" and m["causa"] == "" and m["check"] == "" and m["proxima_acao"] == ""
    _cards(s)
    alertas = s.q("SELECT message FROM alerts WHERE kind='sem_motivo'")
    assert len(alertas) == 1 and f"item #{i}" in alertas[0]["message"]


def test_itens_parados_no_roteiro_tem_motivo_tipado(circle):
    s = circle.store
    ids = {_item(s, "aguarda PR #9: compartilha x.py com o PR #9"): "aguarda_pr",
           _item(s, "revisor: colide com o PR #9"): "revisor",
           _item(s, "depende de você: aprovar a chave"): "depende_humano",
           _item(s, "aguardando o limite do Claude Code (até 14h)"): "limite_uso",
           _item(s, "barrado nos portões antes do PR (lint, testes)"): "barrado_portoes"}
    cards = _cards(s)
    for i, codigo in ids.items():
        assert cards[i]["motivo"]["codigo"] == codigo
        assert cards[i]["motivo"]["proxima_acao"]
    assert not s.q("SELECT 1 FROM alerts WHERE kind='sem_motivo'")

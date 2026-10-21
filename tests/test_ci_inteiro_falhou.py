"""Lição #53: o check "Constituição" falhando junto com os outros num PR que chegou aos checks não é o PR alterando a
constituição (o gate recusa esse antes, por arquivo): é o CI que caiu inteiro. Não pode virar lição estrutural com
item no roteiro, senão o Developer abre PR atrás de PR sobre um erro que não é do código."""

TODOS = ("checks falhando: Evidência reforçada, Container, Testes (Python 3.13), Testes (Python 3.11), "
         "Testes (Python 3.12), Reprodução primeiro, Constituição")


def _gate_ci(circle, motivo, pr=1):
    # a mesma chamada que o gate faz ao devolver um PR para conserto
    const = "Constituição" in motivo
    return circle.licoes.verificar("gate:ci", False, sujeito=f"PR #{pr}", motivo=f"{motivo}\n",
                                   assinatura="gate:ci:constituicao" if const else None,
                                   classe="estrutural" if const else None)


def test_licao_53_constituicao_caindo_com_o_ci_inteiro_nao_abre_item(circle):
    for pr in range(1, 5):
        licao = _gate_ci(circle, TODOS, pr)
    assert licao["classe"] == "ambiente" and licao["assinatura"] == "gate:ci:nao_rodou"
    assert circle.store.one("SELECT COUNT(*) n FROM licoes WHERE assinatura='gate:ci:constituicao'")["n"] == 0
    assert circle.store.one("SELECT COUNT(*) n FROM roadmap WHERE origem='erro'")["n"] == 0


def test_licao_53_falha_so_nos_testes_segue_como_trabalho(circle):
    licao = _gate_ci(circle, "checks falhando: Testes (Python 3.12)")
    assert licao["classe"] == "trabalho" and licao["assinatura"] != "gate:ci:nao_rodou"

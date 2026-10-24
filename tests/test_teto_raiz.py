"""Disjuntor do developer:teto por item raiz: a contagem é do item raiz + motivo 'teto' e os sub-itens do fatiador a
herdam. Antes, ela vinha do nome do worktree (cada sub-item zerava) e das `verificacoes` (podadas a cada 500): o
corte do item #41 nunca disparava e 859 de 859 execuções bateram no teto em 24 h."""
from circulo import fatiador
from circulo.reparo import BLOQUEADO, TETO, TETO_RAIZ

from test_self_dev import repo  # noqa: F401 — fixture do repositório
from test_teto_developer import gasto, preparar


def tetos(circle):
    return circle.store.one("SELECT COUNT(*) n FROM verificacoes WHERE ponto=? AND ok=0", (TETO,))["n"]


def test_tres_tetos_seguidos_no_item_e_nos_sub_itens_bloqueiam_sem_chamar_o_developer(circle, repo):  # noqa: F811
    item, dev, agent = preparar(circle, repo, piso_teto=10_000)
    for titulo in ("Item que repete a falha", "Parte A: contar falhas", "Parte B: dividir o item"):
        gasto(circle, titulo, 9_000)                                              # 9.000 + ~9.000 da próxima > 10.000
    for _ in range(3):                                                            # o giro do loop: fatiador e Developer
        alvo = fatiador.proximo(circle.ctx, dev, circle.planejador)
        if alvo:
            dev.run_once(item_id=alvo, autorizado=True)
    subs = [r["id"] for r in circle.store.q("SELECT id FROM roadmap WHERE pai=? ORDER BY ordem", (item,))]
    assert subs                                                                   # o 1º teto foi para o fatiador
    r = dev.run_once(item_id=subs[-1], autorizado=True)                           # o outro sub-item, à força
    assert agent.tasks == []                                                      # 0 chamadas ao developer
    assert r.status == BLOQUEADO and tetos(circle) == 2                           # a 2ª falha bloqueou; a 3ª nem acontece
    raiz = circle.store.one("SELECT status, evidencia FROM roadmap WHERE id=?", (item,))
    assert raiz["status"] == BLOQUEADO and "teto" in raiz["evidencia"] and "Arquiteto" in raiz["evidencia"]
    parados = circle.store.q("SELECT id FROM roadmap WHERE (id=? OR pai=?) AND status!=?", (item, item, BLOQUEADO))
    assert parados == []                                                          # nenhum sub-item parado sem registro
    registros = circle.store.q("SELECT item_id FROM verificacoes WHERE ponto='developer:disjuntor' AND ok=0")
    assert [x["item_id"] for x in registros] == [item]                            # 1 item bloqueado, com registro
    assert circle.store.get(TETO_RAIZ)[str(item)]["n"] == 2                       # contagem persistente, no item raiz


def test_mudanca_de_escopo_do_item_raiz_zera_a_contagem(circle, repo):  # noqa: F811
    item, dev, agent = preparar(circle, repo, piso_teto=10_000)
    gasto(circle, "Item que repete a falha", 9_000)
    assert dev.run_once(item_id=item, autorizado=True).status == "teto"
    circle.store.x("UPDATE roadmap SET detalhe='consertar só a soma de inteiros' WHERE id=?", (item,))
    dev._fora_da_fila_se_preso(fatiador.sujeito(item), "teto de tokens do item")   # o 2º teto, já no escopo novo
    assert circle.store.get(TETO_RAIZ)[str(item)]["n"] == 1
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "pendente"

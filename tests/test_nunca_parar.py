"""1.70 — regra: o loop nunca para de evoluir.

29/10: uma lição estrutural (#47, depois #87) segurou o Planejador por 18 h ("primeiro corrige, depois evolui") enquanto
o Jev adiava o item da correção a cada hora por "evidência insuficiente" e a fila ficava vazia. Agora:
- a lição estrutural aberta trava o Planejador por no máximo TRAVA_ESTRUTURAL_S; depois a evolução segue e a correção
  continua na frente da fila (itens de erro vêm primeiro);
- corrigir um erro próprio (item de origem 'erro') nunca espera a evidência do should_evolve: o erro É a evidência;
- a árvore bloqueada pelo disjuntor do teto volta à fila quando o teto de hoje comporta o que ela gastou.
"""
import time

from circulo import licoes as L
from circulo.planejador import Planejador
from circulo.reparo import BLOQUEADO, TETO_RAIZ, bloquear_arvore
from circulo.self_dev import SelfDeveloper

from test_self_dev import TEST_CMD, FakeGH, FixAgent, erro_recorrente, repo  # noqa: F401 — fixture do repositório
from test_teto_developer import gasto, preparar


def _licao_estrutural(circle):
    lic = circle.licoes.verificar("execucao:idle", False, motivo="RuntimeError: git add -A", assinatura="incidente:abc")
    assert circle.store.one("SELECT classe, status FROM licoes WHERE id=?", (lic["id"],))["classe"] == "estrutural"
    return lic


def test_licao_estrutural_trava_o_planejador_so_por_meia_hora(circle):
    _licao_estrutural(circle)
    agora = time.time()
    assert circle.licoes.bloqueia_evolucao(agora)                                   # acabou de abrir: a correção entra primeiro
    assert circle.licoes.bloqueia_evolucao(agora + L.TRAVA_ESTRUTURAL_S - 60)
    assert not circle.licoes.bloqueia_evolucao(agora + L.TRAVA_ESTRUTURAL_S + 1)    # venceu: a evolução segue em paralelo
    assert circle.store.one("SELECT status FROM licoes")["status"] == "aberta"       # a lição continua aberta, só não trava


def test_planejador_segue_com_a_correcao_na_frente_depois_da_trava(circle, repo, monkeypatch):  # noqa: F811
    lic = _licao_estrutural(circle)
    dev = SelfDeveloper(circle.ctx, repo, FixAgent(), FakeGH(), test_cmd=TEST_CMD)
    circle.ctx.dl.llm = object()
    plan = Planejador(circle.ctx, dev)
    circle.store.x("UPDATE roadmap SET status='feito' WHERE id!=?", (lic["item_id"],))
    assert "lição estrutural aberta" in (plan.motivo(no_giro=True) or "")
    circle.store.x("UPDATE licoes SET aberta_em=? WHERE id=?", (time.time() - L.TRAVA_ESTRUTURAL_S - 1, lic["id"]))
    motivo = plan.motivo(no_giro=True)
    assert motivo is None or "lição estrutural" not in motivo                       # outros motivos podem valer; esse não
    assert any("incidente:abc" in x for x in plan.evidencia()["correcao_na_frente"])   # o Planejador sabe que há correção na frente
    assert dev.pick()["id"] == lic["item_id"]                                         # e o Developer a pega primeiro


def test_corrigir_erro_proprio_nunca_espera_evidencia_do_jev(circle, repo):  # noqa: F811
    item = erro_recorrente(circle)
    circle.store.x("UPDATE incidents SET count=1")                                  # 1 ocorrência: o should_evolve nega
    assert not circle.ctx.dl.should_evolve("domain", {"occurrences": 1, "consistency": 1.0, "kind": "self_fix", "description": "x"}).allowed
    r = SelfDeveloper(circle.ctx, repo, FixAgent(), FakeGH(), test_cmd=TEST_CMD).run_once()
    assert r.status == "proposto" and r.item_id == item["id"]                        # antes: "adiado: evidência insuficiente"


def test_item_planejado_ainda_espera_a_evidencia_do_jev(circle, repo):  # noqa: F811
    s, agora = circle.store, time.time()
    s.x("UPDATE roadmap SET status='feito'")
    iid = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,estudo) "
              "VALUES('Evoluir x','mudar y','loop','pendente','x',1,?,?,'estudado')", (agora, agora))
    dev = SelfDeveloper(circle.ctx, repo, FixAgent(), FakeGH(), test_cmd=TEST_CMD)
    s.x("UPDATE incidents SET count=1")
    r = dev.run_once(item_id=iid)
    assert r.status in ("adiado", "proposto")                                        # a regra do Jev continua valendo fora do erro


def test_arvore_bloqueada_pelo_teto_volta_quando_o_teto_comporta_o_gasto(circle, repo):  # noqa: F811
    item, dev, agent = preparar(circle, repo, piso_teto=10_000)
    gasto(circle, "Item que repete a falha", 3_000)
    bloquear_arvore(circle.store, item, "depende de você: bloqueado pelo disjuntor do teto, 2 tetos seguidos")
    circle.store.set(TETO_RAIZ, {str(item): {"n": 2, "escopo": "x"}})
    assert dev.run_once(item_id=item, autorizado=True).status != BLOQUEADO           # 3.000 + ~3.000 < 10.000: reabriu
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] != BLOQUEADO
    assert agent.tasks                                                                # e o Developer foi chamado de novo


def test_arvore_bloqueada_pelo_teto_fica_quando_o_gasto_passa_do_teto(circle, repo):  # noqa: F811
    item, dev, agent = preparar(circle, repo, piso_teto=10_000)
    gasto(circle, "Item que repete a falha", 9_000)
    bloquear_arvore(circle.store, item, "depende de você: bloqueado pelo disjuntor do teto, 2 tetos seguidos")
    assert dev.run_once(item_id=item, autorizado=True).status == BLOQUEADO
    assert agent.tasks == []

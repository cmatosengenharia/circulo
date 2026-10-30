"""Pergunta #533: pares (entrada normalizada → decisão) que o Jev repete com o mesmo resultado viram regra determinística
consultada antes do Jev; a regra é auditada contra o Jev e desligada se divergir mais de 10%. Item #306: a regra
promovida roda em sombra (grava regra × Jev em `regra_sombra`, sem agir) e só assume com ≥7 dias, n≥40 e limite
inferior de Wilson da concordância ≥90%."""
import json
import time

from circulo import aluno, regras
from circulo.decision import SN, Decision, Question

Q = Question("noul", "A trava `achados.0.titulo` é real?", SN("sim", "não"))


class Jev:
    """Jev que conta chamadas e responde sempre o mesmo valor."""
    source = "jev"
    model = "jev-1.13.0"

    def __init__(self, valor=0.9):
        self.valor, self.chamadas = valor, []

    def ask_many(self, state, questions):
        self.chamadas.append(sorted(questions))
        return {qid: Decision(qid, q.kind, self.valor, 0.8, "jev") for qid, q in questions.items()}, 10


def _decisoes(s, pergunta, estado, valores, idade=3600):
    for v in valores:
        s.x("INSERT INTO decisions(tick,question,value,confidence,source,created_at,estado) VALUES(0,?,?,0.8,'jev',?,?)",
            (pergunta, json.dumps(v), time.time() - idade, aluno.compactar(estado)))


def _estado(i):
    return {"achados": [{"titulo": f"Item #{i} parado", "gravidade": 0.7}]}


def _sombra(s, acertos, n, dias):
    """Regra única promovida há `dias` com `n` comparações em sombra, `acertos` delas iguais ao Jev; avalia."""
    r = s.one("SELECT id, rotulo FROM regras_jev")
    s.x("UPDATE regras_jev SET created_at=?", (time.time() - dias * 86400,))
    for i in range(n):
        s.x("INSERT INTO regra_sombra(regra_id,regra,jev,concorda,assumida,em) VALUES(?,?,?,?,0,?)",
            (r["id"], r["rotulo"], r["rotulo"] if i < acertos else "outro", int(i < acertos), time.time()))
    return regras.avaliar(s, r["id"])


def _assumida(s):
    assert _sombra(s, 40, 40, 8) is True


def test_tres_pares_mais_repetidos_e_consistentes_viram_regra_com_n_e_taxa(circle):
    s = circle.store
    _decisoes(s, "vigia_trava_0", _estado(1), [0.9] * 30)
    _decisoes(s, "vigia_trava_0", _estado(2), [0.1] * 25)
    _decisoes(s, "vigia_acao_0", _estado(3), [0.8] * 23 + [0.2])          # 23/24 = 96 %
    _decisoes(s, "vigia_acao_0", _estado(4), [0.9] * 21)                  # 4º: fica de fora
    _decisoes(s, "vigia_acao_0", _estado(5), [0.9] * 15 + [0.1] * 10)     # inconsistente
    _decisoes(s, "vigia_acao_0", _estado(6), [0.9] * 19)                  # n < 20
    _decisoes(s, "vigia_acao_0", _estado(7), [0.9] * 40, idade=8 * 86400)  # fora dos 7 dias
    promovidas = regras.promover(s)
    assert [(r["question"], r["n"]) for r in promovidas] == [("vigia_trava_0", 30), ("vigia_trava_0", 25), ("vigia_acao_0", 24)]
    assert promovidas[2]["taxa"] == round(23 / 24, 4)
    assert s.one("SELECT COUNT(*) c FROM regras_jev WHERE ativa=1")["c"] == 3


def test_par_promovido_e_decidido_sem_chamar_o_jev(circle):
    s = circle.store
    _decisoes(s, "indaga_pert_0", _estado(1), [0.9] * 20)
    regras.promover(s)
    _assumida(s)
    circle.ctx.dl.jev = jev = Jev()
    d = circle.ctx.dl.ask_many(_estado(1), {"indaga_pert_0": Q})["indaga_pert_0"]
    assert jev.chamadas == [] and d.source == "local" and d.value == 0.9
    circle.ctx.dl.ask_many(_estado(99), {"indaga_pert_0": Q})                # entrada sem regra: o Jev decide
    assert jev.chamadas == [["indaga_pert_0"]]


def test_decisao_divergente_do_jev_desliga_a_regra_e_o_jev_volta_a_decidir(circle):
    s = circle.store
    _decisoes(s, "indaga_pert_0", _estado(1), [0.9] * 20)
    regras.promover(s)
    _assumida(s)
    circle.ctx.dl.jev = jev = Jev(valor=0.1)
    for _ in range(regras.AUDITAR_A_CADA):
        circle.ctx.dl.ask_many(_estado(1), {"indaga_pert_0": Q})
    assert len(jev.chamadas) == 1                                           # só a auditoria chamou o Jev
    r = s.one("SELECT ativa, conferidas, erros FROM regras_jev")
    assert (r["ativa"], r["conferidas"], r["erros"]) == (0, 1, 1)
    d = circle.ctx.dl.ask_many(_estado(1), {"indaga_pert_0": Q})["indaga_pert_0"]
    assert len(jev.chamadas) == 2 and d.source == "jev"
    assert regras.promover(s) == []                                         # desligada não volta sozinha


def test_regra_que_concorda_com_o_jev_continua_ligada(circle):
    s = circle.store
    _decisoes(s, "indaga_pert_0", _estado(1), [0.9] * 20)
    regras.promover(s)
    _assumida(s)
    circle.ctx.dl.jev = Jev(valor=0.85)
    for _ in range(regras.AUDITAR_A_CADA):
        circle.ctx.dl.ask_many(_estado(1), {"indaga_pert_0": Q})
    r = s.one("SELECT ativa, usos, conferidas, erros FROM regras_jev")
    assert (r["ativa"], r["usos"], r["conferidas"], r["erros"]) == (1, regras.AUDITAR_A_CADA - 1, 1, 0)


def test_regra_promovida_roda_em_sombra_sem_agir_e_grava_regra_e_jev(circle):
    s = circle.store
    _decisoes(s, "indaga_pert_0", _estado(1), [0.9] * 20)
    regras.promover(s)
    circle.ctx.dl.jev = jev = Jev(valor=0.85)
    for _ in range(3):
        d = circle.ctx.dl.ask_many(_estado(1), {"indaga_pert_0": Q})["indaga_pert_0"]
        assert d.source == "jev"                                            # em sombra quem decide é o Jev
    assert len(jev.chamadas) == 3
    linhas = s.q("SELECT regra, jev, concorda, assumida FROM regra_sombra")
    assert [tuple(r) for r in linhas] == [("sim", "sim", 1, 0)] * 3
    assert s.one("SELECT assumiu_em FROM regras_jev")["assumiu_em"] is None


def test_regra_com_6_dias_n_39_ou_19_de_20_nao_assume(circle):
    """Regressão do item #306: só assume com ≥7 dias, n≥40 e limite inferior de Wilson (95%) ≥90%."""
    s = circle.store
    _decisoes(s, "indaga_pert_0", _estado(1), [0.9] * 20)
    regras.promover(s)
    assert regras.wilson_inf(19, 20) < 0.8                                 # 95% pontual, ~76% no limite inferior
    assert _sombra(s, 40, 40, 6) is False                                   # 6 dias
    s.x("DELETE FROM regra_sombra")
    assert _sombra(s, 39, 39, 8) is False                                   # n = 39
    s.x("DELETE FROM regra_sombra")
    assert _sombra(s, 19, 20, 8) is False                                   # 19 de 20
    s.x("DELETE FROM regra_sombra")
    assert _sombra(s, 39, 40, 8) is False                                   # 97,5% pontual, limite inferior < 90%
    assert s.one("SELECT assumiu_em FROM regras_jev")["assumiu_em"] is None
    s.x("DELETE FROM regra_sombra")
    assert _sombra(s, 40, 40, 7) is True
    r = s.one("SELECT assumiu_em, concordancia_inf FROM regras_jev")
    assert r["assumiu_em"] is not None and r["concordancia_inf"] >= 0.9


def test_regra_assumida_mantem_10_por_cento_em_sombra_e_volta_a_sombra_se_a_concordancia_cai(circle):
    s = circle.store
    _decisoes(s, "indaga_pert_0", _estado(1), [0.9] * 20)
    regras.promover(s)
    _assumida(s)
    circle.ctx.dl.jev = jev = Jev(valor=0.85)
    fontes = [circle.ctx.dl.ask_many(_estado(1), {"indaga_pert_0": Q})["indaga_pert_0"].source
              for _ in range(2 * regras.AUDITAR_A_CADA)]
    assert fontes.count("local") == 18 and len(jev.chamadas) == 2         # 10% seguem em sombra ao lado do Jev
    assert s.one("SELECT COUNT(*) c FROM regra_sombra WHERE assumida=1 AND concorda=1")["c"] == 2
    assert _sombra(s, 0, 1, 8) is False                                     # 42/43: limite inferior < 90%
    r = s.one("SELECT ativa, assumiu_em FROM regras_jev")
    assert (r["ativa"], r["assumiu_em"]) == (1, None)                       # rebaixada à sombra, não desligada
    assert circle.ctx.dl.ask_many(_estado(1), {"indaga_pert_0": Q})["indaga_pert_0"].source == "jev"


def test_sombra_grava_o_pr_do_estado_e_o_desfecho_quando_o_pr_fecha(circle):
    s = circle.store
    com_pr = dict(_estado(1), pr=7)
    _decisoes(s, "indaga_pert_0", com_pr, [0.9] * 20)
    regras.promover(s)
    circle.ctx.dl.jev = Jev(valor=0.85)
    circle.ctx.dl.ask_many(com_pr, {"indaga_pert_0": Q})
    assert tuple(s.one("SELECT pr, desfecho FROM regra_sombra")) == (7, None)   # PR ainda aberto: sem desfecho
    s.x("INSERT INTO prs(number,titulo,status,created_at,updated_at) VALUES(7,'x','aberto',0,0)")
    regras.desfechos(s)
    assert s.one("SELECT desfecho FROM regra_sombra")["desfecho"] is None
    s.x("UPDATE prs SET status='mergeado' WHERE number=7")
    regras.desfechos(s)
    assert s.one("SELECT desfecho FROM regra_sombra")["desfecho"] == "mergeado"

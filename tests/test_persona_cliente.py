"""Persona `cliente` (Mom Test, wondelai/skills `mom-test`, ADR 0004 WON-3): para cada produto da fábrica o conselho
pergunta o que o cliente já faz e já pagou; o Jev (Noul `mom_test_valida`) veta a pergunta que pede opinião sobre a ideia."""
import time

from circulo import indagador, persona_cliente, repo_cliente
from circulo.decision import Decision
from circulo.perguntas import PERSONAS, Conselho


def _produto(circle, raiz, nome="Agenda do salão", pedido="agendamento online para salão de beleza"):
    s = circle.store
    agora = time.time()
    pid = s.x("INSERT INTO projects(nome,pedido,tipo,kit,status,proposito,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
              (nome, pedido, "cli", repo_cliente.KIT, "ativo", pedido, agora, agora))
    repo_cliente.repos(s)                                     # cria o esquema
    s.x("INSERT INTO repos_cliente(projeto_id,caminho,remoto,base,testes,created_at) VALUES(?,?,?,?,?,?)",
        (pid, str(raiz / f"cliente-{pid}"), str(raiz / f"cliente-{pid}.git"), "main", "pytest", agora))
    return pid


def _cand(texto):
    return {"chave": "cliente:x", "persona": "cliente", "texto": texto, "relevancia": 0.7, "eixo": "produto",
            "evidencia": {"base": "medido"}}


def test_persona_cliente_esta_no_conselho():
    assert "cliente" in PERSONAS


def test_cada_produto_da_fabrica_gera_perguntas_do_cliente_sobre_o_passado(circle, tmp_path):
    pid = _produto(circle, tmp_path)
    cands = [p for p in Conselho(circle.ctx).candidatas() if p.persona == "cliente"]
    assert cands and all(p.eixo == "produto" and p.evidencia["projeto"] == pid for p in cands)
    assert any("Agenda do salão" in p.texto for p in cands)
    assert all(persona_cliente.regra(p.texto) >= 0.5 for p in cands)          # as do conselho passam no próprio Mom Test


def test_sem_produto_da_fabrica_o_cliente_nao_pergunta(circle):
    assert not [p for p in Conselho(circle.ctx).candidatas() if p.persona == "cliente"]


def test_regra_mom_test_separa_comportamento_passado_de_opiniao():
    assert persona_cliente.regra("Você usaria um app que agenda o corte pelo WhatsApp?") < 0.5
    assert persona_cliente.regra("Quanto você pagaria por isso?") < 0.5
    assert persona_cliente.regra("O que você acha da ideia de lembrete automático?") < 0.5
    assert persona_cliente.regra("Da última vez que um cliente faltou, o que você fez e quanto isso custou?") >= 0.5
    assert persona_cliente.regra("Quanto você já pagou no último mês pela ferramenta que usa hoje para agendar?") >= 0.5


def test_jev_veta_pergunta_do_cliente_que_pede_opiniao_sobre_a_ideia(circle):
    ctxt = indagador.contexto(circle.store, None)
    res = indagador.classificar(circle.ctx, [_cand("Como cliente da Agenda do salão, você usaria um app que agenda o corte pelo WhatsApp?"),
                                             _cand("Como cliente da Agenda do salão, da última vez que um cliente faltou, o que você "
                                                   "fez e quanto pagou pela ferramenta que usa hoje?")], ctxt)
    assert [r["veredito"] for r in res] == ["descartada", "valida"]
    assert res[0]["classificacao"]["mom_test"]["p"] < 0.5 and res[0]["eixo"] == "produto"
    nomes = {r["question"] for r in circle.store.q("SELECT question FROM decisions")}
    assert any(persona_cliente.NOUL in n for n in nomes)                     # a pergunta foi ao Jev, com o nome do Noul


def test_o_jev_manda_no_mom_test_mesmo_quando_a_regra_aprovaria(circle):
    class JevVeta:
        source = "jev"
        ultimo_modelo = "jev-1.13.0"

        def ask_many(self, state, questions):
            out = {}
            for qid, q in questions.items():
                if persona_cliente.NOUL in qid:
                    out[qid] = Decision(qid, "noul", 0.1, 0.9, "jev")
                elif q.kind == "noul":
                    out[qid] = Decision(qid, "noul", 0.9, 0.9, "jev")
                elif q.kind == "choice":
                    out[qid] = Decision(qid, "choice", "missao", 0.9, "jev")
                else:
                    out[qid] = Decision(qid, "score", 2.0, 0.9, "jev")
            return out, 50
    circle.ctx.dl.jev = JevVeta()
    res = indagador.classificar(circle.ctx, [_cand("Como cliente da Agenda do salão, da última vez que um cliente faltou, o que "
                                                   "você fez e quanto pagou?")], indagador.contexto(circle.store, None))
    assert res[0]["veredito"] == "descartada"

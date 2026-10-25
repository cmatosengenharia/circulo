"""1.57.0: o aluno como decisor (circulo/aluno_jev.py), itens por módulo (planejador/self_dev) e memória entre repositórios."""
import json
import sqlite3
import time

from circulo import aluno
from circulo.aluno_jev import AlunoJev
from circulo.decision import LocalJev, Question, build_jev
from circulo.memoria import Memoria
from circulo.planejador import _item, modulo_de
from circulo.state import Store

from test_aluno import _semear
from test_capacidade import _fila_dev
from test_self_dev import TEST_CMD, FakeGH, FixAgent, repo  # noqa: F401


class Regra(LocalJev):
    def __init__(self):
        self.chamadas = []

    def ask_many(self, state, questions):
        self.chamadas.append(sorted(questions))
        return super().ask_many(state, questions)


def test_aluno_decide_so_onde_provou_e_a_regra_responde_o_resto(circle):
    s = circle.store
    _semear(s)
    aluno.treinar(s)
    for _ in range(aluno.MIN_SOMBRA + 1):
        aluno.observar(s, "category", {"texto": "farmácia remédio", "valor": 20.0}, "saúde")
    assert aluno.pronto_para_decidir(s, "category")
    regra = Regra()
    dec = AlunoJev(s, reserva=regra, conf_min=0.0)
    qs = {"category": Question("choice", "categoria", {"saúde": "", "transporte": ""}), "worth_spending": Question("noul", "vale?")}
    out, usados = dec.ask_many({"texto": "farmácia remédio", "valor": 20.0, "est_tokens": 500, "value_signal": 0.9}, qs)
    assert usados == 0 and set(out) == {"category", "worth_spending"}
    assert out["category"].source == "aluno" and out["category"].value == "saúde" and out["category"].probabilities.get("_aluno")
    assert out["worth_spending"].source == "local" and regra.chamadas == [["worth_spending"]]   # só o que o aluno não decide
    assert dec.respondidas == 1


def test_aluno_nao_pronto_delega_tudo_e_nunca_derruba_a_decisao(circle):
    s = circle.store
    regra = Regra()
    dec = AlunoJev(s, reserva=regra)
    out, _ = dec.ask_many({"est_tokens": 500}, {"worth_spending": Question("noul", "vale?")})
    assert out["worth_spending"].source == "local" and regra.chamadas == [["worth_spending"]] and dec.respondidas == 0


def test_build_jev_respeita_o_decisor_escolhido(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "x")
    monkeypatch.setenv("CIRCULO_DECISOR", "aluno")
    assert isinstance(build_jev(), LocalJev)
    monkeypatch.delenv("CIRCULO_DECISOR")
    assert type(build_jev()).__name__ == "JevHttpClient"


def test_planejador_declara_o_modulo_e_o_texto_serve_de_reserva():
    assert _item({"titulo": "t", "detalhe": "d", "modulo": "circulo/estudo.py"})["modulo"] == "circulo/estudo.py"
    assert modulo_de({"modulo": "mexer em circulo/estudo.py"}) == "circulo/estudo.py"
    assert modulo_de({"titulo": "t", "detalhe": "trocar o retry em circulo/llm.py e testar"}) == "circulo/llm.py"
    assert modulo_de({"titulo": "t", "detalhe": "sem caminho"}) is None


def test_developer_escalado_nao_pega_dois_itens_do_mesmo_modulo_nem_de_pr_aberto(circle, repo):  # noqa: F811
    from circulo.self_dev import SelfDeveloper
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    _fila_dev(s, 4)
    s.x("UPDATE roadmap SET modulo='circulo/estudo.py' WHERE titulo IN ('Item 0','Item 1')")
    s.x("UPDATE roadmap SET modulo='circulo/llm.py' WHERE titulo='Item 2'")
    s.x("UPDATE roadmap SET modulo='circulo/painel.py' WHERE titulo='Item 3'")
    dev = SelfDeveloper(circle.ctx, repo, FixAgent(), FakeGH(), test_cmd=TEST_CMD)
    assert [i["titulo"] for i in dev.picks(3)] == ["Item 0", "Item 2", "Item 3"]      # Item 1 repete o módulo do 0
    agora = time.time()
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,item_id,arquivos,created_at,updated_at) VALUES(7,1,'x','b','aberto',999,?,?,?)",
        (json.dumps(["circulo/llm.py", "tests/test_llm.py"]), agora, agora))
    assert [i["titulo"] for i in dev.picks(3)] == ["Item 0", "Item 3"]                # llm.py já está num PR aberto
    assert dev.pick()["titulo"] == "Item 0"                                             # o pick simples não muda


def test_memoria_externa_entra_no_indice_e_banco_indisponivel_nao_quebra(circle, tmp_path, monkeypatch):
    outro = tmp_path / "outro-loop" / "circulo.db"
    outro.parent.mkdir()
    o = Store(str(outro))
    agora = time.time()
    o.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,created_at,updated_at) "
        "VALUES('developer:worktree:lint','developer','trabalho','ruff reclamou de import não usado no worktree','rode o ruff antes','validada',3,1,?,?)", (agora, agora))
    o.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES('Teto de tokens por item do Developer','d','loop','feito','PR #1',1,?,?)", (agora, agora))
    o.db.commit()
    monkeypatch.setenv("CIRCULO_MEMORIA_EXTERNA", f"{outro},{tmp_path / 'nao-existe' / 'circulo.db'}")
    m = Memoria(circle.store)
    n = m.reindexar(forcar=True)
    assert n.get(f"ext:{outro}") == 2
    r = circle.store.one("SELECT tipo, titulo, peso FROM memoria WHERE ref='ext:outro-loop:1' AND tipo='licao'")
    assert r and r["titulo"].startswith("[outro-loop]") and r["peso"] < 1.0
    assert any("outro-loop" in x["titulo"] for x in m.buscar("ruff import worktree"))
    assert not m.reindexar(forcar=True).get(f"ext:{outro}")                           # cursor: nada novo, nada regravado
    assert not sqlite3.connect(str(outro)).execute("SELECT name FROM sqlite_master WHERE name='memoria'").fetchall()   # só leitura no outro banco


def test_item_e_estudo_de_outro_loop_nao_quebram_o_planejador(circle, tmp_path, monkeypatch):
    """Vigia (pergunta_valida_parada): `ValueError: invalid literal for int() with base 10: 'ext:outro-loop:1'` em
    idle:planejar_roteiro. Item/estudo de outro loop têm ref `ext:<nome>:<id>`, que não é id do roteiro local."""
    outro = tmp_path / "outro-loop" / "circulo.db"
    outro.parent.mkdir()
    o = Store(str(outro))
    agora = time.time()
    est = json.dumps({"justificativa": "teto por item", "fontes": ["https://exemplo"], "achados": []})
    o.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,estudo,ordem,created_at,updated_at) "
        "VALUES('Teto de tokens por item do Developer','d','loop','feito','PR #1',?,1,?,?)", (est, agora, agora))
    o.db.commit()
    monkeypatch.setenv("CIRCULO_MEMORIA_EXTERNA", str(outro))
    m = Memoria(circle.store)
    m.reindexar(forcar=True)
    assert circle.store.one("SELECT 1 FROM memoria WHERE ref='ext:outro-loop:1' AND tipo='item'")
    assert m.item_parecido("Teto de tokens por item do Developer") is None
    assert m.estudo_parecido({"id": 99, "titulo": "Teto de tokens por item do Developer"}) is None

"""Portão de pedido que bloqueia: o item do loop (planejador/conselho) com pedido incompleto não chega à LLM do Developer.
Sai UMA pergunta, a do primeiro campo faltante, de volta ao gerador (o item volta ao Estudo, que o reescreve); no
máximo 1 rodada: incompleto de novo, o item é descartado com motivo, sem ficar pendente."""
import time

from test_reparo import ZipAgent, dev_de
from test_self_dev import repo  # noqa: F401 — fixture do repositório

from circulo.custo import tokens_por_veredito
from circulo.pedido_claro import ARQUIVO, PERGUNTAS, esclarecer, itens_com_veredito, registrar

SEM_ARQUIVO = "Teste de regressão cobre o giro do loop.\nSucesso: giro 20% mais rápido"
COMPLETO = "Mudar circulo/loop.py; teste de regressão cobre o giro.\nSucesso: giro 20% mais rápido"


def item_do_loop(s, detalhe, titulo="Giro mais rápido"):
    agora = time.time()
    pid = s.x("INSERT INTO perguntas(chave,persona,texto,status,created_at,updated_at) "
              "VALUES('arquiteto','arquiteto','O giro pode ser mais rápido?','virou_item',?,?)", (agora, agora))
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,pergunta_id,created_at,updated_at) "
        "VALUES(?,?,'loop','pendente','planejado',1,'{}',?,?,?)", (titulo, detalhe, pid, agora, agora))
    return dict(s.one("SELECT * FROM roadmap WHERE titulo=?", (titulo,)))


def test_pedido_sem_arquivo_alvo_gera_1_pergunta_e_0_chamadas_ao_developer(circle, repo, tmp_path):  # noqa: F811
    s = circle.store
    item = item_do_loop(s, SEM_ARQUIVO)
    agent = ZipAgent(conserta_na=1)
    dev, gh = dev_de(circle, repo, tmp_path, agent)
    r = dev.run_once()
    assert agent.tasks == [] and not gh.prs                          # 0 chamadas à LLM do Developer
    perguntas = s.q("SELECT item, campo, pergunta FROM esclarecimentos")
    assert [tuple(p) for p in perguntas] == [(item["id"], ARQUIVO, PERGUNTAS[ARQUIVO])]
    volta = s.one("SELECT status, estudo, detalhe FROM roadmap WHERE id=?", (item["id"],))
    assert (r.status, volta["status"], volta["estudo"]) == ("esclarecer", "pendente", None)   # volta ao Estudo
    assert PERGUNTAS[ARQUIVO] in volta["detalhe"] and dev.pick() is None   # o Developer só o vê depois de reescrito


def test_segundo_pedido_incompleto_do_mesmo_item_e_descartado_sem_perguntar_de_novo(circle, repo, tmp_path):  # noqa: F811
    s = circle.store
    item = item_do_loop(s, SEM_ARQUIVO)
    agent = ZipAgent(conserta_na=1)
    dev, _ = dev_de(circle, repo, tmp_path, agent)
    dev.run_once()
    s.x("UPDATE roadmap SET estudo='{}' WHERE id=?", (item["id"],))   # o Estudo devolveu o item ainda sem arquivo alvo
    r = dev.run_once()
    fim = s.one("SELECT status, evidencia FROM roadmap WHERE id=?", (item["id"],))
    assert (r.status, fim["status"]) == ("descartado", "descartado") and "arquivo" in fim["evidencia"]
    assert s.one("SELECT COUNT(*) n FROM esclarecimentos")["n"] == 1 and agent.tasks == []


def test_item_reescrito_completo_segue_e_conta_como_esclarecido_nos_tokens(circle):
    s = circle.store
    item = item_do_loop(s, SEM_ARQUIVO)
    assert esclarecer(s, item, registrar(s, item))[0] == "esclarecer"
    s.x("UPDATE roadmap SET detalhe=?, estudo='{}' WHERE id=?", (COMPLETO, item["id"]))
    novo = dict(s.one("SELECT * FROM roadmap WHERE id=?", (item["id"],)))
    assert esclarecer(s, novo, registrar(s, novo)) is None           # completo: vai para o Developer
    s.x("UPDATE roadmap SET status='feito' WHERE id=?", (item["id"],))
    r = tokens_por_veredito([{"entrada": "Giro mais rápido", "tokens": 12_000}], itens_com_veredito(s))
    assert r["por_veredito"] == {"esclarecido": {"tokens": 12_000, "prs": 1, "tokens_por_pr": 12_000}}


def test_item_de_erro_nao_passa_pelo_portao_que_bloqueia(circle):
    s, agora = circle.store, time.time()
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
        "VALUES('Erro vago','sem nada','erro','pendente','',1,?,?)", (agora, agora))
    item = dict(s.one("SELECT * FROM roadmap WHERE titulo='Erro vago'"))
    assert esclarecer(s, item, registrar(s, item)) is None           # a evidência do erro é o próprio erro


def test_item_do_loop_sem_pergunta_de_origem_segue_so_medido(circle):
    s, agora = circle.store, time.time()
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
        "VALUES('Legado vago',?,'loop','pendente','',1,?,?)", (SEM_ARQUIVO, agora, agora))
    item = dict(s.one("SELECT * FROM roadmap WHERE titulo='Legado vago'"))
    assert esclarecer(s, item, registrar(s, item)) is None           # sem gerador conhecido, não há a quem perguntar
    assert s.one("SELECT completo FROM pedidos_claros WHERE item=?", (item["id"],))["completo"] == 0

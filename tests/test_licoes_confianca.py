"""Confiança das lições como nos 'instintos' do ECC (ADR 0001, ECC-3): nasce em 0,3, sobe 0,1 quando a prevenção
segura, cai 0,2 a cada reincidência; abaixo de 0,2 fica em quarentena; com 0,8 ou mais vira candidata ao AGENTS.md."""
import json
import sqlite3
import time

import pytest

from circulo import contexto_cursor, licoes_confianca
from circulo.state import Store

SIG = "planejador:saida_invalida"


def _falhar(circle):
    return circle.licoes.verificar("planejador:saida", False, motivo="resposta sem JSON válido", assinatura=SIG)


def _confianca(store, lid):
    return store.one("SELECT confianca FROM licoes WHERE id=?", (lid,))["confianca"]


def _fechar(store, lid, status="validada"):
    store.x("UPDATE licoes SET status=? WHERE id=?", (status, lid))


def test_licao_nasce_com_confianca_0_3(circle):
    lic = _falhar(circle)
    assert lic["confianca"] == pytest.approx(licoes_confianca.INICIAL) == pytest.approx(0.3)
    assert not licoes_confianca.em_quarentena(lic)


def test_prevencao_que_segura_sobe_0_1_e_para_em_0_9(circle):
    s = circle.store
    lid = _falhar(circle)["id"]
    _fechar(s, lid, "validada")
    assert _confianca(s, lid) == pytest.approx(0.4)
    _fechar(s, lid, "evidenciada")
    assert _confianca(s, lid) == pytest.approx(0.5)
    _fechar(s, lid, "evidenciada")                       # sem mudar de estado não é confirmação nova
    assert _confianca(s, lid) == pytest.approx(0.5)
    for _ in range(10):
        _fechar(s, lid, "aberta")
        _fechar(s, lid, "validada")
    assert _confianca(s, lid) == pytest.approx(licoes_confianca.TETO) == pytest.approx(0.9)


def test_reincidencia_cai_0_2_e_abaixo_de_0_2_vai_para_quarentena(circle):
    s = circle.store
    lid = _falhar(circle)["id"]
    _fechar(s, lid)                                       # 0,4
    assert _falhar(circle)["status"] == "reincidente"
    assert _confianca(s, lid) == pytest.approx(0.2)
    assert not licoes_confianca.em_quarentena(dict(s.one("SELECT * FROM licoes WHERE id=?", (lid,))))
    _fechar(s, lid)                                       # 0,3
    _falhar(circle)                                       # 0,1
    lic = dict(s.one("SELECT * FROM licoes WHERE id=?", (lid,)))
    assert lic["confianca"] == pytest.approx(0.1) and licoes_confianca.em_quarentena(lic)
    assert [q["id"] for q in licoes_confianca.quarentena(s)] == [lid]
    _fechar(s, lid)                                       # 0,2
    _falhar(circle)                                       # 0,0
    _fechar(s, lid)                                       # 0,1
    _falhar(circle)                                       # nunca abaixo de zero
    assert _confianca(s, lid) == pytest.approx(0.0)


def test_teste_da_licao_verde_num_sha_novo_e_confirmacao(circle):
    s = circle.store
    L = circle.licoes
    lid = L.verificar("developer:testes", False, motivo="FAILED tests/test_a.py::test_b - x")["id"]
    for _ in range(3):
        L.checar_testes("aaa111", lambda n: 0)
    assert s.one("SELECT status FROM licoes WHERE id=?", (lid,))["status"] == "validada"
    assert _confianca(s, lid) == pytest.approx(0.4)
    L.checar_testes("bbb222", lambda n: 0)                # a prevenção segurou num main novo
    assert _confianca(s, lid) == pytest.approx(0.5)
    L.checar_testes("ccc333", lambda n: 1)                # e depois voltou a falhar
    assert _confianca(s, lid) == pytest.approx(0.3)


def test_mesmo_sha_reexecutado_nao_e_confirmacao_nova(circle):
    """Só um main novo confirma a prevenção: gravar outra checagem verde no mesmo sha não sobe a confiança."""
    s = circle.store
    lid = _falhar(circle)["id"]
    _fechar(s, lid)                                       # 0,4
    checagens = []
    for _ in range(5):
        checagens.append({"sha": "aaa111", "exit": 0, "tick": 1, "em": 0})
        s.x("UPDATE licoes SET checagens=? WHERE id=?", (json.dumps(checagens), lid))
    assert _confianca(s, lid) == pytest.approx(0.5)       # a primeira checagem em aaa111 conta; as repetições, não
    checagens.append({"sha": "bbb222", "exit": 0, "tick": 2, "em": 0})
    s.x("UPDATE licoes SET checagens=? WHERE id=?", (json.dumps(checagens), lid))
    assert _confianca(s, lid) == pytest.approx(0.6)


def _licao(store, sig, desc, status, confianca):
    agora = time.time()
    store.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,status,ocorrencias,reincidencias,created_at,updated_at,"
            "confianca) VALUES(?,?,?,?,?,1,0,?,?,?)",
            (sig, sig.split(":")[0], "estrutural", desc, status, agora, agora, confianca))


def test_confianca_alta_vira_candidata_ao_agents_md_e_quarentena_nao(circle):
    s = circle.store
    _licao(s, "loop:confiavel", "o roteiro sem pergunta do conselho perde o rastro", "validada", 0.8)
    _licao(s, "loop:fraca", "prevenção que nunca segurou", "evidenciada", 0.1)
    _licao(s, "loop:morna", "ainda em teste", "validada", 0.5)
    assert [c["assinatura"] for c in licoes_confianca.candidatas(s)] == ["loop:confiavel"]
    agents = contexto_cursor.gerar(s, readme="", nome="cliente")["AGENTS.md"]
    assert "perde o rastro" in agents
    assert "nunca segurou" not in agents and "ainda em teste" not in agents


def test_banco_antigo_ganha_a_coluna_com_0_3(tmp_path):
    db = tmp_path / "antigo.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE licoes (id INTEGER PRIMARY KEY AUTOINCREMENT, assinatura TEXT NOT NULL UNIQUE, "
                "ponto TEXT NOT NULL, classe TEXT NOT NULL, descricao TEXT NOT NULL, prevencao TEXT, status TEXT NOT NULL, "
                "ocorrencias INTEGER NOT NULL, reincidencias INTEGER NOT NULL, item_id INTEGER, pr INTEGER, "
                "primeira_tick INTEGER, ultima_tick INTEGER, corrigida_tick INTEGER, evidenciada_tick INTEGER, "
                "created_at REAL NOT NULL, updated_at REAL NOT NULL)")
    con.execute("INSERT INTO licoes(assinatura,ponto,classe,descricao,status,ocorrencias,reincidencias,created_at,updated_at) "
                "VALUES('a:b','a','estrutural','x','evidenciada',1,0,0,0)")
    con.commit()
    con.close()
    s = Store(db)
    assert s.one("SELECT confianca FROM licoes")["confianca"] == pytest.approx(0.3)


def test_promove_a_global_com_dois_repositorios_e_media_0_8(circle):
    """Como o ECC promove o instinto a global: aparece em ≥2 repositórios (o loop conta como um) com média ≥0,8."""
    s = circle.store
    _licao(s, "loop:global", "a migração sem coluna nova quebra o banco antigo", "validada", 0.7)
    _licao(s, "loop:local", "só acontece no loop", "validada", 0.7)
    assert licoes_confianca.globais(s) == []
    for _ in range(6):                                     # 0,3 → 0,9 no repositório do cliente
        licoes_confianca.observar(s, "esteira", "loop:global", segurou=True)
    assert licoes_confianca.confianca_no_repo(s, "esteira", "loop:global") == pytest.approx(0.9)
    assert [g["assinatura"] for g in licoes_confianca.globais(s)] == ["loop:global"]   # (0,7 + 0,9) / 2 = 0,8
    agents = contexto_cursor.gerar(s, readme="", nome="cliente")["AGENTS.md"]
    assert "banco antigo" in agents and "só acontece no loop" not in agents
    licoes_confianca.observar(s, "esteira", "loop:global", segurou=False)              # contradição no cliente: 0,7
    assert licoes_confianca.globais(s) == []
    assert "banco antigo" not in contexto_cursor.gerar(s, readme="", nome="cliente")["AGENTS.md"]


def test_um_repositorio_so_nao_promove_mesmo_com_confianca_alta(circle):
    s = circle.store
    for _ in range(6):
        licoes_confianca.observar(s, "esteira", "cliente:so_aqui", segurou=True)
        licoes_confianca.observar(s, "outro", "cliente:outra", segurou=True)
    assert licoes_confianca.globais(s) == []

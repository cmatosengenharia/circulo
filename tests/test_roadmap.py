"""Disjuntor por assinatura na seleção do roadmap: 5 falhas locais iguais no item o tiram da fila ('bloqueado', com
motivo e data, registrado para o conselho); depois do cooldown, ou quando o node id muda, ele ganha UMA tentativa
(meio-aberto). Item de lição fechada só sai da fila se o node id passar isolado no main (o curador do item #37)."""
import time

from circulo import fatiador, licoes, reparo, roadmap


class Fila:
    """O `pick` do Developer: o primeiro pendente na ordem."""
    repo = "repo-falso"

    def __init__(self, store):
        self.s = store

    def pick(self):
        r = self.s.one("SELECT * FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 ORDER BY ordem LIMIT 1")
        return dict(r) if r else None


def _item(s, titulo, ordem):
    return s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
               "VALUES(?,'d','erro','pendente','',?,0,0)", (titulo, ordem))


def _falhar(circle, item_id, n, motivo="FAILED tests/test_x.py::test_y - AssertionError: assert 0 == 1"):
    for i in range(n):
        circle.licoes.verificar("developer:base", False, sujeito=f"roteiro #{item_id}", item_id=item_id, licao=False,
                                motivo=motivo.replace("{i}", str(i)))


def _licao(s, item_id, status):
    return s.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,status,ocorrencias,reincidencias,item_id,node_id,"
               "created_at,updated_at) VALUES('sig','developer:testes','trabalho','d',?,1,0,?,'tests/test_x.py::test_y',0,0)",
               (status, item_id))


def _proximo(circle):
    return fatiador.proximo(circle.ctx, Fila(circle.store), None)


def test_item_com_11_falhas_iguais_nao_e_escolhido_e_fica_bloqueado_com_motivo_e_data(circle):
    s = circle.store
    preso, livre = _item(s, "preso", 1), _item(s, "livre", 2)
    _falhar(circle, preso, 11)
    assert _proximo(circle) == livre
    st = s.one("SELECT status, evidencia FROM roadmap WHERE id=?", (preso,))
    assert st["status"] == "bloqueado" and "11 falhas locais iguais" in st["evidencia"]
    assert "developer:base:teste:tests/test_x.py::test_y" in st["evidencia"]
    assert time.strftime("%Y-%m-%d") in st["evidencia"]                  # a data
    conselho = s.one("SELECT * FROM verificacoes WHERE ponto=?", (roadmap.PONTO,))
    assert conselho["item_id"] == preso and conselho["ok"] == 0


def test_falhas_com_assinaturas_diferentes_nao_abrem_o_disjuntor(circle):
    s = circle.store
    item = _item(s, "variado", 1)
    _falhar(circle, item, 11, motivo="FAILED tests/test_x.py::test_{i} - AssertionError")
    assert _proximo(circle) == item


def test_meio_aberto_da_uma_tentativa_depois_do_cooldown_e_a_falha_seguinte_bloqueia_de_novo(circle):
    s = circle.store
    item, outro = _item(s, "preso", 1), _item(s, "outro", 2)
    _falhar(circle, item, 10)
    assert _proximo(circle) == outro
    d = s.get(roadmap.DISJUNTOR)
    s.set(roadmap.DISJUNTOR, {str(item): {**d[str(item)], "em": d[str(item)]["em"] - roadmap.COOLDOWN - 1}})
    assert _proximo(circle) == item                                        # meio-aberto: uma tentativa
    _falhar(circle, item, 1)
    assert _proximo(circle) == outro                                       # falhou de novo: abre na hora
    d = s.get(roadmap.DISJUNTOR)[str(item)]
    assert d["vezes"] == 2 and s.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "bloqueado"
    s.set(roadmap.DISJUNTOR, {str(item): {**d, "em": d["em"] - roadmap.COOLDOWN - 1}})
    assert _proximo(circle) == outro                                       # o cooldown dobra a cada reabertura


def test_node_id_novo_reabre_o_item_bloqueado_antes_do_cooldown(circle):
    s = circle.store
    item = _item(s, "preso", 1)
    lid = _licao(s, item, "aberta")
    _falhar(circle, item, 10)
    assert _proximo(circle) != item
    s.x("UPDATE licoes SET node_id='tests/test_x.py::test_z' WHERE id=?", (lid,))
    assert _proximo(circle) == item


def _licao_fechada(s, item):
    _licao(s, item, "validada")


def test_item_de_licao_fechada_com_node_id_verde_no_main_nao_e_escolhido(circle, monkeypatch):
    s = circle.store
    fechado, livre = _item(s, "Lição #1: x", 1), _item(s, "livre", 2)
    _licao_fechada(s, fechado)
    rodados = []
    monkeypatch.setattr(licoes, "reexecutar_no_main", lambda repo, nodes, *a, **k: (rodados.append((repo, nodes)) or
                                                                                    ("abc123", {n: 0 for n in nodes})))
    assert _proximo(circle) == livre
    assert rodados == [("repo-falso", ["tests/test_x.py::test_y"])]       # o node id isolado, no main
    st = s.one("SELECT status, evidencia FROM roadmap WHERE id=?", (fechado,))
    assert st["status"] == "feito" and "tests/test_x.py::test_y" in st["evidencia"] and "abc123" in st["evidencia"]


def test_item_de_licao_fechada_com_node_id_vermelho_no_main_segue_na_fila(circle, monkeypatch):
    s = circle.store
    fechado = _item(s, "Lição #1: x", 1)
    _licao_fechada(s, fechado)
    monkeypatch.setattr(licoes, "reexecutar_no_main", lambda repo, nodes, *a, **k: ("abc123", {n: 1 for n in nodes}))
    assert _proximo(circle) == fechado
    assert s.one("SELECT status FROM roadmap WHERE id=?", (fechado,))["status"] == "pendente"


def test_deve_bloquear_no_teto_de_5_falhas_com_a_mesma_assinatura():
    assert not roadmap.deve_bloquear(4) and roadmap.deve_bloquear(5) and roadmap.deve_bloquear(6)
    assert roadmap.deve_bloquear(1, limite=1) and not roadmap.deve_bloquear(0, limite=1)


def test_6_falhas_iguais_levam_a_bloqueado_e_o_item_nao_e_escalado(circle):
    s = circle.store
    preso, livre = _item(s, "preso", 1), _item(s, "livre", 2)
    _falhar(circle, preso, 6)
    assert _proximo(circle) == livre
    st = s.one("SELECT status, evidencia FROM roadmap WHERE id=?", (preso,))
    assert st["status"] == "bloqueado" and "6 falhas locais iguais" in st["evidencia"]
    assert "tests/test_x.py::test_y" in s.get(roadmap.DISJUNTOR)[str(preso)]["sig"]        # a assinatura gravada
    s.x("UPDATE roadmap SET status='feito' WHERE id=?", (livre,))
    assert _proximo(circle) != preso                                        # sem o livre, segue sem ser escalado
    assert s.one("SELECT status FROM roadmap WHERE id=?", (preso,))["status"] == "bloqueado"


def test_4_falhas_iguais_e_2_diferentes_nao_acionam_o_bloqueio(circle):
    s = circle.store
    item = _item(s, "misto", 1)
    _falhar(circle, item, 4)
    _falhar(circle, item, 2, motivo="FAILED tests/test_x.py::test_outro_{i} - AssertionError")
    assert _proximo(circle) == item
    assert s.one("SELECT status FROM roadmap WHERE id=?", (item,))["status"] == "pendente"


def test_base_vermelha_repetida_6_vezes_bloqueia_mesmo_com_um_unico_evento(circle):
    """A base vermelha grava um evento por (item, assinatura) e conta as repetições no kv (item #144: 3786 falhas
    locais sem o disjuntor abrir); o teto conta as duas."""
    s = circle.store
    preso, livre = _item(s, "preso", 1), _item(s, "livre", 2)
    _falhar(circle, preso, 1)
    base = {"sig": "tests/test_x.py::test_y AssertionError", "n": 6, "chave": "t"}
    s.set(reparo.BASE_VERMELHA, {str(preso): base})
    assert _proximo(circle) == livre
    st = s.one("SELECT status, evidencia FROM roadmap WHERE id=?", (preso,))
    assert st["status"] == "bloqueado" and "6 falhas locais iguais" in st["evidencia"]
    d = s.get(roadmap.DISJUNTOR)[str(preso)]
    s.set(roadmap.DISJUNTOR, {str(preso): {**d, "em": d["em"] - roadmap.COOLDOWN - 1}})
    assert _proximo(circle) == preso                                       # meio-aberto: o contador antigo não conta
    s.set(reparo.BASE_VERMELHA, {str(preso): {**base, "n": 7}})
    assert _proximo(circle) == livre                                       # a mesma base vermelha de novo: bloqueia

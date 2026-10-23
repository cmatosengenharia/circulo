"""Disjuntor por assinatura na seleção do roadmap: 10 falhas locais iguais no item o tiram da fila ('bloqueado', com
motivo e data, registrado para o conselho); depois do cooldown, ou quando o node id muda, ele ganha UMA tentativa
(meio-aberto). Item de lição fechada só sai da fila se o node id passar isolado no main (o curador do item #37)."""
import time

from circulo import fatiador, licoes, roadmap


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

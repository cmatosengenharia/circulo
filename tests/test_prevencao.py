"""Pergunta #522: a lição 'validada' cuja Prevenção cita um teste que não existe no repositório não está segura por
nada. A existência do id (arquivo e função) é conferida por ast a cada giro; inexistente, a lição vira sem_prevencao."""
from circulo.prevencao import exigir
from circulo.prevencao import testes_inexistentes as inexistentes  # com o nome original o pytest o coleta como teste

INSERT = ("INSERT INTO licoes(id,assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,"
          "primeira_tick,ultima_tick,created_at,updated_at,camada) VALUES(?,?,'x:y','estrutural','x:y: erro',?,'validada',"
          "1,?,0,0,0,0,'regra')")


def _repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_a.py").write_text("def test_existe():\n    assert True\n")
    return repo


def test_extrai_o_id_da_prevencao_e_confere_arquivo_e_funcao(tmp_path):
    repo = _repo(tmp_path)
    assert inexistentes(repo, "Checagem: teste tests/test_a.py::test_existe; não repetir: x") == []
    assert inexistentes(repo, "Checagem: teste tests/test_a.py; não repetir: x") == []
    assert inexistentes(repo, "teste tests/test_a.py::test_sumiu") == ["tests/test_a.py::test_sumiu"]
    assert inexistentes(repo, "teste tests/test_b.py::test_existe") == ["tests/test_b.py::test_existe"]
    assert inexistentes(repo, "Já corrigido; checagem: portão #28 lint B905") == []


def test_validada_que_cita_teste_inexistente_vira_sem_prevencao_no_mesmo_giro(circle, tmp_path):
    repo, s = _repo(tmp_path), circle.store
    s.x(INSERT, (90, "a:sumiu", "Checagem: teste tests/test_a.py::test_sumiu; não repetir: x", 0))
    s.x(INSERT, (91, "a:existe", "Checagem: teste tests/test_a.py::test_existe; não repetir: x", 0))
    assert exigir(s, 10, 0.0, repo) == ["lição #90 sem prevenção"]
    assert s.one("SELECT status FROM licoes WHERE id=90")["status"] == "sem_prevencao"
    assert s.one("SELECT status FROM licoes WHERE id=91")["status"] == "validada"
    assert exigir(s, 11, 0.0, repo) == []              # o teste citado não existe: não volta a validada sozinha

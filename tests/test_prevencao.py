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


JEV = "tests/test_decision.py::test_jev_fora_do_ar_nao_para_o_circulo"
TESTE = ("INSERT INTO licoes(id,assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,primeira_tick,"
         "ultima_tick,created_at,updated_at,camada,node_id,checagens) VALUES(?,?,'corpo:validacao_falhou',?,?,'',?,1,0,0,0,0,0,"
         "'regra',?,?)")


def _licao_de_teste(s, lid, node, classe="estrutural", status="aberta", checagens="[]"):
    s.x(TESTE, (lid, f"corpo:validacao_falhou:teste:{node}", classe,
                f"corpo:validacao_falhou: FAILED {node} - TimeoutError('timeout')", status, node, checagens))


def _commit(repo, arquivo, texto):
    import subprocess
    (repo / arquivo).write_text(texto)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)


def test_licao_89_timeout_em_teste_de_resiliencia_nao_vira_erro_de_ambiente(circle, tmp_path):
    """Lição #89: test_jev_fora_do_ar_nao_para_o_circulo falhou com TimeoutError('timeout') e foi rotulada 'erro de
    ambiente', mas o teste existe para provar a resiliência a esse timeout. Sem evidência a lição fica 'desconhecida' e
    aberta, e só fecha com o teste de regressão (stub do Jev que lança TimeoutError) na main. O repositório é um git
    local em tmp_path, como em test_licao_47_regressao: `teste_de_regressao` lê o arquivo na main por `git show`."""
    s, repo = circle.store, tmp_path / "repo"
    repo.mkdir()

    def status():
        return s.one("SELECT status FROM licoes WHERE id=89")["status"]

    _licao_de_teste(s, 89, JEV)
    _licao_de_teste(s, 90, "tests/test_a.py::test_soma")
    assert circle.licoes.reclassificar_ambiente() == []
    s.x("UPDATE licoes SET classe='ambiente', prevencao='Erro de ambiente (não é do loop): x' WHERE id=89")
    exigir(s, 10, 0.0, repo)
    lic = s.one("SELECT classe, status, prevencao FROM licoes WHERE id=89")
    assert (lic["classe"], lic["status"]) == ("desconhecida", "sem_prevencao")
    assert "stub" in lic["prevencao"] and "TimeoutError" in lic["prevencao"] and "tests/test_licao_89_regressao.py" in lic["prevencao"]
    for sha in ("a1", "b2"):                                 # o próprio teste passar de novo não basta: pede o stub
        log = circle.licoes.checar_testes(sha, lambda node: 0)
    assert log == ["lição #90 fechada no sha b2"]            # a lição de teste comum fecha pela reexecução…
    assert status() == "sem_prevencao"                       # …a do teste de resiliência segue aberta
    s.x("DELETE FROM licoes WHERE id=90")
    s.x("UPDATE licoes SET status='aberta' WHERE id=89")
    assert circle.licoes.reclassificar_ambiente() == []
    s.x("UPDATE licoes SET status='validada' WHERE id=89")  # fechada antes desta regra
    assert exigir(s, 11, 0.0, repo) == ["lição #89 sem prevenção"]
    assert exigir(s, 12, 0.0, repo) == [] and status() == "sem_prevencao"
    (repo / "tests").mkdir()
    _commit(repo, "tests/test_licao_89_regressao.py", '"""lição #89: Jev por stub que lança TimeoutError."""\n')
    assert exigir(s, 13, 0.0, repo) == ["lição #89 validada"] and status() == "validada"


def test_erro_de_ambiente_em_teste_so_com_evidencia(circle):
    """Lição #89: o tipo do erro não prova ambiente; a reexecução do mesmo teste passando, ou o erro fora do teste em
    outro ponto, prova."""
    s, L = circle.store, circle.licoes
    _licao_de_teste(s, 1, "tests/test_a.py::test_soma")
    _licao_de_teste(s, 2, "tests/test_a.py::test_conta", checagens='[{"exit": 1}, {"exit": 0}]')
    _licao_de_teste(s, 3, "tests/test_a.py::test_lista")
    assert L.reclassificar_ambiente() == [2]
    s.x("INSERT INTO licoes(id,assinatura,ponto,classe,descricao,status,ocorrencias,reincidencias,primeira_tick,ultima_tick,"
        "created_at,updated_at) VALUES(4,'graft:timeout','graft','ambiente','graft: timeout','aberta',1,0,0,0,0,0)")
    assert L.reclassificar_ambiente() == [1, 3]

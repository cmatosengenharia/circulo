from circulo.diff_size import categoria, normalizar_caminho, parse_numstat

NUMSTAT = (
    "120\t30\tcirculo/loop.py\n"
    "40\t0\ttests/test_loop.py\n"
    "-\t-\tdocs/logo.png\n"
    "5\t5\tcirculo/{velho.py => novo.py}\n"
    "300\t0\tuv.lock\n"
    "2\t1\tantigo.txt => novo.txt\n"
)


def test_parse_numstat():
    r = parse_numstat(NUMSTAT)
    assert r.total == 150 + 40 + 0 + 10 + 300 + 3
    por_nome = {a.caminho: a for a in r.arquivos}
    assert por_nome["docs/logo.png"].linhas == 0
    assert "circulo/novo.py" in por_nome and "novo.txt" in por_nome
    assert por_nome["circulo/novo.py"].categoria == "fonte"
    assert por_nome["tests/test_loop.py"].categoria == "teste"
    assert por_nome["uv.lock"].categoria == "gerado"
    assert r.por_categoria == {"fonte": 163, "teste": 40, "gerado": 300}
    assert r.categoria_dominante == "gerado"
    assert r.arquivo_dominante == "uv.lock"


def test_numstat_vazio_nao_tem_dominante():
    r = parse_numstat("")
    assert (r.total, r.categoria_dominante, r.arquivo_dominante) == (0, None, None)


def test_renomeacao_com_prefixo_e_sufixo():
    assert normalizar_caminho("src/{a => b}/x.py") == "src/b/x.py"
    assert normalizar_caminho("src/{ => sub}/x.py") == "src/sub/x.py"
    assert normalizar_caminho("src/{sub => }/x.py") == "src/x.py"


def test_categoria():
    assert categoria("tests/conftest.py") == "teste"
    assert categoria("pkg/test_x.py") == "teste"
    assert categoria("package-lock.json") == "gerado"
    assert categoria("circulo/x.py") == "fonte"

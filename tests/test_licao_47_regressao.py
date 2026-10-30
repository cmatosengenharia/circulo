"""Lição #47 (loop:estagnado, neurônio loop:progresso): "havia trabalho pendente e nada avançou em 10 giros; causa
provável: sem recusa registrada". Os PRs #88/#140/#142/#150 corrigiram a causa e deixaram testes citando a lição, mas
ela seguia sem_prevencao e reincidindo: `cobrar_teste` pede tests/test_licao_47_regressao.py e `checagem_de` nunca
olhava esse arquivo. Só contava o portão do item enquanto o item estivesse feito, e cada reincidência reabre o item.
O teste de regressão que o item cobra, já na main do repositório e citando a lição, é a checagem dela."""
import subprocess

from circulo.estagnacao import ESTAGNADO
from circulo.licoes import Licoes
from circulo.prevencao import cobrar_teste

TESTE = "tests/test_licao_47_regressao.py"
DESCRICAO = "loop:progresso: havia trabalho pendente e nada avançou em 10 giros; causa provável: sem recusa registrada"


def _repo(tmp_path, conteudo):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q", "-b", "main"], cwd=repo, check=True)
    if conteudo is not None:
        (repo / TESTE).write_text(conteudo)
        subprocess.run([*git, "add", "-A"], cwd=repo, check=True)
        subprocess.run([*git, "commit", "-qm", "teste"], cwd=repo, check=True)
    return repo


def _licao_47(s):
    s.x("INSERT INTO licoes(id,assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,primeira_tick,"
        "ultima_tick,created_at,updated_at,camada) VALUES(47,'loop:estagnado','loop:progresso','estrutural',?,"
        "'Não repetir','sem_prevencao',13,6,0,0,0,0,'arquitetura')", (DESCRICAO,))


def test_licao_47_teste_de_regressao_na_main_tira_a_licao_de_sem_prevencao(circle, tmp_path):
    s = circle.store
    _licao_47(s)
    Licoes(s, repo=_repo(tmp_path, '"""Lição #47: loop:estagnado."""\n')).revisar()
    r = s.one("SELECT status, prevencao FROM licoes WHERE id=47")
    assert r["status"] == "validada" and TESTE in r["prevencao"]
    assert cobrar_teste(s) == []


def test_licao_47_sem_o_teste_na_main_ou_sem_citar_a_licao_segue_sem_prevencao(circle, tmp_path):
    s = circle.store
    _licao_47(s)
    for i, conteudo in enumerate((None, '"""Lição #470: outra."""\n')):
        Licoes(s, repo=_repo(tmp_path / str(i), conteudo)).revisar()
        assert s.one("SELECT status FROM licoes WHERE id=47")["status"] == "sem_prevencao", i


def test_licao_47_trabalho_pendente_parado_vira_estagnacao_com_a_causa_medida(circle):
    circle._tem_trabalho = lambda t: t == "corrigir_codigo"
    circle._progresso = lambda: (0,)
    for _ in range(ESTAGNADO):
        circle.tick()
    lic = circle.store.one("SELECT descricao FROM licoes WHERE assinatura='loop:estagnado'")
    assert lic and "nada avançou" in lic["descricao"] and "sem recusa registrada" not in lic["descricao"]

"""Developer: base vermelha com a mesma assinatura 2x seguidas tira o item da fila (pergunta do conselho #129).

Medido: o item 144 (lição #67, tests/test_capacidade.py:97, developer:base) acumulou 3786 falhas locais. O pré-voo
achava a base vermelha, devolvia o item para 'pendente' e o seletor o pegava de novo no giro seguinte, sem fim. Agora a
mesma assinatura (node id + linha do erro) 2x seguidas põe o item em 'bloqueado_base', o evento de falha é um só por
(item, assinatura) com o contador no kv, e o item volta à fila quando a main muda."""
import time

from circulo import self_dev
from circulo.reparo import BASE_VERMELHA, BLOQUEADO_BASE, DeveloperComReparo

from test_preflight_developer import ContaAgent, item
from test_self_dev import FakeGH, git, repo  # noqa: F401 — fixture do repositório


class Relogio:
    """Um giro por segundo: a branch do item leva o segundo no nome e giros no mesmo segundo colidiriam."""
    def __init__(self):
        self.t = time.time()

    def time(self):
        self.t += 1
        return self.t

    def __getattr__(self, nome):
        return getattr(time, nome)


def commit(repo, arquivos):  # noqa: F811
    for nome, corpo in arquivos.items():
        (repo / nome).parent.mkdir(exist_ok=True)
        (repo / nome).write_text(corpo)
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
    git(repo, "push", "-q", "origin", "main")


def test_base_sempre_vermelha_roda_no_maximo_2_vezes_e_volta_quando_a_main_muda(circle, repo, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(self_dev, "time", Relogio())
    execucoes = tmp_path / "execucoes.txt"
    teste = (f"from app import soma\n\n\ndef test_soma():\n    open({str(execucoes)!r}, 'a').write('x\\n')\n"
             "    assert soma(2, 2) == 4\n")
    commit(repo, {"app.py": "def soma(a, b):\n    return a - b\n", "tests/test_app.py": teste})
    it = item(circle, "Mudar a soma em app.py para aceitar negativos.")
    agent = ContaAgent()
    dev = DeveloperComReparo(circle.ctx, repo, agent, FakeGH(), lint_cmd=[], fix_cmds=[])
    for _ in range(5):
        dev.run_once(item_id=it, autorizado=True)
    s = circle.store
    assert agent.tasks == []
    assert execucoes.read_text().count("x") == 2                                  # no máximo 2 execuções locais
    assert s.one("SELECT status FROM roadmap WHERE id=?", (it,))["status"] == BLOQUEADO_BASE
    assert s.one("SELECT COUNT(*) n FROM verificacoes WHERE ponto='developer:base' AND ok=0")["n"] == 1
    assert s.get(BASE_VERMELHA)[str(it)]["n"] == 2                                 # deduplicado, com contador
    assert dev.pick() is None                                                      # fora da fila

    commit(repo, {"app.py": "def soma(a, b):\n    return a + b\n"})               # a base ficou verde
    dev.run_once(item_id=it, autorizado=True)
    assert len(agent.tasks) == 1
    assert str(it) not in (s.get(BASE_VERMELHA) or {})


def test_assinatura_diferente_nao_bloqueia(circle, repo, monkeypatch):  # noqa: F811
    monkeypatch.setattr(self_dev, "time", Relogio())
    commit(repo, {"app.py": "def soma(a, b):\n    return a - b\n",
                  "tests/test_app.py": "from app import soma\n\n\ndef test_soma():\n    assert soma(2, 2) == 4\n"})
    it = item(circle, "Mudar a soma em app.py para aceitar negativos.")
    dev = DeveloperComReparo(circle.ctx, repo, ContaAgent(), FakeGH(), lint_cmd=[], fix_cmds=[])
    dev.run_once(item_id=it, autorizado=True)
    commit(repo, {"tests/test_app.py": "from app import soma\n\n\ndef test_dobro():\n    assert soma(1, 1) == 2\n"})
    dev.run_once(item_id=it, autorizado=True)
    assert circle.store.one("SELECT status FROM roadmap WHERE id=?", (it,))["status"] == "pendente"
    assert circle.store.get(BASE_VERMELHA)[str(it)]["n"] == 1

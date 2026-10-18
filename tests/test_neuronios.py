"""Neurônios: a saída só segue se todos os portões aprovarem; lições criam portões novos (neurogênese)."""
import re
from pathlib import Path

from circulo.neuronios import ABRIR_PR, cerebros, criar_portao, portoes, portoes_natos_pr
from circulo.self_dev import SelfDeveloper

from test_self_dev import TEST_CMD, FakeGH, git, repo  # noqa: F401 — fixture do repositório


def item_do_loop(circle, titulo="Melhorar algo"):
    circle.store.x("UPDATE roadmap SET status='feito'")
    return circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,estudo) "
                          "VALUES(?,?,'loop','pendente','x',999,0,0,'{}')", (titulo, "detalhe"))   # já estudado


class Agente:
    """Escreve a correção; `passos` define o que cada chamada faz (simula o Developer corrigindo o que foi barrado)."""

    def __init__(self, *passos):
        self.passos = list(passos)
        self.tasks = []

    def run(self, task, workdir):
        self.tasks.append(task)
        passo = self.passos.pop(0) if self.passos else (lambda w, t: None)
        passo(Path(workdir), task)
        return {"ok": True, "tokens": 10, "log": "ok"}


def corrige(w, t):
    (w / "app.py").write_text("def soma(a, b):\n    return a + b\n")


def com_teste(w, t):
    m = re.search(r"lição #(\d+)", t)
    marca = f"    # lição #{m.group(1)}\n" if m else ""
    (w / "test_app.py").write_text(f"from app import soma\n\ndef test_soma():\n{marca}    assert soma(2, 2) == 4\n")


def test_sem_teste_novo_o_pr_nao_nasce_e_o_developer_corrige_antes(circle, repo):  # noqa: F811
    item_do_loop(circle)
    gh = FakeGH()
    agente = Agente(corrige, com_teste)            # 1ª: só o código (barrado: sem teste); 2ª: acrescenta o teste
    r = SelfDeveloper(circle.ctx, repo, agente, gh, test_cmd=TEST_CMD).run_once()
    assert r.status == "proposto" and len(gh.prs) == 1
    assert "BARRADA nos portões" in agente.tasks[1] and "teste novo" in agente.tasks[1]
    falhou = circle.store.one("SELECT ok FROM verificacoes WHERE ponto=? ORDER BY id LIMIT 1", (f"{ABRIR_PR}:teste_novo",))
    assert falhou["ok"] == 0


def test_portao_nato_barra_constituicao_e_nada_e_enviado(circle, repo):  # noqa: F811
    item_do_loop(circle)

    def mexe_na_constituicao(w, t):
        corrige(w, t)
        com_teste(w, t)
        (w / "circulo").mkdir(exist_ok=True)
        (w / "circulo" / "merge_gate.py").write_text("# afrouxar o gate\n")
    gh = FakeGH()
    r = SelfDeveloper(circle.ctx, repo, Agente(mexe_na_constituicao, mexe_na_constituicao), gh, test_cmd=TEST_CMD).run_once()
    assert r.status == "fora_do_alcance" and gh.prs == [] and "constituição" in r.detalhe   # vai para você, sem retentar


def test_licao_de_estrutura_cria_portao_e_o_pr_precisa_provar_a_licao(circle, repo):  # noqa: F811
    lic = circle.licoes.verificar("planejador:saida", False, motivo="sem JSON", assinatura="planejador:saida_invalida")
    ps = portoes(circle.store, ABRIR_PR, lic["item_id"])
    assert len(ps) == 1 and ps[0]["tipo"] == "obrigatorio" and ps[0]["licao_id"] == lic["id"]
    assert portoes(circle.store, ABRIR_PR, item_id=None) == []        # vale só para o item da lição
    circle.store.x("UPDATE roadmap SET status='feito' WHERE id!=?", (lic["item_id"],))

    def teste_sem_marca(w, t):
        corrige(w, t)
        (w / "test_app.py").write_text("from app import soma\n\ndef test_soma():\n    assert soma(2, 2) == 4\n")
    gh = FakeGH()
    agente = Agente(teste_sem_marca, com_teste)
    r = SelfDeveloper(circle.ctx, repo, agente, gh, test_cmd=TEST_CMD).run_once()
    assert r.status == "proposto"
    assert f"lição #{lic['id']}" in agente.tasks[0]                    # a tarefa já avisa
    assert "aprendido" in agente.tasks[1]                              # barrado pelo portão aprendido, corrigido
    assert circle.store.one("SELECT bloqueios FROM portoes")["bloqueios"] == 1


def test_licao_de_lint_vira_portao_executavel(circle):
    circle.licoes.verificar("gate:ci", False, motivo="a.py:1:1: B905 zip sem strict (ruff)")
    [p] = portoes(circle.store, ABRIR_PR)
    assert p["tipo"] == "comando" and p["spec"]["argv"][:2] == ["-m", "ruff"] and "B905" in p["spec"]["argv"]
    assert circle.store.one("SELECT 1 FROM alerts WHERE message LIKE 'Neurogênese%'")


def test_portao_so_aceita_comandos_da_allowlist(circle):
    assert criar_portao(circle.store, ABRIR_PR, "comando", {"argv": ["-c", "import os; os.remove('x')"]}, "x", None) is None
    assert criar_portao(circle.store, ABRIR_PR, "outro", {}, "x", None) is None


def test_portoes_natos_espelham_o_gate_do_merge():
    r = {x.portao: x.ok for x in portoes_natos_pr([{"filename": "circulo/engine.py", "additions": 900, "deletions": 0}])}
    assert r == {"constituição intacta": True, "tamanho": False, "teste novo": False, "sem marcador de conflito": True}
    r = {x.portao: x.ok for x in portoes_natos_pr([{"filename": "tests/test_a.py", "additions": 3, "deletions": 0}],
                                                  {"tests/test_a.py": ["<<<<<<< HEAD", "x = 1", "======="]})}
    assert r["sem marcador de conflito"] is False


def test_cerebros_agrupam_neuronios(circle):
    L = circle.licoes
    L.verificar("developer:testes", True)
    L.verificar("missao:evidencia", False, sujeito="Portal do fotógrafo", motivo="nota caiu", licao=False)
    nomes = {c["cerebro"]: c for c in cerebros(circle.store)}
    assert "Cérebro do Loop" in nomes and "Cérebro da missão Portal do fotógrafo" in nomes
    assert nomes["Cérebro da missão Portal do fotógrafo"]["falhas"] == 1

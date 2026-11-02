"""1.75 — Fabricante: o loop entrega um pedido de repositório cliente com plano, teste antes do código, técnicas,
revisão cruzada e evidência (ADR 0014). De ponta a ponta com um remoto git local e um agente falso que escreve de
verdade no clone, como o Claude Code faria."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from circulo import fabricante, repo_cliente
from circulo.fabricante import Fabricante, ferramentas_do_kit, plano_valido, proximo, vermelho_na_base
from circulo.kit import Kit

FIXTURE = Path(__file__).parent / "fixtures" / "repo_cliente"
PLANO = """Suposições: subtrair recebe dois inteiros.
1. Escrever tests/teste_sub.py com test_subtrair → verificar: python -m pytest -q falha
2. Implementar subtrair em calc.py → verificar: python -m pytest -q passa
Arquivos: tests/teste_sub.py, calc.py
Custo: nenhum
"""
TESTE = "from calc import subtrair\n\n\ndef test_subtrair():\n    assert subtrair(5, 3) == 2\n"
CODIGO = "\n\ndef subtrair(a: int, b: int) -> int:\n    return a - b\n"


def git(cwd, *args) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class AgenteFalso:
    """Fase de plano devolve o plano; fase de implementar escreve teste e código (na ordem pedida); correção corrige."""

    def __init__(self, plano=PLANO, implementar=None, modelo="claude-opus-5-5"):
        self.plano, self.implementar, self.modelo = plano, implementar, modelo
        self.chamadas: list[dict] = []
        self.ouvinte = None

    def run(self, task, workdir, sessao=None, ferramentas=None):
        self.chamadas.append({"task": task, "sessao": sessao, "ferramentas": ferramentas})
        wd = Path(workdir)
        if "NÃO edite nada nesta fase" in task:
            return {"ok": True, "tokens": 10, "log": "", "modelo": self.modelo, "passos": [], "sessao": "s1", "resposta": self.plano}
        if self.implementar is not None:
            return {"ok": True, "tokens": 50, "log": "", "modelo": self.modelo, "sessao": "s1", **self.implementar(wd, task)}
        (wd / "tests" / "teste_sub.py").write_text(TESTE, encoding="utf-8")
        (wd / "calc.py").write_text((wd / "calc.py").read_text() + CODIGO, encoding="utf-8")
        return {"ok": True, "tokens": 50, "log": "", "modelo": self.modelo, "sessao": "s1",
                "passos": ["Claude Code: TodoWrite", "Claude Code: escrevendo tests/teste_sub.py", "Claude Code: rodando os testes", "Claude Code: editando calc.py"],
                "resposta": "Mudei calc.py e tests/teste_sub.py.\nVerificado: python -m pytest -q → 2 passed."}


@pytest.fixture
def fabrica(tmp_path, circle):
    """Cliente registrado, um pedido aberto (clone isolado) e o Fabricante com agente falso e PR falso."""
    remoto, pasta = tmp_path / "remoto.git", tmp_path / "cliente"
    shutil.copytree(FIXTURE, pasta)
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remoto))
    git(pasta, "init", "-q", "-b", "main")
    git(pasta, "add", "-A")
    git(pasta, "commit", "-q", "-m", "inicial")
    git(pasta, "remote", "add", "origin", remoto.as_uri())
    git(pasta, "push", "-q", "origin", "main")
    reg = repo_cliente.registrar(circle.store, pasta)
    pedido = repo_cliente.receber(circle.store, reg["id"], "Criar a função subtrair em calc.py", tmp_path / "fabrica")
    prs = []
    fab = Fabricante(circle.ctx, AgenteFalso(), abrir_pr=lambda k, r, branch, titulo, corpo: prs.append((branch, titulo, corpo)) or f"pr://{branch}")
    return {"circle": circle, "store": circle.store, "remoto": remoto, "pedido": pedido, "fab": fab, "prs": prs, "reg": reg}


# ---------------------------------------------------------------- medidas puras

def test_plano_valido_exige_passos_numerados_com_verificacao_e_arquivos():
    assert plano_valido(PLANO) == (True, "")
    assert not plano_valido("vou fazer e pronto")[0]
    assert "sem 'verificar'" in plano_valido("1. fazer a\n2. fazer b\nArquivos: a.py")[1]
    assert "Arquivos" in plano_valido("1. a → verificar: x\n2. b → verificar: y")[1]


def test_ferramentas_do_kit_somam_os_executaveis_do_cliente():
    k = Kit(nome="esteira", pasta="/x", testes="dotnet test Esteira.sln", lint=None, etapas={"pedido": (), "estudo": (), "desenvolvimento": ("dotnet build Esteira.sln",), "pr": ("bash scripts/portoes.sh",), "merge": ()})
    f = ferramentas_do_kit(k, ("Bash(python:*)", "Bash(pytest:*)"))
    assert "Bash(dotnet:*)" in f and "Bash(bash:*)" in f and "TodoWrite" in f and f.count("Bash(dotnet:*)") == 1
    assert "Bash(python:*)" in f


def test_vermelho_na_base_prova_que_o_teste_novo_falha_no_codigo_antigo(fabrica):
    clone = Path(fabrica["pedido"]["pasta"])
    assert not vermelho_na_base(clone, "origin/main", [], "python -m pytest -q")[0]
    (clone / "tests" / "teste_sub.py").write_text(TESTE, encoding="utf-8")
    ok, det = vermelho_na_base(clone, "origin/main", ["tests/teste_sub.py"], "python -m pytest -q")
    assert ok and "falham na base" in det
    (clone / "tests" / "teste_sub.py").write_text("def test_nada():\n    assert True\n", encoding="utf-8")
    ok, det = vermelho_na_base(clone, "origin/main", ["tests/teste_sub.py"], "python -m pytest -q")
    assert not ok and "PASSAM no código antigo" in det
    assert not list(clone.glob("**/circulo-base-*"))           # worktree temporário removido


# ---------------------------------------------------------------- de ponta a ponta

def test_fabricante_entrega_o_pedido_com_plano_teste_antes_tecnicas_validador_e_pr(fabrica):
    fab, store, remoto, pedido = fabrica["fab"], fabrica["store"], fabrica["remoto"], fabrica["pedido"]
    assert proximo(store)["id"] == pedido["id"]
    res = fab.run_once()
    assert res["status"] == "entregue" and res["pr"] == f"pr://circulo/{pedido['id']}", res
    # o remoto do cliente recebeu só a branch do pedido, com teste e código
    assert git(remoto, "rev-parse", "--verify", f"refs/heads/circulo/{pedido['id']}")
    assert git(remoto, "show", f"circulo/{pedido['id']}:tests/teste_sub.py") == TESTE.strip()
    assert "subtrair" not in git(remoto, "show", "main:calc.py")
    # evidência de cada fase guardada no loop (ficha do pedido) e em verificacoes
    etapas = {e["etapa"]: e for e in repo_cliente.evidencias(store, pedido["id"])}
    for fase in ("plano", "implementar", "teste_vermelho", "teste_verde", "tecnicas", "validador", "entrega", "pr"):
        assert etapas[fase]["ok"], fase
    assert "1. Escrever tests/teste_sub.py" in etapas["plano"]["saida"]
    assert "falham na base" in etapas["teste_vermelho"]["saida"]
    pontos = {r["ponto"] for r in store.q("SELECT DISTINCT ponto FROM verificacoes WHERE ok=1")}
    assert {"fabrica:plano", "fabrica:teste_vermelho", "fabrica:teste_verde", "fabrica:entrega", "tecnica:plano_antes",
            "tecnica:teste_antes", "tecnica:cirurgica", "tecnica:simplicidade", "tecnica:resposta_direta"} <= pontos
    cruzada = store.one("SELECT ok, motivo FROM verificacoes WHERE ponto='tecnica:revisao_cruzada' ORDER BY id DESC")
    assert cruzada["ok"] == 0 and "não revisou" in cruzada["motivo"]        # sem LLM nos testes: a medida diz a verdade
    # o agente: fase de plano só leitura, implementação na mesma sessão com o plano e as técnicas, ferramentas do kit
    ch = fab.agent.chamadas
    assert len(ch) == 2 and ch[0]["ferramentas"] == fabricante.LEITURA and ch[1]["sessao"] == "s1"
    assert PLANO.strip() in ch[1]["task"] and "MUDANÇA CIRÚRGICA" in ch[1]["task"] and "Bash(python:*)" in ch[1]["ferramentas"]
    # PR com a evidência no corpo; pedido fechado; fila vazia
    [(branch, titulo, corpo)] = fabrica["prs"]
    assert branch == f"circulo/{pedido['id']}" and "teste_vermelho: ✓" in corpo and "Criar a função subtrair" in titulo
    assert store.one("SELECT status FROM pedidos_repo WHERE id=?", (pedido["id"],))["status"] == "entregue"
    assert proximo(store) is None and fab.run_once() == {"status": "nada"}


def test_teste_que_nao_falha_na_base_barra_e_a_correcao_na_mesma_sessao_salva(fabrica):
    """TDD provado: o 1º teste já passa no código antigo → barrado; a rodada de correção escreve o teste certo."""
    fab, store, pedido = fabrica["fab"], fabrica["store"], fabrica["pedido"]
    rodadas = []

    def implementar(wd, task):
        rodadas.append("correção" if "BARRADA" in task else "implementação")
        if len(rodadas) == 1:
            (wd / "tests" / "teste_sub.py").write_text("def test_nada():\n    assert True\n", encoding="utf-8")
            (wd / "calc.py").write_text((wd / "calc.py").read_text() + CODIGO, encoding="utf-8")
        else:
            (wd / "tests" / "teste_sub.py").write_text(TESTE, encoding="utf-8")
        return {"passos": ["Claude Code: TodoWrite", "Claude Code: escrevendo tests/teste_sub.py", "Claude Code: editando calc.py"], "resposta": "ok"}
    fab.agent.implementar = implementar
    res = fab.run_once()
    assert res["status"] == "entregue" and rodadas == ["implementação", "correção"]
    assert "PASSAM no código antigo" in fab.agent.chamadas[2]["task"]
    vermelhos = [e for e in repo_cliente.evidencias(store, pedido["id"]) if e["etapa"] == "teste_vermelho"]
    assert [e["ok"] for e in vermelhos] == [False, True]


def test_pedido_barrado_duas_vezes_fica_vermelho_volta_a_fila_e_esgota(fabrica, monkeypatch):
    fab, store, pedido = fabrica["fab"], fabrica["store"], fabrica["pedido"]
    fab.agent.implementar = lambda wd, task: ((wd / "calc.py").write_text((wd / "calc.py").read_text() + CODIGO, encoding="utf-8"),
                                               {"passos": ["Claude Code: editando calc.py"], "resposta": "ok"})[1]      # código sem teste
    res = fab.run_once()
    assert res["status"] == "vermelho" and "nenhum arquivo de teste" in res["motivo"] and res["tentativas"] == 1
    assert store.one("SELECT status FROM pedidos_repo WHERE id=?", (pedido["id"],))["status"] == "vermelho"
    assert proximo(store)["id"] == pedido["id"]                       # volta à fila com o motivo
    res2 = fab.run_once()
    assert "Tentativa anterior barrada" in fab.agent.chamadas[-3]["task"] or any("Tentativa anterior" in c["task"] for c in fab.agent.chamadas)
    assert res2["tentativas"] == 2
    res3 = fab.run_once()
    assert res3["esgotou"] and proximo(store) is None
    assert any("esgotou" in r["message"] for r in store.q("SELECT message FROM alerts WHERE kind='saude'"))


def test_sem_plano_valido_o_fabricante_nao_implementa(fabrica):
    fab, store, pedido = fabrica["fab"], fabrica["store"], fabrica["pedido"]
    fab.agent.plano = "vou fazer rapidinho"
    res = fab.run_once()
    assert res["status"] == "vermelho" and "sem plano" in res["motivo"]
    assert all("NÃO edite nada" in c["task"] for c in fab.agent.chamadas) and len(fab.agent.chamadas) == 2
    assert [e["ok"] for e in repo_cliente.evidencias(store, pedido["id"]) if e["etapa"] == "plano"] == [False, False]


def test_clone_sumido_e_refeito_antes_de_trabalhar(fabrica):
    fab, pedido = fabrica["fab"], fabrica["pedido"]
    shutil.rmtree(pedido["pasta"])
    assert fab.run_once()["status"] == "entregue"
    assert git(Path(pedido["pasta"]), "branch", "--show-current") == pedido["branch"]


def test_loop_poe_fabricar_no_trabalho_real_quando_ha_pedido(fabrica, monkeypatch):
    from circulo import loop as modulo
    circle = fabrica["circle"]
    assert "fabricar" in modulo.TRABALHO and modulo.IDLE_COST["fabricar"] == 0
    circle.fabricante = fabrica["fab"]
    assert circle._tem_trabalho("fabricar")
    circle._run_idle_task("fabricar")
    assert fabrica["store"].one("SELECT status FROM pedidos_repo WHERE id=?", (fabrica["pedido"]["id"],))["status"] == "entregue"
    assert not circle._tem_trabalho("fabricar")


def test_build_fabricante_nunca_dentro_de_testes(circle):
    assert fabricante.build_fabricante(circle.ctx) is None

"""O Escalador (circulo/capacidade.py): mede a carga por agente, acha o gargalo, o Jev decide subir um trabalhador — só para
quem não conflita na esteira (Arquiteto, Desenvolvedor) — e o loop roda esses agentes em paralelo."""
import json
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from circulo import capacidade, intencoes
from circulo.estudo import Estudo
from circulo.llm import LLMResult

from test_estudo import Pesquisa, resposta  # noqa: F401
from test_painel import painel  # noqa: F401
from test_self_dev import FakeGH, repo  # noqa: F401


def _ocupar(s, acao, segundos, n=1, ha=0):
    """A trilha de intenções é só de acréscimo: para datar no passado, o relógio do módulo é que anda."""
    agora = time.time() - ha
    real = intencoes.time.time
    try:
        for i in range(n):
            intencoes.time.time = (lambda t: lambda: t)(agora - segundos * (n - i))
            seq = intencoes.registrar(s, acao, "x")
            intencoes.time.time = (lambda t: lambda: t)(agora - segundos * (n - i - 1))
            intencoes.concluir(s, seq, True)
    finally:
        intencoes.time.time = real


def _fila_dev(s, n, detalhe=lambda i: "d", modulo=lambda i: None):
    """n itens estudados. `modulo` dá a pegada que o Escalador estima; sem ela, a pegada é desconhecida e ele não sobe."""
    agora = time.time()
    for i in range(n):
        s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,estudo,modulo) VALUES(?,?,'loop','pendente','x',?,?,?,'estudado',?)",
            (f"Item {i}", detalhe(i), 100 + i, agora - 1800, agora - 1800, modulo(i)))


def _cada_um_no_seu(i):
    return f"item_{i}.py"


def test_mede_ocupacao_fila_e_acha_o_gargalo(circle):
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    _ocupar(s, "corrigir_codigo", 600, n=5)          # 50 min ocupado na última hora
    _ocupar(s, "estudar_pedido", 30, n=2)
    _fila_dev(s, 6)
    med = capacidade.medir(s)
    dev = next(m for m in med if m["agente"] == "corrigir_codigo")
    assert dev["ocupacao"] >= 0.8 and dev["fila"] == 6 and dev["tarefas_1h"] == 5 and dev["sobrecarregado"] and dev["escalavel"]
    assert dev["espera_s"] >= 1700 and med[0]["agente"] == "corrigir_codigo"           # ordenado por carga
    g = capacidade.gargalo(med)
    assert g["agente"] == "corrigir_codigo" and "worktrees" in g["porque"]
    qa = next((m for m in med if m["agente"] == "revisar_prs"), None)
    assert qa is None or not qa["escalavel"]


def test_jev_decide_subir_um_trabalhador_so_para_quem_escala_e_desce_com_fila_vazia(circle):
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    _ocupar(s, "corrigir_codigo", 600, n=5)
    _ocupar(s, "revisar_prs", 600, n=5)
    _fila_dev(s, 6, modulo=_cada_um_no_seu)          # o Developer só sobe com o par que pegaria em módulos disjuntos
    for _ in range(5):
        s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(?,2,'x','b','aberto',?,?)", (900 + _, time.time(), time.time()))
    r = capacidade.rodar(s, circle.ctx.dl)
    assert any(a["agente"] == "corrigir_codigo" and a["acao"] == "subir" and a["para"] == 2 for a in r["acoes"])
    assert not any(a["agente"] == "revisar_prs" for a in r["acoes"])                    # QA nunca escala
    assert capacidade.trabalhadores(s, "corrigir_codigo") == 2 and capacidade.trabalhadores(s, "revisar_prs") == 1
    assert s.one("SELECT COUNT(*) n FROM alerts WHERE kind='capacidade'")["n"] == 1
    r2 = capacidade.rodar(s, circle.ctx.dl)                                                # 15 min entre escaladas
    assert not r2["acoes"]
    s.x("UPDATE roadmap SET status='feito'")
    cap = s.get(capacidade.KV)
    cap["corrigir_codigo"]["desde"] = time.time() - 700
    s.set(capacidade.KV, cap)
    r3 = capacidade.rodar(s, circle.ctx.dl)
    assert any(a["acao"] == "descer" and a["para"] == 1 for a in r3["acoes"]) and capacidade.trabalhadores(s, "corrigir_codigo") == 1
    res = capacidade.resumo(s)
    assert len(res["historico"]) == 2 and res["max_paralelo"] == capacidade.MAX_PARALELO
    assert "corrigir_codigo" in res["escalaveis"] and "revisar_prs" in res["nao_escalaveis"]


def test_arquiteto_estuda_varios_itens_ao_mesmo_tempo(circle, monkeypatch):
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    agora = time.time()
    for i in range(3):
        s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,'loop','pendente','pedido',?,?,?)", (f"Estudar coisa {i}", "d", 500 + i, agora, agora))
    juntos = threading.Barrier(3, timeout=10)   # só abre com os 3 estudos dentro do LLM ao mesmo tempo; em série, quebra

    class Junta(Pesquisa):
        def generate(self, *, system, prompt, model, max_tokens, web_search=0):
            juntos.wait()
            return LLMResult(json.dumps(resposta("adotar")), 100, model, [])
    circle.ctx.dl.llm = Junta({})
    s.set(capacidade.KV, {"estudar_pedido": {"trabalhadores": 3, "desde": agora}})
    out = Estudo(circle.ctx).run_paralelo(autorizado=True)
    assert len(out) == 3 and all(o and o["veredito"] == "adotar" for o in out)
    assert s.one("SELECT COUNT(*) n FROM roadmap WHERE estudo IS NOT NULL AND status='pendente'")["n"] == 3
    assert not juntos.broken


class AgenteDoModulo:
    """Cada item mexe só no seu módulo: itens distintos não compartilham arquivo e o Revisor não recusa o que terminar
    depois (lição #63: com os dois mexendo em app.py, o resultado dependia de qual thread chegava primeiro).
    A barreira só abre com os dois agentes dentro ao mesmo tempo; em série, quebra no prazo em vez de travar a suíte."""
    def __init__(self, n: int):
        self.juntos = threading.Barrier(n, timeout=5)
        self.pegos = []

    def run(self, task, workdir):
        n = re.search(r"Item (\d+)", task).group(1)
        self.pegos.append(n)
        self.juntos.wait()
        (Path(workdir) / f"item_{n}.py").write_text(f"N = {n}\n")
        (Path(workdir) / f"test_item_{n}.py").write_text(f"from item_{n} import N\n\n\ndef test_n():\n    assert N == {n}\n")
        return {"ok": True, "tokens": 1, "log": "ok"}


def test_desenvolvedor_pega_itens_distintos_em_paralelo(circle, repo):  # noqa: F811
    from circulo.self_dev import SelfDeveloper
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    _fila_dev(s, 3)
    s.x("UPDATE roadmap SET modulo='item_' || substr(titulo, 6) || '.py' WHERE titulo LIKE 'Item %'")
    agente = AgenteDoModulo(2)
    dev = SelfDeveloper(circle.ctx, repo, agente, FakeGH(), test_cmd=["python3", "-c", "import glob, runpy; [runpy.run_path(f)['test_n']() for f in glob.glob('test_item_*.py')]"])
    assert [i["titulo"] for i in dev.picks(2)] == ["Item 0", "Item 1"]
    s.set(capacidade.KV, {"corrigir_codigo": {"trabalhadores": 2, "desde": time.time()}})
    r = dev.run_paralelo(autorizado=True)
    assert sorted(agente.pegos) == ["0", "1"]                                             # dois itens distintos, ao mesmo tempo
    assert r.status == "proposto"
    assert s.one("SELECT COUNT(*) n FROM alerts WHERE message LIKE 'Developer abriu correção%'")["n"] == 2   # dois PRs (o GitHub falso numera os dois como #42)
    assert s.one("SELECT COUNT(*) n FROM roadmap WHERE status='em_andamento'")["n"] == 2
    assert s.one("SELECT COUNT(*) n FROM alerts WHERE message LIKE 'Developer (paralelo)%'")["n"] == 1


def _dev(circle, repo, agente):  # noqa: F811
    from circulo.self_dev import SelfDeveloper
    return SelfDeveloper(circle.ctx, repo, agente, FakeGH(), test_cmd=["python3", "-c", "import glob, runpy; [runpy.run_path(f)['test_n']() for f in glob.glob('test_item_*.py')]"])


VINTE = range(20)   # critério de aceite: 20 execuções seguidas sem flakiness, na suíte (o Barrier prova a sobreposição)


@pytest.mark.parametrize("rodada", VINTE)
def test_escalador_com_3_estudados_e_pegadas_disjuntas_sobe_2_developers_e_abre_2_prs_sem_conflito(circle, repo, rodada):  # noqa: F811
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    _fila_dev(s, 3, modulo=_cada_um_no_seu)            # 3 estudados, cada um no seu módulo; ninguém ocupado ainda
    r = capacidade.rodar(s, None)
    assert [a for a in r["acoes"] if a["agente"] == "corrigir_codigo"] == [{"agente": "corrigir_codigo", "acao": "subir", "para": 2, "conf": 1.0}]
    agente = AgenteDoModulo(2)                         # Barrier(2) com prazo: só abre com os dois Developers dentro ao mesmo tempo
    dev = _dev(circle, repo, agente)
    dev.run_paralelo(autorizado=True)
    assert sorted(agente.pegos) == ["0", "1"] and not agente.juntos.broken
    branches = [pr[0] for pr in dev.gh.prs]
    assert len(branches) == 2                          # dois PRs no mesmo giro
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=repo, check=True)
    merge = subprocess.run(["git", "merge-tree", "--write-tree", f"origin/{branches[0]}", f"origin/{branches[1]}"], cwd=repo, capture_output=True, text=True)
    assert merge.returncode == 0, merge.stdout        # 0 conflitos de merge entre os dois


@pytest.mark.parametrize("rodada", VINTE)
def test_escalador_serializa_par_com_pegadas_sobrepostas(circle, repo, rodada):  # noqa: F811
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    _ocupar(s, "corrigir_codigo", 600, n=5)            # sobrecarregado: sem a partição, subiria
    _fila_dev(s, 3, detalhe=lambda i: "mexe em circulo/comum.py" if i < 2 else "d", modulo=_cada_um_no_seu)   # 0 e 1: módulos diferentes, mesma área
    s.set(capacidade.KV, {"corrigir_codigo": {"trabalhadores": 2, "desde": time.time()}})
    r = capacidade.rodar(s, None)
    assert any(a["agente"] == "corrigir_codigo" and a["acao"] == "descer" and a["para"] == 1 for a in r["acoes"])   # na hora, sem esperar
    assert capacidade.trabalhadores(s, "corrigir_codigo") == 1
    assert "circulo/comum.py" in s.get(capacidade.KV)["corrigir_codigo"]["motivo"]
    agente = AgenteDoModulo(1)
    dev = _dev(circle, repo, agente)
    dev.run_paralelo(autorizado=True)
    assert agente.pegos == ["0"] and len(dev.gh.prs) == 1                                # um por vez
    assert not capacidade.rodar(s, None)["acoes"]                                         # e não volta a subir com o par sobreposto


def test_arquivo_de_convergencia_conta_como_colisao():
    a = capacidade.pegada({"modulo": "circulo/garimpo.py", "titulo": "x", "detalhe": "registra em circulo/licoes.py"})
    b = capacidade.pegada({"modulo": "circulo/daily.py", "titulo": "x", "detalhe": ""})
    assert a >= {"circulo/garimpo.py", "tests/test_garimpo.py", "circulo/licoes.py"} and b == {"circulo/daily.py", "tests/test_daily.py"}
    assert capacidade.colisao(a, b) == ["circulo/licoes.py"]                               # lições compartilhadas: ponto de convergência
    assert capacidade.colisao(b, capacidade.pegada({"modulo": "circulo/cli.py"})) == ["circulo/cli.py"]   # registro de comandos
    assert capacidade.colisao(b, capacidade.pegada({"modulo": "circulo/norte.py"})) == []
    assert capacidade.colisao(b, capacidade.pegada({"titulo": "sem arquivo citado"})) == ["(pegada desconhecida)"]


def test_painel_e_equipe_mostram_gargalo_e_paralelo(circle, painel):  # noqa: F811
    s = circle.store
    s.set(capacidade.KV, {"estudar_pedido": {"trabalhadores": 2, "desde": time.time()}})
    capacidade.rodar(s, None)
    j = json.loads(urllib.request.urlopen(painel + "/api/capacidade", timeout=5).read())
    assert j["paralelo"] == {"estudar_pedido": 2} and "medidas" in j
    e = json.loads(urllib.request.urlopen(painel + "/api/equipe", timeout=5).read())
    assert e["paralelo"] == {"estudar_pedido": 2} and any(m.get("capacidade") for m in e["membros"])
    html = urllib.request.urlopen(painel + "/loop", timeout=5).read().decode()
    assert 'id="saudeCapacidade"' in html and 'addEventListener("capacidade"' in html
    assert 'class="xn"' in urllib.request.urlopen(painel + "/equipe", timeout=5).read().decode()

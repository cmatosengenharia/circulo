"""O Escalador (circulo/capacidade.py): mede a carga por agente, acha o gargalo, o Jev decide subir um trabalhador — só para
quem não conflita na esteira (Arquiteto, Desenvolvedor) — e o loop roda esses agentes em paralelo."""
import json
import re
import time
import urllib.request
from pathlib import Path

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


def _fila_dev(s, n):
    agora = time.time()
    for i in range(n):
        s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,estudo) VALUES(?,?,'loop','pendente','x',?,?,?,'estudado')",
            (f"Item {i}", "d", 100 + i, agora - 1800, agora - 1800))


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
    _fila_dev(s, 6)
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
    import threading
    vistos = set()

    class Lenta(Pesquisa):
        def generate(self, *, system, prompt, model, max_tokens, web_search=0):
            vistos.add(threading.current_thread().name.split("_")[0])
            time.sleep(0.2)
            return LLMResult(json.dumps(resposta("adotar")), 100, model, [])
    circle.ctx.dl.llm = Lenta({})
    s.set(capacidade.KV, {"estudar_pedido": {"trabalhadores": 3, "desde": agora}})
    t0 = time.time()
    out = Estudo(circle.ctx).run_paralelo(autorizado=True)
    assert len(out) == 3 and all(o and o["veredito"] == "adotar" for o in out) and time.time() - t0 < 0.55   # 3 em paralelo, não 0,6 s em série
    assert s.one("SELECT COUNT(*) n FROM roadmap WHERE estudo IS NOT NULL AND status='pendente'")["n"] == 3
    assert any(v.startswith("estudo") for v in vistos)


class AgenteDoModulo:
    """Cada item mexe só no seu módulo: itens distintos não compartilham arquivo e o Revisor não recusa o que terminar
    depois (lição #63: com os dois mexendo em app.py, o resultado dependia de qual thread chegava primeiro)."""
    def __init__(self, atraso: dict | None = None):
        self.atraso = atraso or {}

    def run(self, task, workdir):
        n = re.search(r"Item (\d+)", task).group(1)
        time.sleep(self.atraso.get(n, 0))
        (Path(workdir) / f"item_{n}.py").write_text(f"N = {n}\n")
        (Path(workdir) / f"test_item_{n}.py").write_text(f"from item_{n} import N\n\n\ndef test_n():\n    assert N == {n}\n")
        return {"ok": True, "tokens": 1, "log": "ok"}


def test_desenvolvedor_pega_itens_distintos_em_paralelo(circle, repo):  # noqa: F811
    from circulo.self_dev import SelfDeveloper
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    _fila_dev(s, 3)
    s.x("UPDATE roadmap SET modulo='item_' || substr(titulo, 6) || '.py' WHERE titulo LIKE 'Item %'")
    dev = SelfDeveloper(circle.ctx, repo, AgenteDoModulo({"0": 0.5}), FakeGH(), test_cmd=["python3", "-c", "import glob, runpy; [runpy.run_path(f)['test_n']() for f in glob.glob('test_item_*.py')]"])   # o 1º termina por último
    assert [i["titulo"] for i in dev.picks(2)] == ["Item 0", "Item 1"]
    s.set(capacidade.KV, {"corrigir_codigo": {"trabalhadores": 2, "desde": time.time()}})
    r = dev.run_paralelo(autorizado=True)
    assert r.status == "proposto"
    assert s.one("SELECT COUNT(*) n FROM alerts WHERE message LIKE 'Developer abriu correção%'")["n"] == 2   # dois PRs (o GitHub falso numera os dois como #42)
    assert s.one("SELECT COUNT(*) n FROM roadmap WHERE status='em_andamento'")["n"] == 2
    assert s.one("SELECT COUNT(*) n FROM alerts WHERE message LIKE 'Developer (paralelo)%'")["n"] == 1


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

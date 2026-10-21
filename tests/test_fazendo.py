"""O que cada agente está fazendo agora (circulo/fazendo.py): registro por agente com os passos, o Claude Code em
streaming virando passos visíveis, e a Equipe ao vivo mostrando em vez de só "trabalhando"."""
import io
import json
import time

from circulo import fazendo, intencoes
from circulo.equipe import retrato


class FakePopen:
    """Um Claude Code falso em stream-json: as linhas que o loop leria, uma a uma."""
    eventos: list[dict] = []
    returncode = 0
    visto: dict = {}

    def __init__(self, cmd, **kw):
        FakePopen.visto = {"cmd": cmd, **kw}
        self.stdout = io.StringIO("".join(json.dumps(e) + "\n" for e in self.eventos))
        self.stderr = io.StringIO("")
        self.returncode = FakePopen.returncode

    def wait(self):
        return self.returncode

    def kill(self):
        pass


def _tool(nome, **inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": nome, "input": inp}]}}


RESULT = {"type": "result", "subtype": "success", "is_error": False, "usage": {"input_tokens": 120, "output_tokens": 30},
          "modelUsage": {"claude-opus-5-5": {}}, "result": "feito"}


def test_registro_por_agente_com_passos_e_termino(circle):
    s = circle.store
    fazendo.marcar(s, "estudar_pedido", "item #55: lição 22", item=55, passo="modo completo: 4 buscas")
    fazendo.marcar(s, "vigia", "sondando travas")
    fazendo.passo(s, "estudar_pedido", "lendo as fontes")
    fazendo.passo(s, "ninguem", "não existe")                                 # passo sem começo: ignorado
    a = fazendo.agora(s)
    assert set(a) == {"estudar_pedido", "vigia"} and a["estudar_pedido"]["passo"] == "lendo as fontes" and a["estudar_pedido"]["item"] == 55
    assert [p["texto"] for p in a["estudar_pedido"]["passos"]] == ["modo completo: 4 buscas", "lendo as fontes"]
    for i in range(12):
        fazendo.passo(s, "vigia", f"passo {i}")
    assert len(fazendo.agora(s)["vigia"]["passos"]) == fazendo.PASSOS                 # só os últimos
    fazendo.terminar(s, "estudar_pedido", "adotar")
    assert "estudar_pedido" not in fazendo.agora(s) and fazendo.ultimo(s)["estudar_pedido"]["resultado"] == "adotar"
    assert fazendo.agora(s, t=time.time() + fazendo.VALE_S + 1) == {}            # processo morto: some sozinho


def test_eventos_do_claude_code_viram_passos_legiveis():
    assert fazendo.passo_do_evento(_tool("Edit", file_path="/Users/x/.circulo-wt-91/circulo/diff_size.py")) == "Claude Code: editando circulo/diff_size.py"
    assert fazendo.passo_do_evento(_tool("Bash", command="python -m pytest -q tests/test_diff_size.py")) == "Claude Code: rodando os testes"
    assert fazendo.passo_do_evento(_tool("Bash", command="ruff check circulo")) == "Claude Code: rodando o lint"
    assert fazendo.passo_do_evento(_tool("Bash", command="git diff --stat")) == "Claude Code: git diff"
    assert fazendo.passo_do_evento(_tool("Read", file_path="circulo/loop.py")) == "Claude Code: lendo circulo/loop.py"
    assert fazendo.passo_do_evento({"type": "assistant", "message": {"content": [{"type": "text", "text": "Vou escrever o teste primeiro.\nDepois…"}]}}) == "Claude Code: Vou escrever o teste primeiro."
    assert fazendo.passo_do_evento({"type": "system", "subtype": "init"}) is None and fazendo.passo_do_evento(RESULT) is None


def test_claude_code_em_streaming_avisa_cada_passo_e_devolve_o_resultado(monkeypatch, tmp_path):
    from circulo.self_dev import ClaudeCodeAgent
    FakePopen.eventos = [{"type": "system", "subtype": "init"}, _tool("Read", file_path="circulo/a.py"), _tool("Edit", file_path="circulo/a.py"),
                         _tool("Bash", command="python -m pytest -q tests/test_a.py"), RESULT]
    FakePopen.returncode = 0
    monkeypatch.setattr("circulo.self_dev.subprocess.Popen", FakePopen)
    ag = ClaudeCodeAgent()
    vistos = []
    ag.ouvinte = vistos.append
    out = ag.run("tarefa", tmp_path)
    assert out["ok"] and out["tokens"] == 150 and out["modelo"] == "claude-opus-5-5" and '"is_error": false' in out["log"]
    assert vistos == ["Claude Code: lendo circulo/a.py", "Claude Code: editando circulo/a.py", "Claude Code: rodando os testes"] and out["passos"] == vistos
    cmd = FakePopen.visto["cmd"]
    assert "stream-json" in cmd and "--verbose" in cmd and "--allowedTools" in cmd
    FakePopen.eventos = [{**RESULT, "is_error": True, "result": "Failed to authenticate: OAuth session expired"}]
    out = ag.run("tarefa", tmp_path)
    assert not out["ok"] and "OAuth session expired" in out["log"]           # o _limite do Developer continua lendo o log


def test_toda_tarefa_do_giro_marca_comeco_e_fim_e_a_equipe_mostra(circle):
    s = circle.store
    visto = {}
    s.set("batimento", {"em": time.time(), "pid": 1, "proximo_giro_em": time.time() + 60})

    def tarefa():
        visto["durante"] = fazendo.agora(s).get("estudar_pedido")
        fazendo.passo(s, "estudar_pedido", "lendo as fontes")
        r = retrato(s)
        visto["membro"] = next(m for m in r["membros"] if m["id"] == "estudar_pedido")
        return 1
    intencoes.executar(s, "estudar_pedido", tarefa, motivo="Estudando o próximo pedido")
    assert visto["durante"]["o_que"] == "Estudando o próximo pedido"
    m = visto["membro"]
    assert m["estado"] == "trabalhando" and "lendo as fontes" in m["agora"] and m["fazendo"]["passos"][-1]["texto"] == "lendo as fontes"
    assert fazendo.agora(s) == {} and fazendo.ultimo(s)["estudar_pedido"]["resultado"] == "ok"
    m2 = next(m for m in retrato(s)["membros"] if m["id"] == "estudar_pedido")
    assert m2["estado"] != "trabalhando" and m2["ultimo"]["resultado"] == "ok"
    try:
        intencoes.executar(s, "indagar", lambda: 1 / 0, motivo="x")
    except ZeroDivisionError:
        pass
    assert fazendo.ultimo(s)["indagar"]["resultado"] == "falhou: ZeroDivisionError"


def test_tela_da_equipe_tem_os_passos(painel):  # noqa: F811
    import urllib.request
    html = urllib.request.urlopen(painel + "/equipe", timeout=5).read().decode()
    assert 'class="passos"' in html and "m.fazendo" in html


from test_painel import painel  # noqa: E402,F401 — fixture do servidor do painel

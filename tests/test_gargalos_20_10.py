"""Os gargalos medidos no Mac em 20/10 (1.5 M tokens para 7 itens): o Desenvolvedor não podia rodar teste nem lint
(pedia aprovação e o item voltava barrado), um portão aprendido apontava para um teste que já não existia (135 vezes),
o estudo voltava sem texto porque a busca comia o teto de tokens, e o mesmo aviso de saúde entrava 20× por hora."""
import json
import sys
import time
from pathlib import Path

from circulo.estudo import MODOS, Estudo
from circulo.llm import LLMResult
from circulo.neuronios import ABRIR_PR, avaliar_aprendidos, criar_portao, portoes
from circulo.self_dev import FERRAMENTAS, ClaudeCodeAgent, SelfDeveloper

from test_estudo import Pesquisa, pedido  # noqa: F401


def test_desenvolvedor_pode_rodar_testes_lint_e_git_de_leitura_sozinho(monkeypatch, tmp_path):
    visto = {}

    def falso_run(cmd, **kw):
        visto["cmd"] = cmd

        class P:
            returncode, stdout, stderr = 0, '{"usage":{"input_tokens":1,"output_tokens":1}}', ""
        return P()
    monkeypatch.setattr("subprocess.run", falso_run)
    monkeypatch.delenv("CIRCULO_CODE_AGENT_FERRAMENTAS", raising=False)
    ClaudeCodeAgent().run("tarefa", tmp_path)
    i = visto["cmd"].index("--allowedTools")
    permitidas = visto["cmd"][i + 1].split(",")
    assert "Bash(pytest:*)" in permitidas and "Bash(ruff:*)" in permitidas and "Bash(git diff:*)" in permitidas and "Bash(python:*)" in permitidas
    assert not any(x.startswith(("Bash(git push", "Bash(git commit", "Bash(rm")) for x in permitidas)   # nada que saia do worktree
    assert "--permission-mode" in visto["cmd"] and list(permitidas) == list(FERRAMENTAS)
    monkeypatch.setenv("CIRCULO_CODE_AGENT_FERRAMENTAS", "Bash(pytest:*)")
    ClaudeCodeAgent().run("tarefa", tmp_path)
    assert visto["cmd"][visto["cmd"].index("--allowedTools") + 1] == "Bash(pytest:*)"


def test_espera_vencida_do_desenvolvedor_some_do_banco(circle, tmp_path):
    dev = SelfDeveloper(circle.ctx, tmp_path, agent=None, github=None)
    circle.store.set("self_dev_espera", {"ate": time.time() - 1, "motivo": "Claude Code deslogado", "hora": "18:40", "precisa_de_voce": True})
    assert not dev.em_espera() and circle.store.get("self_dev_espera") is None
    circle.store.set("self_dev_espera", {"ate": time.time() + 600, "motivo": "limite", "hora": "19:00"})
    assert dev.em_espera() and circle.store.get("self_dev_espera")


def test_portao_com_teste_inexistente_vira_obsoleto_e_nao_bloqueia(circle, tmp_path):
    s = circle.store
    agora = time.time()
    lid = s.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,created_at,updated_at) VALUES('developer:abrir_pr:x','developer','trabalho','d','p','aberta',1,0,?,?)", (agora, agora))
    pid = criar_portao(s, ABRIR_PR, "comando", {"argv": ["-m", "pytest", "-q", "tests/test_nao_existe.py::test_x"]}, "teste tests/test_nao_existe.py::test_x", licao_id=lid)
    (tmp_path / "tests").mkdir()
    [r] = avaliar_aprendidos(s, ABRIR_PR, tmp_path, {}, {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(Path(sys.executable).parent)})
    assert r.ok and "não existe mais" in r.motivo
    assert portoes(s, ABRIR_PR) == [] and s.one("SELECT ativo FROM portoes WHERE id=?", (pid,))["ativo"] == 0
    assert s.one("SELECT status FROM licoes WHERE id=?", (lid,))["status"] == "obsoleta"


def test_estudo_sem_texto_tenta_de_novo_sem_busca_com_teto_maior(circle):
    class Engolida(Pesquisa):
        def generate(self, *, system, prompt, model, max_tokens, web_search=0):
            self.chamadas.append({"web_search": web_search, "max_tokens": max_tokens})
            if web_search:
                return LLMResult("", 13000, model, [])                       # a busca comeu a resposta
            return LLMResult(json.dumps({"veredito": "adotar", "justificativa": "ok", "achados": [{"ideia": "x", "fonte": "f", "url": "https://a.org/x", "base": "inferido"}]}), 800, model, [])
    pedido(circle)
    circle.ctx.dl.llm = llm = Engolida({})
    r = Estudo(circle.ctx).run()
    assert r and r["veredito"] == "adotar"
    assert [c["web_search"] for c in llm.chamadas] == [4, 0] and llm.chamadas[0]["max_tokens"] == MODOS["completo"]["max_tokens"] >= 8000
    assert circle.store.one("SELECT ok FROM llm_calls WHERE papel='estudo' ORDER BY id DESC LIMIT 1")["ok"] == 1


def test_aviso_de_saude_igual_nao_repete_na_mesma_hora(circle):
    s = circle.store
    for _ in range(5):
        circle.ctx.reply("Developer: “x” foi barrado nos portões antes do PR; nada foi enviado.", "saude")
    circle.ctx.reply("Developer: “x” foi barrado nos portões antes do PR; nada foi enviado.", "merge")
    circle.ctx.reply("outro aviso", "saude")
    assert s.one("SELECT COUNT(*) n FROM alerts WHERE kind='saude'")["n"] == 2 and s.one("SELECT COUNT(*) n FROM alerts WHERE kind='merge'")["n"] == 1

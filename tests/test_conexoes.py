"""Conexões ao vivo (circulo/conexoes.py): cada chamada externa vira um pulso e a faixa do painel diz, por serviço,
se o Jev, o Claude Code, a LLM, o GitHub e o próprio loop estão respondendo agora — sem gastar nada para olhar."""
import json
import time
import urllib.error

from circulo import conexoes
from circulo.merge_gate import GitHubREST


def _llm(s, papel, ok, erro=None, ha=0, ms=120):
    s.x("INSERT INTO llm_calls(tick,papel,modelo,decidido_por,tokens,duracao_ms,ok,erro,created_at) VALUES(1,?,'m','fixo',10,?,?,?,?)",
        (papel, ms, 1 if ok else 0, erro, time.time() - ha))


def test_pulsos_viram_estado_ok_instavel_fora_e_ocioso(circle):
    s = circle.store
    agora = time.time()
    assert {x["servico"]: x["estado"] for x in conexoes.estado(s, agora)["servicos"]}["github"] in ("ocioso", "sem_chave")
    for _ in range(5):
        conexoes.pulso(s, "github", True, 230)
    g = next(x for x in conexoes.estado(s, agora)["servicos"] if x["servico"] == "github")
    assert g["estado"] == "ok" and g["latencia_ms"] == 230 and g["chamadas_1h"] == 5 and g["falhas_1h"] == 0 and len(g["serie"]) == 5
    conexoes.pulso(s, "github", False, 15000, "GET /pulls: timeout")
    g = next(x for x in conexoes.estado(s, agora)["servicos"] if x["servico"] == "github")
    assert g["estado"] == "instavel" and g["ultimo_erro"]["texto"] == "GET /pulls: timeout"
    conexoes.pulso(s, "github", False, 15000, "GET /pulls: timeout")
    g = next(x for x in conexoes.estado(s, agora)["servicos"] if x["servico"] == "github")
    assert g["estado"] == "fora" and conexoes.estado(s, agora)["resumo"].startswith("fora: GitHub")


def test_llm_e_claude_code_vem_de_llm_calls_e_a_espera_do_desenvolvedor_aparece(circle):
    s = circle.store
    agora = time.time()
    _llm(s, "estudo", True, ms=900)
    _llm(s, "developer", False, "Failed to authenticate: OAuth session expired", ha=30)
    _llm(s, "developer", False, "Failed to authenticate: OAuth session expired", ha=10)
    e = {x["servico"]: x for x in conexoes.estado(s, agora)["servicos"]}
    assert e["llm"]["estado"] == "ok" and e["llm"]["latencia_ms"] == 900 and e["llm"]["chamadas_1h"] == 1
    assert e["claude"]["estado"] == "fora" and "OAuth" in e["claude"]["ultimo_erro"]["texto"]
    s.set("self_dev_espera", {"ate": agora + 600, "motivo": "Claude Code deslogado no Mac", "hora": "18:07", "precisa_de_voce": True})
    e = {x["servico"]: x for x in conexoes.estado(s, agora)["servicos"]}
    assert e["claude"]["estado"] == "parado" and "18:07" in e["claude"]["detalhe"]


def test_batimento_do_loop_e_o_quinto_servico(circle):
    s = circle.store
    agora = time.time()
    lp = next(x for x in conexoes.estado(s, agora)["servicos"] if x["servico"] == "loop")
    assert lp["estado"] == "fora" and "batimento" in lp["detalhe"]
    s.set("batimento", {"em": agora - 5, "pid": 1, "proximo_giro_em": agora + 60})
    lp = next(x for x in conexoes.estado(s, agora)["servicos"] if x["servico"] == "loop")
    assert lp["estado"] == "ok" and lp["ultima_ok"] == agora - 5
    s.set("batimento", {"em": agora - 900, "pid": 1, "proximo_giro_em": agora - 800})
    assert next(x for x in conexoes.estado(s, agora)["servicos"] if x["servico"] == "loop")["estado"] == "fora"


def test_jev_fora_do_ar_deixa_pulso_de_falha_e_o_local_nao_conta(circle):
    class Down:
        source = "jev"

        def ask_many(self, state, questions):
            raise TimeoutError("timeout")

    circle.submit("38,90 ifood almoço")
    circle.tick()
    assert conexoes.estado(circle.store)["servicos"][0]["chamadas_1h"] == 0          # LocalJev: não é conexão
    circle.ctx.dl.jev = Down()
    circle.submit("12,00 padaria pão")
    circle.tick()
    j = conexoes.estado(circle.store)["servicos"][0]
    assert j["servico"] == "jev" and j["falhas_1h"] >= 1 and j["ultimo_erro"]["texto"] == "timeout"


def test_cliente_do_github_avisa_o_ouvinte_sem_conhecer_o_registro(circle, monkeypatch):
    conexoes.instalar(circle.store)
    gh = GitHubREST("x/y", "t")

    def falha(req, timeout):
        raise urllib.error.URLError("rede fora")
    monkeypatch.setattr("urllib.request.urlopen", falha)
    try:
        gh.open_prs()
    except urllib.error.URLError:
        pass
    g = next(x for x in conexoes.estado(circle.store)["servicos"] if x["servico"] == "github")
    assert g["falhas_1h"] == 1 and "GET /pulls" in g["ultimo_erro"]["texto"] and "rede fora" in g["ultimo_erro"]["texto"]
    GitHubREST.ouvinte = None


def test_painel_expoe_a_faixa_de_conexoes(circle, painel):  # noqa: F811
    import urllib.request
    j = json.loads(urllib.request.urlopen(painel + "/api/conexoes", timeout=5).read())
    assert [x["servico"] for x in j["servicos"]] == ["jev", "claude", "llm", "github", "loop"] and "resumo" in j
    html = urllib.request.urlopen(painel + "/loop", timeout=5).read().decode()
    assert 'id="conexoes"' in html and "/api/conexoes" in html


from test_painel import painel  # noqa: E402,F401 — fixture do servidor do painel


def test_403_esperado_do_check_runs_nao_e_falha_de_conexao(circle, monkeypatch):
    """Token sem a permissão Checks: o gate cai para a API do Actions por desenho; a faixa não pode chamar isso de instável."""
    import io
    conexoes.instalar(circle.store)
    gh = GitHubREST("x/y", "t")

    def resposta(req, timeout):
        if "check-runs" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b""))

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return R(json.dumps({"workflow_runs": []}).encode())
    monkeypatch.setattr("urllib.request.urlopen", resposta)
    assert gh.check_runs("abc1234") == []
    g = next(x for x in conexoes.estado(circle.store)["servicos"] if x["servico"] == "github")
    assert g["falhas_1h"] == 0 and g["chamadas_1h"] == 2 and g["estado"] == "ok"
    GitHubREST.ouvinte = None

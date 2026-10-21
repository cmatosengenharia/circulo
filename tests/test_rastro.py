"""Rastreabilidade de ponta a ponta: origem → estudo → Developer → PR → gate → versão rodando → evidência."""
import json
import re
import time

from circulo import rastro
from circulo.rastro import cadeia_item, completude, elo, localizar, trace_id, traceparent

from test_self_dev import TEST_CMD, FixAgent, erro_recorrente, git, repo  # noqa: F401 — fixture do repositório


def _item(s, titulo="Painel mostra p95", origem="loop", status="feito", criado=None):
    t = criado or time.time() - 10 * 3600
    return s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
               (titulo, "detalhe", origem, status, "x", 99, t, t))


def _pr(s, n, item_id, em, status="mergeado"):
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
        (n, None, "t", f"circulo/fix-{item_id}-{int(em)}", status, em, em))


def _merge(s, pr, em, ok=True):
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,?,?,?,?,?)",
        (pr, "abc123", int(ok), "checks verdes" if ok else "CI vermelho", "{}", em))


def test_ids_seguem_o_w3c_trace_context_e_sao_estaveis():
    t, tp = trace_id("item:36"), traceparent("item:36")
    assert re.fullmatch(r"[0-9a-f]{32}", t) and t.strip("0")
    assert re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-01", tp) and tp.split("-")[1] == t
    assert trace_id("item:36") == t and trace_id("item:37") != t


def test_fio_completo_da_pergunta_ate_a_evidencia(circle):
    s = circle.store
    agora = time.time()
    i = _item(s)
    s.x("INSERT INTO perguntas(chave,persona,texto,status,item_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
        ("k", "usuario", "Qual componente melhora a leitura das métricas?", "virou_item", i, agora - 9 * 3600, agora))
    s.x("UPDATE roadmap SET estudo=? WHERE id=?", (json.dumps({"veredito": "adotar", "fontes": ["a", "b"], "justificativa": "ok"}), i))
    elo(s, f"item:{i}", f"estudo:{i}", "estudou")
    elo(s, f"item:{i}", "giro:aaaaaaaaaaaa", "developer")
    _pr(s, 9, i, agora - 8 * 3600)
    _merge(s, 9, agora - 7 * 3600)
    elo(s, "pr:9", "versao:c371955d23bb", "entrou_em")
    elo(s, "versao:c371955d23bb", "giro:bbbbbbbbbbbb", "evidenciada")
    c = cadeia_item(s, i)
    etapas = [p["etapa"] for p in c["passos"]]
    for e in ("origem", "estudo", "developer", "pr", "gate", "versao", "evidencia", "fim"):
        assert e in etapas, e
    assert c["lacunas"] == [] and c["completo"] and c["entregue"]
    assert c["passos"][0]["titulo"].startswith("Conselho (usuario)")
    assert c["trace_id"] == trace_id(f"item:{i}")
    assert completude(s)["taxa"] == 1.0


def test_historico_antigo_ganha_fio_sem_elos(circle):
    """Entregas de antes dos elos: o fio vem da branch do PR, do merge e das verificações do corpo."""
    s = circle.store
    agora = time.time()
    i = _item(s, origem="pedido_cassio")
    _pr(s, 4, i, agora - 9 * 3600)
    _merge(s, 4, agora - 8 * 3600)
    for ponto, em in (("corpo:atualizar", agora - 7.9 * 3600), ("corpo:evidencia", agora - 7.8 * 3600)):
        s.x("INSERT INTO verificacoes(tick,ponto,sujeito,ok,created_at) VALUES(?,?,?,?,?)", (1, ponto, "c371955d23bb", 1, em))
    c = cadeia_item(s, i)
    assert c["completo"], c["lacunas"]
    assert any(p["etapa"] == "versao" and "primeira atualização" in p["detalhe"] for p in c["passos"])


def test_merge_que_nao_chega_ao_codigo_rodando_e_lacuna_e_vira_licao_uma_vez(circle):
    s = circle.store
    agora = time.time()
    i = _item(s, origem="pedido_cassio")
    _pr(s, 5, i, agora - 5 * 3600)
    _merge(s, 5, agora - 4 * 3600)
    c = cadeia_item(s, i)
    assert not c["completo"] and "não chegou ao código rodando" in c["lacunas"][0]
    assert rastro.verificar(circle.ctx) == [i]
    v = s.one("SELECT ok, assinatura FROM verificacoes WHERE ponto='rastro:cadeia'")
    assert v["ok"] == 0 and v["assinatura"] == "rastro:lacuna"
    lic = s.one("SELECT classe FROM licoes WHERE assinatura='rastro:lacuna'")
    assert lic["classe"] == "trabalho"                       # registrada, mas não trava a evolução
    assert not circle.licoes.bloqueia_evolucao()
    assert rastro.verificar(circle.ctx) == []                # cada entrega é conferida uma vez só


def test_merge_recente_ainda_nao_e_lacuna(circle):
    s = circle.store
    agora = time.time()
    i = _item(s, origem="pedido_cassio", status="em_andamento")
    _pr(s, 6, i, agora - 600, status="aberto")
    _merge(s, 6, agora - 300)
    c = cadeia_item(s, i)
    assert c["lacunas"] == [] and any(p["estado"] == "pendente" and p["etapa"] == "versao" for p in c["passos"])


def test_busca_por_qualquer_ponta(circle):
    s = circle.store
    agora = time.time()
    i = _item(s, titulo="Rastro de ponta a ponta no painel")
    _pr(s, 12, i, agora)
    assert localizar(s, "PR 12")["id"] == i
    assert localizar(s, f"#{i}")["id"] == i and localizar(s, f"item {i}")["id"] == i
    assert localizar(s, trace_id(f"item:{i}"))["id"] == i
    assert localizar(s, "ponta a ponta")["id"] == i
    pid = s.one("SELECT id FROM projects LIMIT 1")["id"]
    assert localizar(s, f"missão {pid}")["tipo"] == "missao"
    circle.tick()
    run = s.one("SELECT run_id FROM trail WHERE run_id IS NOT NULL LIMIT 1")["run_id"]
    g = localizar(s, run)
    assert g["tipo"] == "giro" and g["passos"]
    assert localizar(s, "nada-disso-existe") is None


def test_developer_grava_elos_e_leva_o_traceparent(circle, repo):  # noqa: F811
    item = erro_recorrente(circle)

    class GH:
        corpo = ""

        def create_pr(self, head, base, title, body):
            GH.corpo = body
            return 42
    from circulo.self_dev import SelfDeveloper
    agent = FixAgent()
    circle.store.set("run_id", "abcdefabcdef")
    r = SelfDeveloper(circle.ctx, repo, agent, GH(), test_cmd=TEST_CMD).run_once()
    assert r.status == "proposto"
    no = f"item:{item['id']}"
    assert agent.ambiente_extra["TRACEPARENT"] == traceparent(no)
    rel = {(e["para"], e["relacao"]) for e in rastro.elos_de(circle.store, no)}
    assert ("giro:abcdefabcdef", "developer") in rel and ("pr:42", "abriu_pr") in rel
    assert trace_id(no) in GH.corpo
    branch = circle.store.one("SELECT branch FROM prs WHERE number=42")["branch"]
    msg = git(repo.parent / "origin.git", "log", "-1", "--format=%B", branch)
    assert f"Circulo-Trace: {trace_id(no)}" in msg and f"Circulo-Item: {item['id']}" in msg


def test_claude_code_recebe_o_traceparent_no_ambiente(monkeypatch, tmp_path):
    from circulo.self_dev import ClaudeCodeAgent
    visto = {}

    from test_fazendo import RESULT, FakePopen
    FakePopen.eventos = [RESULT]
    monkeypatch.setattr("circulo.self_dev.subprocess.Popen", lambda cmd, **k: visto.update(k["env"]) or FakePopen(cmd, **k))
    ag = ClaudeCodeAgent()
    ag.ambiente_extra = {"TRACEPARENT": traceparent("item:1")}
    ag.run("x", tmp_path)
    assert visto["TRACEPARENT"] == traceparent("item:1")


def test_corpo_liga_exatamente_os_prs_que_entraram_na_versao(circle, tmp_path):
    from circulo.corpo import Corpo
    r = tmp_path / "r"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    for msg in ("base", "Painel novo (#7)", "Fix lint (#8)"):
        (r / "f.txt").write_text(msg)
        git(r, "add", "-A")
        git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)
    shas = git(r, "log", "--format=%H").splitlines()
    corpo = Corpo(circle.ctx, r, tmp_path / "dados")
    corpo._rastrear(shas[-1], shas[0])
    rel = {(e["de"], e["para"]) for e in map(dict, circle.store.q("SELECT de, para FROM elos WHERE relacao='entrou_em'"))}
    assert rel == {("pr:7", f"versao:{shas[0][:12]}"), ("pr:8", f"versao:{shas[0][:12]}")}


def test_traco_do_giro_aponta_para_o_fio_do_item(circle):
    from circulo.telemetria import ler
    circle.tick()
    run = circle.store.one("SELECT run_id FROM trail WHERE run_id IS NOT NULL ORDER BY seq DESC LIMIT 1")["run_id"]
    elo(circle.store, "item:3", f"giro:{run}", "developer")
    from circulo.telemetria import spans_do_ciclo
    spans = spans_do_ciclo(circle.store, run, circle.store.tick, time.time() - 5, time.time())
    raiz = spans[0]
    assert raiz["links"][0]["trace_id"] == trace_id("item:3") and raiz["attributes"]["circulo.itens"] == ["item:3"]
    assert ler  # o arquivo do giro real também foi gravado sem erro

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


# ---------------------------------------------------------------- 1.76.1: o clone registrado acompanha o remoto
def test_clone_registrado_avanca_e_rele_o_kit_antes_de_trabalhar(fabrica, tmp_path):
    """A esteira foi registrada antes de ter circulo.toml: `testes` ficou `python -m pytest` para um repo .NET e o clone
    3 commits atrás. Antes de cada trabalho o clone registrado dá fast-forward e o kit é relido; sujo, não é tocado."""
    store, reg, remoto = fabrica["store"], fabrica["reg"], fabrica["remoto"]
    assert store.one("SELECT testes FROM repos_cliente WHERE projeto_id=?", (reg["id"],))["testes"] == reg["testes"]
    outro = tmp_path / "outro-clone"
    git(tmp_path, "clone", "-q", remoto.as_uri(), str(outro))
    (outro / "circulo.toml").write_text('nome = "cliente"\ntestes = "python -m pytest -q --maxfail=1"\n', encoding="utf-8")   # nunca `dotnet` aqui: a 1ª execução dele no runner, morta pelo timeout, deixava ~/.nuget/NuGet/NuGet.Config vazio para o teste do esqueleto .NET
    git(outro, "add", "-A")
    git(outro, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "kit do cliente")
    git(outro, "push", "-q", "origin", "main")
    at = repo_cliente.atualizar(store, reg["id"])
    assert at == {"avancou": True, "kit_mudou": True, "erro": None, "testes": "python -m pytest -q --maxfail=1"}
    assert store.one("SELECT testes FROM repos_cliente WHERE projeto_id=?", (reg["id"],))["testes"] == "python -m pytest -q --maxfail=1"
    assert repo_cliente.atualizar(store, reg["id"])["avancou"] is False                      # já na ponta: nada a fazer
    pasta = Path(reg["caminho"])
    (pasta / "rascunho.txt").write_text("trabalho local do Cássio", encoding="utf-8")       # clone sujo: nunca é tocado
    (outro / "x.txt").write_text("x", encoding="utf-8")
    git(outro, "add", "-A")
    git(outro, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "mais um")
    git(outro, "push", "-q", "origin", "main")
    assert repo_cliente.atualizar(store, reg["id"])["avancou"] is False and (pasta / "rascunho.txt").exists()
    (pasta / "rascunho.txt").unlink()
    fab = fabrica["fab"]
    fab.run_once()
    kit = [e for e in repo_cliente.evidencias(store, fabrica["pedido"]["id"]) if e["etapa"] == "kit"]
    assert kit and kit[0]["ok"] and "--maxfail=1" in kit[0]["saida"] and "clone avançou" in kit[0]["saida"]


# ---------------------------------------------------------------- 1.76.2: o card da missão de repositório mede o Fabricante
def test_card_da_missao_repo_mede_pedidos_e_mostra_o_fabricante_trabalhando(fabrica):
    """Cássio (1/11): 'temos o card esteira na interface sem dados de que está rodando'. O card de kit repo não tem ciclos
    de missão: mede pedidos (fila, entregues, barrados), e 'Trabalhando agora' aparece quando o Fabricante está num pedido dele."""
    from circulo import projects
    store, reg, fab = fabrica["store"], fabrica["reg"], fabrica["fab"]
    antes = next(c for c in projects.cards(store) if c["id"] == reg["id"])
    assert antes["metricas"]["fabrica"] == {"abertos": 1, "entregues": 0, "vermelhos": 0, "trabalhados": 0}
    assert antes["metricas"]["principal"]["rotulo"] == "Pedidos entregues" and antes["metricas"]["principal"]["valor"] == 0.0
    assert antes["metricas"]["versao"] == "1 pedido(s)" and antes["agora"] is False
    store.set("etapa", {"nome": "fabricante", "tick": store.tick, "em": 0, "projeto": reg["id"]})
    assert next(c for c in projects.cards(store) if c["id"] == reg["id"])["agora"] is True
    fab.run_once()
    depois = next(c for c in projects.cards(store) if c["id"] == reg["id"])["metricas"]
    assert depois["fabrica"]["entregues"] == 1 and depois["fabrica"]["trabalhados"] == 1 and depois["principal"]["valor"] == 1.0
    assert depois["ciclos"] == 1 and depois["evolucoes"] == 1 and depois["prs"]["abertos"] == 1 and depois["erros_abertos"] == 0


def test_fabricar_vem_antes_do_trabalho_interno_do_loop_e_alterna_com_ele(fabrica, monkeypatch):
    """1.76.3: com pedido aberto, o giro vai ao Fabricante antes de estudar/corrigir item do loop; no giro seguinte o
    espaço de 2 dá a vez ao trabalho interno; depois volta ao Fabricante. Antes, atrás de estudar/corrigir, nunca rodava."""
    from circulo import loop as lp
    circle = fabrica["circle"]
    assert lp.TRABALHO.index("fabricar") < lp.TRABALHO.index("estudar_pedido") < lp.TRABALHO.index("corrigir_codigo")
    monkeypatch.setattr(circle, "_tem_trabalho", lambda t: t in ("fabricar", "corrigir_codigo", "estudar_pedido"))
    tasks = ["fabricar", "corrigir_codigo", "estudar_pedido"]
    circle.store.set("idle_last", {})
    assert circle._trabalho_pronto(tasks)[0] == "fabricar"
    circle.store.set("idle_last", {"fabricar": circle.store.tick, "estudar_pedido": circle.store.tick})
    pronto = circle._trabalho_pronto(tasks)
    assert "fabricar" not in pronto and pronto[0] == "corrigir_codigo"                   # espaço de 2 giros: a vez do loop
    circle.store.set("idle_last", {"fabricar": circle.store.tick - 2, "corrigir_codigo": circle.store.tick, "estudar_pedido": circle.store.tick - 2})
    assert circle._trabalho_pronto(tasks)[0] == "fabricar"


# ---------------------------------------------------------------- 1.77: auto-merge squash do PR do cliente
VERDE = [{"id": 1, "name": "Testes", "status": "completed", "conclusion": "success"}]


class GitHubFalso:
    """A API do cliente: check-runs do head, arquivos do PR e o merge por squash (recusa head divergente, como o GitHub)."""

    def __init__(self, runs, arquivos=None):
        self.runs, self.arquivos, self.merged, self.head = runs, arquivos or [{"filename": "calc.py"}, {"filename": "tests/teste_sub.py"}], [], None

    def check_runs(self, sha):
        return self.runs

    def pr_files(self, n):
        return self.arquivos

    def merge(self, n, sha, titulo):
        if self.head is not None and sha != self.head:
            return False, "Head branch was modified. Review and try the merge again."
        self.merged.append((n, sha, titulo))
        return True, "5qu45h"


def com_github(fabrica, gh) -> Fabricante:
    return Fabricante(fabrica["circle"].ctx, AgenteFalso(), abrir_pr=fabrica["fab"]._abrir_pr, github=lambda repo: gh)


def _merge(store, pedido_id):
    return [e for e in repo_cliente.evidencias(store, pedido_id) if e["etapa"] == "merge"]


def test_pr_do_cliente_mescla_por_squash_com_checks_verdes_validador_ok_e_nada_protegido(fabrica):
    """Verde mescla: checks do kit (`Testes`) success na API de check-runs, Validador aprovado, nenhum arquivo em
    `protegidos`; squash pela API com o sha do head; `fabrica:merge` em verificacoes e o sha do merge na ficha."""
    store, pedido = fabrica["store"], fabrica["pedido"]
    gh = GitHubFalso(VERDE)
    fab = com_github(fabrica, gh)
    assert fab.run_once()["status"] == "entregue" and gh.merged == []          # o CI é assíncrono: mescla na passagem seguinte
    assert fabricante.precisa(store)                                           # PR pendente de merge é trabalho
    assert fab.run_once() == {"status": "nada"}
    head = store.one("SELECT commit_sha FROM pedidos_repo WHERE id=?", (pedido["id"],))["commit_sha"]
    assert gh.merged == [(pedido["id"], head, "Criar a função subtrair em calc.py")]
    [m] = _merge(store, pedido["id"])
    assert m["ok"] and "5qu45h" in m["saida"]
    assert store.one("SELECT ok FROM verificacoes WHERE ponto='fabrica:merge' ORDER BY id DESC")["ok"] == 1
    assert not fabricante.precisa(store) and fab.run_once() == {"status": "nada"} and len(gh.merged) == 1


def test_pr_do_cliente_com_check_vermelho_pendente_ou_ausente_so_espera(fabrica):
    store, pedido = fabrica["store"], fabrica["pedido"]
    gh = GitHubFalso([{"id": 1, "name": "Testes", "status": "completed", "conclusion": "failure"}])
    fab = com_github(fabrica, gh)
    assert fab.run_once()["status"] == "entregue"
    for runs in ([{"id": 1, "name": "Testes", "status": "completed", "conclusion": "failure"}],
                 [{"id": 2, "name": "Testes", "status": "in_progress", "conclusion": None}],
                 [{"id": 3, "name": "CI", "status": "completed", "conclusion": "success"}]):     # nome do kit não existe no PR
        gh.runs = runs
        assert fab.run_once() == {"status": "nada"} and gh.merged == [] and fabricante.precisa(store)
    assert _merge(store, pedido["id"]) == []
    gh.runs = [{"id": 1, "name": "Testes", "status": "completed", "conclusion": "failure"}, {"id": 4, "name": "Testes", "status": "completed", "conclusion": "success"}]
    fab.run_once()
    assert len(gh.merged) == 1 and _merge(store, pedido["id"])[0]["ok"]       # a execução mais recente do check decide


def test_pr_do_cliente_que_toca_protegido_nunca_mescla_mesmo_verde(fabrica):
    store, pedido = fabrica["store"], fabrica["pedido"]
    gh = GitHubFalso(VERDE, arquivos=[{"filename": "calc.py"}, {"filename": ".github/workflows/ci.yml"}])
    fab = com_github(fabrica, gh)
    assert fab.run_once()["status"] == "entregue"
    fab.run_once()
    assert gh.merged == [] and not fabricante.precisa(store)                 # não fica esperando: nunca
    [m] = _merge(store, pedido["id"])
    assert not m["ok"] and ".github/" in m["saida"] and "nunca" in m["saida"]
    assert store.one("SELECT ok FROM verificacoes WHERE ponto='fabrica:merge' ORDER BY id DESC")["ok"] == 0


def test_merge_leva_o_sha_do_head_avaliado_e_head_divergente_nao_mescla(fabrica):
    store, pedido = fabrica["store"], fabrica["pedido"]
    gh = GitHubFalso(VERDE)
    fab = com_github(fabrica, gh)
    assert fab.run_once()["status"] == "entregue"
    gh.head = "outro-commit-empurrado-depois"
    fab.run_once()
    assert gh.merged == [] and not fabricante.precisa(store)
    [m] = _merge(store, pedido["id"])
    assert not m["ok"] and "Head branch was modified" in m["saida"]


def test_github_fora_do_ar_no_merge_so_espera_e_nao_derruba_a_passagem(fabrica):
    """O PUT do merge falha com URLError (GitHub fora): a passagem do Fabricante segue, o PR continua à espera e
    mescla quando o GitHub volta. Antes a exceção saía de `mesclar()`, no começo de `run_once()`, antes de `proximo()`."""
    import urllib.error
    store, pedido = fabrica["store"], fabrica["pedido"]
    gh = GitHubFalso(VERDE)
    fab = com_github(fabrica, gh)
    assert fab.run_once()["status"] == "entregue"
    fora = [True]
    merge_real = gh.merge

    def merge(n, sha, titulo):
        if fora[0]:
            raise urllib.error.URLError("api.github.com: connection refused")
        return merge_real(n, sha, titulo)
    gh.merge = merge
    assert fab.run_once() == {"status": "nada"} and gh.merged == []
    assert fabricante.precisa(store) and _merge(store, pedido["id"]) == []
    fora[0] = False
    fab.run_once()
    assert len(gh.merged) == 1 and _merge(store, pedido["id"])[0]["ok"] and not fabricante.precisa(store)


def test_pedido_que_depende_do_que_nao_existe_fica_bloqueado_sem_queimar_tentativas(fabrica):
    """Pedido #1 da esteira (Playwright no painel): o painel não existe; o agente explicou em vez de planejar e o pedido
    queimou 2 planos por tentativa. Agora ele responde `Bloqueado: …`, a ficha registra, o pedido fica vermelho sem
    novas tentativas (não é promessa quebrada: sem lição estrutural) e o Fabricante segue para o próximo."""
    fab, store, pedido = fabrica["fab"], fabrica["store"], fabrica["pedido"]
    fab.agent.plano = "Bloqueado: o painel web de aprovação (web/) não existe; o pedido 12 (painel mínimo) o traria."
    res = fab.run_once()
    assert res["status"] == "vermelho" and res["esgotou"] and res["motivo"].startswith("bloqueado: o painel web")
    assert len(fab.agent.chamadas) == 1                                                        # um plano, não dois
    planos = [e for e in repo_cliente.evidencias(store, pedido["id"]) if e["etapa"] == "plano"]
    assert len(planos) == 1 and not planos[0]["ok"] and planos[0]["saida"].startswith("Bloqueado:")
    assert not store.q("SELECT 1 FROM licoes WHERE classe='estrutural' AND descricao LIKE '%promessa%'")
    assert fab.run_once()["status"] == "nada"                                                  # não volta para a fila
    aviso = store.one("SELECT message FROM alerts WHERE message LIKE 'Fabricante: pedido%' ORDER BY id DESC LIMIT 1")["message"]
    assert "bloqueado" in aviso and "painel" in aviso


def test_licao_98_escrita_recusada_pelo_agente_bloqueia_o_pedido_sem_queimar_tentativas(fabrica):
    """Lição #98 (pedido 3 da esteira, skills em .claude/skills): o Claude Code recusou o Write em `.claude/` e o agente
    terminou "ok" só com o teste escrito; o Fabricante rodou os portões, a correção e queimou as 3 tentativas com
    "testes do cliente falham no clone". Escrita pedida pelo agente que não existe no clone depois = recusada: o
    pedido fica bloqueado na hora, sem portões, sem correção e sem lição de promessa."""
    fab, store, pedido = fabrica["fab"], fabrica["store"], fabrica["pedido"]

    def implementar(wd, task):
        (wd / "tests" / "teste_sub.py").write_text(TESTE, encoding="utf-8")
        return {"passos": ["Claude Code: escrevendo tests/teste_sub.py", f"Claude Code: escrevendo {wd}/.claude/skills/dotnet-patterns/SKILL.md"],
                "resposta": "Parei: a ferramenta Write recusou escrever em .claude/skills/."}
    fab.agent.implementar = implementar
    res = fab.run_once()
    assert res["status"] == "vermelho" and res["esgotou"] and res["motivo"].startswith("bloqueado: ")
    assert ".claude/skills/dotnet-patterns/SKILL.md" in res["motivo"]
    etapas = [e["etapa"] for e in repo_cliente.evidencias(store, pedido["id"])]
    assert "teste_vermelho" not in etapas and "teste_verde" not in etapas
    assert sum("BARRADA" in c["task"] for c in fab.agent.chamadas) == 0                       # nenhuma rodada de correção
    assert not store.q("SELECT 1 FROM licoes WHERE classe='estrutural' AND descricao LIKE '%promessa%'")
    assert fab.run_once()["status"] == "nada"

"""1.75 — técnicas absorvidas das skills externas como portões MEDIDOS (ADR 0010–0013).

Cada teste prova uma técnica ativa: a medida pega o desvio, grava `tecnica:<nome>` em verificacoes e o relatório
(`circulo tecnicas`) mostra a taxa. O prompt do Developer carrega o texto; os portões cirúrgica/simplicidade barram.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from circulo import tecnicas, validador
from circulo.self_dev import TASK_TEMPLATE
from circulo.tecnicas import (NOMES, PROMPT, cirurgica, dependencias_novas, plano_antes, relatorio, resposta_direta,
                              revisao_cruzada, simplicidade, texto_relatorio)
from circulo.tecnicas import teste_antes as medir_teste_antes

PASSOS_TDD = ["Claude Code: lendo circulo/x.py", "Claude Code: TodoWrite", "Claude Code: escrevendo tests/test_x.py",
              "Claude Code: rodando os testes", "Claude Code: editando circulo/x.py", "Claude Code: rodando os testes"]
PASSOS_SEM = ["Claude Code: lendo circulo/x.py", "Claude Code: editando circulo/x.py", "Claude Code: escrevendo tests/test_x.py"]


# ---------------------------------------------------------------- plano e teste antes (superpowers, karpathy §4)

def test_plano_antes_exige_plano_registrado_antes_da_primeira_edicao():
    assert plano_antes(PASSOS_TDD) == (True, "")
    ok, motivo = plano_antes(PASSOS_SEM)
    assert not ok and "sem plano" in motivo and "circulo/x.py" in motivo
    assert plano_antes([]) == (True, "")                                    # nada editado: nada a medir
    assert plano_antes(["Claude Code: lendo a.py"]) == (True, "")


def test_teste_antes_exige_que_a_primeira_edicao_seja_em_tests():
    assert medir_teste_antes(PASSOS_TDD) == (True, "")
    ok, motivo = medir_teste_antes(PASSOS_SEM)
    assert not ok and "primeira edição foi em código (circulo/x.py)" in motivo
    assert medir_teste_antes(["Claude Code: editando docs/x.md", "Claude Code: editando pyproject.toml"]) == (True, "")   # só docs/config
    assert medir_teste_antes(["Claude Code: escrevendo tests/Esteira.UnitTests/Media/XTests.cs", "Claude Code: editando src/A/B.cs"]) == (True, "")


# ---------------------------------------------------------------- cirúrgica (karpathy §3)

def test_cirurgica_barra_arquivos_de_codigo_fora_do_escopo_do_item():
    item = {"titulo": "Corrigir o detector em circulo/silencio.py", "detalhe": "ver tests/test_silencio.py"}
    assert cirurgica(item, ["circulo/silencio.py", "tests/test_silencio.py", "CHANGELOG.md", "docs/x.md"]) == (True, "")
    assert cirurgica(item, ["circulo/silencio.py", "circulo/a.py", "circulo/b.py", "tests/test_silencio.py"]) == (True, "")   # até 2 fora
    ok, motivo = cirurgica(item, ["circulo/silencio.py", "circulo/a.py", "circulo/b.py", "circulo/c.py", "tests/test_silencio.py"])
    assert not ok and "3 arquivos de código fora do escopo" in motivo and "circulo/a.py" in motivo


def test_cirurgica_sem_escopo_citado_so_tem_o_teto_absoluto():
    item = {"titulo": "Melhorar o painel", "detalhe": ""}
    assert cirurgica(item, [f"circulo/m{i}.py" for i in range(4)]) == (True, "")
    assert not cirurgica(item, [f"circulo/m{i}.py" for i in range(5)])[0]


def test_cirurgica_aceita_citacao_por_nome_de_modulo_e_caminho_parcial():
    item = {"titulo": "Fabricante em fabricante.py e src/Esteira.Infrastructure/Media/Tools/FfmpegRenderer.cs", "detalhe": ""}
    assert cirurgica(item, ["circulo/fabricante.py", "src/Esteira.Infrastructure/Media/Tools/FfmpegRenderer.cs", "circulo/loop.py", "circulo/cli.py"]) == (True, "")


# ---------------------------------------------------------------- simplicidade (karpathy §2)

def test_simplicidade_barra_dependencia_nova_que_o_item_nao_pede(tmp_path):
    item = {"titulo": "Ler CSV mais rápido", "detalhe": ""}
    adicionadas = {"pyproject.toml": ['dependencies = ["pandas>=2"]', '"pandas>=2",']}
    assert dependencias_novas(adicionadas) == ["pandas"]
    ok, motivo = simplicidade(item, adicionadas, tmp_path)
    assert not ok and "pandas" in motivo
    assert simplicidade({"titulo": "Usar pandas para ler CSV", "detalhe": ""}, adicionadas, tmp_path) == (True, "")
    assert dependencias_novas({"src/A/A.csproj": ['    <PackageReference Include="Remotion.Core" />']}) == ["Remotion.Core"]


def test_simplicidade_barra_definicao_nova_que_ninguem_usa(tmp_path):
    (tmp_path / "circulo").mkdir()
    (tmp_path / "circulo" / "x.py").write_text("class Estrategia:\n    pass\n\n\ndef usada():\n    return 1\n\nprint(usada())\n", encoding="utf-8")
    adicionadas = {"circulo/x.py": ["class Estrategia:", "def usada():", "def _privada():"]}
    ok, motivo = simplicidade({"titulo": "x", "detalhe": ""}, adicionadas, tmp_path)
    assert not ok and "Estrategia" in motivo and "usada" not in motivo and "_privada" not in motivo
    (tmp_path / "circulo" / "y.py").write_text("from .x import Estrategia\n", encoding="utf-8")
    assert simplicidade({"titulo": "x", "detalhe": ""}, adicionadas, tmp_path) == (True, "")


def test_simplicidade_ignora_testes_e_outras_linguagens(tmp_path):
    adicionadas = {"tests/test_x.py": ["def test_a():", "class Fake:"], "src/A.cs": ["class Nova {"]}
    assert simplicidade({"titulo": "x", "detalhe": ""}, adicionadas, tmp_path) == (True, "")


# ---------------------------------------------------------------- resposta direta (i-have-adhd)

@pytest.mark.parametrize("texto", ["Mudei circulo/x.py e tests/test_x.py.\nVerificado: pytest -q → 12 passed.\nPróximo: nada.",
                                   "", "   "])
def test_resposta_direta_aceita_curta_e_sem_preambulo(texto):
    assert resposta_direta(texto) == (True, "")


def test_resposta_direta_pega_preambulo_e_resposta_longa():
    ok, motivo = resposta_direta("Great question! Let me walk you through what I did.\nMudei x.")
    assert not ok and "preâmbulo" in motivo
    assert not resposta_direta("Vou começar analisando o código.\nfeito")[0]
    ok, motivo = resposta_direta("\n".join(f"linha {i}" for i in range(13)))
    assert not ok and "13 linhas" in motivo


# ---------------------------------------------------------------- revisão cruzada (superpowers review, octopus)

def test_revisao_cruzada_exige_olhos_distintos():
    assert revisao_cruzada("claude-opus-5-5", "claude-haiku-5-5", "llm") == (True, "")
    assert revisao_cruzada("", "claude-haiku-5-5", "llm") == (True, "")
    assert not revisao_cruzada("claude-sonnet-5-5", "claude-sonnet-5-5", "llm")[0]
    assert not revisao_cruzada("claude-opus-5-5", "claude-haiku-5-5", "indisponivel")[0]
    assert revisao_cruzada("claude-opus-5-5", "", "externo") == (True, "")


def test_modelo_cruzado_troca_de_nivel_quando_coincide_com_o_developer():
    modelos = {"pequena": "claude-haiku-5-5", "grande": "claude-sonnet-5-5"}
    assert validador.modelo_cruzado("claude-sonnet-5-5", "claude-sonnet-5-5", modelos) == "claude-haiku-5-5"
    assert validador.modelo_cruzado("claude-haiku-5-5", "claude-sonnet-5-5", modelos) == "claude-haiku-5-5"
    assert validador.modelo_cruzado("claude-sonnet-5-5", "", modelos) == "claude-sonnet-5-5"
    assert validador.modelo_cruzado("claude-sonnet-5-5", "claude-sonnet-5-5", {"grande": "claude-sonnet-5-5"}) == "claude-sonnet-5-5"


def test_revisor_externo_so_roda_se_o_cli_existir_e_nunca_para_a_entrega(monkeypatch, tmp_path):
    monkeypatch.setenv("CIRCULO_REVISOR_EXTERNO", "1")
    monkeypatch.setattr(validador.shutil, "which", lambda nome: None)
    assert validador.revisor_externo("s", "p") is None
    monkeypatch.setattr(validador.shutil, "which", lambda nome: "/usr/bin/codex" if nome == "codex" else None)
    chamadas = []

    def executar(argv, entrada):
        chamadas.append(argv[0])
        return '{"aprovado": false, "problemas": ["teste não prova o item"], "risco": "medio"}'
    v = validador.revisor_externo("s", "p", executar=executar)
    assert chamadas == ["codex"] and v["aprovado"] is False and v["comando"] == "codex"
    assert validador.revisor_externo("s", "p", executar=lambda a, e: "sem json") is None
    monkeypatch.setenv("CIRCULO_REVISOR_EXTERNO", "0")
    assert validador.revisor_externo("s", "p", executar=executar) is None


def test_revisar_pr_soma_o_revisor_externo_e_mede_a_revisao_cruzada(circle, tmp_path, monkeypatch):
    import subprocess
    wt = tmp_path / "wt"
    wt.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=wt, check=True)
    (wt / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], cwd=wt, check=True)
    (wt / "a.py").write_text("x = 2\n", encoding="utf-8")
    monkeypatch.setattr(validador.shutil, "which", lambda nome: "/usr/bin/codex" if nome == "codex" else None)
    run_real = subprocess.run
    monkeypatch.setattr(validador.subprocess, "run", lambda *a, **k: type("P", (), {"stdout": '{"aprovado": false, "problemas": ["falta teste"], "risco": "alto"}'})()
                        if a and a[0] and a[0][0] == "codex" else run_real(*a, **k))
    item = {"id": 1, "titulo": "mudar a", "detalhe": "", "modelo_developer": "claude-opus-5-5"}
    v = validador.revisar_pr(circle.ctx, wt, "HEAD", item, chamar=lambda s, p: '{"aprovado": true, "problemas": [], "risco": "baixo"}')
    assert v["aprovado"] is False and any("revisor externo (codex)" in p for p in v["problemas"])
    r = circle.store.one("SELECT ok, motivo FROM verificacoes WHERE ponto='tecnica:revisao_cruzada' ORDER BY id DESC")
    assert r is not None and r["ok"] == 1


# ---------------------------------------------------------------- integração: prompt, neurônio, relatório

def test_prompt_do_developer_carrega_as_tecnicas():
    texto = TASK_TEMPLATE.format(titulo="t", detalhe="d", incidente="", protegidos="x", licoes="", tecnicas=PROMPT)
    for marca in ("PLANO ANTES DO CÓDIGO", "TESTE ANTES DO CÓDIGO", "MUDANÇA CIRÚRGICA", "SIMPLICIDADE", "RESPOSTA DIRETA"):
        assert marca in texto
    assert "Regras:" in texto and texto.index("Regras:") < texto.index("PLANO ANTES")


def test_medir_grava_toda_tecnica_e_devolve_so_os_portoes_que_barram(circle, tmp_path):
    item = {"id": 7, "titulo": "mexer em circulo/x.py", "detalhe": ""}
    falhas = tecnicas.medir(circle.ctx, item, PASSOS_SEM, "Great! done", ["circulo/x.py", "circulo/a.py", "circulo/b.py", "circulo/c.py"],
                            {"pyproject.toml": ['"pandas",']}, tmp_path)
    assert sorted(f.portao for f in falhas) == ["técnica cirurgica", "técnica simplicidade"]
    pontos = {r["ponto"]: r["ok"] for r in circle.store.q("SELECT ponto, ok FROM verificacoes WHERE ponto LIKE 'tecnica:%'")}
    assert pontos == {"tecnica:plano_antes": 0, "tecnica:teste_antes": 0, "tecnica:cirurgica": 0, "tecnica:simplicidade": 0, "tecnica:resposta_direta": 0}
    assert not circle.store.q("SELECT 1 FROM licoes WHERE ponto LIKE 'tecnica:%'")      # evidência, não lição


def test_portao_pr_do_developer_passa_pelas_tecnicas(circle, tmp_path, monkeypatch):
    """A prova de que a técnica está ATIVA no caminho real: o neurônio 'abrir PR' chama tecnicas.medir com os passos
    e a resposta da última sessão do agente, e uma falha de simplicidade barra o PR."""
    import subprocess
    from circulo import self_dev as sd
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "tests").mkdir()
    (repo / "circulo").mkdir()
    (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], cwd=repo, check=True)
    dev = sd.SelfDeveloper(circle.ctx, repo, agent=None)
    dev.ultima_saida = {"passos": PASSOS_TDD, "resposta": "ok", "modelo": "claude-opus-5-5"}
    iid = circle.store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,0,0)",
                         ("mexer em circulo/x.py", "", "pedido_cassio", "pendente", "", 1))
    (repo / "circulo" / "x.py").write_text("class Sozinha:\n    pass\n", encoding="utf-8")
    (repo / "tests" / "test_x.py").write_text("def test_x():\n    assert 1\n", encoding="utf-8")
    monkeypatch.setattr(sd, "MAX_CORRECOES_LOCAIS", 0)
    ok, texto = dev.portao_pr(repo, "HEAD", iid, "mexer em circulo/x.py")
    assert not ok and "técnica simplicidade" in texto and "Sozinha" in texto
    assert circle.store.one("SELECT 1 FROM verificacoes WHERE ponto='tecnica:simplicidade' AND ok=0")
    assert circle.store.one("SELECT 1 FROM verificacoes WHERE ponto='tecnica:teste_antes' AND ok=1")


def test_relatorio_mostra_cada_tecnica_e_se_esta_ativa(circle):
    assert [r["tecnica"] for r in relatorio(circle.store)] == list(NOMES)
    assert all(not r["ativa"] for r in relatorio(circle.store))
    tecnicas.registrar(circle.ctx, "cirurgica", True, "x")
    tecnicas.registrar(circle.ctx, "cirurgica", False, "y", "3 fora")
    r = next(x for x in relatorio(circle.store) if x["tecnica"] == "cirurgica")
    assert r == {**r, "ativa": True, "medicoes": 2, "ok": 1, "taxa": 0.5, "ultima_falha": "3 fora"}
    txt = texto_relatorio(circle.store)
    assert "cirurgica" in txt and "1/2 ok (50%)" in txt and "sem medição ainda" in txt


def test_skills_vendorizadas_estao_instaladas_com_licenca():
    from circulo import skills
    raiz = Path(__file__).resolve().parents[1]
    nomes = {s["nome"] for s in skills.instaladas(raiz)}
    assert {"test-driven-development", "writing-plans", "verification-before-completion", "systematic-debugging",
            "requesting-code-review", "karpathy-guidelines", "i-have-adhd"} <= nomes
    origem = (raiz / ".claude" / "skills" / "ORIGEM.md").read_text(encoding="utf-8")
    assert "MIT" in origem and "obra/superpowers" in origem and "claude-octopus" in origem
    assert all((raiz / "docs" / "adr" / f).exists() for f in ("0010-superpowers.md", "0011-karpathy-guidelines.md", "0012-i-have-adhd.md", "0013-claude-octopus.md"))

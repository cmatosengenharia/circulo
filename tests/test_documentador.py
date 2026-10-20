"""O Redator técnico (circulo/documentador.py): documentação gerada do que o loop é e fez, classificada pelo Jev,
publicada por PR só com docs/ — e o gate que só aceita essa porta para documentação."""
import json
import shutil
import subprocess
import time
from pathlib import Path

from circulo import documentador
from circulo.merge_gate import MergeGate

from test_merge_gate import OK_RUNS, FakeGH, pr  # noqa: F401

RAIZ = Path(__file__).resolve().parent.parent


def _clone(tmp_path: Path) -> Path:
    """Um clone leve do próprio repo (pyproject, CHANGELOG, circulo/) sem remoto: o Redator escreve no local."""
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(RAIZ / "pyproject.toml", repo / "pyproject.toml")
    shutil.copy(RAIZ / "CHANGELOG.md", repo / "CHANGELOG.md")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def _semear(s):
    agora = time.time()
    i = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES('Vigia: drenar a pergunta parada','d','loop','feito','PR #31 mergeado',1,?,?)", (agora, agora))
    s.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,item_id,created_at,updated_at) VALUES('k','operador','Por que a pergunta validada espera horas?','entregue','loop',?,?,?)", (i, agora, agora))
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,item_id,arquivos,created_at,updated_at) VALUES(31,2,'Vigia: drenar sozinho a pergunta validada mais antiga','circulo/fix-56-1','mergeado',?,?,?,?)",
        (i, json.dumps(["circulo/vigia.py", "tests/test_vigia.py"]), agora, agora))
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,item_id,arquivos,created_at,updated_at) VALUES(29,2,'Jardineiro: podar linhas com noqa','circulo/fix-52-1','mergeado',NULL,?,?,?)",
        (json.dumps(["circulo/jardineiro.py"]), agora, agora))
    s.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,created_at,updated_at) VALUES('developer:lint:F811','developer','trabalho','fixture redefinida','renomear','aberta',3,1,?,?)", (agora, agora))
    return i


def test_gera_documentacao_profissional_do_codigo_do_banco_e_do_changelog(circle, tmp_path):
    repo = _clone(tmp_path)
    _semear(circle.store)
    docs = documentador.gerar(circle.ctx, repo)
    assert set(docs) == {"docs/README.md", "docs/agentes.md", "docs/arquitetura.md", "docs/decisoes.md", "docs/evolucao.md", "docs/licoes.md"}
    ag = docs["docs/agentes.md"]
    assert "**Redator técnico**" in ag and "**Product owner**" in ag and "`indagar` (Indagador)" in ag and "| `documentar`" in ag
    arq = docs["docs/arquitetura.md"]
    assert "`merge_gate.py` ⚖️" in arq and "`documentador.py`" in arq and "| `/aprovacoes` |" in arq and "| `/api/aluno` |" in arq
    dec = docs["docs/decisoes.md"]
    assert "Catálogo das" in dec and "| `decision.py:" in dec and "noul" in dec
    ev = docs["docs/evolucao.md"]
    assert "| #31 |" in ev and "pergunta do operador: “Por que a pergunta validada espera horas?”" in ev and "| #29 |" in ev
    assert "## Versões" in ev and "| 1.39.0 |" in ev                                  # do CHANGELOG
    tipos = circle.store.get("documentador_tipos")
    assert set(tipos) == {"31", "29"} and all(v["tipo"] in documentador.TIPOS for v in tipos.values())   # o Jev classificou, uma vez
    assert "developer:lint:F811" in docs["docs/licoes.md"] and "Redator técnico" in docs["docs/README.md"]
    n_antes = circle.store.one("SELECT COUNT(*) n FROM decisions WHERE question LIKE 'doc_tipo_%'")["n"]
    documentador.gerar(circle.ctx, repo)
    assert circle.store.one("SELECT COUNT(*) n FROM decisions WHERE question LIKE 'doc_tipo_%'")["n"] == n_antes   # cache: não pergunta de novo


def test_roda_quando_ha_entrega_nova_e_publica_no_local_sem_github(circle, tmp_path, monkeypatch):
    repo = _clone(tmp_path)
    s = circle.store
    assert not documentador.precisa(s)                                    # sem PR mergeado e sem 24 h: nada
    _semear(s)
    assert documentador.precisa(s)
    monkeypatch.setenv("CIRCULO_REPO_DIR", str(repo))
    r = documentador.rodar(circle.ctx)
    assert r["modo"] == "local" and (repo / "docs/README.md").exists() and (repo / "docs/evolucao.md").read_text().count("| #") >= 2
    st = s.get(documentador.KV)
    assert st["merge_visto"] == 31 and st["pr_aberto"] is None
    assert not documentador.precisa(s)                                    # já documentou até o PR #31
    assert s.one("SELECT COUNT(*) n FROM alerts WHERE kind='docs'")["n"] == 1
    assert documentador.precisa(s, agora=time.time() + documentador.A_CADA + 1)   # ou depois de 24 h


def test_gate_aceita_pr_de_docs_so_com_docs_e_recusa_se_tocar_codigo(circle):
    so_docs = [{"filename": "docs/README.md", "additions": 900, "deletions": 0}, {"filename": "docs/evolucao.md", "additions": 400, "deletions": 10}]
    gh = FakeGH([pr(7, ref="circulo/docs-1792500000", sha="d0c")], files={7: so_docs})
    [v] = MergeGate(circle.ctx, gh, human="x").run()
    assert v.merge and v.reason.startswith("documentação") and gh.merged == [(7, "d0c")]   # 1.300 linhas: o teto de 800 não vale para docs
    gh = FakeGH([pr(8, ref="circulo/docs-1792500001", sha="d1c")], files={8: so_docs + [{"filename": "circulo/loop.py", "additions": 1, "deletions": 0}]})
    [v] = MergeGate(circle.ctx, gh, human="x").run()
    assert not v.merge and "toca código" in v.reason and v.details.get("fora_do_alcance")
    gh = FakeGH([pr(9, ref="circulo/docs-1792500002", sha="d2c")], files={9: so_docs}, runs={"d2c": []})
    [v] = MergeGate(circle.ctx, gh, human="x").run()
    assert not v.merge and "ausentes" in v.reason                              # CI continua obrigatório


def test_pr_de_docs_fechado_libera_o_proximo(circle):
    s = circle.store
    s.set(documentador.KV, {"em": time.time(), "merge_visto": 0, "pr_aberto": 42})
    assert not documentador.precisa(s)
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(42,2,'docs','circulo/docs-1','aberto',?,?)", (time.time(), time.time()))
    assert not documentador.precisa(s)                                    # o PR de docs ainda está aberto
    s.x("UPDATE prs SET status='mergeado' WHERE number=42")              # o gate fechou: a tabela prs diz
    assert not documentador.precisa(s)                                    # mas a doc mergeada não é entrega nova
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(43,2,'x','circulo/fix-1','mergeado',?,?)", (time.time(), time.time()))
    assert documentador.precisa(s)                                        # uma entrega do loop, sim


def test_doc_mergeada_nao_dispara_outra_doc(circle):
    """No Mac: cada PR de docs mergeado contava como entrega nova e o Redator abria PR atrás de PR (#34, #35, #36, #37)."""
    s = circle.store
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(50,2,'x','circulo/fix-1','mergeado',?,?)", (time.time(), time.time()))
    s.set(documentador.KV, {"em": time.time(), "merge_visto": 50, "pr_aberto": None})
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(51,2,'docs','circulo/docs-1','mergeado',?,?)", (time.time(), time.time()))
    assert not documentador.precisa(s)
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(52,2,'y','circulo/fix-2','mergeado',?,?)", (time.time(), time.time()))
    assert documentador.precisa(s)

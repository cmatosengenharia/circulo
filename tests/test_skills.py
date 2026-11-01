"""31/10: skills prontas de repositórios públicos entram no ecossistema por PR e o Jev escolhe a da tarefa."""
import time

from circulo import skills
from circulo.decision import Question


def _skill(repo, nome, desc):
    p = repo / ".claude" / "skills" / nome
    p.mkdir(parents=True)
    (p / "SKILL.md").write_text(f"---\nname: {nome}\ndescription: {desc}\n---\n# {nome}\n", encoding="utf-8")


def test_catalogo_vira_itens_de_instalacao_sem_repetir(circle, tmp_path):
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    _skill(tmp_path, "pdf", "ler e criar PDF")
    ids = skills.pedir_instalacao(s, tmp_path, maximo=3)
    assert len(ids) == 3
    itens = [dict(r) for r in s.q("SELECT * FROM roadmap WHERE id IN (?,?,?)", ids)]
    assert all(i["origem"] == "referencia" and i["estudo"] and i["titulo"].startswith("Instalar a skill") for i in itens)
    assert itens[0]["titulo"].startswith("Instalar a skill docx") and "pdf" not in {k for k in s.get(skills.KV_PEDIDOS)}   # instalada: não pede
    assert "licença" in itens[0]["detalhe"].lower() and ".claude/skills/docx/" in itens[0]["detalhe"]
    ids2 = skills.pedir_instalacao(s, tmp_path, maximo=3)
    assert len(ids2) == 3 and not set(ids2) & set(ids) and len(s.get(skills.KV_PEDIDOS)) == 6     # as próximas 3, sem repetir
    s.set("skills_catalogo", [{"nome": "minha", "repo": "https://github.com/x/y", "caminho": "skills/minha", "area": "frontend", "para": "x", "licenca": "MIT"}])
    assert [c["nome"] for c in skills.catalogo(s)] == ["minha"] and len(skills.pedir_instalacao(s, tmp_path)) == 1


def test_jev_escolhe_a_skill_da_tarefa_pela_regra_local(circle, tmp_path):
    _skill(tmp_path, "frontend-design", "interfaces com direção visual, tipografia e layout")
    _skill(tmp_path, "pytest-skill", "pytest: fixtures, parametrização, isolamento de testes")
    _skill(tmp_path, "semgrep", "varredura de segurança com Semgrep e triagem")
    inst = skills.instaladas(tmp_path)
    assert [s["nome"] for s in inst] == ["frontend-design", "pytest-skill", "semgrep"] and inst[0]["descricao"].startswith("interfaces")
    dl = circle.ctx.dl
    e = skills.para_tarefa(dl, {"titulo": "Painel: card de links por assunto na tela Meu trabalho", "detalhe": "trabalho.html"}, tmp_path)
    assert [s["nome"] for s in e] == ["frontend-design"]
    e = skills.para_tarefa(dl, {"titulo": "Isolar o fixture circle nos testes de orçamento", "detalhe": "pytest fixtures"}, tmp_path)
    assert [s["nome"] for s in e] == ["pytest-skill"]
    assert skills.para_tarefa(dl, {"titulo": "Registrar causa do adiamento", "detalhe": ""}, tmp_path) == []      # nada casa: nenhuma
    assert skills.para_tarefa(dl, {"titulo": "x"}, tmp_path / "vazio") == []
    txt = skills.texto_para_prompt(e)
    assert "/pytest-skill" in txt and "SKILL.md" in txt and skills.texto_para_prompt([]) == ""
    q = Question("choice", "?", {"a": "nada a ver", "nenhuma": "n"})
    assert skills.regra(circle.ctx.dl.jev, "skills_para_tarefa", q, {"tarefa": "zzz"}).value == "nenhuma"

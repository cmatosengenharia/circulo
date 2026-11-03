"""Skill pytest-skill (TestMu AI, antes LambdaTest; MIT) vendorizada em .claude/skills: SKILL.md, reference/playbook.md (o
SKILL.md manda ler) e licença. O catálogo apontava para testmu-ai/skills, que não existe (404): a fonte real é
LambdaTest/agent-skills, com a skill na raiz em `pytest-skill/`."""

from pathlib import Path

from circulo import skills

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / ".claude" / "skills" / "pytest-skill"


def test_pytest_skill_instalada_com_descricao_playbook_e_licenca():
    inst = {s["nome"]: s["descricao"] for s in skills.instaladas(RAIZ)}
    assert "pytest-skill" in inst
    assert "pytest" in inst["pytest-skill"].lower() and "fixtures" in inst["pytest-skill"].lower()
    assert "reference/playbook.md" in (PASTA / "SKILL.md").read_text(encoding="utf-8")
    assert (PASTA / "reference" / "playbook.md").is_file()
    assert "MIT License" in (PASTA / "LICENSE.txt").read_text(encoding="utf-8")


def test_catalogo_aponta_para_o_repositorio_real_da_testmu_com_licenca_mit():
    e = next(c for c in skills.CATALOGO if c[0] == "pytest-skill")
    assert e[1] == "https://github.com/LambdaTest/agent-skills" and e[2] == "pytest-skill" and e[5] == "MIT"

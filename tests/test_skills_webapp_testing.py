"""Skill webapp-testing (anthropics/skills, Apache-2.0) vendorizada em .claude/skills: SKILL.md, script e licença."""

from pathlib import Path

from circulo import skills

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / ".claude" / "skills" / "webapp-testing"


def test_webapp_testing_instalada_com_descricao_script_e_licenca():
    inst = {s["nome"]: s["descricao"] for s in skills.instaladas(RAIZ)}
    assert "webapp-testing" in inst
    assert "Playwright" in inst["webapp-testing"] and "testing" in inst["webapp-testing"]
    texto = (PASTA / "SKILL.md").read_text(encoding="utf-8")
    assert "scripts/with_server.py" in texto and (PASTA / "scripts" / "with_server.py").is_file()  # o script que o SKILL.md cita vem junto
    assert "Apache License" in (PASTA / "LICENSE.txt").read_text(encoding="utf-8")

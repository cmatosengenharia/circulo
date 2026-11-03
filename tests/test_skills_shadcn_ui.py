"""Skill shadcn-ui (google-labs-code/stitch-skills, Apache-2.0) vendorizada em .claude/skills: SKILL.md e licença.

O catálogo apontava para github.com/google-labs-code/skills, que não existe: a skill mora em stitch-skills."""

from pathlib import Path

from circulo import skills

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / ".claude" / "skills" / "shadcn-ui"


def test_shadcn_ui_instalada_com_descricao_e_licenca():
    inst = {s["nome"]: s["descricao"] for s in skills.instaladas(RAIZ)}
    assert "shadcn-ui" in inst
    assert "shadcn/ui" in inst["shadcn-ui"] and "customization" in inst["shadcn-ui"]
    assert "Apache License" in (PASTA / "LICENSE.txt").read_text(encoding="utf-8")


def test_catalogo_aponta_shadcn_ui_para_o_stitch_skills_com_licenca_apache():
    e = next(c for c in skills.CATALOGO if c[0] == "shadcn-ui")
    assert e[1] == "https://github.com/google-labs-code/stitch-skills"
    assert e[2] == "plugins/stitch-build/skills/shadcn-ui"
    assert e[5] == "Apache-2.0"

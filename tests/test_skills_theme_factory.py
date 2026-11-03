"""Skill theme-factory (anthropics/skills, Apache-2.0) vendorizada em .claude/skills: SKILL.md, temas, showcase e licença."""

from pathlib import Path

from circulo import skills

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / ".claude" / "skills" / "theme-factory"
TEMAS = ("arctic-frost", "botanical-garden", "desert-rose", "forest-canopy", "golden-hour",
         "midnight-galaxy", "modern-minimalist", "ocean-depths", "sunset-boulevard", "tech-innovation")


def test_theme_factory_instalada_com_descricao_temas_showcase_e_licenca():
    inst = {s["nome"]: s["descricao"] for s in skills.instaladas(RAIZ)}
    assert "theme-factory" in inst
    assert "theme" in inst["theme-factory"].lower() and "colors/fonts" in inst["theme-factory"]
    texto = (PASTA / "SKILL.md").read_text(encoding="utf-8")
    assert "theme-showcase.pdf" in texto and (PASTA / "theme-showcase.pdf").is_file()  # o SKILL.md manda mostrar o PDF
    assert "`themes/`" in texto
    for tema in TEMAS:                                                                   # um arquivo por tema citado
        assert "## Color Palette" in (PASTA / "themes" / f"{tema}.md").read_text(encoding="utf-8")
    assert "Apache License" in (PASTA / "LICENSE.txt").read_text(encoding="utf-8")

"""Item #383: a skill `xlsx` (anthropics/skills, source-available) instalada em `.claude/skills/xlsx/` só com o SKILL.md."""

from pathlib import Path

from circulo import skills

RAIZ = Path(__file__).resolve().parents[1]


def test_skill_xlsx_instalada_aparece_com_a_descricao_do_cabecalho():
    inst = {s["nome"]: s["descricao"] for s in skills.instaladas(RAIZ)}
    assert "xlsx" in inst
    assert inst["xlsx"].startswith("Use this skill any time a spreadsheet file is the primary input or output")


def test_skill_xlsx_source_available_traz_so_o_skill_md_com_atribuicao():
    pasta = RAIZ / ".claude" / "skills" / "xlsx"
    assert sorted(p.name for p in pasta.iterdir()) == ["SKILL.md"]       # source-available: nenhum script copiado
    origem = (RAIZ / ".claude" / "skills" / "ORIGEM.md").read_text(encoding="utf-8")
    assert "https://github.com/anthropics/skills" in origem and "xlsx" in origem

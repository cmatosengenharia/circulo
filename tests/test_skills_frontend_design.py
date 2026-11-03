"""Skill frontend-design (anthropics/skills, Apache-2.0) instalada em .claude/skills: o loop a lista com a descrição do cabeçalho."""
from pathlib import Path

from circulo import skills

REPO = Path(__file__).resolve().parents[1]


def test_frontend_design_instalada_com_descricao_do_cabecalho():
    inst = {s["nome"]: s["descricao"] for s in skills.instaladas(REPO)}
    assert "frontend-design" in inst
    assert "design" in inst["frontend-design"].lower() and len(inst["frontend-design"]) > 20
    assert (REPO / skills.PASTA / "frontend-design" / "LICENSE.txt").read_text(encoding="utf-8").lstrip().startswith("Apache License")

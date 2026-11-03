"""Skill canvas-design (anthropics/skills, Apache-2.0) vendorizada em .claude/skills: SKILL.md, fontes que ele cita e licença.
As 27 cópias idênticas da SIL OFL 1.1 que vinham com as fontes ficam num único canvas-fonts/OFL.txt (com todos os avisos
de copyright): o texto repetido somava ~2500 linhas e o PR passava do limite de 800 linhas do gate."""

from pathlib import Path

from circulo import skills

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / ".claude" / "skills" / "canvas-design"


def test_canvas_design_instalada_com_descricao_fontes_e_licenca():
    inst = {s["nome"]: s["descricao"] for s in skills.instaladas(RAIZ)}
    assert "canvas-design" in inst
    assert "poster" in inst["canvas-design"] and ".png" in inst["canvas-design"]
    texto = (PASTA / "SKILL.md").read_text(encoding="utf-8")
    assert "./canvas-fonts" in texto                                   # o SKILL.md manda procurar as fontes nesta pasta
    fontes = sorted(p.name for p in (PASTA / "canvas-fonts").glob("*.ttf"))
    assert "WorkSans-Regular.ttf" in fontes and "IBMPlexMono-Regular.ttf" in fontes
    ofl = (PASTA / "canvas-fonts" / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in ofl                 # a licença das fontes, uma vez só...
    assert "The Work Sans Project Authors" in ofl and "IBM Corp." in ofl   # ...com o aviso de copyright de cada família
    assert not list((PASTA / "canvas-fonts").glob("*-OFL.txt"))        # e nenhuma cópia repetida por família
    assert "Apache License" in (PASTA / "LICENSE.txt").read_text(encoding="utf-8")

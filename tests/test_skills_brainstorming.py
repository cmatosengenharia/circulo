"""Skill brainstorming (obra/superpowers, MIT) vendorizada em .claude/skills: SKILL.md com a descrição do cabeçalho, o
builder-check-prompt.md que ele cita, a licença na própria pasta e a origem (URL, commit, o que ficou de fora)."""

from pathlib import Path

from circulo import skills

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / ".claude" / "skills" / "brainstorming"


def test_brainstorming_instalada_com_descricao_e_licenca():
    inst = {s["nome"]: s["descricao"] for s in skills.instaladas(RAIZ)}
    assert "brainstorming" in inst
    assert "creative work" in inst["brainstorming"] and "planning anything new" in inst["brainstorming"]
    assert (PASTA / "builder-check-prompt.md").is_file()
    assert "MIT License" in (PASTA / "LICENSE.txt").read_text(encoding="utf-8")
    origem = (PASTA / "ORIGEM.md").read_text(encoding="utf-8")
    assert "https://github.com/obra/superpowers" in origem and "visual-companion.md" in origem

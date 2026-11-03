"""Skill subagent-driven-development (obra/superpowers, MIT) vendorizada em .claude/skills: SKILL.md com a descrição
do cabeçalho, a licença na própria pasta e a origem (URL, commit, o que ficou de fora)."""

from pathlib import Path

from circulo import skills

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / ".claude" / "skills" / "subagent-driven-development"


def test_subagent_driven_development_instalada_com_descricao_e_licenca():
    inst = {s["nome"]: s["descricao"] for s in skills.instaladas(RAIZ)}
    assert "subagent-driven-development" in inst
    assert "executing implementation plans" in inst["subagent-driven-development"]
    assert "MIT License" in (PASTA / "LICENSE.txt").read_text(encoding="utf-8")
    origem = (PASTA / "ORIGEM.md").read_text(encoding="utf-8")
    assert "https://github.com/obra/superpowers" in origem and "scripts/" in origem

"""Skill using-git-worktrees (obra/superpowers, MIT) vendorizada em .claude/skills: SKILL.md com a descrição do
cabeçalho (a pasta de origem só tem ele), a licença na própria pasta e a origem (URL, commit)."""

from pathlib import Path

from circulo import skills

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / ".claude" / "skills" / "using-git-worktrees"


def test_using_git_worktrees_instalada_com_descricao_e_licenca():
    inst = {s["nome"]: s["descricao"] for s in skills.instaladas(RAIZ)}
    assert "using-git-worktrees" in inst
    assert "isolated workspace" in inst["using-git-worktrees"] and "git worktree fallback" in inst["using-git-worktrees"]
    assert "MIT License" in (PASTA / "LICENSE.txt").read_text(encoding="utf-8")
    origem = (PASTA / "ORIGEM.md").read_text(encoding="utf-8")
    assert "https://github.com/obra/superpowers" in origem and "2ce8aa15d05bd57213e6f746f953aafb7ded7a8b" in origem

"""Skill postgres-best-practices (supabase/agent-skills, MIT) vendorizada em .claude/skills: SKILL.md com a descrição do
cabeçalho, a licença na própria pasta e a origem (URL do repositório oficial, commit)."""

from pathlib import Path

from circulo import skills

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / ".claude" / "skills" / "postgres-best-practices"


def test_postgres_best_practices_instalada_com_descricao_e_licenca():
    inst = {s["nome"]: s["descricao"] for s in skills.instaladas(RAIZ)}
    assert "postgres-best-practices" in inst
    assert "Postgres best practices maintained by Supabase" in inst["postgres-best-practices"]
    assert "MIT License" in (PASTA / "LICENSE.txt").read_text(encoding="utf-8")
    origem = (PASTA / "ORIGEM.md").read_text(encoding="utf-8")
    assert "https://github.com/supabase/agent-skills" in origem and "c9be0e931b7930f7d02126d04774d904c381e7d7" in origem

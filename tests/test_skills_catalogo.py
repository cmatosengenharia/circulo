"""ADR 0007 (SUPA-2): a entrada de Postgres do catálogo aponta para a skill oficial da Supabase, com licença MIT."""

from circulo import skills


def _entrada(nome):
    return next(dict(zip(("nome", "repo", "caminho", "area", "para", "licenca"), c, strict=True)) for c in skills.CATALOGO if c[0] == nome)


def test_postgres_best_practices_vem_do_repositorio_oficial_da_supabase_com_licenca_mit():
    e = _entrada("postgres-best-practices")
    assert e["repo"] == "https://github.com/supabase/agent-skills"
    assert e["caminho"] == "skills/supabase-postgres-best-practices"
    assert e["licenca"] == "MIT"
    assert e["area"] == "arquitetura"
    assert sum(1 for c in skills.CATALOGO if "postgres" in c[0]) == 1      # substitui a entrada antiga, não soma outra


def test_nenhuma_entrada_do_catalogo_aponta_para_supabase_skills_que_nao_e_o_oficial():
    assert not [c for c in skills.CATALOGO if c[1].rstrip("/").endswith("github.com/supabase/skills")]

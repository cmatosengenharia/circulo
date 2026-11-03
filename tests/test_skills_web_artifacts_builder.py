"""Skill web-artifacts-builder (anthropics/skills, Apache-2.0) vendorizada em .claude/skills: SKILL.md, scripts e licença."""

from pathlib import Path

from circulo import skills

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / ".claude" / "skills" / "web-artifacts-builder"


def test_web_artifacts_builder_instalada_com_descricao_scripts_e_licenca():
    inst = {s["nome"]: s["descricao"] for s in skills.instaladas(RAIZ)}
    assert "web-artifacts-builder" in inst
    assert "shadcn" in inst["web-artifacts-builder"] and "React" in inst["web-artifacts-builder"]
    texto = (PASTA / "SKILL.md").read_text(encoding="utf-8")
    for script in ("scripts/init-artifact.sh", "scripts/bundle-artifact.sh"):
        assert script in texto and (PASTA / script).is_file()          # os scripts que o SKILL.md cita vêm junto
    assert (PASTA / "scripts" / "shadcn-components.tar.gz").is_file()  # init-artifact.sh extrai este pacote
    assert "Apache License" in (PASTA / "LICENSE.txt").read_text(encoding="utf-8")

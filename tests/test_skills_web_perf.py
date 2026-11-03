"""Skill web-perf (cloudflare/skills, Apache-2.0) vendorizada em .claude/skills: SKILL.md e licença (não cita scripts)."""

from pathlib import Path

from circulo import skills

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / ".claude" / "skills" / "web-perf"


def test_web_perf_instalada_com_descricao_e_licenca():
    inst = {s["nome"]: s["descricao"] for s in skills.instaladas(RAIZ)}
    assert "web-perf" in inst
    assert "Core Web Vitals" in inst["web-perf"] and "Lighthouse" in inst["web-perf"]
    assert "Apache License" in (PASTA / "LICENSE.txt").read_text(encoding="utf-8")

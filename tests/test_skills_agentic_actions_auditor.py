"""agentic-actions-auditor (trailofbits/skills, CC-BY-SA-4.0): só o SKILL.md; references/ (1.309 linhas > MAX_LINES) na origem."""

from pathlib import Path

from circulo import skills

RAIZ = Path(__file__).resolve().parent.parent


def test_agentic_actions_auditor_instalada():
    inst = {s["nome"]: s["descricao"] for s in skills.instaladas(RAIZ)}
    assert "Audits GitHub Actions workflows" in inst["agentic-actions-auditor"]
    origem = (RAIZ / ".claude/skills/agentic-actions-auditor/ORIGEM.md").read_text(encoding="utf-8")
    assert "trailofbits/skills/tree/711af095215ad4ecde5b90cd1d0124b3f1c4ca9e/" in origem and "CC-BY-SA-4.0" in origem

"""Skill frontend-design-review (microsoft/skills, MIT) vendorizada em .claude/skills: SKILL.md, references/ e licença.
O cabeçalho dela usa `description: >` (bloco YAML dobrado): `instaladas` tem de devolver o texto, não o `>`."""

from pathlib import Path

from circulo import skills

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / ".claude" / "skills" / "frontend-design-review"
REFERENCES = ("pattern-examples.md", "quick-checklist.md", "review-output-format.md", "review-type-modifiers.md")


def test_frontend_design_review_instalada_com_descricao_references_e_licenca():
    inst = {s["nome"]: s["descricao"] for s in skills.instaladas(RAIZ)}
    assert "frontend-design-review" in inst
    assert "design" in inst["frontend-design-review"].lower() and "review" in inst["frontend-design-review"].lower()
    for nome in REFERENCES:                                                   # o SKILL.md cita os quatro
        assert (PASTA / "references" / nome).is_file()
    assert "MIT License" in (PASTA / "LICENSE.txt").read_text(encoding="utf-8")


def test_descricao_em_bloco_yaml_dobrado_e_lida_inteira(tmp_path):
    pasta = tmp_path / ".claude" / "skills" / "dobrada"
    pasta.mkdir(parents=True)
    (pasta / "SKILL.md").write_text("---\nname: dobrada\ndescription: >\n  Primeira linha.\n  Segunda linha.\nacknowledgments: |\n  outro campo\n---\n# x\n",
                                    encoding="utf-8")
    assert skills.instaladas(tmp_path) == [{"nome": "dobrada", "descricao": "Primeira linha. Segunda linha."}]


def test_descricao_que_comeca_na_linha_seguinte_continua_sendo_lida(tmp_path):
    pasta = tmp_path / ".claude" / "skills" / "plana"
    pasta.mkdir(parents=True)
    (pasta / "SKILL.md").write_text("---\nname: plana\ndescription:\n  Texto na linha seguinte.\n  E mais uma.\nversion: 1\n---\n# x\n", encoding="utf-8")
    assert skills.instaladas(tmp_path) == [{"nome": "plana", "descricao": "Texto na linha seguinte. E mais uma."}]


def test_catalogo_aponta_para_o_caminho_real_na_microsoft_com_licenca_mit():
    e = next(c for c in skills.CATALOGO if c[0] == "frontend-design-review")
    assert e[1] == "https://github.com/microsoft/skills" and e[2] == ".github/skills/frontend-design-review" and e[5] == "MIT"

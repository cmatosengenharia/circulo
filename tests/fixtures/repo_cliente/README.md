# repo_cliente

Repositório Python de exemplo para a fábrica (`circulo init <pasta> --cliente`): um módulo (`calc.py`) e um teste
(`tests/teste_calc.py`). O CI do cliente é `python -m pytest -q`, declarado em `[tool.circulo]` no `pyproject.toml`.

O teste se chama `teste_*.py` (e o `pyproject.toml` daqui diz isso ao pytest) para que o pytest do próprio loop, que
varre `tests/`, não o colete: ele só roda dentro de um clone deste repositório.

import importlib
import inspect
import os
import sys
import tempfile
import traceback
from pathlib import Path

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [AQUI, os.getcwd(), os.getcwd() + "/tests"]
for k in ("ANTHROPIC_API_KEY", "GITHUB_TOKEN", "CIRCULO_REPO", "CIRCULO_REPO_DIR", "CLAUDE_CODE_OAUTH_TOKEN",
          "CIRCULO_CONTA", "CIRCULO_LLM_PROVEDOR", "TYPESAFE_API_KEY", "JEV_API_KEY"):
    os.environ.pop(k, None)
os.environ["CIRCULO_SEM_DEVELOPER"] = "1"
os.environ["CIRCULO_GRAFT"] = "0"
import conftest  # noqa: E402
from circulo import configuracao, planejador  # noqa: E402

planejador.dormir = lambda s: None
falhas = 0
nomes = sorted(p.stem for p in Path("tests").glob("test_*.py")) if sys.argv[1] == "ALL" else sys.argv[1].split(",")
for nome_mod in nomes:
    try:
        mod = importlib.import_module(nome_mod)
    except Exception as e:  # noqa: BLE001
        print("IMPORTFAIL", nome_mod, e)
        continue
    for nome, f in list(vars(mod).items()):
        if not nome.startswith("test_") or not callable(f) or (len(sys.argv) > 2 and sys.argv[2] not in nome):
            continue
        tmp = Path(tempfile.mkdtemp())
        configuracao.ENV_FILE = tmp / "circulo-env"
        kw = {}
        for p in inspect.signature(f).parameters:
            if p == "tmp_path":
                kw[p] = tmp
            elif p == "circle":
                kw[p] = conftest.Circle(tmp, jev=conftest.LocalJev(), now=conftest.Clock(conftest.NOON))
            elif p == "repo":
                kw[p] = importlib.import_module("test_self_dev").repo(tmp)
            elif p == "clock":
                kw[p] = conftest.Clock(conftest.NOON)
            else:
                kw = None
                break
        if kw is None:
            print("SKIP", nome_mod, nome)
            continue
        try:
            f(**kw)
            print("PASS", nome_mod, nome)
        except Exception:
            falhas += 1
            print("FAIL", nome_mod, nome)
            traceback.print_exc(limit=4)
sys.exit(1 if falhas else 0)

import contextlib
import importlib
import inspect
import os
import pathlib
import sys
import tempfile
import traceback
import types

for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "TYPESAFE_API_KEY", "JEV_API_KEY", "GITHUB_TOKEN",
          "CIRCULO_REPO", "CIRCULO_REPO_DIR"):
    os.environ.pop(k, None)
os.environ["CIRCULO_SEM_DEVELOPER"] = "1"
pt = types.ModuleType("pytest")
pt.fixture = lambda *a, **k: (a[0] if a and callable(a[0]) else (lambda f: f))


class _Mark:
    def __getattr__(self, n):
        return lambda *a, **k: (lambda f: f)


def raises(e, **k):
    @contextlib.contextmanager
    def cm():
        try:
            yield
        except e:
            return
        raise AssertionError("did not raise")
    return cm()


pt.mark = _Mark()
pt.raises = raises
sys.modules["pytest"] = pt
sys.path[:0] = [".", "tests"]
import conftest  # noqa: E402
from circulo import planejador  # noqa: E402

planejador.dormir = lambda s: None
pt.approx = lambda x, **k: x
ok = fail = skip = 0
mods = sys.argv[1:] or sorted(p.stem for p in pathlib.Path("tests").glob("test_*.py"))
for mod in mods:
    try:
        m = importlib.import_module(mod)
    except Exception as e:
        print("IMPORT", mod, e)
        continue
    for n, f in list(vars(m).items()):
        if not n.startswith("test_") or not callable(f):
            continue
        ps = list(inspect.signature(f).parameters)
        if set(ps) - {"circle", "clock", "tmp_path"}:
            skip += 1
            continue
        tmp = pathlib.Path(tempfile.mkdtemp())
        clock = conftest.Clock(conftest.NOON)
        vals = {"tmp_path": tmp, "clock": clock, "circle": conftest.Circle(tmp, jev=conftest.LocalJev(), now=clock)}
        try:
            f(**{p: vals[p] for p in ps})
            ok += 1
        except Exception:
            fail += 1
            print("FAIL", mod, n)
            traceback.print_exc(limit=4)
print("ok", ok, "fail", fail, "skip", skip)

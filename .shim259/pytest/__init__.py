import contextlib


def fixture(*a, **k):
    if a and callable(a[0]):
        return a[0]
    return lambda f: f


class _Mark:
    def __getattr__(self, n):
        return lambda *a, **k: (lambda f: f)


mark = _Mark()


@contextlib.contextmanager
def raises(e, match=None):
    try:
        yield
    except e:
        return
    raise AssertionError("did not raise")


def approx(x, **k):
    return x

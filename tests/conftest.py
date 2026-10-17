from datetime import datetime

import pytest

from circulo.budget import TZ
from circulo.decision import LocalJev
from circulo.loop import Circle

NOON = datetime.now(TZ).replace(hour=12, minute=0, second=0, microsecond=0)


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "TYPESAFE_API_KEY", "JEV_API_KEY"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def clock():
    return Clock(NOON)


@pytest.fixture
def circle(tmp_path, clock):
    return Circle(tmp_path, jev=LocalJev(), now=clock)


def say(c: Circle, text: str, ticks: int = 1):
    c.submit(text, at=NOON.timestamp())
    results = [c.tick() for _ in range(ticks)]
    reply = c.store.one("SELECT message FROM alerts WHERE kind='resposta' ORDER BY id DESC LIMIT 1")
    return reply["message"] if reply else None, results

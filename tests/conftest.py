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
    # testes são herméticos: nada de chave, repositório ou GitHub de verdade, mesmo rodando na máquina do loop
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_WORKSPACE_ID", "TYPESAFE_API_KEY", "JEV_API_KEY", "GITHUB_TOKEN",
              "CIRCULO_REPO", "CIRCULO_REPO_DIR", "CLAUDE_CODE_OAUTH_TOKEN", "CIRCULO_CONTA", "CIRCULO_LLM_PROVEDOR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CIRCULO_SEM_DEVELOPER", "1")


@pytest.fixture(autouse=True)
def env_file_isolado(monkeypatch, tmp_path):
    # o arquivo de configuração real muda com o loop rodando: o descanso dos testes acordava no 1º pedaço (5 s)
    from circulo import configuracao
    monkeypatch.setattr(configuracao, "ENV_FILE", tmp_path / "circulo-env")


@pytest.fixture(autouse=True)
def sem_espera_do_retry(monkeypatch):
    # a única nova tentativa do Planejador espera segundos com jitter; nos testes, a espera é instantânea
    from circulo import planejador
    monkeypatch.setattr(planejador, "dormir", lambda s: None, raising=False)


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

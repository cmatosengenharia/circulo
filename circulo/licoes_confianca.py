"""Confiança das lições como nos 'instintos' do ECC (skill continuous-learning-v2; ADR 0001, ECC-3), portada para SQLite.

A lição nasce com `INICIAL`. Cada vez que a prevenção segura (a lição fecha como validada/evidenciada, ou o teste dela
passa de novo num sha do main diferente da última checagem; o mesmo sha reexecutado não conta) a confiança sobe
`SOBE`, até `TETO`; cada reincidência tira `CAI`. Abaixo de `QUARENTENA` a prevenção não merece crédito: a lição fica
em quarentena e não sai do círculo. Com `CANDIDATA` ou mais, a lição do loop vira candidata ao AGENTS.md do
repositório cliente (contexto_cursor → contexto_cliente).

Entre repositórios, como o ECC promove o instinto de projeto a global: `observar` guarda a confiança da mesma
assinatura em cada repositório cliente (tabela `licoes_repos`, mesma aritmética); o loop conta como o repositório
`LOOP`, com a confiança da própria lição. A lição presente em `REPOS_GLOBAL` repositórios ou mais com média
`CANDIDATA` ou mais é global (`globais`) e vai ao AGENTS.md mesmo sem 0,8 no loop.

As regras ficam em gatilhos do banco, não em quem escreve: os caminhos que reabrem uma lição (licoes.py e gemeas.py)
e os que a fecham ajustam a confiança sem precisar lembrar dela.
"""
from __future__ import annotations

import sqlite3
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import Store

INICIAL, SOBE, CAI, TETO = 0.3, 0.1, 0.2, 0.9
QUARENTENA, CANDIDATA = 0.2, 0.8
LOOP, REPOS_GLOBAL = "circulo", 2
FECHADAS = ("validada", "evidenciada")
_FECHADAS_SQL = "('validada','evidenciada')"

GATILHOS = (
    f"""CREATE TRIGGER IF NOT EXISTS licoes_confianca_fechou AFTER UPDATE OF status ON licoes
        WHEN NEW.status IN {_FECHADAS_SQL} AND NEW.status != OLD.status
        BEGIN UPDATE licoes SET confianca=MIN({TETO}, ROUND(COALESCE(confianca, {INICIAL}) + {SOBE}, 2)) WHERE id=NEW.id; END""",
    f"""CREATE TRIGGER IF NOT EXISTS licoes_confianca_segurou AFTER UPDATE OF checagens ON licoes
        WHEN OLD.status IN {_FECHADAS_SQL} AND NEW.status = OLD.status AND NEW.checagens IS NOT OLD.checagens
         AND json_valid(NEW.checagens) AND json_extract(NEW.checagens, '$[#-1].exit') = 0
         AND json_extract(NEW.checagens, '$[#-1].sha') IS NOT
             (CASE WHEN json_valid(OLD.checagens) THEN json_extract(OLD.checagens, '$[#-1].sha') END)
        BEGIN UPDATE licoes SET confianca=MIN({TETO}, ROUND(COALESCE(confianca, {INICIAL}) + {SOBE}, 2)) WHERE id=NEW.id; END""",
    f"""CREATE TRIGGER IF NOT EXISTS licoes_confianca_reincidiu AFTER UPDATE OF reincidencias ON licoes
        WHEN NEW.reincidencias > OLD.reincidencias
        BEGIN UPDATE licoes SET confianca=MAX(0, ROUND(COALESCE(confianca, {INICIAL}) - {CAI}, 2)) WHERE id=NEW.id; END""",
)


TABELA = """CREATE TABLE IF NOT EXISTS licoes_repos (assinatura TEXT NOT NULL, repo TEXT NOT NULL,
    confianca REAL NOT NULL, em REAL NOT NULL, PRIMARY KEY (assinatura, repo))"""


def migrar(db: sqlite3.Connection) -> None:
    db.execute(TABELA)
    for sql in GATILHOS:
        db.execute(sql)


def ajustar(confianca: float, segurou: bool) -> float:
    return round(min(TETO, confianca + SOBE) if segurou else max(0.0, confianca - CAI), 2)


def confianca_no_repo(store: Store, repo: str, assinatura: str) -> float | None:
    r = store.one("SELECT confianca FROM licoes_repos WHERE assinatura=? AND repo=?", (assinatura, repo))
    return r["confianca"] if r else None


def observar(store: Store, repo: str, assinatura: str, segurou: bool) -> float:
    """A prevenção da assinatura segurou (True) ou foi contradita (False) no repositório cliente `repo`."""
    if repo == LOOP:
        raise ValueError(f"a confiança do loop ({LOOP}) é a da própria lição, não de licoes_repos")
    atual = confianca_no_repo(store, repo, assinatura)
    nova = ajustar(INICIAL if atual is None else atual, segurou)
    store.x("INSERT INTO licoes_repos(assinatura, repo, confianca, em) VALUES(?,?,?,?) ON CONFLICT(assinatura, repo) "
            "DO UPDATE SET confianca=excluded.confianca, em=excluded.em", (assinatura, repo, nova, time.time()))
    return nova


def em_quarentena(lic) -> bool:
    return float(lic["confianca"] if lic["confianca"] is not None else INICIAL) < QUARENTENA


def quarentena(store: Store) -> list[dict]:
    return [dict(r) for r in store.q("SELECT * FROM licoes WHERE status!='unida' AND confianca < ? ORDER BY id",
                                     (QUARENTENA,))]


def candidatas(store: Store) -> list[dict]:
    """Lições do loop (não de ambiente) com a prevenção segurando e confiança de instinto global."""
    return [dict(r) for r in store.q(f"SELECT * FROM licoes WHERE classe!='ambiente' AND status IN {_FECHADAS_SQL} "
                                     "AND confianca >= ? ORDER BY confianca DESC, id DESC", (CANDIDATA,))]


_GLOBAIS_SQL = (f"SELECT assinatura FROM (SELECT assinatura, '{LOOP}' repo, confianca FROM licoes WHERE classe!='ambiente' "
                f"AND status IN {_FECHADAS_SQL} UNION ALL SELECT assinatura, repo, confianca FROM licoes_repos) "
                "GROUP BY assinatura HAVING COUNT(DISTINCT repo) >= ? AND ROUND(AVG(confianca), 2) >= ?")


def globais(store: Store) -> list[dict]:
    """Lições do loop promovidas a globais: em REPOS_GLOBAL repositórios ou mais, com média CANDIDATA ou mais."""
    return [dict(r) for r in store.q(f"SELECT * FROM licoes WHERE classe!='ambiente' AND status IN {_FECHADAS_SQL} "
                                     f"AND assinatura IN ({_GLOBAIS_SQL}) ORDER BY id", (REPOS_GLOBAL, CANDIDATA))]


def para_agents(store: Store) -> list[dict]:
    """O que vai ao AGENTS.md do cliente: as evidenciadas fora da quarentena, as candidatas e as globais."""
    return [dict(r) for r in store.q(
        f"SELECT * FROM licoes WHERE confianca >= ? AND (status='evidenciada' OR (classe!='ambiente' "
        f"AND status IN {_FECHADAS_SQL} AND (confianca >= ? OR assinatura IN ({_GLOBAIS_SQL})))) "
        "ORDER BY COALESCE(evidenciada_tick, 0) DESC, id DESC", (QUARENTENA, CANDIDATA, REPOS_GLOBAL, CANDIDATA))]

"""Estado persistente do círculo (SQLite). Tudo que o loop precisa para retomar de onde parou."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',      -- pending | processing | done | failed
  attempts INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at REAL NOT NULL,
  processed_at REAL
);

CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER,
  kind TEXT NOT NULL CHECK (kind IN ('despesa','receita')),
  amount_cents INTEGER NOT NULL CHECK (amount_cents > 0 AND typeof(amount_cents) = 'integer'),
  description TEXT NOT NULL,
  category TEXT NOT NULL,
  tag TEXT NOT NULL,
  confidence REAL NOT NULL,
  auto_accepted INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',          -- open | confirmed | corrected
  policy_version INTEGER NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tx_id INTEGER NOT NULL,
  field TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_versions (
  version INTEGER PRIMARY KEY AUTOINCREMENT,
  body TEXT NOT NULL,
  status TEXT NOT NULL,                          -- active | shadow | retired | rolled_back | rejected
  parent INTEGER,
  reason TEXT NOT NULL,
  proposal_id INTEGER,
  created_at REAL NOT NULL,
  activated_tick INTEGER
);

CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  level INTEGER NOT NULL,
  kind TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  description TEXT NOT NULL,
  patch TEXT NOT NULL,
  evidence TEXT NOT NULL,
  status TEXT NOT NULL,                          -- deferred | rejected | shadow | applied | rolled_back | backlog
  notes TEXT,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tick INTEGER NOT NULL,
  question TEXT NOT NULL,
  value TEXT NOT NULL,
  confidence REAL NOT NULL,
  source TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS shadow_obs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version INTEGER NOT NULL,
  tx_id INTEGER NOT NULL,
  would_accept INTEGER NOT NULL,
  UNIQUE(version, tx_id)
);

CREATE TABLE IF NOT EXISTS budget (
  day TEXT PRIMARY KEY,
  tokens INTEGER NOT NULL DEFAULT 0,
  jev_calls INTEGER NOT NULL DEFAULT 0,
  llm_calls INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS metrics (
  tick INTEGER PRIMARY KEY,
  body TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS merges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pr INTEGER NOT NULL,
  sha TEXT NOT NULL,
  merged INTEGER NOT NULL,
  reason TEXT NOT NULL,
  details TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nome TEXT NOT NULL,
  pedido TEXT NOT NULL,
  tipo TEXT NOT NULL,
  kit TEXT,
  status TEXT NOT NULL,          -- ativo | aguardando_kit | manutencao | pausado | arquivado
  proposito TEXT NOT NULL,
  tipo_confianca REAL NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

-- todo ponto de verificação (validação, verificação, evidência) deixa um registro: o loop se monitora
CREATE TABLE IF NOT EXISTS verificacoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tick INTEGER NOT NULL,
  ponto TEXT NOT NULL,
  sujeito TEXT,
  ok INTEGER NOT NULL,
  assinatura TEXT,
  motivo TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verificacoes_ponto ON verificacoes(ponto, created_at);
CREATE INDEX IF NOT EXISTS idx_verificacoes_assinatura ON verificacoes(assinatura, created_at);

-- erros aprendidos: uma assinatura por causa; o mesmo erro de estrutura só acontece uma vez
CREATE TABLE IF NOT EXISTS licoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  assinatura TEXT NOT NULL UNIQUE,
  ponto TEXT NOT NULL,
  classe TEXT NOT NULL,          -- estrutural | trabalho | ambiente
  descricao TEXT NOT NULL,
  prevencao TEXT,
  status TEXT NOT NULL,          -- aberta | em_correcao | validada | evidenciada | reincidente
  ocorrencias INTEGER NOT NULL,
  reincidencias INTEGER NOT NULL,
  item_id INTEGER,
  pr INTEGER,
  primeira_tick INTEGER,
  ultima_tick INTEGER,
  corrigida_tick INTEGER,
  evidenciada_tick INTEGER,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

-- portões aprendidos (neurogênese): nascem de uma lição e barram o erro antes de a saída do neurônio seguir adiante
CREATE TABLE IF NOT EXISTS portoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  neuronio TEXT NOT NULL,
  tipo TEXT NOT NULL,            -- comando | proibido | obrigatorio
  spec TEXT NOT NULL,
  descricao TEXT,
  licao_id INTEGER,
  ativo INTEGER NOT NULL,
  avaliacoes INTEGER NOT NULL,
  bloqueios INTEGER NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(neuronio, tipo, spec)
);

-- conselho de perguntas: toda autoevolução parte de uma pergunta feita por uma perspectiva (persona)
CREATE TABLE IF NOT EXISTS perguntas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chave TEXT NOT NULL,
  persona TEXT NOT NULL,
  texto TEXT NOT NULL,
  relevancia REAL,
  score REAL,
  evidencia TEXT,
  status TEXT NOT NULL,          -- feita | virou_item | entregue | contestada | repetida | descartada
  item_id INTEGER,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

-- perspectivas do conselho: as do loop e as de cada tipo de missão (criadas pelo Questionador)
CREATE TABLE IF NOT EXISTS personas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cerebro TEXT NOT NULL,         -- loop | missao:<tipo>
  chave TEXT NOT NULL,
  objetivo TEXT NOT NULL,
  origem TEXT NOT NULL,          -- gerada
  created_at REAL NOT NULL,
  UNIQUE(cerebro, chave)
);

-- perguntas criadas pelo Questionador (LLM especializada), presas a uma métrica do catálogo (priorizadas sem LLM)
CREATE TABLE IF NOT EXISTS perguntas_modelo (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  persona TEXT NOT NULL,
  texto TEXT NOT NULL,
  metrica TEXT NOT NULL,
  origem TEXT NOT NULL,
  ativo INTEGER NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fingerprint TEXT NOT NULL UNIQUE,
  stage TEXT NOT NULL,
  kind TEXT NOT NULL,
  message TEXT NOT NULL,
  trace TEXT,
  project_id INTEGER,
  count INTEGER NOT NULL,
  first_seen REAL NOT NULL,
  last_seen REAL NOT NULL,
  first_tick INTEGER NOT NULL,
  last_tick INTEGER NOT NULL,
  status TEXT NOT NULL,          -- aberto | isolado | resolvido
  resolution TEXT
);

CREATE TABLE IF NOT EXISTS roadmap (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  titulo TEXT NOT NULL,
  detalhe TEXT NOT NULL,
  origem TEXT NOT NULL,          -- pedido_cassio | erro | circulo
  status TEXT NOT NULL,          -- feito | parcial | em_andamento | pendente
  evidencia TEXT NOT NULL,
  ordem INTEGER NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS memory (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,             -- achado | licao | feedback | entrega
  text TEXT NOT NULL,
  tipo TEXT,
  project_id INTEGER,
  source TEXT,
  trust TEXT NOT NULL,            -- confiavel | nao_confiavel
  status TEXT NOT NULL,           -- ativa | quarentena | aposentada
  meta TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rubrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  version INTEGER NOT NULL,
  criteria TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS deliverables (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  version INTEGER NOT NULL,
  formato TEXT NOT NULL,
  path TEXT NOT NULL,
  content TEXT NOT NULL,
  nota REAL,
  nota_oculta REAL,
  notas TEXT,
  status TEXT NOT NULL,           -- atual | anterior | descartada (nada é apagado)
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cycles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  tick INTEGER NOT NULL,
  fase TEXT NOT NULL,
  nota_antes REAL,
  nota_depois REAL,
  ganho REAL,
  aceita INTEGER,
  tokens INTEGER NOT NULL,
  lessons TEXT,
  resultado TEXT,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS harness_experiments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role TEXT NOT NULL,
  variante TEXT NOT NULL,
  trials TEXT NOT NULL,
  status TEXT NOT NULL,          -- rodando | promovido | descartado | rejeitado
  notes TEXT,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS prs (
  number INTEGER PRIMARY KEY,
  project_id INTEGER,
  titulo TEXT NOT NULL,
  branch TEXT,
  status TEXT NOT NULL,           -- aberto | mergeado | fechado
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS trail (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  tick INTEGER NOT NULL,
  etapa TEXT NOT NULL,
  project_id INTEGER,
  em REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS links (
  a INTEGER NOT NULL,
  b INTEGER NOT NULL,
  relacao TEXT NOT NULL,
  forca REAL NOT NULL,
  evidencia TEXT NOT NULL,
  origem TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  PRIMARY KEY (a, b)
);

CREATE TABLE IF NOT EXISTS transfers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lesson_id INTEGER NOT NULL,
  copia_id INTEGER NOT NULL,
  de INTEGER NOT NULL,
  para INTEGER NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  tick INTEGER NOT NULL,
  fase TEXT NOT NULL,
  versao INTEGER,
  antes REAL, depois REAL, oculta_antes REAL, oculta_depois REAL,
  checks TEXT,
  jev_avanca REAL, jev_contraprova REAL,
  decisao TEXT NOT NULL,          -- avancar | descartar | refazer | cumprida | base
  motivo TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_calls (
  -- registro estruturado e permanente de cada chamada de LLM: qual modelo, quem escolheu (Jev), por quê,
  -- quanto custou e se o resultado foi aceito. É contexto para as próximas escolhas do Jev.
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tick INTEGER NOT NULL,
  project_id INTEGER,
  papel TEXT NOT NULL,            -- researcher | rubric | builder | improver | reflector | developer | fallback:<pergunta>
  modelo TEXT NOT NULL,
  nivel TEXT,                     -- pequena | grande
  decidido_por TEXT NOT NULL,     -- jev | local | harness (Jev inseguro: vale o padrão do harness) | fixo
  confianca REAL,
  contexto TEXT,                  -- o que o Jev viu ao escolher (JSON)
  tokens INTEGER NOT NULL DEFAULT 0,
  duracao_ms INTEGER,
  ok INTEGER NOT NULL,
  erro TEXT,
  entrada TEXT,                   -- início do pedido (para lembrar do que se tratava)
  saida TEXT,                     -- início da resposta
  aceita INTEGER,                 -- o ciclo que usou esta chamada foi aceito pela catraca?
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS llm_calls_papel ON llm_calls(papel, nivel);

-- trilha write-ahead (circulo/intencoes.py): a intenção entra antes da ação; só de acréscimo, encadeada por hash
CREATE TABLE IF NOT EXISTS intencoes (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  tipo TEXT NOT NULL,             -- intencao (antes de executar) | resultado (depois, com ref)
  ref INTEGER,
  tick INTEGER,
  ator TEXT NOT NULL,             -- loop | humano | teste
  acao TEXT NOT NULL,
  motivo TEXT,
  regra TEXT,                     -- quem decidiu: regra, jev ou llm (e com que confiança)
  entradas TEXT,
  em REAL NOT NULL,
  prev TEXT NOT NULL,
  hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS intencoes_ref ON intencoes(ref);
CREATE TRIGGER IF NOT EXISTS intencoes_sem_update BEFORE UPDATE ON intencoes
  BEGIN SELECT RAISE(ABORT, 'trilha de intenções é só de acréscimo'); END;
CREATE TRIGGER IF NOT EXISTS intencoes_sem_delete BEFORE DELETE ON intencoes
  BEGIN SELECT RAISE(ABORT, 'trilha de intenções é só de acréscimo'); END;

CREATE TABLE IF NOT EXISTS frescor (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  atraso_ms REAL NOT NULL,        -- atraso dado → tela medido pelo próprio painel (SLO: p99 ≤ 3 s em 24 h)
  em REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS frescor_em ON frescor(em);

CREATE TABLE IF NOT EXISTS run_errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,                    -- execução (giro) em que o erro aconteceu: o painel abre o erro por ele
  tick INTEGER NOT NULL,
  stage TEXT NOT NULL,
  kind TEXT NOT NULL,
  message TEXT NOT NULL,
  trace TEXT,
  incident_id INTEGER,
  em REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS run_errors_run ON run_errors(run_id);
CREATE INDEX IF NOT EXISTS run_errors_em ON run_errors(em);

-- rastreabilidade de ponta a ponta: elos entre o que o loop faz (pedido → item → giro → PR → merge → versão → evidência)
CREATE TABLE IF NOT EXISTS elos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  de TEXT NOT NULL,
  para TEXT NOT NULL,
  relacao TEXT NOT NULL,
  detalhe TEXT,
  em REAL NOT NULL,
  UNIQUE(de, para, relacao)
);
CREATE INDEX IF NOT EXISTS elos_de ON elos(de);
CREATE INDEX IF NOT EXISTS elos_para ON elos(para);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at REAL NOT NULL,
  delivered INTEGER NOT NULL DEFAULT 0
);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # Uma conexão compartilhada entre as threads do loop (missões evoluem em paralelo):
        # toda operação passa pelo mesmo lock, e uma transação segura o lock do começo ao fim.
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self._migrate()

    # colunas adicionadas depois da primeira versão (bancos antigos ganham a coluna sem perder dados)
    MIGRATIONS = (("decisions", "project_id", "INTEGER"), ("proposals", "project_id", "INTEGER"),
                  ("alerts", "project_id", "INTEGER"), ("metrics", "project_id", "INTEGER"),
                  ("projects", "melhor_nota", "REAL"), ("projects", "ciclos", "INTEGER"), ("projects", "plateau", "INTEGER"),
                  ("projects", "ultima_pesquisa_tick", "INTEGER"), ("projects", "ultimo_ciclo_tick", "INTEGER"),
                  ("projects", "ultimo_ciclo_em", "REAL"), ("proposals", "rollbacks", "INTEGER"),
                  ("cycles", "braco", "TEXT"), ("cycles", "experimento", "INTEGER"),
                  ("trail", "detalhe", "TEXT"), ("roadmap", "desativado", "INTEGER"), ("alerts", "evento", "INTEGER"),
                  ("shadow_obs", "tag_ativa", "TEXT"), ("shadow_obs", "tag_shadow", "TEXT"),
                  ("roadmap", "estudo", "TEXT"), ("trail", "run_id", "TEXT"), ("trail", "tarefa", "TEXT"),
                  ("perguntas", "cerebro", "TEXT"), ("projects", "paralelo", "INTEGER"))

    def _migrate(self) -> None:
        for table, col, typ in self.MIGRATIONS:
            cols = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        self.db.execute("CREATE INDEX IF NOT EXISTS trail_run ON trail(run_id)")

    # ---------- utilidades ----------
    def tx(self):
        return _Tx(self.db, self.lock)

    def q(self, sql: str, args: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return list(self.db.execute(sql, tuple(args)))

    def one(self, sql: str, args: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.db.execute(sql, tuple(args)).fetchone()

    def x(self, sql: str, args: Iterable[Any] = ()) -> int:
        with self.lock:
            cur = self.db.execute(sql, tuple(args))
            return cur.lastrowid

    def run(self, sql: str, args: Iterable[Any] = ()) -> int:
        """Como x(), mas devolve quantas linhas mudaram."""
        with self.lock:
            return self.db.execute(sql, tuple(args)).rowcount

    # ---------- kv ----------
    def get(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def set(self, key: str, value: Any) -> None:  # noqa: A003
        self.x("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, json.dumps(value, ensure_ascii=False)))

    def next_tick(self) -> int:
        with self.tx():
            t = int(self.get("tick", 0)) + 1
            self.set("tick", t)
        return t

    @property
    def tick(self) -> int:
        return int(self.get("tick", 0))

    # ---------- eventos (fila de pedidos) ----------
    def enqueue(self, kind: str, payload: dict) -> int:
        return self.x("INSERT INTO events(kind,payload,created_at) VALUES(?,?,?)",
                      (kind, json.dumps(payload, ensure_ascii=False), time.time()))

    def claim_next_event(self) -> sqlite3.Row | None:
        with self.tx():
            row = self.one("SELECT * FROM events WHERE status='pending' ORDER BY id LIMIT 1")
            if row:
                self.x("UPDATE events SET status='processing', attempts=attempts+1 WHERE id=?", (row["id"],))
        return row

    def finish_event(self, event_id: int, ok: bool, error: str | None = None, max_attempts: int = 3) -> None:
        if ok:
            self.x("UPDATE events SET status='done', processed_at=? WHERE id=?", (time.time(), event_id))
            return
        row = self.one("SELECT attempts FROM events WHERE id=?", (event_id,))
        status = "failed" if row and row["attempts"] >= max_attempts else "pending"
        self.x("UPDATE events SET status=?, error=? WHERE id=?", (status, error, event_id))

    def recover_interrupted(self) -> int:
        """Eventos que estavam 'processing' quando o processo caiu voltam para a fila."""
        cur = self.db.execute("UPDATE events SET status='pending' WHERE status='processing'")
        return cur.rowcount

    def pending_count(self) -> int:
        return self.one("SELECT COUNT(*) c FROM events WHERE status='pending'")["c"]


class _Tx:
    def __init__(self, db: sqlite3.Connection, lock):
        self.db = db
        self.lock = lock
        self.nested = False

    def __enter__(self):
        self.lock.acquire()
        self.nested = self.db.in_transaction
        if not self.nested:
            self.db.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if not self.nested:
                self.db.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.lock.release()
        return False

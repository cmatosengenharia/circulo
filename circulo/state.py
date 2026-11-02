"""Estado persistente do círculo (SQLite). Tudo que o loop precisa para retomar de onde parou."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from circulo import licoes_confianca, roadmap

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

-- base vermelha do pré-voo: uma linha por (item, assinatura do teste, sha da main), as repetições no contador (Sentry)
CREATE TABLE IF NOT EXISTS base_vermelha (
  item_id INTEGER NOT NULL,
  assinatura TEXT NOT NULL,
  sha TEXT NOT NULL,
  causa TEXT,
  ocorrencias INTEGER NOT NULL,
  primeira_vez REAL NOT NULL,
  ultima_vez REAL NOT NULL,
  PRIMARY KEY (item_id, assinatura, sha)
);

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
  updated_at REAL NOT NULL,
  confianca REAL NOT NULL DEFAULT 0.3  -- licoes_confianca.py
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
  status TEXT NOT NULL,          -- feita | virou_item | entregue | contestada | repetida | descartada | quarentenada | recusada_porteiro | descartada_abaixo_do_limiar
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

CREATE TABLE IF NOT EXISTS experimentos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item_id INTEGER NOT NULL UNIQUE,
  hipotese TEXT NOT NULL,
  metrica TEXT NOT NULL,
  guarda INTEGER NOT NULL,
  baseline REAL NOT NULL,
  alvo REAL NOT NULL,
  margem_nao_inferioridade REAL NOT NULL,
  janela_s REAL NOT NULL,
  n_min INTEGER NOT NULL,
  inicio REAL,
  fim REAL,
  estendida INTEGER NOT NULL DEFAULT 0,
  medido REAL,
  n INTEGER,
  veredito TEXT,                 -- melhorou | neutro | piorou | inconclusivo
  decidido_em REAL,
  reversao_item INTEGER,
  created_at REAL NOT NULL
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

CREATE TABLE IF NOT EXISTS llm_cache (
  -- uma linha por chamada de LLM (circulo/llm_cache.py): o acerto potencial medido em modo sombra e, por TTL_S,
  -- a resposta completa de chamada que deu certo (servida só se o ciclo foi aceito e a taxa de 24 h passa do limiar)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chave TEXT NOT NULL,            -- sha256(neurônio + modelo + system + prompt normalizados)
  papel TEXT NOT NULL,
  chamada INTEGER,                -- llm_calls.id
  acerto_potencial INTEGER NOT NULL,
  servido INTEGER NOT NULL DEFAULT 0,
  texto TEXT,
  citacoes TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS llm_cache_chave ON llm_cache(chave, created_at);
CREATE INDEX IF NOT EXISTS llm_cache_em ON llm_cache(created_at);

CREATE TABLE IF NOT EXISTS gasto_cursor (
  -- gasto do Cursor em centavos de US$ por dia, assunto e tipo de tarefa (circulo/gasto_cursor.py)
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dia TEXT NOT NULL,
  assunto TEXT,
  tipo TEXT,
  modelo TEXT,
  tokens INTEGER NOT NULL DEFAULT 0,
  centavos INTEGER NOT NULL,
  origem TEXT NOT NULL,           -- manual | csv
  chave TEXT UNIQUE,              -- hash da linha do CSV: reimportar não duplica
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS gasto_cursor_dia ON gasto_cursor(dia);

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
  em REAL NOT NULL,
  versao TEXT                     -- versão da página que mediu; só a página no ar entra no SLO
);
CREATE INDEX IF NOT EXISTS frescor_em ON frescor(em);

CREATE TABLE IF NOT EXISTS canarios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ponto TEXT NOT NULL,            -- ponto de verificação que nunca falhou; a falha foi injetada num estado temporário
  ok INTEGER NOT NULL,            -- 1 = a falha injetada foi acusada e o controle sem falha passou
  velho_falhou INTEGER NOT NULL,
  fresco_passou INTEGER NOT NULL,
  em REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS canarios_ponto ON canarios(ponto, em);

CREATE TABLE IF NOT EXISTS revisoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pr INTEGER,
  item_id INTEGER,
  momento TEXT NOT NULL,
  veredito TEXT NOT NULL,
  motivo TEXT,
  evidencia TEXT,
  conf REAL,
  fonte TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS revisoes_pr ON revisoes(pr);

CREATE TABLE IF NOT EXISTS vigia (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chave TEXT NOT NULL,
  titulo TEXT NOT NULL,
  evidencia TEXT,
  sugestao TEXT,
  gravidade REAL,
  veredito TEXT,                 -- trava | nao_trava | em_duvida
  acao TEXT,                     -- abrir_item | alertar | observar | ignorar
  conf REAL,
  classificacao TEXT,
  status TEXT NOT NULL,          -- aberta | resolvida
  item_id INTEGER,
  primeira_em REAL NOT NULL,
  ultima_em REAL NOT NULL,
  resolvida_em REAL,
  vezes INTEGER NOT NULL DEFAULT 1
);

-- cada ação executada pelo Vigia (abrir item ou alertar): contador que só cresce; a janela é calculada na leitura
CREATE TABLE IF NOT EXISTS vigia_disparos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chave TEXT NOT NULL,
  acao TEXT NOT NULL,
  evidencia TEXT,
  em REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS vigia_disparos_chave ON vigia_disparos(chave, em);

-- rodadas de comentário de revisão seguidas de commit de correção, medidas uma vez por PR mergeado (rodadas_revisao.py)
CREATE TABLE IF NOT EXISTS rodadas_revisao (
  pr INTEGER PRIMARY KEY,
  rodadas INTEGER NOT NULL,
  comentarios INTEGER NOT NULL,
  commits INTEGER NOT NULL,
  mergeado_em REAL NOT NULL,
  medido_em REAL NOT NULL
);

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

-- da pergunta validada ao item: cada sub-etapa com o id da pergunta (a espera de cada passagem tem dono)
CREATE TABLE IF NOT EXISTS pergunta_etapas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pergunta_id INTEGER NOT NULL,
  etapa TEXT NOT NULL CHECK(etapa IN ('validada','porteiro_decidiu','planejador_chamado','item_gravado')),
  detalhe TEXT,
  em REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS pergunta_etapas_p ON pergunta_etapas(pergunta_id, id);

-- resposta do Planejador por pergunta normalizada (circulo/planejador_cache.py): a mesma pergunta com evidência quase
-- igual em 24 h não volta à LLM; em_andamento enquanto a LLM responde, para dois giros não perguntarem juntos
CREATE TABLE IF NOT EXISTS planejador_cache (
  chave TEXT PRIMARY KEY,         -- sha256 da pergunta e do nome da métrica normalizados
  estado TEXT NOT NULL,           -- em_andamento | completa
  pergunta_id INTEGER NOT NULL,   -- a pergunta que a LLM respondeu (a origem do acerto)
  evidencia TEXT,                 -- a evidência dessa pergunta: comparada número a número por tolerância relativa
  desfecho TEXT,
  motivo TEXT,
  item_id INTEGER,
  em REAL NOT NULL
);

-- laboratório do Jev: a mesma pergunta em duas formulações, na mesma chamada, para adotar a melhor com evidência
CREATE TABLE IF NOT EXISTS jev_lab (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pergunta TEXT NOT NULL,
  valor_pt TEXT,
  conf_pt REAL,
  valor_en TEXT,
  conf_en REAL,
  modelo TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jev_lab_p ON jev_lab(pergunta, id);

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
        # timeout 30 s: o painel/SRE em processo próprio escreve enquanto o loop segura uma transação (antes, 5 s → "database is locked")
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False, timeout=30.0)
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
                  ("perguntas", "cerebro", "TEXT"), ("projects", "paralelo", "INTEGER"),
                  ("projects", "pausada", "INTEGER"), ("projects", "pausada_em", "REAL"), ("licoes", "camada", "TEXT"),
                  ("decisions", "probabilidades", "TEXT"), ("licoes", "node_id", "TEXT"), ("licoes", "origens", "TEXT"),
                  ("licoes", "checagens", "TEXT"), ("licoes", "aberta_em", "REAL"),
                  ("perguntas", "eixo", "TEXT"), ("perguntas", "pertinencia", "REAL"), ("perguntas", "acionavel", "INTEGER"),
                  ("perguntas", "classificacao", "TEXT"), ("roadmap", "pai", "INTEGER"), ("perguntas", "motivo", "TEXT"),
                  ("verificacoes", "item_id", "INTEGER"), ("verificacoes", "item_titulo", "TEXT"),
                  ("verificacoes", "causa", "TEXT"),
                  ("events", "job", "TEXT"), ("events", "job_fonte", "TEXT"), ("events", "job_conf", "REAL"),
                  ("events", "job_margem", "REAL"),
                  ("llm_calls", "tokens_entrada", "INTEGER"), ("llm_calls", "tokens_saida", "INTEGER"),
                  ("llm_calls", "cache_lido", "INTEGER"), ("llm_calls", "cache_escrito", "INTEGER"),
                  ("llm_calls", "job", "TEXT"), ("llm_calls", "retry", "INTEGER NOT NULL DEFAULT 0"),
                  ("llm_calls", "variante", "TEXT"),
                  ("prs", "item_id", "INTEGER"), ("prs", "arquivos", "TEXT"), ("prs", "conserto", "TEXT"),
                  ("prs", "consertos", "INTEGER DEFAULT 0"), ("prs", "conserto_sha", "TEXT"),
                  ("decisions", "estado", "TEXT"), ("roadmap", "modulo", "TEXT"), ("ledger", "import_key", "TEXT"),
                  ("frescor", "versao", "TEXT"),
                  ("vigia_disparos", "giro", "INTEGER"), ("vigia_disparos", "resultado", "TEXT"),
                  ("vigia_disparos", "giros_ate_destravar", "INTEGER"), ("vigia_disparos", "padrao", "TEXT"),
                  ("licoes", "confianca", f"REAL NOT NULL DEFAULT {licoes_confianca.INICIAL}"))

    def _migrate(self) -> None:
        for table, col, typ in self.MIGRATIONS:
            cols = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        roadmap.migrar(self.db)
        licoes_confianca.migrar(self.db)
        # a lição que volta a ficar aberta (reincidência, reabertura no main) carimba quando: a idade da trava é a do
        # período aberto atual, não a de created_at (item #170: reincidiu agora e o Vigia via "aberta há 76 h")
        self.db.execute("""CREATE TRIGGER IF NOT EXISTS licoes_aberta_em AFTER UPDATE OF status ON licoes
                           WHEN NEW.status IN ('aberta','em_correcao','reincidente')
                            AND OLD.status NOT IN ('aberta','em_correcao','reincidente')
                           BEGIN UPDATE licoes SET aberta_em=(julianday('now') - 2440587.5) * 86400.0 WHERE id=NEW.id; END""")
        self.db.execute("CREATE INDEX IF NOT EXISTS trail_run ON trail(run_id)")
        # `decisions` cresce uma linha por pergunta e é varrida por pergunta/data em toda passagem (indagador, perguntas, jev_lab)
        self.db.execute("CREATE INDEX IF NOT EXISTS decisions_q_em ON decisions(question, created_at)")
        self.db.execute("CREATE INDEX IF NOT EXISTS decisions_em ON decisions(created_at)")
        # extrato reimportado não duplica: a chave (FITID ou hash+ocorrência) é única no ledger
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ledger_import_key ON ledger(import_key) WHERE import_key IS NOT NULL")

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
        from .pedidos import canal
        return self.x("INSERT INTO events(kind,payload,created_at) VALUES(?,?,?)",
                      (kind, json.dumps({**payload, "canal": canal(payload)}, ensure_ascii=False), time.time()))

    def claim_next_event(self) -> sqlite3.Row | None:
        from .pausa import evento_em_espera, pausadas
        paradas = pausadas(self)        # pedido de missão pausada fica guardado na fila até você retomar
        with self.tx():
            row = None
            for r in self.q("SELECT * FROM events WHERE status='pending' ORDER BY id LIMIT 500"):
                if not evento_em_espera(self, r["kind"], r["payload"], paradas):
                    row = r
                    break
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
        from .pausa import evento_em_espera, pausadas
        paradas = pausadas(self)
        if not paradas:
            return self.one("SELECT COUNT(*) c FROM events WHERE status='pending'")["c"]
        return sum(1 for r in self.q("SELECT kind, payload FROM events WHERE status='pending'")
                   if not evento_em_espera(self, r["kind"], r["payload"], paradas))


class _Tx:
    def __init__(self, db: sqlite3.Connection, lock):
        self.db = db
        self.lock = lock
        self.nested = False

    def __enter__(self):
        self.lock.acquire()
        try:
            self.nested = self.db.in_transaction
            if not self.nested:
                self.db.execute("BEGIN IMMEDIATE")
        except BaseException:          # BEGIN falhou (outro processo segura a escrita): o lock não pode vazar
            self.lock.release()
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if not self.nested:
                try:
                    self.db.execute("ROLLBACK" if exc_type else "COMMIT")
                except sqlite3.Error:
                    if self.db.in_transaction:      # COMMIT falhou (disco, I/O): não deixa a transação aberta para sempre
                        self.db.execute("ROLLBACK")
                    raise
        finally:
            self.lock.release()
        return False

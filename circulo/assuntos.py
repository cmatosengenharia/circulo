"""Espaço de trabalho por assunto (tribo, squad, cada microsserviço, a migração Blip → Amazon Connect).

Cada assunto tem descrição, links, decisões, pendências e notas. O Cássio anota em uma frase
('decidimos X no serviço Y', 'pendência: Z'); o tipo sai da própria frase (regra), o assunto o Jev escolhe
(`assunto_arquivo`, com a sobreposição de palavras como regra local) e a nota vai para o Graft. Depois
'o que decidimos sobre X?' volta com a data e a frase de origem, como num registro de decisão (ADR).

Só notas, links e decisões: frase com cara de credencial ou de código é recusada antes de tocar o banco.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

from . import graft
from .budget import TZ
from .decision import Decision, Question
from .memoria import termos
from .state import Store

ESQUEMA = """
CREATE TABLE IF NOT EXISTS assuntos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nome TEXT NOT NULL UNIQUE,
  descricao TEXT NOT NULL DEFAULT '',
  links TEXT NOT NULL DEFAULT '',          -- um por linha
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS assunto_notas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  assunto_id INTEGER NOT NULL REFERENCES assuntos(id),
  tipo TEXT NOT NULL,                      -- decisao | pendencia | link | nota
  texto TEXT NOT NULL,
  origem TEXT NOT NULL,                    -- a frase como foi dita
  confianca REAL,
  graft_id TEXT,
  created_at REAL NOT NULL,
  feita_em REAL                            -- pendência marcada como feita pela tela
);
CREATE INDEX IF NOT EXISTS assunto_notas_assunto ON assunto_notas(assunto_id, tipo, created_at);
CREATE TABLE IF NOT EXISTS assunto_regras (    -- a escolha do clique na tela: estes termos vão para este assunto
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  termos TEXT NOT NULL UNIQUE,             -- termos da nota, ordenados, separados por espaço
  assunto_id INTEGER NOT NULL REFERENCES assuntos(id),
  created_at REAL NOT NULL
);
"""
PERGUNTA = "assunto_arquivo"
CONFIANCA_MIN = 0.3
COBERTURA_REGRA = 0.5                    # fração dos termos de uma regra aprendida que a nota precisa ter
OPCOES = 3
TRECHO = 200
URL = re.compile(r"https?://\S+")
PROIBIDO = re.compile(
    r"(?i)\b(senha|password|passwd|secret|segredo|token|api[_-]?key|client[_-]?secret)\b[^.\n]{0,40}[:=]\s*\S"
    r"|AKIA[0-9A-Z]{16}|\bgh[pousr]_[A-Za-z0-9]{20,}|\bxox[abprs]-|-----BEGIN [A-Z ]*PRIVATE KEY"
    r"|://[^/\s:@]+:[^/\s@]+@|```|^\s*(import \w|from \S+ import |def \w+\(|class \w+[:(])", re.M)
TIPOS = (("decisao", re.compile(r"(?i)^\s*(decis[aã]o\s*:|decidid[oa]\s*:|decidimos\s+(que\s+)?|decidiram\s+(que\s+)?)")),
         ("pendencia", re.compile(r"(?i)^\s*(pend[eê]ncia|todo|a fazer)\s*:\s*")),
         ("nota", re.compile(r"(?i)^\s*nota\s*:\s*")))
FILTRO = {"decisao": re.compile(r"(?i)\bdecid|\bdecis"), "pendencia": re.compile(r"(?i)\bpend[eê]n"),
          "link": re.compile(r"(?i)\blinks?\b")}


def preparar(store: Store) -> None:
    if getattr(store, "_assuntos_pronto", False):
        return
    for sql in ESQUEMA.strip().split(";"):
        if sql.strip():
            store.x(sql)
    if "feita_em" not in {r["name"] for r in store.q("PRAGMA table_info(assunto_notas)")}:
        store.x("ALTER TABLE assunto_notas ADD COLUMN feita_em REAL")
    store._assuntos_pronto = True


def criar(store: Store, nome: str, descricao: str = "", links: list[str] | tuple[str, ...] = (), agora: float | None = None) -> int:
    preparar(store)
    _sem_segredo(" ".join([nome, descricao, *links]))
    return store.x("INSERT INTO assuntos(nome, descricao, links, created_at) VALUES(?,?,?,?)",
                   (nome.strip(), descricao.strip(), "\n".join(x.strip() for x in links if x.strip()), agora or time.time()))


def _sem_segredo(texto: str) -> None:
    if PROIBIDO.search(texto or ""):
        raise ValueError("isto parece credencial ou código da empresa: aqui só entram notas, links e decisões")


def classificar(frase: str) -> tuple[str, str]:
    """(tipo, texto sem o prefixo) pela própria frase."""
    for tipo, rx in TIPOS:
        m = rx.match(frase)
        if m:
            return tipo, frase[m.end():].strip() or frase.strip()
    return ("link" if URL.search(frase) else "nota"), frase.strip()


class SemAssunto(ValueError):
    """O Jev e as regras não sabem onde arquivar: a tela mostra o trecho e as opções para um clique."""

    def __init__(self, msg: str, trecho: str, opcoes: list[dict]):
        super().__init__(msg)
        self.trecho, self.opcoes = trecho, opcoes


def _rotulo(a) -> str:
    return f"{a['nome']}: {a['descricao']}" if a["descricao"] else a["nome"]


def regra(jev, qid: str, q: Question, state) -> Decision:
    """A regra local (LocalJev) quando o Jev está em dúvida ou nos testes: o assunto que mais divide palavras com a nota."""
    nota = set(termos(URL.sub(" ", state.get("note", "")), 30))
    pontos = {op: len(nota & set(termos(desc, 30))) for op, desc in (q.criteria or {}).items()}
    melhor = max(pontos.values(), default=0)
    lideres = [op for op, p in pontos.items() if p == melhor]
    if not melhor or len(lideres) > 1:
        return Decision(qid, "choice", q.options()[-1], 0.0, jev.source)
    return Decision(qid, "choice", lideres[0], 0.6, jev.source)


def anotar(store: Store, dl, frase: str, agora: float | None = None) -> dict:
    """Arquiva a frase no assunto que o Jev escolher e indexa no Graft. Se ele não decide, vale a regra aprendida
    no clique; sem ela, levanta SemAssunto com as opções para a tela."""
    preparar(store)
    frase = (frase or "").strip()
    _sem_segredo(frase)
    tipo, texto = classificar(frase)
    if len(texto) < 3:
        raise ValueError("nota vazia")
    todos = store.q("SELECT * FROM assuntos ORDER BY id")
    if not todos:
        raise ValueError("nenhum assunto criado ainda")
    opcoes = {f"a{a['id']}": _rotulo(a) for a in todos}
    d = dl.ask(PERGUNTA, Question(
        "choice", "Which subject of the user's workspace does this `note` belong to? Pick the subject the note is "
                  "about (a team, a service by name, a migration), not the one it merely mentions in passing.", opcoes),
        {"note": frase, "subjects": opcoes})
    if d.value in opcoes and d.confidence >= CONFIANCA_MIN:
        return _gravar(store, next(x for x in todos if f"a{x['id']}" == d.value), tipo, texto, frase, d.confidence, agora)
    aprendida = _regra_aprendida(store, texto)
    if aprendida:
        return _gravar(store, aprendida[0], tipo, texto, frase, aprendida[1], agora)
    raise SemAssunto("não sei em que assunto arquivar; escolha um abaixo ou diga o nome dele na frase. Assuntos: "
                     + ", ".join(a["nome"] for a in todos), frase[:TRECHO], _opcoes(store, todos, texto))


def arquivar(store: Store, frase: str, assunto_id: int, agora: float | None = None) -> dict:
    """O clique da tela: arquiva no assunto escolhido e grava (termos da nota → assunto) como regra local."""
    preparar(store)
    frase = (frase or "").strip()
    _sem_segredo(frase)
    tipo, texto = classificar(frase)
    if len(texto) < 3:
        raise ValueError("nota vazia")
    a = store.one("SELECT * FROM assuntos WHERE id=?", (assunto_id,))
    if not a:
        raise ValueError("assunto não existe")
    agora = agora or time.time()
    chave = " ".join(sorted(_termos(texto)))
    if chave:
        store.x("INSERT INTO assunto_regras(termos, assunto_id, created_at) VALUES(?,?,?) "
                "ON CONFLICT(termos) DO UPDATE SET assunto_id=excluded.assunto_id, created_at=excluded.created_at",
                (chave, a["id"], agora))
    return _gravar(store, a, tipo, texto, frase, 1.0, agora)


def _termos(texto: str) -> set[str]:
    return set(termos(URL.sub(" ", texto), 30))


def _regra_aprendida(store: Store, texto: str):
    """(assunto, cobertura) da regra do clique que a nota mais cobre, se cobrir o bastante e sem empate entre assuntos."""
    nota = _termos(texto)
    melhor: dict[int, tuple[float, Any]] = {}
    for r in store.q("SELECT r.termos, a.* FROM assunto_regras r JOIN assuntos a ON a.id = r.assunto_id") if nota else ():
        regra_termos = set(r["termos"].split())
        c = len(nota & regra_termos) / len(regra_termos)
        if c >= COBERTURA_REGRA and c > melhor.get(r["id"], (0.0,))[0]:
            melhor[r["id"]] = (c, r)
    topo = max((c for c, _ in melhor.values()), default=0.0)
    lideres = [r for c, r in melhor.values() if c == topo]
    return (lideres[0], topo) if len(lideres) == 1 else None


def _opcoes(store: Store, todos, texto: str) -> list[dict]:
    """As OPCOES mais prováveis: mais palavras em comum, depois o assunto mais usado."""
    nota = _termos(texto)
    uso = {r["assunto_id"]: r["n"] for r in store.q("SELECT assunto_id, COUNT(*) n FROM assunto_notas GROUP BY assunto_id")}
    ordem = sorted(todos, key=lambda a: (-len(nota & _termos(_rotulo(a))), -uso.get(a["id"], 0), a["id"]))
    return [{"id": a["id"], "nome": a["nome"], "descricao": a["descricao"]} for a in ordem[:OPCOES]]


def _gravar(store: Store, a, tipo: str, texto: str, frase: str, confianca: float, agora: float | None) -> dict:
    agora = agora or time.time()
    nid = store.x("INSERT INTO assunto_notas(assunto_id, tipo, texto, origem, confianca, created_at) VALUES(?,?,?,?,?,?)",
                  (a["id"], tipo, texto, frase, round(float(confianca), 3), agora))
    gid = graft.inserir("assunto_nota", nid, f"{tipo} em {a['nome']}: {texto}", f"{_data(agora)} · nota de origem: {frase}",
                        extras=[f"assunto:{a['id']}"])
    if gid:
        store.x("UPDATE assunto_notas SET graft_id=? WHERE id=?", (gid, nid))
    return {"id": nid, "assunto": a["nome"], "tipo": tipo, "texto": texto, "confianca": float(confianca)}


def _data(em: float) -> str:
    return datetime.fromtimestamp(em, TZ).strftime("%d/%m/%Y")


def _nota(r) -> dict[str, Any]:
    return {"id": r["id"], "assunto": r["nome"], "tipo": r["tipo"], "texto": r["texto"], "origem": r["origem"],
            "data": _data(r["created_at"]), "em": r["created_at"], "feita_em": r["feita_em"],
            "feita": _data(r["feita_em"]) if r["feita_em"] else None}


_SELECT = "SELECT n.*, a.nome FROM assunto_notas n JOIN assuntos a ON a.id = n.assunto_id"


def marcar_feita(store: Store, nota_id: int, feita: bool, agora: float | None = None) -> dict:
    """Marca (ou reabre) uma pendência: `feita_em` guarda quando; a daily deixa de listá-la e a ficha mostra a data."""
    preparar(store)
    r = store.one(_SELECT + " WHERE n.id=?", (nota_id,))
    if not r or r["tipo"] != "pendencia":
        raise ValueError("pendência não existe")
    store.x("UPDATE assunto_notas SET feita_em=? WHERE id=?", ((agora or time.time()) if feita else None, nota_id))
    return _nota(store.one(_SELECT + " WHERE n.id=?", (nota_id,)))


def ver(store: Store, nome: str) -> dict | None:
    preparar(store)
    a = store.one("SELECT * FROM assuntos WHERE nome=?", (nome,))
    if not a:
        return None
    notas = [_nota(r) for r in store.q(_SELECT + " WHERE n.assunto_id=? ORDER BY n.created_at, n.id", (a["id"],))]
    links = [x for x in a["links"].split("\n") if x] + [u for n in notas if n["tipo"] == "link" for u in URL.findall(n["texto"])]
    return {"nome": a["nome"], "descricao": a["descricao"], "links": links,
            "decisoes": [n for n in notas if n["tipo"] == "decisao"], "pendencias": [n for n in notas if n["tipo"] == "pendencia"],
            "notas": [n for n in notas if n["tipo"] in ("nota", "link")]}


def perguntar(store: Store, pergunta: str, k: int = 5) -> list[dict]:
    """As notas que respondem à pergunta: primeiro o que o Graft acha por significado, depois por palavra. Cada nota diz
    `por`: "palavra" se divide algum termo com a pergunta, "significado" se só o Graft a achou."""
    preparar(store)
    tipo = next((t for t, rx in FILTRO.items() if rx.search(pergunta or "")), None)
    rows = {r["id"]: r for r in store.q(_SELECT + (" WHERE n.tipo=?" if tipo else ""), (tipo,) if tipo else ())}
    ordem = [int(h["ref"]) for h in graft.recuperar(pergunta, k=12)
             if h.get("tipo") == "assunto_nota" and str(h.get("ref", "")).isdigit() and int(h["ref"]) in rows]
    q = set(termos(pergunta, 30)) - {"decidimos", "decidiu", "decisao", "decisoes", "pendencia", "pendencias", "link", "links"}
    pontos = {i: len(q & set(termos(r["texto"] + " " + r["nome"], 40))) for i, r in rows.items()}
    ordem += [i for _, _, i in sorted(((p, rows[i]["created_at"], i) for i, p in pontos.items() if p > 0), reverse=True)]
    return [{**_nota(rows[i]), "por": "palavra" if pontos[i] else "significado"} for i in dict.fromkeys(ordem)][:k]


def responder(notas: list[dict]) -> str:
    if not notas:
        return "Não achei nada anotado sobre isso."
    return "\n".join(f"{n['data']} · [{n['assunto']}] {n['texto']}{' (por significado)' if n.get('por') == 'significado' else ''}"
                     f" (nota #{n['id']}: \"{n['origem']}\")" for n in notas)

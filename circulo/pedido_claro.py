"""Portão de pedido (pergunta do conselho #323): antes da LLM, o pedido do Developer (título + detalhe do item) cita
critério de aceite, arquivo alvo (.py) e resultado esperado? Se falta algum, sai UMA pergunta de esclarecimento, a do
primeiro campo ausente. O veredito de cada item fica em `pedidos_claros`.

Item do loop (planejador/conselho) incompleto não chega à LLM do Developer (`esclarecer`): a pergunta volta ao gerador
(o item volta ao Estudo, que o reescreve) e fica em `esclarecimentos`. No máximo 1 rodada: incompleto de novo, o item é
descartado com motivo, sem ficar pendente. Erro, pedido humano e item sem a pergunta de origem seguem só medidos."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from .state import Store

CRITERIO, ARQUIVO, RESULTADO = "criterio", "arquivo", "resultado"
PADROES = {
    CRITERIO: re.compile(r"crit[ée]rios? de aceite|\baceite\s*:|\btestes?\b|\btests/", re.I),
    ARQUIVO: re.compile(r"[\w./-]+\.py\b"),
    RESULTADO: re.compile(r"\bsucesso\s*:|resultado esperado|\besperad[oa]s?\s*:|\balvo\s*:", re.I),
}
PERGUNTAS = {
    CRITERIO: "Qual teste ou critério de aceite mostra que o pedido está pronto?",
    ARQUIVO: "Qual arquivo ou módulo (caminho .py) deve mudar?",
    RESULTADO: "Qual resultado se espera depois da mudança (Sucesso: ...)?",
}
JANELA = 24 * 3600
ESQUEMA = """
CREATE TABLE IF NOT EXISTS pedidos_claros (
  item INTEGER PRIMARY KEY,
  completo INTEGER NOT NULL,
  faltando TEXT NOT NULL,
  pergunta TEXT,
  created_at REAL NOT NULL
)
"""
ESQUEMA_ESCLARECIMENTOS = """
CREATE TABLE IF NOT EXISTS esclarecimentos (
  item INTEGER PRIMARY KEY,
  campo TEXT NOT NULL,
  pergunta TEXT NOT NULL,
  para TEXT,
  created_at REAL NOT NULL
)
"""
ESCLARECER, DESCARTADO = "esclarecer", "descartado"
BLOQUEIA = ("loop",)        # só o item que o próprio loop gerou tem a quem devolver a pergunta sem esperar um humano


@dataclass(frozen=True)
class Veredito:
    faltando: tuple[str, ...]

    @property
    def completo(self) -> bool:
        return not self.faltando

    @property
    def pergunta(self) -> str | None:
        return PERGUNTAS[self.faltando[0]] if self.faltando else None


def avaliar(titulo: str | None, detalhe: str | None) -> Veredito:
    """Os campos ausentes no pedido, na ordem critério → arquivo → resultado. Pura."""
    texto = f"{titulo or ''}\n{detalhe or ''}"
    return Veredito(tuple(campo for campo, padrao in PADROES.items() if not padrao.search(texto)))


def registrar(store: Store, item: dict, agora: float | None = None) -> Veredito:
    """Guarda o veredito do item (um por item; o detalhe reescrito pelo Estudo atualiza, a hora da 1ª vez fica)."""
    v = avaliar(item.get("titulo"), item.get("detalhe"))
    store.x(ESQUEMA)
    store.x("INSERT INTO pedidos_claros(item, completo, faltando, pergunta, created_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(item) DO UPDATE SET completo=excluded.completo, faltando=excluded.faltando, "
            "pergunta=excluded.pergunta",
            (item["id"], int(v.completo), ",".join(v.faltando), v.pergunta, time.time() if agora is None else agora))
    from .criterio_aceite import congelar
    congelar(store, item)                 # o critério de aceite congela ao entrar no item: reescritas não o mudam
    return v


def esclarecer(store: Store, item: dict, v: Veredito, agora: float | None = None) -> tuple[str, str] | None:
    """None = o item segue para o Developer. Senão (ESCLARECER | DESCARTADO, texto), sem chamar a LLM: a 1ª vez a
    pergunta do 1º campo faltante volta ao gerador (o item volta ao Estudo com ela no detalhe); a 2ª, descarta."""
    if v.completo or item.get("origem") not in BLOQUEIA:
        return None
    origem = store.one("SELECT persona FROM perguntas WHERE id=?", (item.get("pergunta_id"),))
    if not origem:                  # item legado, sem a pergunta que o gerou: não há a quem devolver, segue só medido
        return None
    agora = time.time() if agora is None else agora
    store.x(ESQUEMA_ESCLARECIMENTOS)
    feita = store.one("SELECT pergunta FROM esclarecimentos WHERE item=?", (item["id"],))
    if feita:
        texto = (f"descartado (pedido incompleto depois de 1 rodada de esclarecimento): ainda falta {', '.join(v.faltando)}; "
                 f"a pergunta “{feita['pergunta']}” não foi respondida na reescrita")
        store.x("UPDATE roadmap SET status=?, evidencia=?, updated_at=? WHERE id=?", (DESCARTADO, texto[:300], agora, item["id"]))
        return DESCARTADO, texto
    para = origem["persona"]
    store.x("INSERT INTO esclarecimentos(item, campo, pergunta, para, created_at) VALUES(?,?,?,?,?)",
            (item["id"], v.faltando[0], v.pergunta, para, agora))
    texto = f"esclarecimento ao gerador ({para}): {v.pergunta}"
    store.x("UPDATE roadmap SET detalhe=?, estudo=NULL, evidencia=?, updated_at=? WHERE id=?",
            ((f"{item.get('detalhe') or ''}\n\nPortão de pedido, responda reescrevendo o item: {v.pergunta}")[:4000],
             texto[:300], agora, item["id"]))
    return ESCLARECER, texto


def registrar_sem_veredito(store: Store) -> int:
    """Pergunta #331: avalia pelo texto o item com PR ainda sem veredito (aberto antes do portão, ou sem passar pelo
    pick), com a hora do próprio item, para a fração das 24 h não contar o passado como novo. O item sem PR recebe o
    seu no pick, já com o detalhe reescrito pelo Estudo."""
    store.x(ESQUEMA)
    itens = store.q("SELECT * FROM roadmap r WHERE EXISTS (SELECT 1 FROM prs WHERE prs.item_id=r.id) "
                    "AND NOT EXISTS (SELECT 1 FROM pedidos_claros p WHERE p.item=r.id)")
    for it in itens:
        registrar(store, dict(it), agora=it["created_at"])
    return len(itens)


def itens_com_veredito(store: Store) -> list[dict]:
    """Itens do roadmap com o veredito do portão ('completo' | 'incompleto' | None se nunca avaliado); o completo que
    passou pela rodada de esclarecimento é 'esclarecido' (o originalmente incompleto que chegou ao Developer)."""
    store.x(ESQUEMA)
    store.x(ESQUEMA_ESCLARECIMENTOS)
    return store.q("SELECT r.titulo, r.status, CASE WHEN p.completo=1 AND e.item IS NOT NULL THEN 'esclarecido' "
                   "WHEN p.completo=1 THEN 'completo' WHEN p.completo=0 THEN 'incompleto' END veredito "
                   "FROM roadmap r LEFT JOIN pedidos_claros p ON p.item=r.id LEFT JOIN esclarecimentos e ON e.item=r.id")


def fracao_incompletos(store: Store, agora: float | None = None) -> float | None:
    """Fração dos pedidos avaliados nas últimas 24 h sem algum dos 3 campos; None sem pedido avaliado."""
    store.x(ESQUEMA)
    r = store.one("SELECT COUNT(*) n, SUM(1 - completo) incompletos FROM pedidos_claros WHERE created_at>=?",
                  ((time.time() if agora is None else agora) - JANELA,))
    return r["incompletos"] / r["n"] if r["n"] else None

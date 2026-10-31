"""Disjuntor de LLM: a conta sem crédito ("credit balance is too low") não volta sozinha, e cada chamada repetida só
gasta tentativa e enche o log de falhas do Developer.

`transicao(estado, evento, agora)` é pura e devolve (novo_estado, pode_chamar, proxima_tentativa, avisar):
- fechado: tudo passa; só a falha 'externa' (crédito, regra do PR #91) abre o circuito;
- aberto: nenhuma chamada até `proxima`; o backoff é exponencial (BASE_S, 2×, ..., TETO_S) com jitter injetado;
- meio-aberto: vencida a pausa, uma única chamada de teste; sucesso fecha, falha externa reabre com backoff maior.
O aviso sai uma vez por abertura (fechado → aberto); a reabertura no meio-aberto é a mesma falta de crédito.

`LLMProtegida` envolve a LLM do loop: consulta o disjuntor antes de cada chamada e grava o estado no kv do banco do
loop (sobrevive a reinício). Na pausa, levanta CircuitoAberto sem chamar a LLM.
"""
from __future__ import annotations

import functools
import random
import time
from typing import Any, Callable

from .llm import EXTERNA, FalhaExterna, conferir_saida

FECHADO, ABERTO, MEIO_ABERTO = "fechado", "aberto", "meio-aberto"
KV = "disjuntor_llm"
BASE_S = 300            # primeira pausa
TETO_S = 3600           # nenhuma pausa passa disso (pergunta #576)
TESTE_S = 3600          # a chamada de teste do meio-aberto sem desfecho depois disso libera outra
JITTER = 0.25          # a pausa vai de 75% a 100% do degrau: o próximo degrau (2×) é sempre maior


class CircuitoAberto(FalhaExterna):
    """A LLM está em pausa pelo disjuntor (conta sem crédito); nenhuma chamada saiu."""


def classificar(texto: str) -> str:
    """'externa' para a conta sem crédito (só ela abre o circuito); 'falha' para qualquer outro erro."""
    return "externa" if EXTERNA.search(texto or "") else "falha"


def pausa(aberturas: int, jitter: float) -> float:
    degrau = min(TETO_S, BASE_S * 2 ** max(0, aberturas - 1))
    return degrau * (1 - JITTER + JITTER * min(1.0, max(0.0, jitter)))


def transicao(estado: dict | None, evento: str, agora: float, jitter: float = 0.0) -> tuple[dict, bool, float | None, bool]:
    """evento: 'consulta' (posso chamar?), 'sucesso', 'externa' ou 'falha'. jitter em [0, 1], injetado por quem chama."""
    e = {"estado": FECHADO, "aberturas": 0, "proxima": None, "em_teste": None, **(estado or {})}
    avisar = False
    if evento == "sucesso":
        e = {"estado": FECHADO, "aberturas": 0, "proxima": None, "em_teste": None}
    elif evento == "externa" and e["estado"] != ABERTO:
        avisar = e["estado"] == FECHADO
        e["aberturas"] += 1
        e.update(estado=ABERTO, em_teste=None, proxima=agora + pausa(e["aberturas"], jitter))
    elif evento == "falha" and e["estado"] == MEIO_ABERTO:
        e["em_teste"] = None                        # o teste não disse nada sobre o crédito: libera outro
    elif evento == "consulta":
        if e["estado"] == ABERTO and agora >= e["proxima"]:
            e.update(estado=MEIO_ABERTO, em_teste=None)
        # o teste que nunca deu notícia (processo caiu no meio) expira: o meio-aberto não fica preso
        if e["estado"] == MEIO_ABERTO and (e["em_teste"] is None or agora - e["em_teste"] >= TESTE_S):
            e["em_teste"] = agora
            return e, True, e["proxima"], False
    pode = e["estado"] == FECHADO
    return e, pode, None if pode else e["proxima"], avisar


def passo(store: Any, evento: str, agora: float | None = None) -> bool:
    """Um evento no disjuntor gravado no kv do loop (`store`: get/set e x para o alerta); devolve se pode chamar."""
    agora = time.time() if agora is None else agora
    antes = store.get(KV)
    estado, pode, proxima, avisar = transicao(antes, evento, agora, random.Random(int(agora)).random())
    if estado != antes:
        store.set(KV, estado)
    if avisar:
        hora = time.strftime("%H:%M", time.localtime(proxima))
        store.x("INSERT INTO alerts(kind,message,created_at,delivered) VALUES('saude',?,?,0)",
                (f"LLM em pausa: a conta está sem crédito (credit balance is too low). Nenhuma chamada até {hora}; "
                 "depois, uma chamada de teste por vez.", agora))
    return pode


class LLMProtegida:
    """A LLM do loop atrás do disjuntor."""

    def __init__(self, llm: Any, store: Any, agora: Callable[[], float] = time.time):
        self._llm, self._store, self._agora = llm, store, agora

    def __getattr__(self, nome):
        """generate/complete só existem se a LLM de dentro os tem: quem pergunta `hasattr(llm, "generate")` não erra."""
        if nome.startswith("_"):
            raise AttributeError(nome)
        atributo = getattr(self._llm, nome)
        return functools.partial(self._chamar, nome) if nome in ("generate", "complete") else atributo

    def _passo(self, evento: str) -> bool:
        return passo(self._store, evento, self._agora())

    def _chamar(self, metodo: str, *a, **kw):
        if not self._passo("consulta"):
            raise CircuitoAberto(f"LLM em pausa pelo disjuntor até {self._store.get(KV)['proxima']:.0f} (sem crédito)")
        try:
            r = conferir_saida(getattr(self._llm, metodo)(*a, **kw))
        except Exception as exc:
            self._passo(classificar(str(exc)))
            raise
        self._passo("sucesso")
        return r


AGENTE_RESPONDEU = frozenset({"sem_mudanca", "fora_do_alcance", "testes_falharam", "revisor_rejeitou", "proposto"})


def evento_do_developer(status: str, detalhe: str) -> str:
    """O desfecho de uma rodada do Developer como evento: o agente respondeu (sucesso), caiu sem crédito (externa) ou
    nada disse sobre o crédito (falha, que só libera o teste do meio-aberto)."""
    if status == "agente_falhou":
        return classificar(detalhe)
    return "sucesso" if status in AGENTE_RESPONDEU else "falha"


def protegida(store: Any, llm: Any) -> LLMProtegida | None:
    """A LLM do loop atrás do disjuntor; sem LLM, continua sem LLM."""
    if llm is None:
        from .llm import build_llm
        llm = build_llm()
    return None if llm is None else LLMProtegida(llm, store)

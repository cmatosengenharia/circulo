"""Parada verificável (kill switch): o botão do painel, a confirmação do loop e o teste semanal.

Um kill switch que nunca foi testado não é um kill switch. Por isso a parada tem três pontas, todas medidas:
- `pedir`: o humano (botão Parar do painel) ou o teste grava a intenção na trilha write-ahead e liga a pausa;
- `confirmar`: o loop, no primeiro giro pausado, registra que parou (giro e horário);
- `estado`: o painel confere de ponta a ponta: o loop confirmou e nenhuma ação do loop começou depois disso;
- `testar`: uma vez por semana o próprio loop aperta o botão, gira, confere e retoma; o resultado é o neurônio
  `loop:parada` (falha vira lição de estrutura).
"""
from __future__ import annotations

import time

from . import intencoes
from .state import Store

SEMANA = 7 * 86400


def _controle(store: Store, pausado: bool) -> dict:
    c = store.get("controle", {}) or {}
    c = {"pausado": bool(pausado), "modo_seguro": bool(c.get("modo_seguro"))}
    store.set("controle", c)
    return c


def pedir(store: Store, ator: str = "humano", motivo: str = "botão Parar do painel") -> dict:
    seq = intencoes.registrar(store, "parar", motivo, {"controle_antes": store.get("controle") or {}}, ator=ator,
                              regra="pedido do humano: não passa por regra nem pelo Jev" if ator == "humano" else "teste semanal da parada")
    _controle(store, True)
    p = {"pedida_em": time.time(), "seq": seq, "ator": ator, "confirmada_em": None, "tick": None}
    store.set("parada", p)
    intencoes.concluir(store, seq, True, "pausa ligada; o loop confirma no próximo giro")
    return p


def retomar(store: Store, ator: str = "humano", motivo: str = "botão Retomar do painel") -> dict:
    seq = intencoes.registrar(store, "retomar", motivo, {}, ator=ator, regra="pedido do humano" if ator == "humano" else "fim do teste")
    c = _controle(store, False)
    p = store.get("parada") or {}
    if p:
        store.set("parada", {**p, "retomada_em": time.time()})
    intencoes.concluir(store, seq, True)
    return c


def confirmar(store: Store) -> None:
    """Chamado pelo loop no giro pausado: a parada só conta quando o próprio loop diz que parou."""
    p = store.get("parada") or {}
    if p and not p.get("confirmada_em") and not p.get("retomada_em"):
        store.set("parada", {**p, "confirmada_em": time.time(), "tick": store.tick})


def estado(store: Store) -> dict:
    p = store.get("parada") or {}
    pausado = bool((store.get("controle") or {}).get("pausado"))
    if not p or p.get("retomada_em") or not pausado:
        return {"estado": "rodando" if not pausado else "pausado", "pausado": pausado, "verificada": False}
    if not p.get("confirmada_em"):
        return {"estado": "aguardando", "pausado": True, "verificada": False, "pedida_em": p["pedida_em"]}
    # ponta a ponta: depois da confirmação, nenhuma intenção do loop pode ter sido gravada (e sem intenção, nada roda)
    depois = store.one("SELECT COUNT(*) n FROM intencoes WHERE tipo='intencao' AND ator='loop' AND em>?",
                       (p["confirmada_em"],))["n"]
    return {"estado": "parado" if not depois else "vazou", "pausado": True, "verificada": not depois, "acoes_depois": depois,
            "pedida_em": p["pedida_em"], "confirmada_em": p["confirmada_em"], "tick": p.get("tick")}


def teste_vencido(store: Store, now: float | None = None) -> bool:
    t = store.get("parada_teste") or {}
    return (now or time.time()) - float(t.get("em", 0)) >= SEMANA


def testar(circle) -> bool | None:
    """Aperta o botão de verdade, gira o loop, confere pelo mesmo caminho do painel e retoma."""
    s = circle.store
    if circle.controls()["pausado"]:
        return None                          # você já pausou: o teste não mexe na sua parada
    pedir(s, ator="teste", motivo="teste semanal da parada")
    try:
        r = circle.tick()
        e = estado(s)
        ok = bool(r.paused and e["verificada"])
        motivo = "" if ok else f"o loop não parou como esperado: giro pausado={r.paused}, estado da parada={e['estado']}"
    finally:
        if (s.get("parada") or {}).get("ator") == "teste":
            retomar(s, ator="teste", motivo="fim do teste semanal da parada")
    s.set("parada_teste", {"em": time.time(), "ok": ok})
    from .licoes import registrar as monitorar
    monitorar(circle.ctx, "loop:parada", ok, sujeito="teste semanal", motivo=motivo,
              assinatura=None if ok else "loop:parada_falhou", classe="estrutural")
    return ok

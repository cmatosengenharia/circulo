"""Laboratório do Jev: o loop testa, com evidência, formas melhores de perguntar ao Jev e adota sozinho a que vence.

O que a documentação da TypeSafe diz e o loop ainda não aproveitava (docs.typesafe.ai):
- o Jev responde melhor em **inglês** (outras línguas são tratadas com menos precisão);
- instruções devem dizer a **condição exata** e referenciar campos do estado com crases (`campo`);
- várias perguntas na **mesma chamada** saem quase pelo preço de uma (rodam em paralelo sobre o mesmo estado);
- a confiança é calibrada (RLCD): dá para medir e comparar formulações;
- a resposta traz o **modelo versionado** que respondeu; limiares calibrados pedem versão fixa e registro dela.

Nos dados do loop, as perguntas mais frequentes estavam com o Jev em dúvida (worth_spending: confiança média 0,22,
44% abaixo do limiar; should_evolve: 0,14), e a regra decidia no lugar. Em vez de trocar no escuro, cada pergunta
com variante vai **em dobro na mesma chamada** (a atual e a variante em inglês, com a condição explícita). O loop
guarda as duas confianças e a concordância; com evidência suficiente (MIN_N pares e ganho ≥ GANHO_MIN), a variante
passa a ser a pergunta oficial, sozinha e com alerta. Se depois o ganho sumir, volta atrás. A original continua
sendo medida em paralelo, então a comparação nunca para.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Mapping

MIN_N = 40
GANHO_MIN = 0.15
GANHO_MANTER = 0.05
JANELA = 200
PREFIXO = "lab__"

TAREFA_EN = {"analisar_padroes": "look for spending patterns", "revisar_baixa_confianca": "review low-confidence decisions",
             "rodar_regressao": "run the regression over history", "resumo": "write the summary", "propor_feature": "propose an improvement",
             "revisar_prs": "review open pull requests at the gate", "evoluir_harness": "A/B test prompts",
             "conectar_missoes": "link missions that complement each other"}


def _worth(q, state: Mapping[str, Any]):
    from .decision import Question
    return Question("noul", "The autonomous loop wants to run `action` now, costing about `est_tokens` tokens. `value_signal` is the "
                            "expected value of this task (0 to 1) and `budget_left_ratio` is the share of today's token budget still "
                            "available. Is running it now worth it?",
                    {"true": "the task has clear value (`value_signal` high) and the remaining budget comfortably covers its cost; or a "
                             "the task unblocks the pipeline (`desbloqueia_fila`: a validated question `pergunta_validada` or an item "
                             "waiting for study `item_esperando_estudo`) while the developer queue is empty (`fila_do_developer` = 0) "
                             "and the budget covers the cost",
                     "false": "the expected value is low, or the remaining budget is tight for what the task costs"})


def _idle(q, state: Mapping[str, Any]):
    from .decision import Question
    return Question("choice", "Which maintenance task gives the loop the most value right now? Prefer the task neglected for the "
                              "most turns in `staleness`, unless another one clearly matters more.",
                    {k: f"{TAREFA_EN.get(k, k.replace('_', ' '))} (neglected for {state.get('staleness', {}).get(k, '?')} turns)" for k in q.options()})


def _evolve(q, state: Mapping[str, Any]):
    from .decision import Question
    return Question("noul", "Does the evidence justify applying this `evolution_type` change now?",
                    {"true": "the same problem was observed several times (`occurrences`) and consistently (`consistency` close to 1)",
                     "false": "few occurrences, inconsistent evidence, or the change is larger than the evidence supports"})


def _review(q, state):
    from .decision import Question
    return Question("choice", "Can this pull request be merged automatically?",
                    {"approve": "`tests_ok` is true, `lines_changed` is small and `touches_money_code` is false: safe to merge without a human",
                     "changes": "tests pass but the change is large or touches money code: needs adjustments or a human look first",
                     "reject": "`tests_ok` is false: discard"})


def _advance(q, state):
    from .decision import Question
    return Question("noul", "Does the evidence show the new version is better and safe to advance?",
                    {"true": "`ganho` and `ganho_oculto` are ≥ 0, `verificacao_ok` and `catraca_ok` are true, and no criterion got worse",
                     "false": "some gain is negative, `criterios_que_pioraram` > 0, a check failed, or `integracao_ok` is false"})


def _contraprova(q, state):
    from .decision import Question
    return Question("noul", "Did the new version make something important worse than the previous one?",
                    {"true": "`ganho_oculto` is negative, `criterios_que_pioraram` > 0 or `integracao_ok` is false",
                     "false": "nothing got worse: all gains ≥ 0 and the checks passed"})


def _pick(q, state):
    from .decision import Question
    return Question("choice", "Which model tier is enough for this task?",
                    {"pequena": "short task with a fixed output format and no multi-step reasoning: classify, summarize, rewrite, extract",
                     "grande": "long or open-ended task that requires planning, comparing alternatives, writing code or multi-step reasoning"})


def _remember(q, state):
    from .decision import Question
    return Question("noul", "Is this lesson worth keeping in the loop's memory?",
                    {"true": "`texto` is a specific, reusable rule that would change a future decision (or `ganho` was relevant)",
                     "false": "it is vague, obvious, only applies to this one case, or repeats what is already known"})


VARIANTES: dict[str, Callable] = {"worth_spending": _worth, "idle_task": _idle, "should_evolve": _evolve, "review_code": _review,
                                  "should_advance": _advance, "contraprova": _contraprova, "pick_model": _pick, "remember": _remember}


def ativas(store) -> dict:
    return store.get("jev_lab_ativas") or {}


def preparar(store, jev, state: Mapping[str, Any], questions: Mapping[str, Any]) -> tuple[dict, dict]:
    """Perguntas a enviar (com as variantes em dobro) e o mapa {pergunta: variante_é_a_oficial}."""
    if getattr(jev, "source", "") != "jev":
        return dict(questions), {}
    at = ativas(store)
    enviar, mapa = dict(questions), {}
    for qid, q in questions.items():
        f = VARIANTES.get(qid)
        if f is None:
            continue
        try:
            v = f(q, state)
        except Exception:  # o laboratório nunca atrapalha a decisão
            continue
        if at.get(qid):
            enviar[qid], enviar[PREFIXO + qid] = v, q
        else:
            enviar[PREFIXO + qid] = v
        mapa[qid] = bool(at.get(qid))
    return enviar, mapa


def colher(store, out: dict, mapa: dict, modelo: str | None = None) -> dict:
    """Separa as respostas do laboratório, registra o par (atual × variante) e devolve só as perguntas pedidas."""
    for qid, variante_oficial in mapa.items():
        a, b = out.get(qid), out.pop(PREFIXO + qid, None)
        if a is None or b is None:
            continue
        pt, en = (b, a) if variante_oficial else (a, b)
        try:
            store.x("INSERT INTO jev_lab(pergunta,valor_pt,conf_pt,valor_en,conf_en,modelo,created_at) VALUES(?,?,?,?,?,?,?)",
                    (qid, str(pt.value), float(pt.confidence), str(en.value), float(en.confidence), modelo, time.time()))
        except Exception:
            pass
    for k in [k for k in out if k.startswith(PREFIXO)]:
        out.pop(k)
    return out


def _concorda(pergunta: str, a: str, b: str) -> bool:
    try:
        return (float(a) >= 0.5) == (float(b) >= 0.5)
    except ValueError:
        return a == b


def placar(store, pergunta: str, desde: float = 0) -> dict:
    rows = store.q("SELECT valor_pt, conf_pt, valor_en, conf_en FROM jev_lab WHERE pergunta=? AND created_at>=? ORDER BY id DESC LIMIT ?",
                   (pergunta, desde, JANELA))
    n = len(rows)
    if not n:
        return {"n": 0}
    pt = sum(r["conf_pt"] for r in rows) / n
    en = sum(r["conf_en"] for r in rows) / n
    return {"n": n, "conf_pt": round(pt, 3), "conf_en": round(en, 3), "ganho": round(en - pt, 3),
            "concordancia": round(sum(_concorda(pergunta, r["valor_pt"], r["valor_en"]) for r in rows) / n, 3)}


def avaliar(store, reply: Callable | None = None) -> list[str]:
    """Adota a variante que provou ganho; volta atrás se o ganho sumir. Roda de tempos em tempos no giro."""
    at, mudou, log = dict(ativas(store)), False, []
    for qid in VARIANTES:
        desde = float((at.get(qid) or {}).get("em", 0)) if isinstance(at.get(qid), dict) else 0
        p = placar(store, qid, desde)
        if p["n"] < MIN_N:
            continue
        if not at.get(qid) and p["ganho"] >= GANHO_MIN:
            at[qid] = {"em": time.time(), "antes": p}
            mudou = True
            log.append(f"Jev: a pergunta “{qid}” passou a ser feita em inglês, com a condição explícita. Evidência em {p['n']} "
                       f"decisões: confiança média {p['conf_pt']:.2f} → {p['conf_en']:.2f} (concordância {p['concordancia']:.0%}).")
        elif at.get(qid) and p["ganho"] < GANHO_MANTER:
            at.pop(qid)
            mudou = True
            log.append(f"Jev: a variante em inglês de “{qid}” deixou de ganhar ({p['conf_pt']:.2f} × {p['conf_en']:.2f} em {p['n']} "
                       "decisões); voltei para a pergunta anterior.")
    if mudou:
        store.set("jev_lab_ativas", at)
        for m in log:
            (reply or (lambda *a: None))(m, "evolucao")
    return log


def resumo(store, now: float | None = None) -> dict:
    """Tudo o que a tela mostra do Jev: versão, como cada pergunta está indo e o laboratório."""
    now = now or time.time()
    try:
        perguntas = [dict(r) for r in store.q(
            "SELECT pergunta, COUNT(*) n, SUM(source='jev') jev, SUM(source='local') regra, SUM(source='llm') llm, "
            "ROUND(AVG(CASE WHEN source='jev' THEN confidence END), 3) conf_jev FROM (SELECT CASE WHEN question LIKE 'indaga_%' "
            "THEN substr(question, 1, length(question) - length(substr(question, instr(substr(question, 8), '_') + 7))) ELSE question END pergunta, "
            "source, confidence FROM decisions WHERE created_at>=?) GROUP BY pergunta ORDER BY n DESC LIMIT 12", (now - 86400,))]
    except Exception:
        perguntas = []
    at = ativas(store)
    lab = []
    for qid in VARIANTES:
        try:
            p = placar(store, qid)
        except Exception:
            p = {"n": 0}
        lab.append({"pergunta": qid, "ativa": bool(at.get(qid)), **p})
    try:
        from .jev_cobertura import cobertura
        cob = cobertura()
    except Exception:
        cob = None
    tot = sum(x["n"] for x in perguntas) or 0
    return {"modelo": store.get("jev_modelo"), "modelo_pedido": store.get("jev_modelo_pedido"), "ultimo_erro": store.get("jev_last_error"),
            "decisoes_24h": tot, "sem_llm_24h": round(sum((x["jev"] or 0) + (x["regra"] or 0) for x in perguntas) / tot, 3) if tot else None,
            "perguntas": perguntas, "laboratorio": lab, "min_n": MIN_N, "ganho_min": GANHO_MIN, "cobertura": cob}

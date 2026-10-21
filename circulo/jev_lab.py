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

import json
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
    return Question("noul", "The autonomous loop wants to run `action` now, costing about `est_tokens` tokens (`custo_pct_dia` percent "
                            "of what it spent today). Is running it now worth it?",
                    {"true": "`value_signal` ≥ 0.7; or `value_signal` ≥ 0.5 and `custo_pct_dia` < 5; or `desbloqueia_fila` is true and "
                             "`fila_do_developer` = 0 — and in every case `orcamento` is not 'esgotado' and `rodou_hoje_sem_render` < 3",
                     "false": "`value_signal` < 0.4; or `orcamento` = 'esgotado'; or `rodou_hoje_sem_render` ≥ 3 (the same action already ran "
                              "three times today without delivering anything); or `custo_pct_dia` ≥ 20 without `desbloqueia_fila`"})


def _idle(q, state: Mapping[str, Any]):
    from .decision import Question
    return Question("choice", "Which maintenance task gives the loop the most value right now? Prefer the task neglected for the "
                              "most turns in `staleness`, unless another one clearly matters more.",
                    {k: f"{TAREFA_EN.get(k, k.replace('_', ' '))} (neglected for {state.get('staleness', {}).get(k, '?')} turns)" for k in q.options()})


def _evolve(q, state: Mapping[str, Any]):
    from .decision import Question
    return Question("noul", "Does the evidence justify applying this `evolution_type` change now?",
                    {"true": "`occurrences` ≥ 3 and `consistency` ≥ 0.8 and `revertida_antes` = 0; or `occurrences` ≥ 6 with `consistency` ≥ 0.6",
                     "false": "`occurrences` < 3; or `consistency` < 0.6; or `revertida_antes` ≥ 1 (the same change was rolled back before); "
                              "or `aplicada_hoje` ≥ 2"})


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


# ---------------------------------------------------------------- cache: a mesma pergunta com o mesmo estado, na mesma janela
# O SRE perguntava `vigia_trava` 353×/dia e o giro `idle_task` 357×/dia com estado idêntico a cada 45 s: a resposta não
# muda, só dilui e custa. Dentro de CACHE_TTL, estado igual (byte a byte) devolve a decisão anterior, marcada `_cache`.
CACHEAVEIS = ("vigia_trava", "vigia_acao", "idle_task", "medico_")
CACHE_TTL = 600
_cache: dict[str, tuple[float, Any]] = {}
CACHE_CHAVE = "__cache__"
PASSE = ("worth_spending", "should_evolve", "dado_na_evidencia", "indaga_pert")   # as 4 reescritas em 1.47.0; o painel mede antes × depois
PASSE_VERSAO = "1.47.0"


def marcar_passe(store, versao: str) -> None:
    """Registra quando o passe entrou (uma vez por versão) para o painel comparar a confiança antes × depois."""
    p = store.get("jev_passe") or {}
    if p.get("versao") != versao:
        store.set("jev_passe", {"versao": versao, "em": time.time()})


def _chave(qid: str, q, state: Mapping[str, Any], jev=None) -> str:
    import hashlib
    raw = json.dumps([qid, q.kind, q.instructions, state, id(jev), getattr(jev, "model", None)], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode()).hexdigest()


def cacheavel(qid: str) -> bool:
    return qid.startswith(CACHEAVEIS)


def lembrar(qid: str, q, state: Mapping[str, Any], jev=None, agora: float | None = None):
    agora = agora or time.time()
    v = _cache.get(_chave(qid, q, state, jev))
    return v[1] if v and agora - v[0] < CACHE_TTL else None


def guardar(qid: str, q, state: Mapping[str, Any], decisao, jev=None, agora: float | None = None) -> None:
    if len(_cache) > 2000:
        _cache.clear()
    _cache[_chave(qid, q, state, jev)] = (agora or time.time(), decisao)


CATALOGO = "jev_catalogo"
CATALOGO_MAX = 400


def catalogar(store, questions: Mapping[str, Any]) -> None:
    """A pergunta inteira como foi ao Jev (instrução, critérios, tipo), por nome: o painel mostra o texto completo."""
    cat = dict(store.get(CATALOGO) or {})
    mudou = False
    for qid, q in questions.items():
        crit = q.criteria if isinstance(q.criteria, dict) else (list(q.criteria) if q.criteria else None)
        ent = {"tipo": q.kind, "texto": str(q.instructions)[:1200], "criterios": crit, "em": time.time()}
        if cat.get(qid, {}).get("texto") != ent["texto"] or cat.get(qid, {}).get("criterios") != crit:
            cat[qid] = ent
            mudou = True
    if mudou:
        if len(cat) > CATALOGO_MAX:
            cat = dict(sorted(cat.items(), key=lambda kv: -float(kv[1].get("em", 0)))[:CATALOGO_MAX])
        store.set(CATALOGO, cat)


def pergunta_completa(store, qid: str) -> dict | None:
    cat = store.get(CATALOGO) or {}
    return cat.get(qid)


def preparar(store, jev, state: Mapping[str, Any], questions: Mapping[str, Any]) -> tuple[dict, dict]:
    """Perguntas a enviar (com as variantes em dobro) e o mapa {pergunta: variante_é_a_oficial}; respostas em cache
    saem do envio e voltam em `colher`."""
    catalogar(store, questions)
    if getattr(jev, "source", "") != "jev":
        return dict(questions), {}
    at = ativas(store)
    enviar, mapa = dict(questions), {}
    lembradas = {}
    for qid, q in questions.items():
        if cacheavel(qid) and (d := lembrar(qid, q, state, jev)) is not None:
            lembradas[qid] = d
            enviar.pop(qid)
    if any(cacheavel(q) for q in questions):
        mapa[CACHE_CHAVE] = (lembradas, state, dict(questions), jev)
    for qid, q in questions.items():
        if qid in lembradas:
            continue
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
    from .decision import Decision
    lembradas, estado, perguntas, jev = mapa.get(CACHE_CHAVE, ({}, {}, {}, None))
    for qid, d in lembradas.items():
        out[qid] = Decision(d.name, d.kind, d.value, d.confidence, d.source, {**(d.probabilities or {}), "cache": True})
    for qid, q in perguntas.items():
        if qid not in lembradas and qid in out and cacheavel(qid) and getattr(out[qid], "source", "") == "jev":
            guardar(qid, q, estado, out[qid], jev)
    for qid, variante_oficial in mapa.items():
        if qid == CACHE_CHAVE:
            continue
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
    marcar_passe(store, PASSE_VERSAO)
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
    passe = store.get("jev_passe") or {}
    if passe.get("em"):
        em = float(passe["em"])
        antes_depois = []
        for qid in PASSE:
            like = qid + "%"
            a = store.one("SELECT COUNT(*) n, ROUND(AVG(confidence),3) c FROM decisions WHERE question LIKE ? AND source='jev' AND created_at>=? AND created_at<?", (like, em - 86400, em))
            d = store.one("SELECT COUNT(*) n, ROUND(AVG(confidence),3) c FROM decisions WHERE question LIKE ? AND source='jev' AND created_at>=?", (like, em))
            antes_depois.append({"pergunta": qid, "antes_n": a["n"], "antes_conf": a["c"], "depois_n": d["n"], "depois_conf": d["c"]})
        passe = {**passe, "perguntas": antes_depois}
    cache_24h = store.one("SELECT COUNT(*) n FROM decisions WHERE created_at>=? AND probabilidades LIKE '%\"cache\": true%'", (now - 86400,))["n"] \
        if store.one("SELECT 1 FROM pragma_table_info('decisions') WHERE name='probabilidades'") else 0
    return {"passe": passe, "cache_24h": int(cache_24h or 0), "modelo": store.get("jev_modelo"), "modelo_pedido": store.get("jev_modelo_pedido"), "ultimo_erro": store.get("jev_last_error"),
            "decisoes_24h": tot, "sem_llm_24h": round(sum((x["jev"] or 0) + (x["regra"] or 0) for x in perguntas) / tot, 3) if tot else None,
            "perguntas": perguntas, "laboratorio": lab, "min_n": MIN_N, "ganho_min": GANHO_MIN, "cobertura": cob}


# ---------------------------------------------------------------- estado enxuto, medido, para as perguntas em que o Jev mais duvidava
# 20/10: `worth_spending` 0,49 de confiança em 604 perguntas/dia (o estado era um `value_signal` solto, sem âncora, e
# `budget_left_ratio` sempre 1,0 no modo sem limite); `should_evolve` 0,39. O Jev classifica bem quando o estado tem
# as poucas features que decidem e o critério tem número.

def _tokens_hoje(store) -> int:
    from datetime import datetime
    from .budget import TZ
    dia = datetime.now(TZ).strftime("%Y-%m-%d")
    r = store.one("SELECT tokens FROM budget WHERE day=?", (dia,))
    return int(r["tokens"] or 0) if r else 0


# que papel de LLM cada ação do porteiro realmente aciona: é isso que conta como "rendeu" hoje (antes, um LIKE pelo
# prefixo da ação — "project", "idle", "planejar" — nunca casava com papel nenhum e o Jev recusava o 4º gasto do dia)
PAPEIS_DA_ACAO = {"project_cycle": ("builder", "improver", "researcher", "rubric", "reflector"), "estudo_pedido": ("estudo",),
                  "planejar_roteiro": ("planejador",), "developer_feature": ("developer",), "llm_fallback": ("fallback",),
                  "harness_variant": ("builder", "improver"), "idle_evolution": None, "apply_proposal": None, "self_fix": None}


def estado_worth(store, budget, action: str, est: int, context: Mapping[str, Any]) -> dict:
    """O que decide se vale gastar: valor, custo relativo ao dia, se destrava a fila, e se a mesma ação já rodou hoje sem render."""
    agora = time.time()
    hoje = agora - (agora % 86400)
    ilimitado = bool(getattr(budget, "ilimitado", False))
    esgotado = not ilimitado and not budget.can_spend(max(est, 1))
    aprov = store.q("SELECT value, created_at FROM decisions WHERE question='worth_spending' AND created_at>=? AND estado LIKE ? ORDER BY id DESC LIMIT 12",
                    (hoje, f'%"action": "{action}"%'))
    rodou = sum(1 for r in aprov if float(r["value"] or 0) >= 0.5)
    papeis = PAPEIS_DA_ACAO.get(action)
    if action and papeis is None:
        rendeu = rodou                   # ação sem chamada de LLM própria (idle, apply, self_fix): não há o que "render"
    elif action:
        cond = " OR ".join("papel=? OR papel LIKE ?" for _ in papeis)          # papel exato ou com sufixo ("fallback:x")
        args = [x for p_ in papeis for x in (p_, p_ + ":%")]
        rendeu = int(store.one(f"SELECT COUNT(*) n FROM llm_calls WHERE created_at>=? AND ok=1 AND COALESCE(aceita,1)=1 AND ({cond})",
                               (hoje, *args))["n"])
    else:
        rendeu = 0
    tokens_dia = _tokens_hoje(store)
    custo_pct = round(100.0 * est / tokens_dia, 1) if tokens_dia else (100.0 if est > 20_000 else 0.0)
    desbloqueia = bool(context.get("pergunta_validada") or context.get("item_esperando_estudo") or context.get("desbloqueia_fila"))
    extras = {k: v for k, v in context.items() if k in ("task", "item", "origem", "pergunta_validada", "item_esperando_estudo", "modo_estudo",
                                                          "fila_do_developer", "esquecida_ha_giros", "eixo", "pertinencia", "question")}
    return {"action": action, "est_tokens": est, "value_signal": round(float(context.get("value_signal", 0.5)), 3),
            "custo_pct_dia": custo_pct, "orcamento": "esgotado" if esgotado else ("sem limite (medindo)" if ilimitado else f"{budget.left_ratio():.0%} do dia"),
            "desbloqueia_fila": desbloqueia, "fila_do_developer": int(context.get("fila_do_developer", 0) or 0),
            "rodou_hoje_sem_render": max(0, rodou - rendeu), "rodou_hoje": rodou, **extras}


def estado_evolve(store, evolution_type: str, evidence: Mapping[str, Any]) -> dict:
    """Ocorrências e consistência medidas, mais o histórico da mesma evolução: revertida antes? aplicada hoje?"""
    desc = str(evidence.get("description", ""))[:200]
    agora = time.time()
    rev = store.one("SELECT COUNT(*) n, COALESCE(SUM(COALESCE(rollbacks,0)),0) rb FROM proposals WHERE description=? AND (status='rolled_back' OR COALESCE(rollbacks,0)>0)", (desc,)) if desc else None
    hoje = store.one("SELECT COUNT(*) n FROM proposals WHERE description=? AND status='applied' AND updated_at>=?", (desc, agora - 86400)) if desc else None
    return {"evolution_type": evolution_type, "occurrences": int(evidence.get("occurrences", 0) or 0),
            "consistency": round(float(evidence.get("consistency", 0) or 0), 2), "kind": evidence.get("kind"),
            "revertida_antes": int((rev["rb"] if rev else 0) or (rev["n"] if rev else 0)), "aplicada_hoje": int(hoje["n"] if hoje else 0),
            "description": desc}


NUMERO = r"\d+(?:[.,]\d+)?"


def _token_numerico(n: str) -> str:
    """0,50 e 0.5 são o mesmo número; 18 não é 18.5 nem 1900 é 9900 (casamento por token inteiro, não por substring)."""
    from decimal import Decimal
    return format(Decimal(n.replace(",", ".")).normalize(), "f")


def estado_dado(dado: str, evidencia: str, base: str = "") -> dict:
    """Verificação mecânica antes do Jev: quais números do dado aparecem, como token numérico, na evidência (com o trecho
    em volta). Sem dígito no dado não há o que conferir: `nao_verificavel`."""
    import re
    evidencia = evidencia or ""
    nums = re.findall(NUMERO, dado or "")[:12]
    tokens = {}
    for m in re.finditer(NUMERO, evidencia):
        tokens.setdefault(_token_numerico(m.group()), m.start())
    achados, trechos = [], []
    for n in nums:
        p = tokens.get(_token_numerico(n))
        if p is not None:
            achados.append(n)
            trechos.append(evidencia[max(0, p - 60):p + len(n) + 40].replace("\n", " "))
    fr = round(len(achados) / len(nums), 2) if nums else None
    return {"dado": (dado or "")[:300], "base": base, "dado_tem_digito": bool(nums),
            "numero_literal_na_evidencia": "nao_verificavel" if fr is None else "sim" if fr == 1 else "nao" if fr == 0 else "parte",
            "numeros_do_dado": nums, "numeros_na_evidencia": achados, "fracao_encontrada": fr,
            "n_numeros_evidencia": len(re.findall(NUMERO, evidencia)), "trechos_da_evidencia": trechos[:6],
            "evidencia_tem_numeros": bool(tokens)}


def regra_dado(s: Mapping[str, Any]) -> float:
    """O número do dado está, como token, na evidência? Todos: sim; nenhum: não (inventado), com confiança alta. Sem
    dígito não há o que conferir (0,5). Base inferida aproxima de 0,5: a conta pode ter transformado o número."""
    fr = s.get("fracao_encontrada")
    if fr is None:
        return 0.5
    p = 0.05 + 0.9 * float(fr)
    return p if s.get("base") != "inferido" else 0.5 + (p - 0.5) * 0.8


FATOR_TESTE = {"passou": (0.85, 0.85, 0.95, 1.0), "falhou": (0.6, 0.6, 0.9, 1.0)}   # por execucoes_seguidas 0, 1, 2, 3+


def estado_evidencia(store, texto: str, base: Mapping[str, Any]) -> dict:
    """O teste citado no item, como o loop o mediu no main (licoes.checagens): existe, último exit, execuções seguidas
    com o mesmo resultado e alternância (passa-falha-passa: teste instável, o resultado isolado não prova nada)."""
    import re
    from .licoes import NAO_COLETADO, alvo_de
    m = re.search(r"tests/[\w./-]+\.py::[\w\[\]-]+", texto or "")
    exits = []
    if m:
        lics = [lic for lic in map(dict, store.q("SELECT * FROM licoes WHERE status!='unida' AND checagens IS NOT NULL ORDER BY id"))
                if alvo_de(lic) == m.group(0)]
        exits = [int(c["exit"]) for c in json.loads(lics[0]["checagens"])] if lics else []
    seguidas = next((i for i, e in enumerate(reversed(exits)) if (e == 0) != (exits[-1] == 0)), len(exits))
    flips = sum((a == 0) != (b == 0) for a, b in zip(exits, exits[1:], strict=False))
    return {**base, "teste_citado": "nenhum" if not m else ("nao_medido" if not exits else
                                                           "nao_existe" if exits[-1] in NAO_COLETADO else "existe"),
            "exit_main": "sem_execucao" if not exits else ("passou" if exits[-1] == 0 else
                                                           "nao_coletado" if exits[-1] in NAO_COLETADO else "falhou"),
            "execucoes_seguidas": "3+" if seguidas >= 3 else str(seguidas), "alternou": flips >= 2}


def regra_evidencia(s: Mapping[str, Any]) -> float:
    """Contrariar o pedido exige fontes (citações reais da busca valem mais que URLs escritas pela LLM); o teste citado
    medido no main só muda a confiança, nunca o lado: alternância e falha isolada aproximam de 0,5, passar seguido afasta."""
    p = min(1.0, int(s.get("n_fontes", 0)) / 3) * (0.9 if int(s.get("n_citacoes", 0)) else 0.6)
    p = p if s.get("veredito") == "contestar" else min(1.0, p + 0.15)
    n = {"0": 0, "1": 1, "2": 2, "3+": 3}.get(str(s.get("execucoes_seguidas", "0")), 0)
    f = (0.8 if s.get("teste_citado", "nenhum") in ("nenhum", "nao_medido") else 0.5 if s.get("alternou")
         else FATOR_TESTE.get(s.get("exit_main"), (0.7,) * 4)[n])
    return 0.5 + (p - 0.5) * f


REGRAS = {"evidencia_sustenta": regra_evidencia, "dado_na_evidencia": regra_dado}   # regras do LocalJev que moram aqui

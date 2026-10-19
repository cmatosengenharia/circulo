"""Fluxo dos agentes ao vivo: quem fez o quê em cada giro, na ordem, para a tela animar a passagem entre agentes.

Cada passagem de etapa do giro (trilha), cada pergunta ao Jev (decisões), cada chamada de LLM, cada verificação
(neurônio) e cada erro vira um evento com: agente, o que fez em português simples, para quem a "requisição" foi
(próximo agente, Jev, regra, LLM, GitHub) e o run_id do giro. A tela recebe os eventos por SSE e anima uma
bolinha indo de um agente ao outro.

O catálogo de agentes não é fixo: uma etapa nova que a autoevolução criar (nova tarefa na trilha) vira agente
sozinha, com nome, descrição e as mesmas métricas (execuções, duração p50 e tendência, falhas, custo), e a tela
desenha e anima do mesmo jeito.
"""
from __future__ import annotations

import json
import time

from .camadas import NOME, chave_trilha
from .state import Store

# o que cada agente faz, em uma frase (os que nascerem depois usam a descrição da própria trilha)
FAZ = {
    "orquestrador": "Abre o giro, confere orçamento e pausa, e decide a ordem do trabalho.",
    "pedido": "Atende o que você pediu: pedidos têm prioridade sobre a evolução natural.",
    "decisao": "Escolhe a próxima tarefa: a regra estreita as opções e o Jev escolhe.",
    "atualizar_corpo": "Valida o código novo (importação e testes) e passa a rodá-lo; prova em 5 giros.",
    "estudar_pedido": "Pesquisa o pedido em fontes confiáveis e decide adotar, adaptar ou contestar.",
    "planejar_roteiro": "Parte de uma pergunta do conselho e propõe o próximo item do roteiro.",
    "corrigir_codigo": "O Developer (Claude Code) muda o código num worktree, passa nos portões e abre o PR.",
    "revisar_prs": "O gate confere CI, constituição e teste novo, e mergeia ou devolve o PR.",
    "evoluir_projeto": "Faz um ciclo nas missões: pesquisa, régua, versão nova, torneio e evidência.",
    "meta_learner": "Aprende regras novas com as correções e propõe mudanças.",
    "shadow": "Testa a política candidata em paralelo (shadow) antes de valer.",
    "licoes": "Revisa as lições: corrigida, validada, evidenciada ou reincidente.",
    "saude": "Mede a saúde e desfaz a última mudança se ela piorou o loop.",
    "analisar_padroes": "Procura padrões nos gastos da família e avisa quando um deles merece alerta.",
    "revisar_baixa_confianca": "Revê as decisões que foram tomadas com pouca confiança.",
    "rodar_regressao": "Roda a regressão sobre o histórico para ver se as regras atuais ainda acertam.",
    "resumo": "Escreve o resumo periódico do que o loop fez.",
    "propor_feature": "Propõe uma melhoria a partir do uso.",
    "evoluir_harness": "Testa prompts por A/B e promove o que rende mais.",
    "conectar_missoes": "Liga missões que se complementam para trocarem contexto e lições.",
    "jardinagem": "O jardineiro: mede padrões ruins se espalhando no código e abre item para podar o que cresce.",
    "indagar": "O Indagador: levanta as perguntas pertinentes de cada missão e o Jev classifica (pertinente, eixo, acionável).",
    "jev": "Decide por tipos (sim/não, escolha, nota) antes de qualquer LLM; quando fica em dúvida, a regra decide.",
    "llm": "Gera texto e raciocina quando o Jev e a regra não bastam (custa tokens).",
    "github": "Repositório: PRs, CI e merge.",
}
EXTERNOS = ("jev", "llm", "github")
PERGUNTAS = {"worth_spending": "vale gastar agora?", "idle_task": "qual tarefa agora?", "should_evolve": "a evidência justifica evoluir?",
             "pick_model": "qual modelo basta?", "review_code": "o PR pode entrar?", "should_run_idle": "vale rodar a manutenção?",
             "next_project": "qual missão ganha mais?", "route": "qual o degrau mais barato?", "remember": "vale guardar a lição?",
             "evidencia_sustenta": "a evidência sustenta?", "isolate_stage": "isolar a etapa?", "should_advance": "a versão avança?",
             "health_rollback": "desfazer a última mudança?", "verify_output": "a saída está certa?", "input_type": "que tipo de mensagem é?"}
PONTO_AGENTE = (("developer:", "corrigir_codigo"), ("gate:", "revisar_prs"), ("corpo:", "atualizar_corpo"),
                ("estudo:", "estudar_pedido"), ("planejador:", "planejar_roteiro"), ("missao", "evoluir_projeto"),
                ("loop:", "orquestrador"), ("rastro:", "licoes"), ("painel:", None))
PAPEL_AGENTE = {"developer": "corrigir_codigo", "estudo": "estudar_pedido", "planejador": "planejar_roteiro",
                "questionador": "planejar_roteiro", "builder": "evoluir_projeto", "pesquisa": "evoluir_projeto",
                "avaliador": "evoluir_projeto", "reviewer": "revisar_prs"}


def _agente_da_trilha(etapa: str, tarefa: str | None) -> str | None:
    if etapa in ("descanso", "pausado"):
        return etapa
    if tarefa and tarefa not in NOME:
        return tarefa                       # agente novo nascido da autoevolução: entra com o próprio nome
    return chave_trilha(etapa, tarefa) or etapa


CURTO = {"orquestrador": "Orquestrador", "pedido": "Pedido seu", "decisao": "Escolha", "atualizar_corpo": "Corpo",
         "estudar_pedido": "Estudo", "planejar_roteiro": "Planejador", "corrigir_codigo": "Developer", "revisar_prs": "Gate",
         "evoluir_projeto": "Missões", "meta_learner": "Aprendiz", "shadow": "Shadow", "licoes": "Lições", "saude": "Saúde",
         "analisar_padroes": "Padrões", "revisar_baixa_confianca": "Revisão", "rodar_regressao": "Regressão", "resumo": "Resumo",
         "propor_feature": "Melhorias", "evoluir_harness": "Prompts A/B", "conectar_missoes": "Conexões",
         "jardinagem": "Jardineiro", "indagar": "Indagador"}


def nome_do_agente(chave: str) -> str:
    if chave in CURTO:
        return CURTO[chave]
    if chave in NOME:
        return NOME[chave]
    return {"jev": "Jev", "llm": "LLM", "github": "GitHub", "descanso": "Descanso", "pausado": "Pausado"}.get(
        chave, chave.replace("_", " ").capitalize())


def _agente_no_momento(store: Store, tick: int | None, em: float) -> tuple[str, float]:
    """Quem estava trabalhando quando a pergunta/chamada aconteceu, e quando esse agente começou."""
    r = store.one("SELECT etapa, tarefa, em FROM trail WHERE tick=? AND em<=? ORDER BY seq DESC LIMIT 1", (tick, em + 1)) if tick else None
    a = _agente_da_trilha(r["etapa"], r["tarefa"]) if r else None
    if a and a not in ("descanso", "pausado"):
        return a, r["em"]
    return "orquestrador", em


def _valor(v) -> str:
    try:
        x = json.loads(v)
    except (TypeError, ValueError):
        x = v
    if isinstance(x, float):
        return f"{x:.2f}"
    return str(x).replace("_", " ")


# ------------------------------------------------------------------ eventos
def cursor_inicial(store: Store, voltar: int = 0) -> dict:
    """Onde começar: o fim de cada tabela (só o que acontecer daqui para frente), ou `voltar` passagens antes,
    para a tela já abrir mostrando o último giro."""
    def m(sql, args=()):
        return store.one(sql, args)["m"] or 0
    if voltar:
        r = store.one("SELECT MIN(seq) m, MIN(em) em FROM (SELECT seq, em FROM trail ORDER BY seq DESC LIMIT ?)", (voltar,))
        em = r["em"] or time.time()
        return {"trail": (r["m"] or 1) - 1, "dec": m("SELECT MAX(id) m FROM decisions WHERE created_at < ?", (int(em),)),
                "llm": m("SELECT MAX(id) m FROM llm_calls WHERE created_at < ?", (em,)),
                "ver": m("SELECT MAX(id) m FROM verificacoes WHERE created_at < ?", (em,)),
                "err": m("SELECT MAX(id) m FROM run_errors WHERE em < ?", (em,))}
    return {"trail": m("SELECT MAX(seq) m FROM trail"), "dec": m("SELECT MAX(id) m FROM decisions"),
            "llm": m("SELECT MAX(id) m FROM llm_calls"), "ver": m("SELECT MAX(id) m FROM verificacoes"),
            "err": m("SELECT MAX(id) m FROM run_errors")}


def eventos(store: Store, cursor: dict, limite: int = 200) -> tuple[list[dict], dict]:
    """Eventos novos desde o cursor, na ordem em que aconteceram, e o cursor seguinte."""
    c = dict(cursor)
    out: list[dict] = []
    ultimo_por_run: dict[str, str] = {}

    rows = store.q("SELECT seq, tick, etapa, tarefa, detalhe, project_id, em, run_id FROM trail WHERE seq > ? ORDER BY seq LIMIT ?",
                   (c.get("trail", 0), limite))
    for t in rows:
        c["trail"] = t["seq"]
        ag = _agente_da_trilha(t["etapa"], t["tarefa"])
        if ag is None:
            continue
        rid = t["run_id"] or f"t{t['tick']}"
        de = ultimo_por_run.get(rid)
        if de is None:
            prev = store.one("SELECT etapa, tarefa FROM trail WHERE seq < ? AND run_id IS ? ORDER BY seq DESC LIMIT 1", (t["seq"], t["run_id"]))
            de = _agente_da_trilha(prev["etapa"], prev["tarefa"]) if prev else None
        if de == ag:
            continue                                   # mesma etapa registrada de novo (ex.: idle → idle com tarefa)
        ultimo_por_run[rid] = ag
        if ag == "orquestrador":
            texto = f"começou o giro {t['tick']}"
        elif ag == "descanso":
            texto = f"giro {t['tick']} terminou; descansando até o próximo"
        elif ag == "pausado":
            texto = "loop pausado por você"
        else:
            texto = t["detalhe"] or FAZ.get(ag, "trabalhando")
        out.append({"tipo": "etapa", "em": t["em"], "agente": ag, "de": de, "texto": texto, "tick": t["tick"],
                    "run_id": t["run_id"], "projeto": t["project_id"], "novo": ag not in FAZ and ag not in ("descanso", "pausado")})

    for d in store.q("SELECT id, tick, question, value, confidence, source, created_at FROM decisions WHERE id > ? ORDER BY id LIMIT ?",
                     (c.get("dec", 0), limite)):
        c["dec"] = d["id"]
        ag, desde = _agente_no_momento(store, d["tick"], float(d["created_at"]))
        em = max(float(d["created_at"]), desde + 0.001)   # decisões antigas têm horário em segundos inteiros
        perg = PERGUNTAS.get(d["question"], d["question"].replace("_", " "))
        conf = int(round(float(d["confidence"] or 0) * 100))
        quem = {"jev": "Jev", "local": "regra", "llm": "LLM"}.get(d["source"], d["source"])
        out.append({"tipo": "decisao", "em": em, "agente": ag, "para": "jev", "decidiu": d["source"],
                    "texto": f"perguntou ao Jev: {perg} → {_valor(d['value'])} ({quem}, {conf}% de confiança)",
                    "confianca": float(d["confidence"] or 0), "tick": d["tick"]})

    for x in store.q("SELECT id, tick, papel, modelo, tokens, ok, duracao_ms, created_at FROM llm_calls WHERE id > ? ORDER BY id LIMIT ?",
                     (c.get("llm", 0), limite)):
        c["llm"] = x["id"]
        papel = str(x["papel"] or "")
        ag = PAPEL_AGENTE.get(papel.split(":")[0], None) or _agente_no_momento(store, x["tick"], x["created_at"])[0]
        out.append({"tipo": "llm", "em": float(x["created_at"]) - (x["duracao_ms"] or 0) / 1000, "agente": ag, "para": "llm",
                    "ok": bool(x["ok"]), "texto": f"chamou a LLM ({x['modelo']}, {int(x['tokens'] or 0):,} tokens)".replace(",", ".")
                    + ("" if x["ok"] else " e falhou"), "tick": x["tick"]})

    for v in store.q("SELECT id, tick, ponto, sujeito, ok, substr(motivo,1,160) motivo, created_at FROM verificacoes WHERE id > ? ORDER BY id LIMIT ?",
                     (c.get("ver", 0), limite)):
        c["ver"] = v["id"]
        ag = next((a for p, a in PONTO_AGENTE if v["ponto"].startswith(p)), "")
        if ag is None:
            continue                                   # ex.: frescor do próprio painel: não é trabalho de agente
        ag = ag or _agente_no_momento(store, v["tick"], v["created_at"])[0]
        para = "github" if v["ponto"].startswith("gate:") or v["ponto"] == "developer:abrir_pr" else None
        out.append({"tipo": "verificacao", "em": v["created_at"], "agente": ag, "para": para, "ok": bool(v["ok"]),
                    "texto": f"{'passou' if v['ok'] else 'reprovou'} em {v['ponto']}" + (f" ({v['sujeito']})" if v["sujeito"] else "")
                    + ("" if v["ok"] else f": {v['motivo'] or ''}"), "tick": v["tick"]})

    for e in store.q("SELECT id, tick, stage, kind, substr(message,1,160) message, em, run_id FROM run_errors WHERE id > ? ORDER BY id LIMIT ?",
                     (c.get("err", 0), limite)):
        c["err"] = e["id"]
        out.append({"tipo": "erro", "em": e["em"], "agente": _agente_no_momento(store, e["tick"], e["em"])[0], "ok": False,
                    "texto": f"erro em {e['stage']}: {e['kind']} — {e['message']} (vira lição)", "tick": e["tick"], "run_id": e["run_id"]})

    out.sort(key=lambda x: (x["em"], {"etapa": 0, "decisao": 1, "llm": 2, "verificacao": 3, "erro": 4}[x["tipo"]]))
    return out, c


# ------------------------------------------------------------------ catálogo e métricas dos agentes
def _p50(xs: list[float]) -> float | None:
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def agentes(store: Store, now: float | None = None) -> list[dict]:
    """Todos os agentes que já trabalharam (inclusive os criados pela autoevolução), com o que fazem e como estão indo:
    execuções, duração p50 agora vs. antes (a conduta está ficando mais rápida?), falhas e custo em tokens."""
    now = now or time.time()
    ini = now - 2 * 86400
    rows = store.q("SELECT run_id, etapa, tarefa, detalhe, em FROM trail WHERE em >= ? AND run_id IS NOT NULL ORDER BY seq", (ini,))
    durs: dict[str, dict[str, list[float]]] = {}
    ultimo: dict[str, dict] = {}
    for i, t in enumerate(rows):
        ag = _agente_da_trilha(t["etapa"], t["tarefa"])
        if ag in (None, "descanso", "pausado"):
            continue
        nxt = rows[i + 1] if i + 1 < len(rows) and rows[i + 1]["run_id"] == t["run_id"] else None
        dur = (nxt["em"] - t["em"]) if nxt else 0.0
        janela = "agora" if t["em"] >= now - 86400 else "antes"
        durs.setdefault(ag, {"agora": [], "antes": []})[janela].append(dur)
        ultimo[ag] = {"em": t["em"], "texto": t["detalhe"] or FAZ.get(ag, "")}
    falhas: dict[str, int] = {}
    for v in store.q("SELECT ponto FROM verificacoes WHERE ok=0 AND created_at >= ?", (now - 86400,)):
        ag = next((a for p, a in PONTO_AGENTE if v["ponto"].startswith(p)), None)
        if ag:
            falhas[ag] = falhas.get(ag, 0) + 1
    tokens: dict[str, int] = {}
    for x in store.q("SELECT papel, SUM(tokens) t FROM llm_calls WHERE created_at >= ? GROUP BY papel", (now - 86400,)):
        ag = PAPEL_AGENTE.get(str(x["papel"] or "").split(":")[0])
        if ag:
            tokens[ag] = tokens.get(ag, 0) + int(x["t"] or 0)
    chaves = [k for k in FAZ if k not in EXTERNOS] + [k for k in durs if k not in FAZ]
    vistos = store.get("agentes_vistos")
    if vistos is None:                                  # primeira vez: os que já existem não são "novos"
        vistos = {k: 0 for k in chaves}
        store.set("agentes_vistos", vistos)
    elif any(k not in vistos for k in chaves):
        vistos.update({k: now for k in chaves if k not in vistos})
        store.set("agentes_vistos", vistos)
    out = []
    for k in chaves:
        d = durs.get(k, {"agora": [], "antes": []})
        p_ag, p_an = _p50(d["agora"]), _p50(d["antes"])
        tendencia = None
        if p_ag is not None and p_an and len(d["agora"]) >= 3 and len(d["antes"]) >= 3:
            tendencia = round((p_ag - p_an) / p_an, 3)            # negativo = ficou mais rápido
        out.append({"id": k, "nome": nome_do_agente(k), "faz": FAZ.get(k) or (ultimo.get(k, {}).get("texto") or "agente criado pela autoevolução"),
                    "execucoes_24h": len(d["agora"]), "p50_ms": None if p_ag is None else round(p_ag * 1000),
                    "tendencia": tendencia, "falhas_24h": falhas.get(k, 0), "tokens_24h": tokens.get(k, 0),
                    "ultimo": ultimo.get(k), "novo": float(vistos.get(k, 0)) > now - 86400,
                    "externo": False})
    for k in EXTERNOS:
        out.append({"id": k, "nome": nome_do_agente(k), "faz": FAZ[k], "externo": True})
    return out


def agora(store: Store) -> dict:
    from .status import loop_status
    st = loop_status(store)
    e = store.get("etapa") or {}
    ag = _agente_da_trilha(e.get("nome", ""), e.get("tarefa")) if e.get("nome") else None
    return {"estado": st["estado"], "titulo": st["titulo"], "detalhe": st.get("detalhe"), "tick": st.get("tick"),
            "agente": ag, "run_id": e.get("run_id"), "desde": e.get("em")}


def visao(store: Store) -> dict:
    from .jev_lab import resumo as jev_resumo
    return {"agora": agora(store), "agentes": agentes(store), "jev": jev_resumo(store), "gerado_em": time.time()}

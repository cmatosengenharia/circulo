"""Indagador: o agente da autoevolução. Faz as perguntas certas para cada missão, e o Jev classifica cada uma.

Toda evolução do loop parte de uma PERGUNTA (o conselho de perspectivas, em perguntas.py). O Indagador é o agente
que, a cada passagem, olha o CONTEXTO de uma missão (a do loop ou qualquer missão cadastrada) e levanta as
perguntas pertinentes àquele momento, sem LLM: critério mais fraco da régua, lição aberta, verificação que
falha, missão que parou de evoluir, gasto desproporcional. Cada candidata vai ao Jev, na mesma chamada, para
três classificações:
- `pertinente` (sim/não): a pergunta é pertinente ao contexto atual da missão?
- `eixo` (escolha): o que ela faz evoluir — arquitetura, missao, operacao — ou nenhum;
- `acao` (nota): dá para agir nela num item pequeno e medível?

Só a pergunta que o Jev classifica como pertinente, com eixo e acionável vira "valida" e entra como ponto de
partida: o planejador parte dela (missão loop) e o ciclo de melhoria da missão parte dela (outras missões).
Pergunta em que o Jev fica em dúvida (a regra decidiu) fica "inconclusa" e volta a ser feita depois:
inconclusivo não passa (Lauren Tan). Pergunta descartada pelo Jev fica registrada com a classificação, para o
placar das perspectivas e para você ver o que o Jev recusou.

Os seus pedidos entram pela mesma porta: viram item do roteiro (fila de estudo → Developer → portões) e o
Indagador anota, pelo Jev, o eixo e a pertinência, sem nunca descartar um pedido seu. Cada pergunta carrega a
evidência medida (SQL nos dados do loop), nunca inferida.
"""
from __future__ import annotations

import json
import time
from typing import Any

import re

from .decision import Decision, SN, Question, norm

EIXOS = {
    "arquitetura": "muda como o loop/missão é construído: módulos, fronteiras, portões, testes, estrutura do código ou da entrega",
    "missao": "muda o que a missão entrega ao humano: conteúdo, qualidade medida pela régua, critérios, formato, utilidade",
    "operacao": "muda como roda: custo, tokens, tempo, falhas, recuperação, observabilidade, frequência das tarefas",
    "nenhum": "não leva a mudança nenhuma: genérica, já respondida, fora do alcance do loop ou sem evidência",
}
ACAO = ("a pergunta é tão ampla ou vaga que nenhum item pequeno a responde (ex.: “como melhorar o sistema?”)",
        "a pergunta aponta uma direção, mas o item que a responde ainda precisa ser descoberto por pesquisa ou várias tentativas",
        "a pergunta cabe num item pequeno e medível: dá para dizer o que muda, onde, e como se mede que respondeu")
PERTINENTE_MIN = 0.6
ACAO_MIN = 1
# Ritmo (1.30): o Indagador é um dos agentes mais atuantes. Com vaga na fila de válidas, volta a cada INTERVALO_FOME;
# espera INTERVALO_VAZIO quando a última passagem não achou pergunta nova, e com a fila cheia não indaga.
INTERVALO_FOME = 300          # há vaga: volta em 5 min (cada passagem só custa uma chamada ao Jev)
INTERVALO_VAZIO = 1800        # a última passagem não tinha candidata nova: 30 min até haver evidência nova
MAX_VALIDAS = 5               # estoque de perguntas válidas esperando o planejador
MAX_CANDIDATAS = 6


def _um(s, sql, args=()):
    r = s.one(sql, args)
    return (r[0] if r is not None else 0) or 0


# ------------------------------------------------------------------ contexto
def contexto(store, project: dict | None) -> dict[str, Any]:
    """O que o Jev vê da missão ao classificar (só dados medidos)."""
    agora = time.time()
    if project is None:
        prog = store.get("progresso") or {}
        return {"missao": "loop", "tipo": "circulo",
                "pedido": "o próprio loop: entregar qualquer pedido do humano com evidência, pelo menor custo, sem babá",
                "itens_pendentes": _um(store, "SELECT COUNT(*) FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0"),
                "licoes_abertas": _um(store, "SELECT COUNT(*) FROM licoes WHERE status IN ('aberta','reincidente')"),
                "giros_sem_avanco": int(prog.get("sem", 0)),
                "falhas_24h": _um(store, "SELECT COUNT(*) FROM verificacoes WHERE ok=0 AND created_at>=?", (agora - 86400,)),
                "tokens_24h": _um(store, "SELECT SUM(tokens) FROM llm_calls WHERE created_at>=?", (agora - 86400,))}
    pid = project["id"]
    cur = store.one("SELECT nota, nota_oculta, notas, version FROM deliverables WHERE project_id=? AND status='atual' "
                    "ORDER BY version DESC LIMIT 1", (pid,))
    rub = store.one("SELECT criteria FROM rubrics WHERE project_id=? ORDER BY version DESC LIMIT 1", (pid,))
    criterios = json.loads(rub["criteria"]) if rub else []
    notas = json.loads(cur["notas"] or "{}") if cur else {}
    fracos = sorted(((c.get("texto") or c.get("text") or ""), float(notas.get(c.get("id"), 0))) for c in criterios if c.get("id") in notas)
    ciclos = store.q("SELECT aceita, ganho FROM cycles WHERE project_id=? ORDER BY id DESC LIMIT 6", (pid,))
    return {"missao": project.get("nome") or f"missão {pid}", "tipo": project.get("tipo"), "pedido": (project.get("pedido") or "")[:400],
            "status": project.get("status"), "versao_atual": cur["version"] if cur else 0,
            "nota": round(float(cur["nota"] or 0), 2) if cur else None, "nota_oculta": round(float(cur["nota_oculta"] or 0), 2) if cur else None,
            "criterios_fracos": [{"criterio": t[:120], "nota": round(n, 2)} for t, n in fracos[:3]],
            "ciclos_recentes": len(ciclos), "ciclos_rejeitados_seguidos": next((i for i, c in enumerate(ciclos) if c["aceita"]), len(ciclos)),
            "licoes_abertas": _um(store, "SELECT COUNT(*) FROM licoes WHERE status IN ('aberta','reincidente') AND descricao LIKE ?",
                                  (f"%{project.get('nome') or '§'}%",)),
            "falhas_24h": _um(store, "SELECT COUNT(*) FROM verificacoes WHERE ok=0 AND created_at>=? AND sujeito=?",
                              (agora - 86400, project.get("nome") or f"missão {pid}")),
            "tokens_24h": _um(store, "SELECT SUM(tokens) FROM llm_calls WHERE created_at>=? AND project_id=?", (agora - 86400, pid))}


# ------------------------------------------------------------------ candidatas (sem LLM, com evidência medida)
def candidatas(ctx, project: dict | None) -> list[dict]:
    """Perguntas possíveis para esta missão agora: texto, persona e evidência (base: medido)."""
    s = ctx.store
    if project is None:
        from .perguntas import Conselho
        # primeiro o funil (onde o tempo está indo), depois o especialista (assunto a assunto), depois o conselho
        out = candidatas_funil(s)
        out += sorted(candidatas_especialista(s), key=lambda c: -c["relevancia"])
        out += [{"chave": p.id, "persona": p.persona, "texto": p.texto, "relevancia": p.relevancia,
                 "evidencia": {**p.evidencia, "base": "medido"}} for p in Conselho(ctx).candidatas()]
        fora = ja_julgadas(s, "loop")
        return [c for c in out if c["chave"] not in fora][:MAX_CANDIDATAS]
    from .perguntas import personas_da_missao
    c = contexto(s, project)
    ps = personas_da_missao(ctx, project["tipo"], project["pedido"])
    out = []
    chaves = list(ps)
    for i, f in enumerate(c["criterios_fracos"]):
        persona = chaves[i % len(chaves)]
        out.append({"chave": f"missao:{project['id']}:criterio:{i}", "persona": persona, "relevancia": round(1 - f["nota"], 3),
                    "texto": f"Como {persona.replace('_', ' ')} ({ps[persona]}), o que na entrega atual mais falha em “{f['criterio']}” "
                             f"(nota {f['nota']:.2f}), e que mudança pequena sobe essa nota?",
                    "evidencia": {"criterio": f["criterio"], "nota": f["nota"], "base": "medido"}})
    if c["ciclos_rejeitados_seguidos"] >= 2:
        out.append({"chave": f"missao:{project['id']}:estagnada", "persona": "cetico", "relevancia": min(1.0, c["ciclos_rejeitados_seguidos"] / 4),
                    "texto": f"A missão rejeitou {c['ciclos_rejeitados_seguidos']} ciclos seguidos: o que a régua não captura, ou que critério "
                             "virou meta e parou de medir utilidade (Goodhart)?",
                    "evidencia": {"ciclos_rejeitados_seguidos": c["ciclos_rejeitados_seguidos"], "base": "medido"}})
    if c["falhas_24h"]:
        out.append({"chave": f"missao:{project['id']}:falhas", "persona": "operador", "relevancia": min(1.0, c["falhas_24h"] / 3),
                    "texto": f"A verificação da saída desta missão falhou {c['falhas_24h']} vez(es) em 24 h: qual checagem reprova, e o que "
                             "no prompt ou na régua evitaria a falha antes de gastar a segunda geração?",
                    "evidencia": {"falhas_24h": c["falhas_24h"], "base": "medido"}})
    if c["tokens_24h"] and c.get("nota") is not None and c["nota"] >= 0.85:
        out.append({"chave": f"missao:{project['id']}:custo", "persona": "economista", "relevancia": 0.5,
                    "texto": f"Com nota {c['nota']:.2f}, esta missão ainda gastou {int(c['tokens_24h'])} tokens em 24 h: que ciclo poderia "
                             "ter sido pulado pelo Jev, e com que sinal?",
                    "evidencia": {"tokens_24h": c["tokens_24h"], "nota": c["nota"], "base": "medido"}})
    return out[:MAX_CANDIDATAS]


# ------------------------------------------------------------------ o Jev classifica
def classificar(ctx, cands: list[dict], ctxt: dict) -> list[dict]:
    """Uma chamada ao Jev com 3 perguntas por candidata. Devolve cada candidata com a classificação."""
    if not cands:
        return []
    qs = {}
    for i in range(len(cands)):
        qs[f"indaga_pert_{i}"] = Question(
            "noul", f"A pergunta `candidatas.{i}.texto` é pertinente ao contexto atual da missão `missao` (pedido `pedido`, "
                    f"critérios fracos `criterios_fracos`, lições abertas `licoes_abertas`, falhas `falhas_24h`)?",
            SN("a pergunta mira uma dor que os dados da missão mostram agora (`candidatas.%d.evidencia`) e respondê-la mudaria o próximo passo" % i,
               "a pergunta é genérica, fala de algo que os dados não mostram, ou repete o que já está em andamento"))
        qs[f"indaga_eixo_{i}"] = Question("choice", f"O que a pergunta `candidatas.{i}.texto` faz evoluir, se respondida?", dict(EIXOS))
        qs[f"indaga_acao_{i}"] = Question("score", f"Quão acionável é a pergunta `candidatas.{i}.texto`?", ACAO)
    state = {**ctxt, "candidatas": [{"texto": c["texto"], "persona": c["persona"], "evidencia": c["evidencia"]} for c in cands]}
    out = ctx.dl.ask_many(state, qs)
    res = []
    for i, c in enumerate(cands):
        p, e, a = out[f"indaga_pert_{i}"], out[f"indaga_eixo_{i}"], out[f"indaga_acao_{i}"]
        inconclusa = any(d.source == "local" for d in (p, e, a)) and getattr(ctx.dl.jev, "source", "") == "jev"
        pert, eixo, acao = float(p.value), str(e.value), int(float(a.value))
        if inconclusa:
            veredito = "inconclusa"           # o Jev ficou em dúvida e a regra decidiu: não passa, volta depois
        elif pert >= PERTINENTE_MIN and eixo != "nenhum" and acao >= ACAO_MIN:
            veredito = "valida"
        else:
            veredito = "descartada"
        res.append({**c, "pertinencia": round(pert, 3), "eixo": eixo, "acionavel": acao, "veredito": veredito,
                    "classificacao": {"pertinente": {"p": round(pert, 3), "conf": round(p.confidence, 3), "fonte": p.source},
                                      "eixo": {"valor": eixo, "conf": round(e.confidence, 3), "probs": dict(e.probabilities or {})},
                                      "acao": {"nivel": acao, "conf": round(a.confidence, 3)}}})
    return res


# ------------------------------------------------------------------ não repete o que já foi julgado
JULGADA_DIAS = 3              # chave válida, em uso, entregue ou descartada: não volta por 3 dias
INCONCLUSA_HORAS = 6          # em dúvida: volta depois de 6 h, e no máximo 2 vezes em 3 dias
INCONCLUSAS_MAX = 2


def ja_julgadas(store, cerebro: str, agora: float | None = None) -> set[str]:
    """Chaves que não devem voltar à classificação agora. Antes só a válida/em uso saía da fila; a descartada e a
    inconclusa voltavam a cada passagem (no Mac a mesma pergunta foi julgada 3 vezes em 14 h, sempre com o mesmo veredito)."""
    agora = agora or time.time()
    fora = {r["chave"] for r in store.q("SELECT chave FROM perguntas WHERE cerebro=? AND status IN ('valida','feita','virou_item','entregue','descartada') "
                                        "AND created_at>=?", (cerebro, agora - JULGADA_DIAS * 86400))}
    for r in store.q("SELECT chave, COUNT(*) n, MAX(created_at) ultima FROM perguntas WHERE cerebro=? AND status='inconclusa' "
                     "AND created_at>=? GROUP BY chave", (cerebro, agora - JULGADA_DIAS * 86400)):
        if r["n"] >= INCONCLUSAS_MAX or agora - float(r["ultima"]) < INCONCLUSA_HORAS * 3600:
            fora.add(r["chave"])
    return fora


# ------------------------------------------------------------------ o especialista: perguntas por ASSUNTO, com evidência
# Cada chave carrega o assunto (lição #12, trava X, pergunta do Jev Y, arquivo Z): assunto novo = pergunta nova. Era isso
# que faltava: as perguntas do conselho têm chave fixa e, uma vez julgadas, somem por 3 dias; o Indagador ficava sem o
# que perguntar e rodava 3 vezes em 3 h.
def _esp_licoes(s, agora):
    out = []
    for r in s.q("SELECT id, descricao, classe, ocorrencias, reincidencias, camada FROM licoes WHERE status IN ('aberta','validada','reincidente','em_correcao') "
                 "AND classe!='ambiente' AND (ocorrencias>=2 OR reincidencias>=1) ORDER BY reincidencias DESC, ocorrencias DESC LIMIT 6"):
        out.append({"chave": f"licao:{r['id']}", "persona": "curador_licoes", "relevancia": min(1.0, 0.4 + 0.1 * r["ocorrencias"] + 0.3 * r["reincidencias"]),
                    "texto": f"A lição #{r['id']} ({r['descricao'][:90]}) ocorreu {r['ocorrencias']} vez(es)"
                             + (f" e reincidiu {r['reincidencias']}x" if r["reincidencias"] else "")
                             + ": que mudança de estrutura torna esse erro impossível, em vez de só um teste a mais?",
                    "evidencia": {"licao": r["id"], "ocorrencias": r["ocorrencias"], "reincidencias": r["reincidencias"], "camada": r["camada"]}})
    return out


def _esp_vigia(s, agora):
    out = []
    for r in s.q("SELECT chave, titulo, gravidade, vezes, primeira_em FROM vigia WHERE status='aberta' AND veredito='trava' ORDER BY gravidade DESC LIMIT 4"):
        mins = int((agora - float(r["primeira_em"] or agora)) / 60)
        out.append({"chave": f"vigia:{r['chave']}", "persona": "operador", "relevancia": min(1.0, float(r["gravidade"] or 0.5)),
                    "texto": f"O Vigia mede a trava “{r['titulo'][:100]}” há {mins} min ({r['vezes']} passagens): que mudança no loop "
                             "evita que essa trava apareça de novo, sem depender do humano?",
                    "evidencia": {"trava": r["chave"], "minutos": mins, "gravidade": r["gravidade"], "vezes": r["vezes"]}})
    return out


def _esp_jev(s, agora):
    out = []
    for r in s.q("SELECT question q, COUNT(*) n, SUM(source='local') regra, AVG(confidence) conf FROM decisions WHERE created_at>=? "
                 "GROUP BY question HAVING n>=20 AND (regra*1.0/n>=0.3 OR conf<0.3) ORDER BY regra*1.0/n DESC LIMIT 4", (agora - 86400,)):
        taxa = r["regra"] / r["n"]
        out.append({"chave": f"jev:{r['q']}", "persona": "economista", "relevancia": min(1.0, 0.4 + taxa),
                    "texto": f"O Jev decide “{r['q']}” com dúvida (a regra decidiu {taxa:.0%} de {r['n']} vezes em 24 h, confiança média {float(r['conf'] or 0):.2f}): "
                             "que dado medido falta no estado dessa pergunta para ele decidir com confiança?",
                    "evidencia": {"pergunta": r["q"], "decisoes_24h": r["n"], "pela_regra": r["regra"], "confianca_media": round(float(r["conf"] or 0), 2)}})
    return out


def _esp_neuronios(s, agora):
    out = []
    for r in s.q("SELECT ponto, COUNT(*) n, SUM(ok=0) f FROM verificacoes WHERE created_at>=? GROUP BY ponto HAVING f>=3 ORDER BY f DESC LIMIT 4", (agora - 86400,)):
        out.append({"chave": f"neuronio:{r['ponto']}", "persona": "operador", "relevancia": min(1.0, 0.3 + r["f"] / max(r["n"], 1)),
                    "texto": f"O neurônio {r['ponto']} foi barrado {r['f']} de {r['n']} vezes em 24 h: qual é a causa que se repete e o que a evita antes de gastar?",
                    "evidencia": {"ponto": r["ponto"], "falhas_24h": r["f"], "total_24h": r["n"]}})
    return out


def _esp_prs(s, agora):
    out = []
    for r in s.q("SELECT p.number, p.titulo, (SELECT reason FROM merges m WHERE m.pr=p.number ORDER BY m.id DESC LIMIT 1) motivo "
                 "FROM prs p WHERE p.status='fechado' AND p.updated_at>=? ORDER BY p.updated_at DESC LIMIT 3", (agora - 86400,)):
        out.append({"chave": f"pr_fechado:{r['number']}", "persona": "arquiteto", "relevancia": 0.7,
                    "texto": f"O PR #{r['number']} (“{(r['titulo'] or '')[:70]}”) fechou sem merge ({(r['motivo'] or 'motivo não registrado')[:80]}): "
                             "que portão antes do PR teria evitado o gasto, e como medi-lo?",
                    "evidencia": {"pr": r["number"], "motivo": r["motivo"]}})
    arquivos: dict[str, int] = {}
    for r in s.q("SELECT evidencia FROM revisoes WHERE veredito='rejeitado' AND created_at>=?", (agora - 7 * 86400,)):
        try:
            for c in json.loads(r["evidencia"] or "{}").get("compartilhados") or []:
                for a in c.get("arquivos") or []:
                    arquivos[a] = arquivos.get(a, 0) + 1
        except ValueError:
            continue
    for a, n in sorted(arquivos.items(), key=lambda kv: -kv[1])[:2]:
        if n >= 2:
            out.append({"chave": f"revisor:{a}", "persona": "arquiteto", "relevancia": min(1.0, 0.4 + 0.15 * n),
                        "texto": f"O arquivo {a} cruzou PRs paralelos {n} vez(es) em 7 dias (o Revisor rejeitou): dividir o módulo ou serializar quem o toca?",
                        "evidencia": {"arquivo": a, "cruzamentos_7d": n}})
    return out


def _esp_itens(s, agora):
    out = []
    feitos = [float(r["updated_at"]) - float(r["created_at"]) for r in s.q(
        "SELECT created_at, updated_at FROM roadmap WHERE status='feito' AND origem IN ('loop','erro') AND updated_at>=?", (agora - 86400,))]
    if len(feitos) >= 3:
        med = sorted(feitos)[len(feitos) // 2]
        for r in s.q("SELECT id, titulo, created_at, updated_at FROM roadmap WHERE status='feito' AND origem IN ('loop','erro') AND updated_at>=? "
                     "ORDER BY (updated_at-created_at) DESC LIMIT 2", (agora - 86400,)):
            dur = float(r["updated_at"]) - float(r["created_at"])
            if dur > 3 * med and dur > 1800:
                out.append({"chave": f"item_lento:{r['id']}", "persona": "operador", "relevancia": min(1.0, 0.4 + dur / (6 * med)),
                            "texto": f"O item #{r['id']} (“{r['titulo'][:70]}”) levou {dur / 60:.0f} min até entrar (mediana do dia {med / 60:.0f}): onde ele esperou, e qual espera era evitável?",
                            "evidencia": {"item": r["id"], "minutos": round(dur / 60), "mediana_min": round(med / 60)}})
    return out


def _esp_missoes(s, agora):
    out = []
    for r in s.q("SELECT id, nome, tipo FROM projects WHERE kit!='circulo' AND status='ativo' AND COALESCE(pausada,0)=0 "
                 "AND id NOT IN (SELECT project_id FROM rubrics)"):
        out.append({"chave": f"missao:{r['id']}:sem_regua", "persona": "cientista", "relevancia": 0.8,
                    "texto": f"A missão “{r['nome']}” ({r['tipo']}) está ativa sem régua: que critérios medidos dizem se ela está entregando valor ao Cássio?",
                    "evidencia": {"missao": r["id"], "rubricas": 0}})
    return out


ESPECIALISTA = (_esp_vigia, _esp_licoes, _esp_jev, _esp_neuronios, _esp_prs, _esp_itens, _esp_missoes)


def candidatas_especialista(store) -> list[dict]:
    """Perguntas por assunto, todas com evidência medida (SQL, sem LLM)."""
    agora = time.time()
    out = []
    for f in ESPECIALISTA:
        out += f(store, agora)
    for c in out:
        c["evidencia"]["base"] = "medido"
    return out


# ------------------------------------------------------------------ o funil da autoevolução (medido)
# Cada etapa tem um alvo em minutos; a mais atrasada vira a primeira pergunta do loop. É o que o especialista em
# autoevolução olharia primeiro: onde, da pergunta ao merge, o tempo está indo.
ALVO_MIN = {"pergunta_para_item": 15, "item_para_pr": 45, "pr_para_merge": 25}
NOME_ETAPA = {"pergunta_para_item": "da pergunta validada ao item do roteiro (Planejador + porteiro)",
              "item_para_pr": "do item ao PR aberto (Estudo + Developer)", "pr_para_merge": "do PR ao merge (CI + gate)"}


def _mediana(xs: list[float]) -> float | None:
    xs = sorted(xs)
    return None if not xs else xs[len(xs) // 2]


def funil(store, horas: int = 24) -> dict[str, Any]:
    """Minutos por etapa nas últimas `horas` (mediana e pior), PRs sem merge, motivo atual de o planejador não planejar."""
    desde = time.time() - horas * 3600
    q1 = [(float(r["r_em"]) - float(r["p_em"])) / 60 for r in store.q(
        "SELECT p.created_at p_em, r.created_at r_em FROM perguntas p JOIN roadmap r ON r.id=p.item_id "
        "WHERE p.cerebro='loop' AND p.persona!='cassio' AND r.created_at>=?", (desde,))]
    q2, q3 = [], []
    for r in store.q("SELECT r.created_at r_em, pr.created_at pr_em, pr.number FROM roadmap r JOIN prs pr ON r.evidencia LIKE 'PR #' || pr.number || '%' "
                     "WHERE r.origem IN ('loop','pedido_cassio','erro') AND pr.created_at>=?", (desde,)):
        q2.append((float(r["pr_em"]) - float(r["r_em"])) / 60)
        m = store.one("SELECT MIN(created_at) em FROM merges WHERE pr=? AND merged=1", (r["number"],))
        if m and m["em"]:
            q3.append((float(m["em"]) - float(r["pr_em"])) / 60)
    prs = store.one("SELECT SUM(status='mergeado') ok, SUM(status='fechado') ruim FROM prs WHERE created_at>=?", (desde,))
    gate = store.get("planejador_gate") or {}
    etapas = {}
    for k, xs in (("pergunta_para_item", q1), ("item_para_pr", q2), ("pr_para_merge", q3)):
        med = _mediana(xs)
        etapas[k] = {"amostras": len(xs), "mediana_min": round(med, 1) if med is not None else None,
                     "pior_min": round(max(xs), 1) if xs else None, "alvo_min": ALVO_MIN[k],
                     "atraso": round(med / ALVO_MIN[k], 2) if med is not None else None}
    return {"horas": horas, "etapas": etapas, "prs_mergeados": int(prs["ok"] or 0), "prs_fechados": int(prs["ruim"] or 0),
            "planejador_motivo": gate.get("motivo"), "base": "medido"}


def candidatas_funil(store) -> list[dict]:
    """Perguntas do loop sobre o próprio funil: só onde a medida passa do alvo."""
    f = funil(store)
    out = []
    piores = sorted(((e["atraso"], k) for k, e in f["etapas"].items() if e["atraso"] and e["amostras"] >= 2), reverse=True)
    if piores and piores[0][0] > 1.0:
        atraso, k = piores[0]
        e = f["etapas"][k]
        out.append({"chave": f"funil:{k}", "persona": "operador", "relevancia": min(1.0, 0.5 + 0.25 * atraso),
                    "texto": f"A etapa “{NOME_ETAPA[k]}” levou {e['mediana_min']:.0f} min na mediana (alvo {e['alvo_min']}, pior {e['pior_min']:.0f}) "
                             f"em {e['amostras']} casos nas últimas 24 h: qual espera dessa etapa é desnecessária e que mudança pequena a corta?",
                    "evidencia": {"etapa": k, **e, "base": "medido"}})
    if f["prs_fechados"] >= 2 and f["prs_fechados"] >= f["prs_mergeados"]:
        out.append({"chave": "funil:prs_fechados", "persona": "arquiteto", "relevancia": min(1.0, 0.4 + 0.15 * f["prs_fechados"]),
                    "texto": f"{f['prs_fechados']} PR(s) do Developer fecharam sem merge contra {f['prs_mergeados']} mesclado(s) em 24 h: "
                             "qual portão reprova mais e o que o Developer deveria checar antes de abrir o PR?",
                    "evidencia": {"prs_fechados": f["prs_fechados"], "prs_mergeados": f["prs_mergeados"], "base": "medido"}})
    from .planejador import ESPERA, FILA_CHEIA
    motivo = f.get("planejador_motivo") or ""
    if motivo and not motivo.startswith((FILA_CHEIA, ESPERA)):
        out.append({"chave": "funil:planejador_parado", "persona": "operador", "relevancia": 0.8,
                    "texto": f"O Planejador não planeja porque “{motivo}”: essa trava é legítima agora, e o que a resolve sem esperar o humano?",
                    "evidencia": {"planejador_motivo": motivo, "base": "medido"}})
    return out


# ------------------------------------------------------------------ uma passagem do agente
def cerebro_de(project: dict | None) -> str:
    return "loop" if project is None else f"missao:{project['id']}"


def indagar(ctx, project: dict | None = None) -> dict:
    s, agora = ctx.store, time.time()
    cer = cerebro_de(project)
    cands = candidatas(ctx, project)
    cands = [c for c in cands if c["chave"] not in ja_julgadas(s, cer, agora)][:max(0, _vaga(s, cer))]
    res = classificar(ctx, cands, contexto(s, project))
    ids = []
    for c in res:
        ids.append(s.x("INSERT INTO perguntas(chave,persona,texto,relevancia,score,evidencia,status,cerebro,eixo,pertinencia,acionavel,"
                       "classificacao,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (c["chave"], c["persona"], c["texto"][:400], c.get("relevancia"), round(c["pertinencia"] * (1 + c["acionavel"]) / 3, 4),
                        json.dumps(c["evidencia"], ensure_ascii=False, default=str), c["veredito"], cer, c["eixo"], c["pertinencia"],
                        c["acionavel"], json.dumps(c["classificacao"], ensure_ascii=False), agora, agora)))
        if c["veredito"] == "valida":
            from .planejador import marcar_etapa
            marcar_etapa(s, ids[-1], "validada", {"cerebro": cer})
    marcas = dict(s.get("indagador") or {})
    marcas[cer] = agora
    s.set("indagador", marcas)
    vazios = dict(s.get("indagador_vazio") or {})
    if cands:
        vazios.pop(cer, None)
    else:
        vazios[cer] = agora                  # nada novo para perguntar: volta em INTERVALO_VAZIO, não em 5 min
    s.set("indagador_vazio", vazios)
    validas = [c for c in res if c["veredito"] == "valida"]
    if validas and callable(getattr(ctx, "reply", None)):
        nome = "o loop" if project is None else (project.get("nome") or f"missão {project['id']}")
        ctx.reply(f"Indagador ({nome}): o Jev validou {len(validas)} de {len(res)} pergunta(s). Ponto de partida: "
                  f"“{validas[0]['texto'][:140]}” (eixo: {validas[0]['eixo']}).", "roteiro")
    return {"cerebro": cer, "candidatas": len(cands), "validas": len(validas), "descartadas": sum(c["veredito"] == "descartada" for c in res),
            "inconclusas": sum(c["veredito"] == "inconclusa" for c in res), "ids": ids}


def _vaga(store, cer: str) -> int:
    """Quantas perguntas válidas ainda cabem no estoque deste cérebro (MAX_VALIDAS é teto, não ritmo)."""
    return MAX_VALIDAS - _um(store, "SELECT COUNT(*) FROM perguntas WHERE cerebro=? AND status='valida'", (cer,))


def precisa(store, engine=None) -> bool:
    return proximo_cerebro(store, engine) is not None


def proximo_cerebro(store, engine=None) -> dict | None:
    """O cérebro mais esquecido que ainda tem espaço para perguntas: {'project': None|dict}."""
    marcas = store.get("indagador") or {}
    agora = time.time()
    opcoes = [None]
    if engine is not None and getattr(engine, "ready", False):
        opcoes += [dict(r) for r in store.q("SELECT * FROM projects WHERE kit!='circulo' AND status='ativo' AND COALESCE(pausada,0)=0 "
                                            "AND id IN (SELECT project_id FROM rubrics) ORDER BY id")]
    pior, pior_em = None, None
    for p in opcoes:
        cer = cerebro_de(p)
        em = float(marcas.get(cer, 0))
        if _vaga(store, cer) <= 0:
            continue
        vazio = float((store.get("indagador_vazio") or {}).get(cer, 0))
        if agora - em < (INTERVALO_VAZIO if vazio >= em else INTERVALO_FOME):
            continue
        if pior_em is None or em < pior_em:
            pior, pior_em = {"project": p}, em
    return pior


def rodar(ctx, engine=None) -> dict | None:
    alvo = proximo_cerebro(ctx.store, engine)
    return indagar(ctx, alvo["project"]) if alvo else None


# ------------------------------------------------------------------ consumo: quem parte da pergunta válida
def espiar(store, cerebro: str) -> dict | None:
    """A melhor pergunta válida esperando, sem consumir (o porteiro do gasto vê o que o gasto vai responder)."""
    r = store.one("SELECT id, texto, eixo, pertinencia, acionavel, created_at FROM perguntas WHERE cerebro=? AND status='valida' "
                  "ORDER BY score DESC, id LIMIT 1", (cerebro,))
    return dict(r) if r else None


def proxima(store, cerebro: str) -> dict | None:
    """A melhor pergunta validada pelo Jev para este cérebro, marcada como 'feita' (quem consome liga ao item)."""
    r = store.one("SELECT * FROM perguntas WHERE cerebro=? AND status='valida' ORDER BY score DESC, id LIMIT 1", (cerebro,))
    if r is None:
        return None
    store.x("UPDATE perguntas SET status='feita', updated_at=? WHERE id=?", (time.time(), r["id"]))
    return dict(r)


def classificar_pedido(ctx, texto: str, item_id: int, project: dict | None = None) -> dict | None:
    """Um pedido seu: entra na fila de qualquer jeito; o Jev só anota eixo e pertinência (nunca descarta)."""
    try:
        res = classificar(ctx, [{"chave": f"pedido:{item_id}", "persona": "cassio", "texto": texto[:400], "relevancia": 1.0,
                                 "evidencia": {"origem": "pedido do humano", "base": "medido"}}], contexto(ctx.store, project))
    except Exception:  # noqa: BLE001 — classificar nunca atrasa o pedido
        return None
    if not res:
        return None
    c, agora = res[0], time.time()
    ctx.store.x("INSERT INTO perguntas(chave,persona,texto,relevancia,score,evidencia,status,cerebro,eixo,pertinencia,acionavel,classificacao,"
                "item_id,created_at,updated_at) VALUES(?,?,?,?,?,?,'virou_item',?,?,?,?,?,?,?,?)",
                (c["chave"], "cassio", c["texto"], 1.0, 1.0, json.dumps(c["evidencia"], ensure_ascii=False), cerebro_de(project), c["eixo"],
                 c["pertinencia"], c["acionavel"], json.dumps(c["classificacao"], ensure_ascii=False), item_id, agora, agora))
    ctx.store.x("UPDATE roadmap SET detalhe = detalhe || ? WHERE id=?",
                (f"\n\nIndagador (Jev): eixo {c['eixo']}, pertinência {c['pertinencia']:.2f}, acionável {c['acionavel']}/2.", item_id))
    return c


def resumo(store, limite: int = 12) -> dict:
    rows = [dict(r) for r in store.q("SELECT id, cerebro, persona, texto, status, eixo, pertinencia, acionavel, item_id, created_at "
                                     "FROM perguntas WHERE eixo IS NOT NULL ORDER BY id DESC LIMIT ?", (limite,))]
    tot = store.one("SELECT COUNT(*) n, SUM(status='valida') v, SUM(status='descartada') d, SUM(status='inconclusa') i, "
                    "SUM(status IN ('feita','virou_item','entregue')) u FROM perguntas WHERE eixo IS NOT NULL")
    por_eixo = {r["eixo"]: r["n"] for r in store.q("SELECT eixo, COUNT(*) n FROM perguntas WHERE eixo IS NOT NULL GROUP BY eixo")}
    return {"ultimas": rows, "total": tot["n"] or 0, "validas": tot["v"] or 0, "descartadas": tot["d"] or 0, "inconclusas": tot["i"] or 0,
            "usadas": tot["u"] or 0, "por_eixo": por_eixo, "marcas": store.get("indagador") or {}, "eixos": EIXOS, "funil": funil(store)}


# ------------------------------------------------------------------ a regra (LocalJev) quando o Jev está em dúvida ou nos testes
def regra(jev, qid: str, q: Question, state) -> Decision:
    tipo, i = qid.split("_")[1], int(qid.rsplit("_", 1)[1])
    cands = state.get("candidatas") or []
    txt = norm(str(cands[i].get("texto") or "")) if i < len(cands) else ""
    generica = bool(re.search(r"\b(como melhorar o sistema|tudo|em geral|qualquer coisa)\b", txt)) or len(txt) < 40
    concreta = bool(re.search(r"\d|“|\"|\b(nota|criterio|verificacao|tokens|ciclo|licao|falh\w*|regua|modulo|teste)\b", txt))
    ctx_txt = " ".join(str(state.get(k, "")) for k in ("pedido", "missao", "tipo")) + " " + \
        " ".join(str(x.get("criterio", "")) for x in state.get("criterios_fracos") or [])
    rel = jev._overlap(ctx_txt, txt)
    if tipo == "pert":
        return jev._noul(qid, 0.25 if generica else min(0.95, 0.5 + rel + (0.2 if concreta else 0)))
    if tipo == "eixo":
        if generica:
            v = "nenhum"
        elif re.search(r"\b(tokens|custo|gast\w*|falh\w*|verificacao|tempo|frequencia|pulad\w*)\b", txt):
            v = "operacao"
        elif re.search(r"\b(modulo|codigo|teste|portao|fronteira|arquitetura|estrutura|regua nao captura|goodhart)\b", txt):
            v = "arquitetura"
        else:
            v = "missao"
        return Decision(qid, "choice", v if v in q.options() else q.options()[-1], 0.6, jev.source)
    nivel = 0 if generica else (2 if concreta else 1)
    return Decision(qid, "score", float(nivel), 0.6, jev.source)

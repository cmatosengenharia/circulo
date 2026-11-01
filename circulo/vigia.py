"""Vigia: o agente que roda em paralelo ao giro e vigia as travas da autoevolução.

Hoje as travas eram descobertas por você perguntando no chat ("o loop está evoluindo?") e por alguém lendo o banco.
O Vigia faz isso sozinho, o tempo todo, numa thread própria (não depende do giro: pega inclusive giro travado):

1. **Sondas** (SQL nos dados do loop, sem LLM, evidência medida): pergunta validada parada, porteiro recusando a mesma
   tarefa repetidas vezes, Developer parado com fila, fila seca, PR preso, corpo atrasado em relação ao GitHub, lição
   de estrutura bloqueando há horas, Jev em dúvida crônica numa pergunta, estagnação, missão sem ciclo, Claude Code no
   limite, giro travado, orçamento esgotado.
2. **Jev First**: cada achado novo vai ao Jev na mesma chamada com duas perguntas: `vigia_trava` (sim/não com os dois
   lados descritos: é uma trava real da autoevolução agora?) e `vigia_acao` (escolha: abrir item · alertar · observar).
   O roteamento é pela confiança (doc da TypeSafe): alta → faz o que o Jev escolheu; média → só alerta; baixa (a regra
   decidiu) → observa e pergunta de novo na próxima passagem. A regra local é a heurística do próprio módulo.
3. **Age**: abre item no roteiro (origem loop, com a evidência e a sugestão; o estudo e o Developer seguem o caminho
   normal), alerta na linha do tempo, ou só registra. Quando a sonda para de disparar, a trava é dada como resolvida,
   com alerta se tinha sido alertada. Tudo fica na tabela `vigia` e no painel (card "Vigia" e página do fluxo).
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import threading
import time
from typing import Any, Callable

from . import roadmap
from .decision import SN, Decision, Question, norm
from .estagnacao import ESTAGNADO, EXPIRA_EM, parado, pendencias
from .licoes import Licoes
from .metrics import seguro
from .planejador import ESPERA, FILA_CHEIA, GATE, MAX_TENTATIVAS, PORTEIRO, PROGRESSO, TENTATIVAS

INTERVALO = 60                   # segundos entre passagens da thread
ESPERA_PERGUNTA = 30 * 60        # pergunta validada esperando mais que isso = trava
DRENAR = 45 * 60                 # trava com pergunta validada mais velha que isso: o Vigia chama o planejador só com ela
DISJUNTOR = 3                    # falhas seguidas da drenagem = falha sistêmica: pausa REAGIR em vez de queimar a fila
DRENAGEM = "vigia_drenagem"      # kv: perguntas já tentadas pela drenagem, falhas seguidas, pausa e a última tentativa
REAGIR = 2 * 3600                # trava que continua aberta tanto tempo depois da ação: age de novo (não fica muda)
RECUSAS_PORTEIRO = 3             # a mesma pergunta recusada tantas vezes seguidas pelo mesmo motivo sai da fila
DEV_PARADO = 45 * 60
PR_PRESO = 60 * 60
CORPO_ATRASADO = 40 * 60
LICAO_BLOQUEIA = 2 * 3600
GIRO_TRAVADO = 20 * 60
ACOES = {"abrir_item": "a trava é estrutural e repetível: um item pequeno no roteiro, com a evidência, corrige a causa",
         "alertar": "a trava é real mas transitória ou depende do humano/ambiente: avisar na linha do tempo basta",
         "observar": "ainda não dá para dizer se é trava: registrar e medir de novo na próxima passagem"}
CONF_AGIR = 0.5
ALVO_DESTRAVAR = 0.8            # dos disparos da estagnação com resultado, ao menos 80% destravam o loop em EXPIRA_EM giros
REPETICAO = 4                   # limiares do StuckDetector do OpenHands: a mesma ação com o mesmo resultado seguidas vezes
ERRO_REPETIDO = 3               # a mesma ação terminando no mesmo erro
MONOLOGO = 3                    # giros em que nada rodou
ALTERNANCIA = 6                 # eventos alternando A/B/A/B
ALVO_PADRAO = 0.8               # dos disparos da estagnação em 7 dias, ao menos 80% com o padrão nomeado


def _normalizar(e: dict) -> tuple:
    """(ação, resultado) pelo conteúdo: ids, números e horários não distinguem um evento do outro."""
    return tuple(re.sub(r"[#\d:.\-]+", "", str(e.get(k) or "")).strip() or None for k in ("acao", "resultado"))


def detectar_travamento(eventos: list[dict]) -> dict | None:
    """O padrão da cauda dos giros parados (desde o último avanço): {padrao, ciclos, limiar} ou None se for saudável."""
    ev = [_normalizar(e) for e in eventos or []]
    if not ev:
        return None
    rep = next((i for i, e in enumerate(reversed(ev)) if e != ev[-1]), len(ev))
    acao, resultado = ev[-1]
    for padrao, ciclos, limiar, vale in (("monologo", rep, MONOLOGO, acao is None),
                                         ("erro_repetido", rep, ERRO_REPETIDO, acao is not None and (resultado or "").startswith("erro")),
                                         ("acao_repetida", rep, REPETICAO, acao is not None)):
        if vale and ciclos >= limiar:
            return {"padrao": padrao, "ciclos": ciclos, "limiar": limiar}
    n = 0 if len(ev) < 2 or ev[-1] == ev[-2] else 2
    while n and n < len(ev) and ev[-n - 1] == ev[-n + 1]:
        n += 1
    return {"padrao": "alternancia", "ciclos": n, "limiar": ALTERNANCIA} if n >= ALTERNANCIA else None


def _um(s, sql, args=()):
    r = s.one(sql, args)
    return (r[0] if r is not None else 0) or 0


def _kv(s, k, default=None):
    return s.get(k) or default


# ------------------------------------------------------------------ causa da falha de um neurônio (pergunta #511)
# A pausa é decisão já tomada (disjuntor, conta sem crédito): vence o timeout que a causou. Depois, o que repetir resolve;
# por fim, o que repetir dá o mesmo. Um número solto ("500 linhas") não é status HTTP.
PAUSA = re.compile(r"disjuntor|circuito ?aberto|credit balance", re.I)
TRANSITORIA = re.compile(r"timed? ?out|rate.?limit|too many requests|overloaded|bad gateway|service unavailable"
                         r"|connection (?:reset|refused|aborted)|(?:HTTP(?: Error)?|status|code)\W{0,3}(?:429|5\d\d)\b"
                         r"|JSONDecodeError|Expecting value|Unterminated string|sem_json", re.I)
DETERMINISTICA = re.compile(r"schema|falta_chave|ValidationError|vazi[ao]s?\b|\b(?:Key|Type|Attribute|Value|Name|Import"
                            r"|Index|Assertion|Syntax)Error|FAILED|falhas locais iguais|nada avançou|m[aá]ximo de passos", re.I)


def classificar_causa(texto_erro: str | None) -> str:
    """'transitoria' (repetir pode dar certo), 'deterministica' (repetir dá o mesmo) ou 'desconhecida'. Pura."""
    t = texto_erro or ""
    if PAUSA.search(t):
        return "deterministica"
    if TRANSITORIA.search(t):
        return "transitoria"
    return "deterministica" if DETERMINISTICA.search(t) else "desconhecida"


def pode_repetir(texto_erro: str | None) -> bool:
    """Só a causa transitória pode acionar retry com backoff."""
    return classificar_causa(texto_erro) == "transitoria"


def causas_por_classe(textos) -> dict[str, int]:
    out = {"transitoria": 0, "deterministica": 0, "desconhecida": 0}
    for t in textos:
        out[classificar_causa(t)] += 1
    return out


# ------------------------------------------------------------------ sondas (cada uma devolve um achado ou None)
def _causa_porteiro(u: dict) -> str:
    """A causa medida no registro do porteiro (planejador.registrar_porteiro); sem registro, nenhuma causa é sugerida."""
    if not u:
        return "sem registro do porteiro worth_spending.idle_evolution sobre o planejador: causa não medida, inspecionar"
    return (f"porteiro worth_spending.idle_evolution {u['decisao']} a pergunta #{u['pergunta_id']} {u['seguidas']}x seguida(s): "
            f"{u['motivo']} (medido {u['valor']:.2f}, limiar {u['limiar']:.2f}, fonte {u['fonte']})")


def _causa_tentativa(t: dict, now: float) -> str:
    """O resultado medido da última tentativa real do planejador (planejador.registrar_tentativa)."""
    falha = f"falhou ({t['classe_da_falha']})" if t.get("classe_da_falha") else t["desfecho"]
    return (f"última tentativa do planejador há {int((now - t['em']) / 60)} min, pergunta #{t['pergunta_id']} "
            f"(tentativa {t['tentativas']}/{MAX_TENTATIVAS}): {falha}: {t['motivo']}")


def _dev_sem_vaga(s) -> bool:
    """Developer sem vaga: todos os MAX_PRS_ABERTOS PRs em uso (1.29); retrato antigo = um PR aberto."""
    aberto = _kv(s, "self_dev_aberto", {}) or {}
    if "abertos" in aberto:
        return len(aberto.get("abertos") or []) >= int(aberto.get("max") or 1)
    return bool(aberto.get("pr") and not aberto.get("fechado"))


def s_pergunta_valida_parada(s, now):
    desde = {p["id"]: float(p["created_at"]) for p in s.q("SELECT id, created_at FROM perguntas WHERE status='valida'")}
    u = (_kv(s, PORTEIRO, {}) or {}).get("ultimo") or {}
    recusa = u if u.get("decisao") == "recusou" and u.get("pergunta_id") in desde else None
    if recusa:                               # recusa registrada é load shedding, não trava: a espera conta da última decisão
        desde[recusa["pergunta_id"]] = max(desde[recusa["pergunta_id"]], float(recusa["em"]))
    r = {"n": len(desde), "em": min(desde.values(), default=now)}
    # a idade só cresce: acima do limite agora e na verificação anterior (INTERVALO atrás) = 2 verificações seguidas
    if not r["n"] or now - r["em"] < ESPERA_PERGUNTA + INTERVALO:
        return None
    plan = float((_kv(s, "planejador", {}) or {}).get("em", 0))
    gate = _kv(s, GATE, {}) or {}
    motivo = gate.get("motivo") if now - float(gate.get("em", 0) or 0) < 30 * 60 else None
    if motivo and motivo.startswith(FILA_CHEIA):
        return None                          # contrapressão medida: o Developer tem trabalho; Developer parado é outra sonda
    tent = _kv(s, TENTATIVAS, {}) or {}
    ult = tent.get("ultima")
    if motivo and motivo.startswith(ESPERA):
        motivo = None                        # o planejador roda a cada intervalo: a causa está no resultado da tentativa
    causa = (f"o planejador não planeja: {motivo}" if motivo else _causa_tentativa(ult, now) if ult else _causa_porteiro(u))
    progresso = tent.get("ultimo_progresso_em")
    sem_progresso = int((now - float(progresso)) / 60) if progresso else None
    rec = (f"; última recusa do porteiro há {int((now - float(recusa['em'])) / 60)} min: {recusa['motivo']} "
           f"{recusa['valor']:.2f} < {recusa['limiar']:.2f}" if recusa else "")
    return {"chave": "pergunta_valida_parada", "titulo": f"{r['n']} pergunta(s) validada(s) pelo Jev esperando há {int((now - r['em']) / 60)} min sem virar item "
                                                         f"(último progresso {f'há {sem_progresso} min' if sem_progresso is not None else 'nunca medido'}{rec})",
            "evidencia": {"perguntas_validas": r["n"], "esperando_min": int((now - r["em"]) / 60), "sem_progresso_min": sem_progresso,
                          "planejador_rodou_ha_min": int((now - plan) / 60) if plan else None,
                          "porteiro": u or None, "recusa_porteiro": recusa, "planejador_motivo": motivo, "ultima_tentativa": ult},
            "gravidade": min(1.0, 0.5 + (now - r["em"]) / (4 * ESPERA_PERGUNTA)), "sugestao": causa}


def s_porteiro_recusa(s, now):
    rec = (_kv(s, "progresso", {}) or {}).get("recusas") or {}
    piores = {k: v for k, v in rec.items() if int(v) >= 3}
    if not piores:
        return None
    k = max(piores, key=piores.get)
    return {"chave": f"porteiro_recusa:{k}", "titulo": f"O porteiro do gasto recusou “{k}” {piores[k]} vezes seguidas",
            "evidencia": {"recusas": rec, "tarefa": k}, "gravidade": min(1.0, 0.4 + 0.1 * piores[k]),
            "sugestao": "o Jev responde abaixo do limiar sem contexto suficiente: dar ao porteiro o que a tarefa faria (como em pergunta_validada)"}


def s_developer_parado(s, now):
    espera = float((_kv(s, "self_dev_espera", {}) or {}).get("ate", 0))
    if espera > now:
        return None
    if _dev_sem_vaga(s):
        return None
    item = s.one("SELECT id, titulo FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 AND estudo IS NOT NULL "
                 "AND evidencia NOT LIKE '%depende de você%' AND origem IN ('pedido_cassio','referencia','loop','erro') ORDER BY ordem LIMIT 1")
    if not item:
        return None
    ult = _um(s, "SELECT MAX(em) FROM trail WHERE etapa='developer' OR tarefa='corrigir_codigo'")
    if now - ult < DEV_PARADO:
        return None
    return {"chave": "developer_parado", "titulo": f"Item #{item['id']} pronto para o Developer há mais de {int((now - ult) / 60)} min e ele não pegou",
            "evidencia": {"item": item["id"], "titulo": item["titulo"][:100], "developer_ultimo_ha_min": int((now - ult) / 60)},
            "gravidade": 0.7, "sugestao": "ver se corrigir_codigo está sendo escolhido no giro e se o porteiro o recusa"}


def s_fila_seca(s, now):
    pend = _um(s, "SELECT COUNT(*) FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 AND origem IN ('pedido_cassio','referencia','loop','erro')")
    val = _um(s, "SELECT COUNT(*) FROM perguntas WHERE status='valida'")
    plan = float((_kv(s, "planejador", {}) or {}).get("em", 0))
    ocupado = _dev_sem_vaga(s)
    if pend or val or ocupado or (plan and now - plan < 2 * 3600):
        return None
    return {"chave": "fila_seca", "titulo": "Nada na fila: sem item pendente, sem pergunta validada e o planejador não roda há mais de 2 h",
            "evidencia": {"itens_pendentes": 0, "perguntas_validas": 0, "planejador_ha_min": int((now - plan) / 60) if plan else None},
            "gravidade": 0.6, "sugestao": "o Indagador ou o planejador não estão sendo escolhidos; ver intervalo e porteiro"}


def s_pr_preso(s, now):
    r = s.one("SELECT number, titulo, created_at FROM prs WHERE status='aberto' ORDER BY created_at LIMIT 1")
    if not r or now - r["created_at"] < PR_PRESO:
        return None
    dev = s.one("SELECT reason FROM merges WHERE pr=? ORDER BY id DESC LIMIT 1", (r["number"],))
    return {"chave": f"pr_preso:{r['number']}", "titulo": f"PR #{r['number']} aberto há {int((now - r['created_at']) / 60)} min sem merge",
            "evidencia": {"pr": r["number"], "titulo": r["titulo"][:100], "ultimo_motivo": (dev["reason"] if dev else None)},
            "gravidade": min(1.0, 0.5 + (now - r["created_at"]) / (6 * 3600)),
            "sugestao": "ver o último motivo do gate (CI, conflito, constituição) e se o Developer está consertando na mesma branch"}


def s_corpo_atrasado(s, now):
    c = _kv(s, "corpo", {}) or {}
    if not c:
        return None
    chk = float(c.get("checado_em", 0))
    if c.get("remoto") and c.get("sha") and c["remoto"] != c["sha"] and now - chk > CORPO_ATRASADO:
        return {"chave": "corpo_atrasado", "titulo": f"GitHub está em {c['remoto'][:7]} e o Mac roda {c['sha'][:7]} há {int((now - chk) / 60)} min",
                "evidencia": {"remoto": c["remoto"][:7], "rodando": c["sha"][:7], "estado": c.get("estado"), "checado_ha_min": int((now - chk) / 60)},
                "gravidade": 0.6, "sugestao": "a tarefa atualizar_corpo não está rodando ou a validação reprovou (ver reprovados)"}
    if c.get("estado") == "validando" and now - chk > 3 * CORPO_ATRASADO:
        return {"chave": "corpo_validando", "titulo": f"Corpo {c['sha'][:7]} em validação há {int((now - chk) / 60)} min ({c.get('giros_ok', 0)}/5 giros)",
                "evidencia": {"sha": c["sha"][:7], "giros_ok": c.get("giros_ok"), "erros": c.get("erros")}, "gravidade": 0.5,
                "sugestao": "os giros não estão acontecendo no ritmo esperado"}
    return None


def s_licao_bloqueia(s, now):
    Licoes(s).expirar_estruturais(now)
    r = s.one("SELECT COUNT(*) n, MIN(COALESCE(aberta_em, created_at)) em FROM licoes WHERE classe='estrutural' AND status IN ('aberta','em_correcao','reincidente')")
    if not r["n"] or now - float(r["em"] or now) < LICAO_BLOQUEIA:
        return None
    return {"chave": "licao_bloqueia", "titulo": f"{r['n']} lição(ões) de estrutura aberta(s) há {int((now - r['em']) / 3600)} h sem correção entregue",
            "evidencia": {"licoes": r["n"], "ha_horas": round((now - r["em"]) / 3600, 1)}, "gravidade": 0.8,
            "sugestao": "a evolução segue (1.70: a trava do Planejador dura 30 min), mas a correção não chega: ver por que o item dela não anda"}


def s_jev_duvida(s, now):
    rows = s.q("SELECT question q, COUNT(*) n, SUM(source='local') regra FROM decisions WHERE created_at>=? AND question NOT LIKE 'crit_%' "
               "AND question NOT LIKE 'rel_%' GROUP BY question HAVING n>=50 AND regra*1.0/n>=0.4 ORDER BY n DESC LIMIT 1", (now - 86400,))
    if not rows:
        return None
    r = rows[0]
    return {"chave": f"jev_duvida:{r['q']}", "titulo": f"Jev em dúvida crônica em “{r['q']}”: a regra decidiu {int(r['regra'] * 100 / r['n'])}% de {r['n']} vezes em 24 h",
            "evidencia": {"pergunta": r["q"], "n_24h": r["n"], "pela_regra": r["regra"]}, "gravidade": 0.5,
            "sugestao": "a pergunta não recebe os campos que determinam a resposta; reescrever critérios ou dividir por situação"}


def s_estagnacao(s, now):
    p = _kv(s, "progresso", {}) or {}
    sem = int(p.get("sem", 0))
    if sem < ESTAGNADO:
        return None
    t = detectar_travamento(p.get("eventos") or [])
    nome = f" · padrão {t['padrao']} ({t['ciclos']}x, limiar {t['limiar']})" if t else " · sem padrão nomeado"
    return {"chave": "estagnacao", "titulo": f"{sem} giros seguidos com trabalho pendente e nada avançando{nome}",
            "evidencia": {"giros_sem_avanco": sem, "limiar": ESTAGNADO, "recusas": p.get("recusas") or {}, "parado": parado(s),
                          "pendencias": pendencias(s, p, now), "padrao": t},
            "gravidade": min(1.0, sem / 20),
            "sugestao": "ver recusas do porteiro e a fila"}


def s_missao_sem_ciclo(s, now):
    if not _kv(s, "motor_pronto"):
        return None
    r = s.one("SELECT p.id, p.nome FROM projects p JOIN rubrics r ON r.project_id=p.id WHERE p.kit!='circulo' AND p.status='ativo' "
              "AND COALESCE(p.pausada,0)=0 AND NOT EXISTS (SELECT 1 FROM cycles c WHERE c.project_id=p.id AND c.created_at>=?) LIMIT 1", (now - 86400,))
    if not r:
        return None
    return {"chave": f"missao_sem_ciclo:{r['id']}", "titulo": f"Missão “{r['nome']}” sem nenhum ciclo há 24 h",
            "evidencia": {"missao": r["id"]}, "gravidade": 0.5, "sugestao": "evoluir_projeto não está sendo escolhido ou o porteiro recusa project_cycle"}


def s_claude_code_limite(s, now):
    e = _kv(s, "self_dev_espera", {}) or {}
    ate = float(e.get("ate", 0))
    if ate <= now:
        return None
    return {"chave": "claude_code_limite", "titulo": f"Developer parado até {time.strftime('%H:%M', time.localtime(ate))}: {e.get('motivo', 'limite')}",
            "evidencia": {"ate": ate, "motivo": e.get("motivo")}, "gravidade": 0.4, "sugestao": "depende da assinatura do Claude Code; nada a corrigir no código"}


def s_giro_travado(s, now):
    b = _kv(s, "batimento", {}) or {}
    if not b or now - float(b.get("em", 0)) > 60:
        return None                          # loop desligado: o painel já mostra; não é trava de evolução
    et = _kv(s, "etapa", {}) or {}
    if et.get("nome") in (None, "descanso", "pausado") or now - float(et.get("em", now)) < GIRO_TRAVADO:
        return None
    return {"chave": "giro_travado", "titulo": f"Giro {et.get('tick')} parado na etapa “{et.get('nome')}” há {int((now - et['em']) / 60)} min",
            "evidencia": {"etapa": et.get("nome"), "tarefa": et.get("tarefa"), "ha_min": int((now - et["em"]) / 60)}, "gravidade": 0.9,
            "sugestao": "uma etapa sem timeout; o Developer ou uma chamada externa pode estar pendurada"}


def s_orcamento(s, now):
    if _kv(s, "loop_status") != "pausado_orcamento":
        return None
    return {"chave": "orcamento_esgotado", "titulo": "Orçamento do dia esgotado: o loop retoma à meia-noite", "evidencia": {"limite": (_kv(s, "orcamento_limite", {}) or {}).get("limite")},
            "gravidade": 0.5, "sugestao": "subir o limite diário no painel, ou aceitar a pausa"}


def s_consumo_alto(s, now):
    """Modo ilimitado: ninguém corta, mas um dia 2× acima da mediana medida merece um aviso (informativo, não trava)."""
    from .budget import consumo, modo_orcamento
    if modo_orcamento(s) != "ilimitado":
        return None
    c = consumo(s, 8, now)
    if c["mediana_dia"] is None or c["hoje"] < 200_000 or c["hoje"] < 2 * c["mediana_dia"]:
        return None
    return {"chave": "consumo_alto", "titulo": f"Consumo de hoje ({c['hoje']:,} tokens) já é {c['hoje'] / c['mediana_dia']:.1f}× a mediana dos últimos dias ({c['mediana_dia']:,})".replace(",", "."),
            "evidencia": {"hoje": c["hoje"], "mediana_dia": c["mediana_dia"], "por_papel": {k: v["tokens"] for k, v in list(c["por_papel"].items())[:4]}, "base": "medido"},
            "gravidade": 0.4, "sugestao": "ver qual papel puxou o gasto (Consumo de tokens, no painel); nada é cortado no modo ilimitado"}


def s_orcamento_curto(s, now):
    from .budget import modo_orcamento
    if modo_orcamento(s) == "ilimitado":
        return None
    """Há item esperando estudo e o que sobra do orçamento do dia não paga o estudo dele (medido na tabela budget).
    No Mac (19/10, 22 h): 392 mil de 400 mil gastos, estudo completo custando ~33 mil: a evolução parou sem ninguém dizer."""
    item = s.one("SELECT id, titulo, origem, evidencia FROM roadmap WHERE status='pendente' AND estudo IS NULL AND origem IN ('loop','pedido_cassio') "
                 "AND COALESCE(desativado,0)=0 AND evidencia NOT LIKE '%depende de você%' ORDER BY ordem LIMIT 1")
    if not item:
        return None
    from datetime import datetime
    from .budget import TZ
    from .estudo import MODOS, modo_do_estudo
    modo = modo_do_estudo(dict(item))
    if modo == "dispensado":
        return None
    from .orcamento_dia import limite_hoje
    limite = limite_hoje(s)
    hoje = datetime.fromtimestamp(now, TZ).date().isoformat()
    r = s.one("SELECT tokens FROM budget WHERE day=?", (hoje,))
    usados = int(r["tokens"] or 0) if r else 0
    xs = sorted(int(x["tokens"] or 0) for x in s.q("SELECT tokens FROM llm_calls WHERE papel='estudo' AND ok=1 AND entrada LIKE ? ORDER BY id DESC LIMIT 8", (f"[{modo}]%",)))
    custo = xs[len(xs) // 2] if len(xs) >= 3 else MODOS[modo]["est"]
    resta = limite - usados
    if resta >= custo:
        return None
    return {"chave": "orcamento_curto", "titulo": f"O orçamento do dia não paga o próximo estudo: restam {resta:,} tokens e o estudo {modo} custa ~{custo:,}".replace(",", "."),
            "evidencia": {"limite": limite, "usados_hoje": usados, "restam": resta, "custo_estudo": custo, "modo": modo, "item": item["id"]},
            "gravidade": 0.7, "sugestao": "subir o limite diário no painel ou esperar a meia-noite; item com evidência interna medida já não gasta estudo"}


SONDAS: list[Callable] = [s_giro_travado, s_pergunta_valida_parada, s_porteiro_recusa, s_developer_parado, s_fila_seca, s_pr_preso,
                          s_corpo_atrasado, s_licao_bloqueia, s_jev_duvida, s_estagnacao, s_missao_sem_ciclo, s_claude_code_limite, s_orcamento,
                          s_orcamento_curto, s_consumo_alto]


def sondar(store, now: float | None = None) -> list[dict]:
    now = now or time.time()
    out = []
    for f in SONDAS:
        try:
            a = f(store, now)
        except Exception:  # noqa: BLE001 — uma sonda quebrada não cala o Vigia
            a = None
        if a:
            a["evidencia"]["base"] = "medido"
            out.append(a)
    return out


# ------------------------------------------------------------------ Jev classifica os achados novos
def classificar(dl, achados: list[dict]) -> list[dict]:
    if not achados:
        return []
    qs = {}
    for i in range(len(achados)):
        qs[f"vigia_trava_{i}"] = Question(
            "noul", f"O achado `achados.{i}.titulo` é uma trava real da autoevolução do loop agora?",
            SN(f"a evidência medida (`achados.{i}.evidencia`) mostra trabalho que deveria estar andando e não anda: pergunta validada sem item, "
               "item pronto sem Developer, PR sem merge, corpo atrás do GitHub, giro parado",
               "é só espera normal do ritmo (minutos), depende do humano ou do ambiente e o loop já avisou, ou os números são pequenos demais"))
        qs[f"vigia_acao_{i}"] = Question("choice", f"O que o loop deve fazer com o achado `achados.{i}.titulo`?", dict(ACOES))
    state = {"achados": [{"titulo": a["titulo"], "evidencia": a["evidencia"], "gravidade": a["gravidade"], "sugestao": a["sugestao"]} for a in achados]}
    out = dl.ask_many(state, qs)
    res = []
    for i, a in enumerate(achados):
        t, ac = out[f"vigia_trava_{i}"], out[f"vigia_acao_{i}"]
        conf = min(t.confidence, ac.confidence)
        duvida = t.source == "local" and getattr(dl.jev, "source", "") == "jev"
        trava = float(t.value) >= 0.5
        if duvida or conf < 0.25:
            acao, veredito = "observar", "em_duvida"          # o Jev não soube: observa e pergunta de novo depois
        elif not trava:
            acao, veredito = "ignorar", "nao_trava"
        elif conf >= CONF_AGIR:
            acao, veredito = str(ac.value), "trava"           # confiança alta: faz o que o Jev escolheu
        else:
            acao, veredito = ("alertar" if ac.value == "abrir_item" else str(ac.value)), "trava"   # média: no máximo alerta
        res.append({**a, "veredito": veredito, "acao": acao, "conf": round(conf, 3), "p_trava": round(float(t.value), 3),
                    "classificacao": {"trava": {"p": round(float(t.value), 3), "conf": round(t.confidence, 3), "fonte": t.source},
                                      "acao": {"valor": str(ac.value), "conf": round(ac.confidence, 3), "probs": dict(ac.probabilities or {})}}})
    return res


def regra(jev, qid: str, q: Question, state) -> Decision:
    """A regra local (LocalJev) quando o Jev está em dúvida ou nos testes: a gravidade medida decide."""
    tipo, i = qid.split("_")[1], int(qid.rsplit("_", 1)[1])
    achs = state.get("achados") or []
    a = achs[i] if i < len(achs) else {}
    g = float(a.get("gravidade", 0))
    if tipo == "trava":
        return jev._noul(qid, min(0.95, 0.3 + g * 0.7))
    sug = norm(str(a.get("sugestao", "")))
    humano = bool(re.search(r"depende|assinatura|aceitar a pausa|meia-noite", sug))
    v = "alertar" if humano or g < 0.7 else "abrir_item"
    if g < 0.4:
        v = "observar"
    return Decision(qid, "choice", v if v in q.options() else q.options()[-1], 0.6, jev.source)


# ------------------------------------------------------------------ o agente
class Vigia:
    def __init__(self, ctx, intervalo: float = INTERVALO):
        self.ctx, self.s, self.intervalo = ctx, ctx.store, intervalo
        self.planejador = None           # o loop liga o Planejador: sem ele, a trava de pergunta só é alertada
        from . import conexoes
        from .medico import Medico
        self.medico = Medico(ctx)        # o plano de controle roda na mesma thread, depois das travas
        conexoes.instalar(self.s)        # cada chamada ao GitHub vira um pulso na faixa de conexões
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _registrar_erro(self, exc: BaseException) -> None:
        try:
            self.s.set("vigia_erro", {"em": time.time(), "erro": repr(exc)[:300], "seguidos": int((self.s.get("vigia_erro") or {}).get("seguidos", 0)) + 1})
        except (sqlite3.Error, OSError, ValueError):
            pass

    # --- uma passagem
    def rodar(self, now: float | None = None) -> dict:
        now = now or time.time()
        self._recusada_pelo_porteiro(now)
        achados = sondar(self.s, now)
        drenou = self._drenar(achados, now)
        abertas = {r["chave"]: dict(r) for r in self.s.q("SELECT * FROM vigia WHERE status='aberta'")}
        novos = [a for a in achados if a["chave"] not in abertas or abertas[a["chave"]]["veredito"] == "em_duvida"]
        try:
            classificados = classificar(self.ctx.dl, novos)
        except Exception as exc:  # noqa: BLE001 — sem Jev, registra como dúvida e segue
            classificados = [{**a, "veredito": "em_duvida", "acao": "observar", "conf": 0.0, "p_trava": None, "classificacao": {"erro": str(exc)[:200]}} for a in novos]
        agiu, resolvidas = [], []
        marcas = self.s.get("vigia_agiu") or {}
        for c in classificados:
            self._registrar(c, abertas.get(c["chave"]), now)
            if c["acao"] in ("abrir_item", "alertar") and (abertas.get(c["chave"]) or {}).get("acao") not in ("abrir_item", "alertar"):
                self._agir(c, now)
                agiu.append(c["chave"])
                marcas[c["chave"]] = now
        # trava que segue aberta REAGIR depois da ação, sem item em andamento: age de novo com a evidência de agora
        # (no Mac uma trava ficou 13 h aberta, 777 passagens, sem nova ação: o item que abrira já estava feito)
        por_chave = {a["chave"]: a for a in achados}
        for chave, r in abertas.items():
            if chave in agiu or chave not in por_chave or r["acao"] not in ("abrir_item", "alertar"):
                continue
            if now - float(marcas.get(chave, r["primeira_em"])) < REAGIR:
                continue
            if r["item_id"] and self.s.one("SELECT 1 FROM roadmap WHERE id=? AND status IN ('pendente','em_andamento')", (r["item_id"],)):
                continue
            self._agir({**r, **por_chave[chave], "acao": r["acao"], "conf": float(r["conf"] or 0)}, now)
            agiu.append(chave)
            marcas[chave] = now
        if agiu:
            self.s.set("vigia_agiu", marcas)
        vistos = {a["chave"] for a in achados}
        for chave, r in abertas.items():
            if chave in vistos:
                self.s.x("UPDATE vigia SET ultima_em=?, vezes=vezes+1 WHERE id=?", (now, r["id"]))
            else:
                self.s.x("UPDATE vigia SET status='resolvida', resolvida_em=? WHERE id=?", (now, r["id"]))
                resolvidas.append(chave)
                if r["acao"] in ("abrir_item", "alertar"):
                    self.ctx.reply(f"Vigia: resolvido — {r['titulo']} (durou {int((now - r['primeira_em']) / 60)} min).", "saude")
        self.s.set("vigia_ultima", {"em": now, "achados": len(achados), "abertas": len([a for a in achados]), "agiu": agiu})
        medico = self.medico.rodar(now)
        from . import higiene
        higiene.rodar(self.s, now)                               # expira "depende de você", encurta títulos, une lições iguais
        from . import capacidade
        cap = capacidade.rodar(self.s, self.ctx.dl, now)        # quem está sobrecarregado; sobe/desce trabalhadores
        from . import graft
        from .memoria import do_ctx
        mem = do_ctx(self.ctx)
        if mem is not None and mem.graft:
            mem.espelhar_pendentes()                                 # linhas antigas ganham nó no Graft, 50 por passagem
            graft.manter(self.s, now)                                # apply-safe a cada 6 h; duplicata do mesmo registro resolvida
        from . import autonomia, daily, garimpo, gasto_cursor, norte, pastas, sentinela, skills, trabalho
        sentinela.checar(self.s, self.ctx.reply, now)                # fila pronta e nada entrou na main há 4 h: avisa você
        daily.checar(self.s, self.ctx.data_dir, self.ctx.reply, now)  # 8 h: pauta da daily por assunto, das suas notas
        gasto_cursor.avisar(self.s, self.ctx.reply)                  # uma vez por dia: os US$ do Cursor acabam antes do fim do mês?
        pastas.manter(self.s, pastas.raiz(self.ctx.data_dir))        # pastas padrão por assunto, espelhando o console
        trabalho.semear_se_pedido(self.s, self.ctx.data_dir, self.ctx.reply)   # CIRCULO_EXEMPLO=1: o exemplo da tela, uma vez
        autonomia.rodar(self.s, now)                                  # nada espera humano: decisão padrão com prazo (31/10)
        if garimpo.devido(self.s, now):                               # 1×/dia: varre o GitHub pelo que o loop precisa agora
            repo_dir = os.environ.get("CIRCULO_REPO_DIR")
            if repo_dir:                                               # … e pede a instalação de até 3 skills do catálogo
                skills.pedir_instalacao(self.s, repo_dir, now)
            with contextlib.suppress(Exception):
                garimpo.garimpar(self.s, now, reply=self.ctx.reply, dl=self.ctx.dl)
        if os.environ.get("CIRCULO_REPO_DIR"):                       # 01/11: absorção (ADR por repo), escudo das skills, ranking diário
            from . import absorcao
            with contextlib.suppress(Exception):
                absorcao.rodar(self.s, now, data_dir=self.ctx.data_dir, repo_dir=os.environ["CIRCULO_REPO_DIR"], dl=self.ctx.dl, reply=self.ctx.reply)
        from . import alavancas, experimentos, praticas
        experimentos.avaliar(self.s, self.ctx.reply, now)           # janela vencida: melhorou/neutro/piorou/inconclusivo
        alavancas.girar(self.s, self.ctx.reply, now)                # uma alavanca de economia por vez, com guarda de qualidade
        praticas.retrospectivo(self.s, now, os.environ.get("CIRCULO_REPO_DIR"), self.ctx.reply)   # 1×/dia: até 3 práticas
        norte.cobrar(self.s, self.ctx.reply, now)                    # prazo de 2 dias do Norte: evoluiu ou a solução é reescrita
        from . import conta
        try:
            conta.vigiar(self.s, self.ctx.reply, now)              # assinatura: sessão do Claude de pé, relogin quando cai
        except (OSError, ValueError) as exc:
            self.s.set("conta_sessao_erro", {"em": now, "erro": str(exc)[:200]})
        return {"achados": len(achados), "novos": len(novos), "agiu": agiu, "resolvidas": resolvidas, "drenou": drenou, "medico": medico,
                "capacidade": {"gargalo": (cap["gargalo"] or {}).get("agente"), "acoes": cap["acoes"]}}

    def _drenar(self, achados: list[dict], now: float) -> dict | None:
        """Trava de pergunta validada além de DRENAR: o planejador responde só a mais antiga ainda não tentada, uma por
        passagem. A falha fica registrada e a próxima passagem tenta outra; DISJUNTOR falhas seguidas pausam a drenagem
        por REAGIR (falha sistêmica: a quarentena do planejador não deve engolir a fila inteira)."""
        if self.planejador is None or "pergunta_valida_parada" not in {a["chave"] for a in achados}:
            return None
        d = self.s.get(DRENAGEM) or {}
        if float(d.get("pausa_ate", 0)) > now:
            return None
        velhas = [r["id"] for r in self.s.q("SELECT id FROM perguntas WHERE cerebro='loop' AND status='valida' AND created_at<=? "
                                            "ORDER BY created_at, id", (now - DRENAR,))]
        tentadas = [p for p in d.get("tentadas", []) if p in velhas]
        pid = next((p for p in velhas if p not in tentadas), None)
        if pid is None:
            return None
        antes = (self.s.get(TENTATIVAS) or {}).get("ultima")
        seguro(self.planejador.run, autorizado=True, pergunta_id=pid)   # a falha classificada fica no registro do planejador
        u = (self.s.get(TENTATIVAS) or {}).get("ultima") or {}
        if u == (antes or {}) or u.get("pergunta_id") != pid:
            u = {"desfecho": "sem_registro", "motivo": "o planejador não registrou a tentativa"}
        falhas = 0 if u["desfecho"] in PROGRESSO else int(d.get("falhas_seguidas", 0)) + 1
        rec = {"em": now, "pergunta_id": pid, "desfecho": u["desfecho"], "motivo": str(u.get("motivo", ""))[:300]}
        pausa = now + REAGIR if falhas >= DISJUNTOR else 0
        self.s.set(DRENAGEM, {"tentadas": [*tentadas, pid], "falhas_seguidas": 0 if pausa else falhas, "pausa_ate": pausa, "ultima": rec})
        if pausa:
            self.ctx.reply(f"Vigia: drenagem pausada por {int(REAGIR / 60)} min: {DISJUNTOR} tentativas seguidas do planejador "
                           f"sem item (última, pergunta #{pid}: {rec['motivo'][:140]})", "saude")
        return rec

    def _recusada_pelo_porteiro(self, now: float) -> None:
        """A mesma pergunta recusada RECUSAS_PORTEIRO vezes seguidas pelo mesmo motivo sai da fila (não trava as outras
        nem repete o alerta) e vira um item de revisão do limiar, com o registro medido."""
        u = (self.s.get(PORTEIRO) or {}).get("ultimo") or {}
        if u.get("decisao") != "recusou" or not u.get("pergunta_id") or int(u.get("seguidas", 0)) < RECUSAS_PORTEIRO:
            return
        if not self.s.run("UPDATE perguntas SET status='recusada_porteiro', updated_at=? WHERE id=? AND status='valida'", (now, u["pergunta_id"])):
            return
        causa = _causa_porteiro(u)
        titulo = f"Vigia: revisar o limiar worth_spending.idle_evolution: pergunta #{u['pergunta_id']} recusada {u['seguidas']}x ({u['motivo']})"
        if not self.s.one("SELECT id FROM roadmap WHERE status IN ('pendente','em_andamento') AND titulo LIKE 'Vigia: revisar o limiar%'"):
            detalhe = f"A pergunta saiu da fila como 'recusada pelo porteiro'.\nEvidência (medida): {json.dumps(u, ensure_ascii=False, default=str)}\nCausa: {causa}"
            roadmap.gravar_medido(self.s, "vigia", "porteiro_recusa_pergunta", titulo[:200], detalhe,
                                  f"Vigia (medido): porteiro_recusa_pergunta:{u['pergunta_id']}")
        self.ctx.reply(f"Vigia: pergunta #{u['pergunta_id']} recusada pelo porteiro. {causa[:160]}", "saude")

    def _registrar(self, c: dict, antes: dict | None, now: float) -> None:
        ev = json.dumps(c["evidencia"], ensure_ascii=False, default=str)
        cls = json.dumps(c["classificacao"], ensure_ascii=False, default=str)
        if antes:
            self.s.x("UPDATE vigia SET titulo=?, evidencia=?, veredito=?, acao=?, conf=?, classificacao=?, ultima_em=?, vezes=vezes+1 WHERE id=?",
                     (c["titulo"][:300], ev, c["veredito"], c["acao"], c["conf"], cls, now, antes["id"]))
        elif c["veredito"] != "nao_trava":
            self.s.x("INSERT INTO vigia(chave,titulo,evidencia,sugestao,gravidade,veredito,acao,conf,classificacao,status,primeira_em,ultima_em,vezes) "
                     "VALUES(?,?,?,?,?,?,?,?,?,'aberta',?,?,1)",
                     (c["chave"], c["titulo"][:300], ev, c["sugestao"][:300], c["gravidade"], c["veredito"], c["acao"], c["conf"], cls, now, now))

    def _agir(self, c: dict, now: float) -> None:
        ev = c["evidencia"] if isinstance(c["evidencia"], str) else json.dumps(c["evidencia"], ensure_ascii=False, default=str)
        padrao = ((c["evidencia"] if isinstance(c["evidencia"], dict) else {}).get("padrao") or {}).get("padrao")
        self.s.x("INSERT INTO vigia_disparos(chave,acao,evidencia,em,giro,padrao) VALUES(?,?,?,?,?,?)",
                 (c["chave"], c["acao"], ev, now, self.s.tick, padrao))
        if c["acao"] == "abrir_item":
            titulo = f"Vigia: {c['titulo'][:150]}"
            ja = self.s.one("SELECT id FROM roadmap WHERE status IN ('pendente','em_andamento') AND titulo LIKE ?", (f"Vigia: {c['chave'].split(':')[0]}%",))
            if not ja:
                detalhe = (f"Trava da autoevolução detectada pelo Vigia (Jev: trava com {c['conf']:.0%} de confiança).\n"
                           f"Evidência (medida): {json.dumps(c['evidencia'], ensure_ascii=False, default=str)}\nSugestão: {c['sugestao']}")
                rid = roadmap.gravar_medido(self.s, "vigia", c["chave"], titulo[:200], detalhe, f"Vigia (medido): {c['chave']}")
                self.s.x("UPDATE vigia SET item_id=? WHERE chave=? AND status='aberta'", (rid, c["chave"]))
                self.ctx.reply(f"Vigia: {c['titulo']} → item #{rid} no roteiro. {c['sugestao'][:140]}", "saude")
                return
        self.ctx.reply(f"Vigia: {c['titulo']}. {c['sugestao'][:160]}", "saude")

    # --- a thread paralela
    def iniciar(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def laco():
            while not self._stop.wait(self.intervalo):
                try:
                    self.rodar()
                    self.s.set("vigia_erro", None)
                except Exception as exc:  # noqa: BLE001 — o Vigia nunca derruba o loop, mas o erro fica visível
                    self._registrar_erro(exc)
        self._thread = threading.Thread(target=laco, name="vigia", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


def disparos_30d(store, chave: str, now: float | None = None) -> int:
    """Quantas vezes o Vigia executou a ação (abrir item ou alertar) para a trava `chave` nos últimos 30 dias."""
    return int(_um(store, "SELECT COUNT(*) FROM vigia_disparos WHERE chave=? AND em>=?", (chave, (now or time.time()) - 30 * 86400)))


def resultado_30d(store, chave: str, now: float | None = None) -> dict[str, Any]:
    """Dos disparos de `chave` nos últimos 30 dias: quantos já têm resultado e a taxa dos que destravaram o loop em até
    EXPIRA_EM giros (alvo ALVO_DESTRAVAR), sobre os disparos fechados. O desfecho é gravado pelo loop (estagnacao.medir_disparos)."""
    r = store.one("SELECT COUNT(*) n, COUNT(resultado) com, COALESCE(SUM(resultado='destravou'), 0) d FROM vigia_disparos "
                  "WHERE chave=? AND em>=?", (chave, (now or time.time()) - 30 * 86400))
    return {"disparos": r["n"], "com_resultado": r["com"], "destravou": r["d"],
            "taxa_destravou": round(r["d"] / r["com"], 2) if r["com"] else None, "em_giros": EXPIRA_EM, "alvo": ALVO_DESTRAVAR}


def padrao_7d(store, chave: str, now: float | None = None) -> dict[str, Any]:
    """Dos disparos de `chave` nos últimos 7 dias, a fração com o padrão de travamento nomeado (alvo ALVO_PADRAO)."""
    r = store.one("SELECT COUNT(*) n, COUNT(padrao) p FROM vigia_disparos WHERE chave=? AND em>=?", (chave, (now or time.time()) - 7 * 86400))
    return {"disparos": r["n"], "com_padrao": r["p"], "fracao": round(r["p"] / r["n"], 2) if r["n"] else None, "alvo": ALVO_PADRAO}


def resumo(store, limite: int = 20) -> dict[str, Any]:
    abertas = [dict(r) for r in store.q("SELECT * FROM vigia WHERE status='aberta' ORDER BY gravidade DESC, primeira_em")]
    hist = [dict(r) for r in store.q("SELECT id, chave, titulo, veredito, acao, conf, item_id, primeira_em, resolvida_em FROM vigia "
                                     "WHERE status='resolvida' ORDER BY resolvida_em DESC LIMIT ?", (limite,))]
    for a in abertas:
        for k in ("evidencia", "classificacao"):
            try:
                a[k] = json.loads(a[k]) if a[k] else None
            except (TypeError, ValueError):
                pass
    ult = store.get("vigia_ultima") or {}
    travas = [a for a in abertas if a["veredito"] == "trava"]
    return {"estado": "travado" if travas else ("observando" if abertas else "livre"), "travas": len(travas), "abertas": abertas,
            "resolvidas": hist, "ultima_em": ult.get("em"), "sondas": [f.__name__[2:] for f in SONDAS], "intervalo_s": INTERVALO,
            "disparos_30d": {"estagnacao": disparos_30d(store, "estagnacao")}, "resultado_30d": {"estagnacao": resultado_30d(store, "estagnacao")},
            "padrao_7d": {"estagnacao": padrao_7d(store, "estagnacao")}}

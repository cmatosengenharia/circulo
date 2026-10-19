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

import json
import re
import threading
import time
from typing import Any, Callable

from .decision import SN, Decision, Question, norm
from .planejador import ESPERA, GATE, MAX_TENTATIVAS, PORTEIRO, TENTATIVAS

INTERVALO = 60                   # segundos entre passagens da thread
ESPERA_PERGUNTA = 30 * 60        # pergunta validada esperando mais que isso = trava
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


def _um(s, sql, args=()):
    r = s.one(sql, args)
    return (r[0] if r is not None else 0) or 0


def _kv(s, k, default=None):
    return s.get(k) or default


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


def s_pergunta_valida_parada(s, now):
    r = s.one("SELECT COUNT(*) n, MIN(created_at) em FROM perguntas WHERE status='valida'")
    # a idade só cresce: acima do limite agora e na verificação anterior (INTERVALO atrás) = 2 verificações seguidas
    if not r["n"] or now - float(r["em"] or now) < ESPERA_PERGUNTA + INTERVALO:
        return None
    plan = float((_kv(s, "planejador", {}) or {}).get("em", 0))
    u = (_kv(s, PORTEIRO, {}) or {}).get("ultimo") or {}
    gate = _kv(s, GATE, {}) or {}
    motivo = gate.get("motivo") if now - float(gate.get("em", 0) or 0) < 30 * 60 else None
    tent = _kv(s, TENTATIVAS, {}) or {}
    ult = tent.get("ultima")
    if motivo and motivo.startswith(ESPERA):
        motivo = None                        # o planejador roda a cada intervalo: a causa está no resultado da tentativa
    causa = (f"o planejador não planeja: {motivo}" if motivo else _causa_tentativa(ult, now) if ult else _causa_porteiro(u))
    progresso = tent.get("ultimo_progresso_em")
    sem_progresso = int((now - float(progresso)) / 60) if progresso else None
    return {"chave": "pergunta_valida_parada", "titulo": f"{r['n']} pergunta(s) validada(s) pelo Jev esperando há {int((now - r['em']) / 60)} min sem virar item "
                                                         f"(último progresso {f'há {sem_progresso} min' if sem_progresso is not None else 'nunca medido'})",
            "evidencia": {"perguntas_validas": r["n"], "esperando_min": int((now - r["em"]) / 60), "sem_progresso_min": sem_progresso,
                          "planejador_rodou_ha_min": int((now - plan) / 60) if plan else None,
                          "porteiro": u or None, "planejador_motivo": motivo, "ultima_tentativa": ult},
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
    aberto = _kv(s, "self_dev_aberto", {}) or {}
    if aberto.get("pr") and not aberto.get("fechado"):
        return None
    item = s.one("SELECT id, titulo FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 AND estudo IS NOT NULL "
                 "AND evidencia NOT LIKE '%depende de você%' AND origem IN ('pedido_cassio','loop','erro') ORDER BY ordem LIMIT 1")
    if not item:
        return None
    ult = _um(s, "SELECT MAX(em) FROM trail WHERE etapa='developer' OR tarefa='corrigir_codigo'")
    if now - ult < DEV_PARADO:
        return None
    return {"chave": "developer_parado", "titulo": f"Item #{item['id']} pronto para o Developer há mais de {int((now - ult) / 60)} min e ele não pegou",
            "evidencia": {"item": item["id"], "titulo": item["titulo"][:100], "developer_ultimo_ha_min": int((now - ult) / 60)},
            "gravidade": 0.7, "sugestao": "ver se corrigir_codigo está sendo escolhido no giro e se o porteiro o recusa"}


def s_fila_seca(s, now):
    pend = _um(s, "SELECT COUNT(*) FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 AND origem IN ('pedido_cassio','loop','erro')")
    val = _um(s, "SELECT COUNT(*) FROM perguntas WHERE status='valida'")
    plan = float((_kv(s, "planejador", {}) or {}).get("em", 0))
    aberto = _kv(s, "self_dev_aberto", {}) or {}
    ocupado = bool(aberto.get("pr") and not aberto.get("fechado"))
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
    r = s.one("SELECT COUNT(*) n, MIN(created_at) em FROM licoes WHERE classe='estrutural' AND status IN ('aberta','em_correcao','reincidente')")
    if not r["n"] or now - float(r["em"] or now) < LICAO_BLOQUEIA:
        return None
    return {"chave": "licao_bloqueia", "titulo": f"{r['n']} lição(ões) de estrutura aberta(s) há {int((now - r['em']) / 3600)} h bloqueando a evolução",
            "evidencia": {"licoes": r["n"], "ha_horas": round((now - r["em"]) / 3600, 1)}, "gravidade": 0.8,
            "sugestao": "o Developer precisa corrigir a lição antes de qualquer evolução; ver por que o item dela não anda"}


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
    if sem < 10:
        return None
    return {"chave": "estagnacao", "titulo": f"{sem} giros seguidos com trabalho pendente e nada avançando",
            "evidencia": {"giros_sem_avanco": sem, "recusas": p.get("recusas") or {}}, "gravidade": min(1.0, sem / 20), "sugestao": "ver recusas do porteiro e a fila"}


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


SONDAS: list[Callable] = [s_giro_travado, s_pergunta_valida_parada, s_porteiro_recusa, s_developer_parado, s_fila_seca, s_pr_preso,
                          s_corpo_atrasado, s_licao_bloqueia, s_jev_duvida, s_estagnacao, s_missao_sem_ciclo, s_claude_code_limite, s_orcamento]


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
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- uma passagem
    def rodar(self, now: float | None = None) -> dict:
        now = now or time.time()
        self._recusada_pelo_porteiro(now)
        achados = sondar(self.s, now)
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
        return {"achados": len(achados), "novos": len(novos), "agiu": agiu, "resolvidas": resolvidas}

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
            ordem = (self.s.one("SELECT COALESCE(MAX(ordem),0) m FROM roadmap")["m"] or 0) + 1
            detalhe = f"A pergunta saiu da fila como 'recusada pelo porteiro'.\nEvidência (medida): {json.dumps(u, ensure_ascii=False, default=str)}\nCausa: {causa}"
            self.s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                     (titulo[:200], detalhe[:2000], "loop", "pendente", f"Vigia (medido): porteiro_recusa_pergunta:{u['pergunta_id']}", ordem, now, now))
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
        if c["acao"] == "abrir_item":
            titulo = f"Vigia: {c['titulo'][:150]}"
            ja = self.s.one("SELECT id FROM roadmap WHERE status IN ('pendente','em_andamento') AND titulo LIKE ?", (f"Vigia: {c['chave'].split(':')[0]}%",))
            if not ja:
                ordem = (self.s.one("SELECT COALESCE(MAX(ordem),0) m FROM roadmap")["m"] or 0) + 1
                detalhe = (f"Trava da autoevolução detectada pelo Vigia (Jev: trava com {c['conf']:.0%} de confiança).\n"
                           f"Evidência (medida): {json.dumps(c['evidencia'], ensure_ascii=False, default=str)}\nSugestão: {c['sugestao']}")
                rid = self.s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                               (titulo[:200], detalhe[:2000], "loop", "pendente", f"Vigia (medido): {c['chave']}", ordem, now, now))
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
                except Exception:  # noqa: BLE001 — o Vigia nunca derruba o loop
                    pass
        self._thread = threading.Thread(target=laco, name="vigia", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


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
            "resolvidas": hist, "ultima_em": ult.get("em"), "sondas": [f.__name__[2:] for f in SONDAS], "intervalo_s": INTERVALO}

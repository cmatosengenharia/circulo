"""O Médico do loop: plano de controle que diagnostica gargalos por PADRÃO medido e responde pela escada mais barata.

Para não virar ruído (as oito regras acordadas):
1. uma fonte só: `incidents`, `run_errors`, `trail`, `llm_calls`, `prs`, `alerts` — toda frase tem uma consulta;
2. padrão, não evento: ≥ MIN_VEZES ocorrências da mesma chave em JANELA; fecha só depois de SILENCIO sem ocorrência;
3. impressão digital: chave única por causa; aberta, só conta `vezes`; nunca um segundo diagnóstico igual;
4. o Jev decide (bloqueia? de quem é? remédio seguro?) com a evidência medida; em dúvida, só observa;
5. escada: observar → conter (determinístico, custo zero) → corrigir (item urgente, pela fila do Desenvolvedor,
   com o porteiro do gasto) → escalar (Precisa de você);
6. orçamento: no máximo ACOES_POR_DIA ações e 1 item urgente em voo;
7. autoexclusão: não trata o que é sobre si mesmo nem sobre a constituição (vai para você); fecha pelo sintoma;
8. é medido: precisão, falsos alarmes e tempo até conter ficam no painel e viram pergunta do Product owner.
Supressão de contexto conhecido: Desenvolvedor deslogado, loop pausado por você ou orçamento no limite não geram
diagnóstico de "fila parada" — a causa já está em Precisa de você.

Roda na thread do SRE (em paralelo ao giro), uma passagem por minuto.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from .state import Store

JANELA = 3600.0
MIN_VEZES = 3
SILENCIO = 1800.0
ACOES_POR_DIA = 6
MUDO_MS = 2000
NAO_TOCA = ("medico", "vigia", "merge_gate", "policy", "budget", "guardrails", "self_dev", "corpo")
DONOS = {"codigo_do_loop": "a causa está no código do próprio loop: uma exceção, um laço ou uma regra errada que um PR corrige",
         "ambiente": "a causa é externa ao código: rede, GitHub fora, CI lento, disco, sessão de uma ferramenta expirada",
         "humano": "só uma pessoa resolve: login, chave, aprovação, orçamento, decisão de produto",
         "custo": "o loop está certo, só está caro ou lento por desenho: vale observar, não corrigir"}
REMEDIO = ("observar: contar e medir mais, nada a fazer ainda",
           "conter: pausar a tarefa que repete ou segurar a versão, sem mexer em código",
           "corrigir: abrir item urgente para o Desenvolvedor, com o trace, antes da fila normal")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS diagnosticos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chave TEXT NOT NULL UNIQUE,
  tipo TEXT NOT NULL,             -- erro_repetido | repeticao_sem_progresso | agente_mudo
  titulo TEXT NOT NULL,
  evidencia TEXT NOT NULL,        -- JSON medido
  vezes INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL,           -- observando | contido | corrigindo | escalado | fechado
  veredito TEXT,                  -- JSON: bloqueia, dono, remedio, conf, fonte
  acao TEXT,
  item_id INTEGER,
  primeira_em REAL NOT NULL,
  ultima_em REAL NOT NULL,
  fechado_em REAL,
  reaberturas INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS medico_acoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  diagnostico_id INTEGER NOT NULL,
  acao TEXT NOT NULL,
  detalhe TEXT,
  created_at REAL NOT NULL
);
"""


def _tabela(store: Store, nome: str) -> bool:
    return bool(store.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nome,)))


def _norm(s: str) -> str:
    s = re.sub(r"\d+", "N", (s or "")[:160].lower())
    return re.sub(r"\s+", " ", s).strip()


# ------------------------------------------------------------------ sondas: padrões, não eventos
def s_erro_repetido(store: Store, now: float) -> list[dict]:
    out = []
    if not _tabela(store, "incidents"):
        return out
    for r in store.q("SELECT id, stage, kind, message, count, first_seen, last_seen FROM incidents WHERE status!='resolvido' AND last_seen>=?", (now - JANELA,)):
        recentes = store.one("SELECT COUNT(*) n FROM run_errors WHERE incident_id=? AND em>=?", (r["id"], now - JANELA))["n"] if _tabela(store, "run_errors") else r["count"]
        if int(recentes or 0) < MIN_VEZES:
            continue
        out.append({"chave": f"erro:{r['stage']}:{_norm(r['kind'])}", "tipo": "erro_repetido",
                    "titulo": f"{r['kind']} em {r['stage']} repetiu {recentes}× na última hora",
                    "evidencia": {"incidente": r["id"], "etapa": r["stage"], "classe": r["kind"], "mensagem": (r["message"] or "")[:200],
                                  "vezes_1h": int(recentes), "total": r["count"], "desde": r["first_seen"], "base": "medido"},
                    "gravidade": min(1.0, 0.5 + 0.1 * int(recentes))})
    return out


def s_repeticao_sem_progresso(store: Store, now: float) -> list[dict]:
    out = []
    if _tabela(store, "prs"):
        for r in store.q("SELECT substr(branch, 1, instr(substr(branch, 9), '-') + 8) pref, COUNT(*) n, GROUP_CONCAT(number) ns FROM prs "
                         "WHERE created_at>=? AND branch LIKE 'circulo/%' GROUP BY pref HAVING n>=?", (now - JANELA, MIN_VEZES)):
            out.append({"chave": f"repete:pr:{r['pref']}", "tipo": "repeticao_sem_progresso",
                        "titulo": f"{r['n']} PRs seguidos da mesma origem ({r['pref']}…) em 1 h",
                        "evidencia": {"prefixo": r["pref"], "prs": [int(x) for x in str(r["ns"]).split(",")], "tarefa": "documentar" if "docs-" in str(r["pref"]) else "corrigir_codigo", "base": "medido"},
                        "gravidade": 0.6})
    if _tabela(store, "alerts"):
        for r in store.q("SELECT message, COUNT(*) n FROM alerts WHERE created_at>=? AND kind='saude' AND message LIKE 'Developer: %→%' "
                         "GROUP BY substr(message, 1, instr(message, '→')) HAVING n>=?", (now - JANELA, MIN_VEZES)):
            titulo = re.search(r"“(.+?)”", r["message"] or "")
            out.append({"chave": f"repete:item:{_norm(titulo.group(1) if titulo else r['message'][:60])}", "tipo": "repeticao_sem_progresso",
                        "titulo": f"O Desenvolvedor tentou “{(titulo.group(1) if titulo else '?')[:70]}” {r['n']}× em 1 h sem avançar",
                        "evidencia": {"item_titulo": titulo.group(1) if titulo else None, "tentativas_1h": int(r["n"]), "ultima": (r["message"] or "")[:200], "base": "medido"},
                        "gravidade": 0.7})
    return out


def s_agente_mudo(store: Store, now: float) -> list[dict]:
    if not _tabela(store, "llm_calls"):
        return []
    r = store.one("SELECT COUNT(*) n, MAX(erro) e FROM llm_calls WHERE papel='developer' AND ok=0 AND tokens=0 AND COALESCE(duracao_ms, 0)<? AND created_at>=?",
                  (MUDO_MS, now - JANELA))
    if int(r["n"] or 0) < MIN_VEZES:
        return []
    return [{"chave": "mudo:developer", "tipo": "agente_mudo", "titulo": f"O Desenvolvedor respondeu mudo (0 tokens, < 2 s, erro) {r['n']}× em 1 h",
             "evidencia": {"vezes_1h": int(r["n"]), "erro": (r["e"] or "")[:200], "base": "medido"}, "gravidade": 0.8}]


SONDAS = (s_erro_repetido, s_repeticao_sem_progresso, s_agente_mudo)


def contexto_conhecido(store: Store, now: float) -> str | None:
    """Causa já conhecida e já em Precisa de você: não vira diagnóstico de fila parada."""
    esp = store.get("self_dev_espera") or {}
    if esp.get("precisa_de_voce") and float(esp.get("ate", 0)) > now:
        return "desenvolvedor_parado_por_voce"
    if (store.get("controle") or {}).get("pausado"):
        return "loop_pausado_por_voce"
    if store.get("loop_status") == "pausado_orcamento":
        return "orcamento_no_limite"
    return None


def sondar(store: Store, now: float | None = None) -> list[dict]:
    now = now or time.time()
    achados: list[dict] = []
    for f in SONDAS:
        achados += f(store, now)
    conhecido = contexto_conhecido(store, now)
    if conhecido:
        achados = [a for a in achados if a["tipo"] == "erro_repetido"]       # o resto já tem causa e dono
    # autoexclusão: o que é sobre o Médico/SRE/constituição vai para você, não para o Médico
    for a in achados:
        texto = json.dumps(a["evidencia"], ensure_ascii=False).lower()
        a["proprio"] = any(f"{m}.py" in texto or f"/{m}" in texto for m in NAO_TOCA)
    return achados


# ------------------------------------------------------------------ o Jev decide
def classificar(dl, achados: list[dict]) -> list[dict]:
    if not achados:
        return []
    from .decision import SN, Question
    qs, estado = {}, {"achados": [{"titulo": a["titulo"], "tipo": a["tipo"], "evidencia": a["evidencia"]} for a in achados]}
    for i in range(len(achados)):
        qs[f"medico_bloqueia_{i}"] = Question("noul", f"Finding `achados.{i}.titulo` (evidence `achados.{i}.evidencia`) is blocking the loop's progress right now.",
                                              SN("the pattern stops items, PRs or stages from advancing, or repeats the same failed work",
                                                 "the loop keeps delivering despite it; it is cosmetic, rare, or already explained"))
        qs[f"medico_dono_{i}"] = Question("choice", f"Who owns the cause of `achados.{i}.titulo`, given `achados.{i}.evidencia`?", dict(DONOS))
        qs[f"medico_remedio_{i}"] = Question("score", f"What is the safe response to `achados.{i}.titulo` now?", REMEDIO)
    out = dl.ask_many(estado, qs)
    res = []
    for i, a in enumerate(achados):
        b, d, r = out[f"medico_bloqueia_{i}"], out[f"medico_dono_{i}"], out[f"medico_remedio_{i}"]
        duvida = any(x.source == "local" for x in (b, d, r)) and getattr(dl.jev, "source", "") == "jev"
        res.append({**a, "veredito": {"bloqueia": float(b.value) >= 0.5, "p_bloqueia": round(float(b.value), 3), "dono": str(d.value), "conf_dono": round(float(d.confidence), 3),
                                      "remedio": int(float(r.value)), "fonte": "duvida" if duvida else b.source}})
    return res


def decidir(a: dict) -> str:
    """A escada: observar → conter → corrigir → escalar. Dúvida observa; o que é sobre si mesmo escala."""
    v = a["veredito"]
    if a.get("proprio"):
        return "escalar"
    if v["fonte"] == "duvida":
        return "observar"
    if v["dono"] == "humano" or (v["dono"] == "ambiente" and v["bloqueia"]):
        return "escalar"
    if v["dono"] == "custo" or not v["bloqueia"]:
        return "observar"
    if v["remedio"] >= 2 and a["tipo"] in ("erro_repetido", "repeticao_sem_progresso"):
        return "corrigir"
    return "conter" if v["remedio"] >= 1 else "observar"


# ------------------------------------------------------------------ remédios (determinísticos, idempotentes)
class Medico:
    def __init__(self, ctx):
        self.ctx, self.s = ctx, ctx.store
        self.s.db.executescript(ESQUEMA)

    def _acoes_hoje(self, now: float) -> int:
        return int(self.s.one("SELECT COUNT(*) n FROM medico_acoes WHERE created_at>=? AND acao!='observar'", (now - 86400,))["n"])

    def _registrar_acao(self, did: int, acao: str, detalhe: str, now: float) -> None:
        self.s.x("INSERT INTO medico_acoes(diagnostico_id,acao,detalhe,created_at) VALUES(?,?,?,?)", (did, acao, detalhe[:400], now))

    def conter(self, a: dict, did: int, now: float) -> str:
        ev = a["evidencia"]
        if a["tipo"] == "repeticao_sem_progresso" and ev.get("tarefa"):
            pausas = dict(self.s.get("medico_pausas") or {})
            pausas[ev["tarefa"]] = {"ate": now + 6 * 3600, "motivo": a["titulo"], "diagnostico": did}
            self.s.set("medico_pausas", pausas)
            return f"tarefa {ev['tarefa']} pausada por 6 h"
        if a["tipo"] == "agente_mudo":
            self.s.set("self_dev_espera", {"ate": now + 1800, "motivo": "Desenvolvedor mudo (responde em < 2 s com erro): " + (ev.get("erro") or "")[:120],
                                           "hora": time.strftime("%H:%M", time.localtime(now + 1800)), "precisa_de_voce": True})
            return "Desenvolvedor em espera de 30 min; Precisa de você avisado"
        return "nada a conter neste tipo"

    def corrigir(self, a: dict, did: int, now: float) -> str:
        if self.s.one("SELECT 1 FROM diagnosticos WHERE status='corrigindo' AND id!=? AND item_id IN (SELECT id FROM roadmap WHERE status IN ('pendente','em_andamento'))", (did,)):
            return "já há um item urgente em voo: espera"
        ev = a["evidencia"]
        detalhe = (f"Diagnóstico do Médico (medido): {a['titulo']}.\n\nEvidência: {json.dumps(ev, ensure_ascii=False)[:900]}\n\n"
                   "Corrija a causa, não o sintoma; o diagnóstico fecha sozinho quando o padrão parar por 30 min.")
        ordem = (self.s.one("SELECT COALESCE(MIN(ordem),0) m FROM roadmap")["m"] or 0) - 1
        rid = self.s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                       (f"Urgente: {a['titulo'][:160]}", detalhe[:2000], "erro", "pendente", f"Médico (medido): {a['chave']}", ordem, now, now))
        self.s.x("UPDATE diagnosticos SET item_id=? WHERE id=?", (rid, did))
        return f"item urgente #{rid} aberto na frente da fila"

    def escalar(self, a: dict, did: int, now: float) -> str:
        esc = dict(self.s.get("medico_escalados") or {})
        esc[a["chave"]] = {"titulo": a["titulo"], "dono": a["veredito"]["dono"], "em": now, "diagnostico": did, "evidencia": a["evidencia"]}
        self.s.set("medico_escalados", esc)
        return f"escalado para você ({a['veredito']['dono']})"

    # --- uma passagem
    def rodar(self, now: float | None = None) -> dict:
        now = now or time.time()
        achados = sondar(self.s, now)
        abertos = {r["chave"]: dict(r) for r in self.s.q("SELECT * FROM diagnosticos WHERE status!='fechado'")}
        novos = [a for a in achados if a["chave"] not in abertos]
        agiu = []
        for a in classificar(self.ctx.dl, novos):
            acao = decidir(a)
            did = self.s.x("INSERT INTO diagnosticos(chave,tipo,titulo,evidencia,vezes,status,veredito,acao,primeira_em,ultima_em) VALUES(?,?,?,?,1,?,?,?,?,?)",
                           (a["chave"], a["tipo"], a["titulo"][:200], json.dumps(a["evidencia"], ensure_ascii=False), "observando",
                            json.dumps(a["veredito"], ensure_ascii=False), acao, now, now))
            detalhe = "só observando"
            if acao != "observar":
                if self._acoes_hoje(now) >= ACOES_POR_DIA:
                    acao, detalhe = "escalar", "orçamento de ações do dia esgotado: " + self.escalar(a, did, now)
                else:
                    detalhe = {"conter": self.conter, "corrigir": self.corrigir, "escalar": self.escalar}[acao](a, did, now)
                self.s.x("UPDATE diagnosticos SET status=?, acao=? WHERE id=?", ({"conter": "contido", "corrigir": "corrigindo", "escalar": "escalado"}[acao], acao, did))
            self._registrar_acao(did, acao, detalhe, now)
            agiu.append((a["chave"], acao))
            if callable(getattr(self.ctx, "reply", None)):
                self.ctx.reply(f"Médico: {a['titulo']} → {acao} ({detalhe}).", "medico")
        vistos = {a["chave"] for a in achados}
        for chave, r in abertos.items():
            if chave in vistos:
                self.s.x("UPDATE diagnosticos SET vezes=vezes+1, ultima_em=? WHERE id=?", (now, r["id"]))
            elif now - float(r["ultima_em"]) >= SILENCIO:
                self.s.x("UPDATE diagnosticos SET status='fechado', fechado_em=? WHERE id=?", (now, r["id"]))
                self._liberar(r, now)
                if callable(getattr(self.ctx, "reply", None)):
                    self.ctx.reply(f"Médico: fechado pelo sintoma — {r['titulo']} (sem ocorrência há 30 min).", "medico")
        # fechado que volta: reabre com reincidência (e a lição, se houver, sobe de camada por conta própria)
        for a in achados:
            r = self.s.one("SELECT id, reaberturas FROM diagnosticos WHERE chave=? AND status='fechado'", (a["chave"],))
            if r:
                self.s.x("UPDATE diagnosticos SET status='observando', reaberturas=reaberturas+1, ultima_em=?, fechado_em=NULL WHERE id=?", (now, r["id"]))
        return {"achados": len(achados), "novos": len(novos), "agiu": agiu}

    def _liberar(self, r: dict, now: float) -> None:
        pausas = dict(self.s.get("medico_pausas") or {})
        for t, p in list(pausas.items()):
            if p.get("diagnostico") == r["id"]:
                pausas.pop(t)
        self.s.set("medico_pausas", pausas)
        esc = dict(self.s.get("medico_escalados") or {})
        esc.pop(r["chave"], None)
        self.s.set("medico_escalados", esc)


def tarefa_pausada(store: Store, tarefa: str, now: float | None = None) -> bool:
    p = (store.get("medico_pausas") or {}).get(tarefa)
    return bool(p and float(p.get("ate", 0)) > (now or time.time()))


# ------------------------------------------------------------------ medido: a precisão do próprio Médico
def resumo(store: Store) -> dict[str, Any]:
    if not _tabela(store, "diagnosticos"):
        return {"abertos": [], "fechados_24h": 0, "precisao": None, "acoes_24h": 0}
    now = time.time()
    abertos = [dict(r) for r in store.q("SELECT * FROM diagnosticos WHERE status!='fechado' ORDER BY primeira_em DESC LIMIT 20")]
    for a in abertos:
        a["evidencia"], a["veredito"] = json.loads(a["evidencia"]), json.loads(a["veredito"] or "{}")
    corrigidos = store.q("SELECT d.id, r.status FROM diagnosticos d JOIN roadmap r ON r.id=d.item_id WHERE d.acao='corrigir'")
    feitos = sum(1 for r in corrigidos if r["status"] == "feito")
    tot = store.one("SELECT COUNT(*) n, SUM(status='fechado') f, SUM(reaberturas) r FROM diagnosticos")
    acoes = store.one("SELECT COUNT(*) n FROM medico_acoes WHERE created_at>=? AND acao!='observar'", (now - 86400,))["n"]
    contidos = store.q("SELECT d.primeira_em, a.created_at FROM diagnosticos d JOIN medico_acoes a ON a.diagnostico_id=d.id WHERE a.acao IN ('conter','corrigir','escalar')")
    ate_conter = sorted(float(c["created_at"]) - float(c["primeira_em"]) for c in contidos)
    return {"abertos": abertos, "total": int(tot["n"] or 0), "fechados": int(tot["f"] or 0), "reaberturas": int(tot["r"] or 0),
            "corrigidos": {"itens": len(corrigidos), "feitos": feitos},
            "precisao": round(feitos / len(corrigidos), 2) if corrigidos else None,
            "acoes_24h": int(acoes), "orcamento_dia": ACOES_POR_DIA,
            "mediana_s_ate_conter": ate_conter[len(ate_conter) // 2] if ate_conter else None,
            "pausas": store.get("medico_pausas") or {}, "escalados": store.get("medico_escalados") or {}}

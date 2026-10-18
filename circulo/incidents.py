"""Registro de erros e autocorreção em tempo de execução.

Todo erro vira um incidente (agrupado por impressão digital). Erro que se repete numa etapa
isolável faz o círculo colocar a etapa em quarentena — com o Jev decidindo antes — por um número
de giros que dobra a cada reincidência. Incidente que se repete vira item do roteiro do próprio
círculo, para ser corrigido no código (pelo Developer quando houver LLM, ou por você).

Guardrail: as etapas `health` e `pedido:*` nunca entram em quarentena — a saúde é quem faz rollback,
e pedidos têm retentativa própria.
"""
from __future__ import annotations

import hashlib
import re
import time
import traceback

from .decision import Question, SN
from .state import Store

NEVER_ISOLATE_PREFIXES = ("health", "pedido")
WINDOW_TICKS = 20
REPEATS_TO_ISOLATE = 3
BASE_QUARANTINE_TICKS = 10
MAX_QUARANTINE_TICKS = 640
RESOLVE_AFTER_TICKS = 200


def fingerprint(stage: str, exc: BaseException) -> str:
    msg = re.sub(r"\d+", "N", str(exc))[:200]
    tb = traceback.extract_tb(exc.__traceback__)
    where = f"{tb[-1].filename.rsplit('/', 1)[-1]}:{tb[-1].name}" if tb else ""
    return hashlib.sha256(f"{stage}|{type(exc).__name__}|{msg}|{where}".encode()).hexdigest()[:16]


class Incidents:
    def __init__(self, store: Store, dl, reply, circulo_project_id):
        self.s = store
        self.dl = dl
        self.reply = reply
        self.circulo_pid = circulo_project_id

    # ------------------------------------------------------------ registrar
    def record(self, stage: str, exc: BaseException, project_id: int | None = None) -> dict:
        fp = fingerprint(stage, exc)
        tick, now = self.s.tick, time.time()
        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=4))[-2000:]
        row = self.s.one("SELECT * FROM incidents WHERE fingerprint=?", (fp,))
        if row:
            status = "aberto" if row["status"] == "resolvido" else row["status"]   # voltou a acontecer
            self.s.x("UPDATE incidents SET count=count+1, last_seen=?, last_tick=?, status=?, trace=? WHERE id=?",
                     (now, tick, status, trace, row["id"]))
            iid = row["id"]
        else:
            iid = self.s.x("""INSERT INTO incidents(fingerprint,stage,kind,message,trace,project_id,count,first_seen,last_seen,
                              first_tick,last_tick,status) VALUES(?,?,?,?,?,?,1,?,?,?,?,'aberto')""",
                           (fp, stage, type(exc).__name__, str(exc)[:500], trace, project_id, now, now, tick, tick))
        inc = dict(self.s.one("SELECT * FROM incidents WHERE id=?", (iid,)))
        # cada ocorrência fica presa à execução em que aconteceu (o incidente agrupa; a ocorrência localiza)
        rid = self.s.x("INSERT INTO run_errors(run_id,tick,stage,kind,message,trace,incident_id,em) VALUES(?,?,?,?,?,?,?,?)",
                       (self.s.get("run_id"), tick, stage, type(exc).__name__, str(exc)[:500], trace, iid, now))
        if rid % 500 == 0:
            self.s.x("DELETE FROM run_errors WHERE em < ?", (now - 30 * 86400,))
        lic =getattr(self, "licoes", None)
        if lic is not None:
            # a lição decide: erro de estrutura vira item na PRIMEIRA vez; ambiente (rede, limite) só se recorrente
            try:
                lic.verificar(f"execucao:{stage}", False, sujeito=stage, motivo=f"{inc['kind']}: {inc['message']}",
                              assinatura=f"incidente:{fp}", detalhe_item=f"(incidente #{inc['id']},",
                              titulo=f"Corrigir erro: {inc['kind']} em {stage}")
            except Exception:  # noqa: BLE001 — registrar nunca derruba quem registra
                pass
        else:
            self._learn(inc)
        self._maybe_isolate(stage, inc)
        return inc

    # ------------------------------------------------------------ aprender: erro recorrente vira roteiro
    def _learn(self, inc: dict) -> None:
        if inc["count"] < 2:
            return
        titulo = f"Corrigir erro recorrente: {inc['kind']} em {inc['stage']}"
        if self.s.one("SELECT 1 FROM roadmap WHERE origem='erro' AND detalhe LIKE ?", (f"%incidente #{inc['id']}%",)):
            return
        now = time.time()
        ordem = (self.s.one("SELECT COALESCE(MAX(ordem),0) m FROM roadmap")["m"] or 0) + 1
        self.s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                 (titulo, f"{inc['message'][:200]} (incidente #{inc['id']}, {inc['count']}x)", "erro", "pendente", "", ordem, now, now))

    # ------------------------------------------------------------ autocorreção: quarentena com backoff
    def _maybe_isolate(self, stage: str, inc: dict) -> None:
        if stage.startswith(NEVER_ISOLATE_PREFIXES):
            return
        tick = self.s.tick
        recent = self.s.one("SELECT COALESCE(SUM(count),0) n FROM incidents WHERE stage=? AND last_tick >= ?",
                            (stage, tick - WINDOW_TICKS))["n"]
        if recent < REPEATS_TO_ISOLATE:
            return
        q = self.s.get("quarentena", {}) or {}
        cur = q.get(stage)
        if cur and cur["ate_tick"] > tick:
            return
        d = self.dl.ask("isolate_stage", Question(
            "noul", "Esta etapa está falhando de forma repetida e deve ser isolada temporariamente para o resto do círculo seguir?",
            SN("`falhas_recentes` se acumulam na janela e já houve `reincidencias`: a etapa derruba giro atrás de giro",
               "foi uma falha isolada ou já parou; isolar tiraria trabalho útil do loop sem necessidade")),
            {"stage": stage, "falhas_recentes": recent, "janela_giros": WINDOW_TICKS, "reincidencias": (cur or {}).get("nivel", 0)})
        if float(d.value) < 0.6:
            return
        nivel = (cur or {}).get("nivel", 0) + 1
        dur = min(MAX_QUARANTINE_TICKS, BASE_QUARANTINE_TICKS * 2 ** (nivel - 1))
        q[stage] = {"ate_tick": tick + dur, "nivel": nivel, "desde_tick": tick, "incidente": inc["id"]}
        self.s.set("quarentena", q)
        self.s.x("UPDATE incidents SET status='isolado', resolution=? WHERE id=?",
                 (f"etapa isolada por {dur} giros (nível {nivel})", inc["id"]))
        self.reply(f"Autocorreção: a etapa “{stage}” falhou {recent}x em {WINDOW_TICKS} giros e ficou isolada por "
                   f"{dur} giros. O resto do círculo segue normalmente.", "saude")

    def isolated(self, stage: str) -> bool:
        q = self.s.get("quarentena", {}) or {}
        return bool(q.get(stage) and q[stage]["ate_tick"] > self.s.tick)

    # ------------------------------------------------------------ fechar o que parou de acontecer
    def resolve_stale(self) -> int:
        tick = self.s.tick
        fechados = [r["id"] for r in self.s.q("SELECT id FROM incidents WHERE status IN ('aberto','isolado') AND last_tick < ?",
                                             (tick - RESOLVE_AFTER_TICKS,))]
        for iid in fechados:   # o erro parou de acontecer: o item do roteiro que pedia a correção está feito
            self.s.x("UPDATE roadmap SET status='feito', evidencia=evidencia || ' · erro não ocorre há ' || ? || ' giros', updated_at=? "
                     "WHERE origem='erro' AND status!='feito' AND detalhe LIKE ?", (RESOLVE_AFTER_TICKS, time.time(), f"%incidente #{iid},%"))
        n = self.s.run(
            "UPDATE incidents SET status='resolvido', resolution=COALESCE(resolution,'') || ' | não ocorre há ' || ? || ' giros' "
            "WHERE status IN ('aberto','isolado') AND last_tick < ?", (RESOLVE_AFTER_TICKS, tick - RESOLVE_AFTER_TICKS))
        return n

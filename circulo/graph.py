"""Grafo de missões: as missões se conhecem, compartilham memória e contexto, e se integram.

- Relações são decididas pelo Jev (Choice por par, tudo numa chamada) e guardadas com a evidência.
- Missões ligadas enxergam o contexto umas das outras (pedido, entrega atual, achados) como DADO,
  nunca como instrução; a memória (RAG) de uma passa a ser consultável pelas ligadas.
- Relação de integração (complementa / consome) vira critério da régua: a missão só "acerta" se integrar.
- Lição confirmada numa missão é transferida (em quarentena) para as missões ligadas: o que deu certo
  num pedido é testado nos outros, e só fica se ajudar lá também.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

from .agents import Ctx
from .decision import Question, norm
from .memory import Memory

RELACOES = {
    "nenhuma": "Não têm relação útil",
    "mesmo_publico": "Atendem o mesmo público ou a mesma pessoa",
    "complementa": "Uma completa a outra (juntas formam uma solução maior)",
    "consome": "Uma usa a saída ou os dados da outra",
    "compartilha_dados": "Dependem dos mesmos dados ou do mesmo objetivo",
}
INTEGRA = ("complementa", "consome")
_STOP = {"crie", "criar", "para", "uma", "com", "dos", "das", "que", "meu", "minha", "monte", "faça", "sobre", "pedido"}


def _palavras(texto: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", norm(texto)) if w not in _STOP}


class MissionGraph:
    def __init__(self, ctx: Ctx, memory: Memory):
        self.ctx = ctx
        self.s = ctx.store
        self.mem = memory

    # ------------------------------------------------------------ descobrir relações
    def perfil(self, pid: int) -> dict:
        p = self.s.one("SELECT id, nome, pedido, proposito, tipo, kit FROM projects WHERE id=?", (pid,))
        achados = [r["text"] for r in self.s.q("SELECT text FROM memory WHERE project_id=? AND kind='achado' ORDER BY id DESC LIMIT 5", (pid,))]
        return {**dict(p), "achados": achados}

    def conectar(self, pid: int) -> list[dict]:
        """Relaciona uma missão com todas as outras. Uma chamada ao Jev para todos os pares."""
        me = self.perfil(pid)
        outras = [self.perfil(r["id"]) for r in self.s.q(
            "SELECT id FROM projects WHERE id!=? AND kit!='circulo' AND status!='arquivado'", (pid,))]
        if not outras or me["kit"] == "circulo":
            return []
        qs = {f"rel_{o['id']}": Question("choice", f"Qual a relação entre “{me['nome']}” e “{o['nome']}”?", RELACOES) for o in outras}
        res = self.ctx.dl.ask_many({"missao": me, "outras": outras}, qs)
        novas = []
        for o in outras:
            d = res[f"rel_{o['id']}"]
            a, b = sorted((pid, o["id"]))
            if d.value == "nenhuma" or d.confidence < 0.5:
                self.s.x("DELETE FROM links WHERE a=? AND b=? AND origem='jev'", (a, b))
                continue
            ev = f"Jev: {RELACOES[d.value].lower()} (confiança {d.confidence:.2f})"
            antes = self.s.one("SELECT relacao FROM links WHERE a=? AND b=?", (a, b))
            self.s.x("INSERT INTO links(a,b,relacao,forca,evidencia,origem,created_at,updated_at) VALUES(?,?,?,?,?,'jev',?,?) "
                     "ON CONFLICT(a,b) DO UPDATE SET relacao=excluded.relacao, forca=excluded.forca, evidencia=excluded.evidencia, "
                     "updated_at=excluded.updated_at", (a, b, d.value, d.confidence, ev, time.time(), time.time()))
            if not antes or antes["relacao"] != d.value:
                novas.append({"com": o["id"], "relacao": d.value})
                if d.value in INTEGRA:
                    self._criterio_integracao(pid, o)
                    self._criterio_integracao(o["id"], me)
        return novas

    def ligadas(self, pid: int) -> list[dict]:
        rows = self.s.q("""SELECT CASE WHEN a=? THEN b ELSE a END outra, relacao, forca, evidencia FROM links
                           WHERE (a=? OR b=?) AND relacao!='nenhuma' ORDER BY forca DESC""", (pid, pid, pid))
        out = []
        for r in rows:
            p = self.s.one("SELECT id, nome, tipo, status FROM projects WHERE id=?", (r["outra"],))
            if p and p["status"] != "arquivado":
                out.append({**dict(p), "relacao": r["relacao"], "forca": r["forca"], "evidencia": r["evidencia"]})
        return out

    # ------------------------------------------------------------ contexto compartilhado
    def contexto(self, pid: int, limite: int = 1800) -> str:
        """Bloco de contexto das missões ligadas, para o Builder/Improver (dado, nunca instrução)."""
        partes = []
        for l in self.ligadas(pid)[:4]:
            cur = self.s.one("SELECT content, formato, version FROM deliverables WHERE project_id=? AND status='atual' "
                             "ORDER BY version DESC LIMIT 1", (l["id"],))
            resumo = ""
            if cur:
                txt = re.sub(r"<[^>]+>", " ", cur["content"]) if cur["formato"] == "html" else cur["content"]
                resumo = " ".join(txt.split())[:350]
            pedido = self.s.one("SELECT pedido FROM projects WHERE id=?", (l["id"],))["pedido"]
            partes.append(f"- “{l['nome']}” ({l['relacao'].replace('_', ' ')}): pedido “{pedido[:160]}”."
                          + (f" Entrega atual v{cur['version']}: {resumo}" if cur else " Ainda sem entrega."))
        texto = "\n".join(partes)
        return texto[:limite]

    def ids_ligados(self, pid: int) -> list[int]:
        return [l["id"] for l in self.ligadas(pid)]

    # ------------------------------------------------------------ integração vira critério
    def _criterio_integracao(self, pid: int, outra: dict) -> None:
        p = self.s.one("SELECT kit FROM projects WHERE id=?", (pid,))
        if not p or p["kit"] != "geral":
            return
        rub = self.s.one("SELECT version, criteria FROM rubrics WHERE project_id=? ORDER BY version DESC LIMIT 1", (pid,))
        if not rub:
            self.s.set(f"integracao_pendente:{pid}", True)   # entra quando a régua nascer
            return
        crit = json.loads(rub["criteria"])
        cid = "i_" + hashlib.sha1(f"{pid}-{outra['id']}".encode()).hexdigest()[:8]
        if any(c["id"] == cid for c in crit):
            return
        crit.append({"id": cid, "texto": f"Integra com a missão “{outra['nome']}” (menciona, aponta ou usa o que ela entrega)",
                     "peso": 2, "integracao": outra["id"]})
        self.s.x("INSERT INTO rubrics(project_id,version,criteria,created_at) VALUES(?,?,?,?)",
                 (pid, rub["version"] + 1, json.dumps(crit, ensure_ascii=False), time.time()))

    def aplicar_pendentes(self, pid: int) -> None:
        if not self.s.get(f"integracao_pendente:{pid}"):
            return
        for l in self.ligadas(pid):
            if l["relacao"] in INTEGRA:
                self._criterio_integracao(pid, {"id": l["id"], "nome": l["nome"]})
        self.s.set(f"integracao_pendente:{pid}", False)

    # ------------------------------------------------------------ lições viajam entre missões
    def transferir(self, lesson_id: int) -> int:
        lic = self.s.one("SELECT * FROM memory WHERE id=?", (lesson_id,))
        if not lic or lic["status"] != "ativa" or not lic["project_id"]:
            return 0
        n = 0
        for l in self.ligadas(lic["project_id"]):
            if l["tipo"] == lic["tipo"]:
                continue   # mesmo tipo já enxerga a lição pelo playbook
            ok = self.ctx.dl.ask("transfer_lesson", Question(
                "noul", f"A lição “{lic['text'][:200]}” provavelmente ajuda também a missão “{l['nome']}”?"),
                {"licao": lic["text"], "origem_tipo": lic["tipo"], "destino": l})
            if float(ok.value) < 0.5:
                continue
            mid = self.mem.add("licao", lic["text"], tipo=l["tipo"], project_id=l["id"],
                               source=f"transferida da missão {lic['project_id']}", status="quarentena",
                               meta={"transferida_de": lesson_id})
            self.s.x("INSERT INTO transfers(lesson_id,copia_id,de,para,created_at) VALUES(?,?,?,?,?)",
                     (lesson_id, mid, lic["project_id"], l["id"], time.time()))
            n += 1
        return n

    def conectar_todas(self) -> int:
        n = 0
        for r in self.s.q("SELECT id FROM projects WHERE kit!='circulo' AND status!='arquivado'"):
            n += len(self.conectar(r["id"]))
        return n

"""Lições: o loop aprende com os próprios erros como um humano, e o mesmo erro de estrutura só acontece uma vez.

Ciclo de maturidade (cada etapa deixa rastro no banco):
  estudar (evidência) → testar → VALIDAR (a mudança funciona: verificação local, CI, gate)
  → aprender (falha vira lição com assinatura) → corrigir (item do roteiro → PR)
  → EVIDENCIAR (o erro parou de acontecer nos dados reais) → evoluir (só sem lição de estrutura aberta).

1. Todo ponto de verificação chama `verificar(ponto, ok, ...)`. Passou ou falhou, fica em `verificacoes`
   (monitoramento: taxa de falha por ponto, painel).
2. Falha vira lição pela assinatura (ex.: `ci:lint:B905`, `planejador:saida_invalida`). As classes:
   - estrutural: erro do próprio loop. Abre item do roteiro na PRIMEIRA vez, sem esperar repetir;
   - trabalho: erro no trabalho do Developer/missões (lint, teste). Vira prevenção nos prompts, sem item próprio;
   - ambiente: limite de conta, rede, timeout. É monitorado e só vira item se for recorrente (código precisa ficar resiliente).
3. Estados: aberta → em_correcao (item em andamento) → validada (item feito: PR entrou ou o incidente sumiu)
   → evidenciada (EVID_GIROS sem reaparecer). A lição só fecha com as duas provas.
4. Reincidência: assinatura que volta depois de validada/evidenciada. Alerta, o item volta para o topo da fila e a
   contagem fica no painel. Zero reincidências é o indicador de maturidade.
5. Com lição estrutural aberta, o loop não se autoevolui (planejador e evolução do círculo esperam): primeiro corrige.
6. Toda lição validada entra no contexto do Developer e do planejador como "erros que você já cometeu".
7. Curador das lições de teste (impressão digital = node id do pytest, como o agrupamento do Sentry):
   - toda assinatura com `teste:<node id>` (developer:testes:, developer:abrir_pr:, gate:ci:...) cai numa lição só,
     com a lista de origens preservada. Só o node id exato une: ImportError, lint e conflito seguem separados;
   - no giro ocioso, o node id roda num worktree descartável do SHA atual do main (sem checkout no clone principal,
     a causa da lição #1), com `-p no:cacheprovider`. Fecha só com exit 0 em 2 execuções seguidas (sha e exit
     registrados). Exit 4/5 (o teste não existe mais) vira "obsoleta/indeterminada" e não fecha;
   - fechada pelo curador, a falha num ramo do Developer não reabre: só reabre se o node id falhar (exit 1) no
     main num SHA posterior ao do fechamento.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

EVID_GIROS = 200            # sem reaparecer por tantos giros depois de corrigida = evidenciada
AMBIENTE_RECORRENTE = 5     # ocorrências de erro de ambiente em 24h que pedem código mais resiliente
MAX_VERIFICACOES = 20_000   # janela do monitoramento
VERDES_PARA_FECHAR = 2      # execuções seguidas com exit 0 no main para o curador fechar uma lição de teste
MAX_EXECUCOES = 10          # histórico de reexecuções guardado por lição
CURAR_POR_GIRO = 3          # node ids reexecutados por giro ocioso
ABERTAS = ("aberta", "em_correcao", "reincidente")
NODE_ID = re.compile(r"teste:(tests/[\w./-]+\.py::\S+)")

AMBIENTE = re.compile(r"\b429\b|rate[ _-]?limit|session limit|usage limit|hit your [a-z ]{0,20}limit|timed? ?out|"
                      r"timeout|connection (?:reset|refused|aborted)|temporar|urlerror|http 5\d\d|"
                      r"remotedisconnected|name resolution|ssl", re.I)


def normalizar(texto: str, n: int = 70) -> str:
    t = (texto or "").lower()
    t = re.sub(r"[0-9a-f]{7,40}", "#", t)
    t = re.sub(r"\d+", "n", t)
    t = re.sub(r"[\"'`“”«»]", "", t)
    t = re.sub(r"[^a-z0-9à-ú#:_./ -]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:n]


def assinatura_de(ponto: str, motivo: str) -> str:
    """Mesma causa → mesma assinatura, mesmo com números, hashes e PRs diferentes."""
    m = motivo or ""
    # causas de ambiente com assinatura estável (o log bruto do agente muda a cada vez)
    if re.search(r'"api_error_status":\s*429|hit your [a-z ]{0,20}limit|session limit|usage limit|rate[ _-]?limit', m, re.I):
        return f"{ponto}:limite_de_uso"
    if re.search(r"timed? ?out|timeout", m, re.I):
        return f"{ponto}:timeout"
    codigos = sorted(set(re.findall(r"\b([A-Z]{1,3}\d{3,4})\b", m)))
    if codigos and re.search(r"ruff|lint|\.py:\d+:\d+", m, re.I):
        return f"{ponto}:lint:{','.join(codigos[:3])}"
    falhos = re.findall(r"FAILED (tests/[\w/]+\.py::\w+)", m)
    if falhos:
        return f"{ponto}:teste:{falhos[0]}"
    erro = re.search(r"\b(\w+(?:Error|Exception))\b", m)
    if erro and not AMBIENTE.search(m):
        return f"{ponto}:{erro.group(1)}"
    return f"{ponto}:{normalizar(m, 50)}"


def node_id_de(assinatura: str | None) -> str | None:
    """`developer:abrir_pr:teste:tests/a.py::test_b` → `tests/a.py::test_b` (None se a chave não é de teste)."""
    m = NODE_ID.search(assinatura or "")
    return m.group(1) if m else None


def _curadoria(lic: dict) -> dict:
    return json.loads(lic.get("curadoria") or "{}")


def _origens(lic: dict) -> list[str]:
    return json.loads(lic.get("origens") or "null") or [lic["assinatura"]]


def classificar(ponto: str, motivo: str) -> str:
    if AMBIENTE.search(motivo or ""):
        return "ambiente"
    if ponto.startswith(("developer:", "gate:ci", "missao")):
        return "trabalho"
    return "estrutural"


class Licoes:
    def __init__(self, store, reply=None):
        self.s = store
        self.reply = reply or (lambda *a, **k: None)

    # ------------------------------------------------------------ monitorar todo ponto de verificação
    def verificar(self, ponto: str, ok: bool, sujeito: str = "", motivo: str = "", assinatura: str | None = None,
                  classe: str | None = None, licao: bool = True, detalhe_item: str = "", titulo: str = "") -> dict | None:
        """Registra o resultado da verificação. Falha (com `licao=True`) vira ou reforça uma lição."""
        tick, agora = self.s.tick, time.time()
        sig = (assinatura or assinatura_de(ponto, motivo)) if not ok else assinatura
        vid = self.s.x("INSERT INTO verificacoes(tick,ponto,sujeito,ok,assinatura,motivo,created_at) VALUES(?,?,?,?,?,?,?)",
                       (tick, ponto, (sujeito or "")[:200], int(bool(ok)), sig, (motivo or "")[:1000], agora))
        if vid % 500 == 0:
            self.s.x("DELETE FROM verificacoes WHERE id <= ?", (vid - MAX_VERIFICACOES,))
        if ok or not licao:
            return None
        return self._aprender(ponto, sig, classe or classificar(ponto, motivo), motivo, sujeito, detalhe_item, titulo)

    # ------------------------------------------------------------ aprender
    def _aprender(self, ponto, sig, classe, motivo, sujeito, detalhe_item, titulo="") -> dict:
        tick, agora = self.s.tick, time.time()
        node = node_id_de(sig)
        if node:
            self.unir()                    # a mesma impressão digital (node id) cai na lição que já existe
        row = (self.s.one("SELECT * FROM licoes WHERE node_id=? AND status!='unida' ORDER BY id LIMIT 1", (node,)) if node
               else None) or self.s.one("SELECT * FROM licoes WHERE assinatura=?", (sig,))
        descricao = _descricao(ponto, motivo)
        if row is None:
            lid = self.s.x("""INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,
                              primeira_tick,ultima_tick,created_at,updated_at,node_id,origens)
                              VALUES(?,?,?,?,?,'aberta',1,0,?,?,?,?,?,?)""",
                           (sig, ponto, classe, descricao, f"Não repetir: {descricao}", tick, tick, agora, agora,
                            node, json.dumps([sig]) if node else None))
            lic = dict(self.s.one("SELECT * FROM licoes WHERE id=?", (lid,)))
            self.reply(f"Erro novo registrado como lição #{lid} ({classe}): {descricao[:160]}", "licao")
            if classe == "estrutural":
                self._abrir_item(lic, motivo, detalhe_item, titulo=titulo)
            return self._neurogenese(lid)
        lic = dict(row)
        if node and sig not in _origens(lic):
            self.s.x("UPDATE licoes SET origens=? WHERE id=?", (json.dumps(_origens(lic) + [sig]), lic["id"]))
        cur = _curadoria(lic)
        if cur.get("fechada") and lic["status"] not in ABERTAS:
            # fechada pelo curador com prova no main: falha num ramo do Developer não reabre. Fica suspeita e o
            # curador reexecuta o node id no main; só reabre se falhar num SHA posterior ao do fechamento.
            cur["suspeita"] = True
            self.s.x("UPDATE licoes SET ocorrencias=ocorrencias+1, curadoria=?, updated_at=? WHERE id=?",
                     (json.dumps(cur), agora, lic["id"]))
            return self._neurogenese(lic["id"])
        reincidiu = lic["status"] in ("validada", "evidenciada")
        if reincidiu:
            self.s.x("UPDATE licoes SET status='reincidente', reincidencias=reincidencias+1, ocorrencias=ocorrencias+1, "
                     "ultima_tick=?, updated_at=? WHERE id=?", (tick, agora, lic["id"]))
            self.reply(f"REINCIDÊNCIA da lição #{lic['id']} ({lic['classe']}): {lic['descricao'][:160]}. "
                       "Um erro já corrigido voltou: prioridade máxima.", "saude")
        else:
            self.s.x("UPDATE licoes SET ocorrencias=ocorrencias+1, ultima_tick=?, updated_at=? WHERE id=?", (tick, agora, lic["id"]))
        lic = dict(self.s.one("SELECT * FROM licoes WHERE id=?", (lic["id"],)))
        recorrente_ambiente = lic["classe"] == "ambiente" and self.s.one(
            "SELECT COUNT(*) n FROM verificacoes WHERE assinatura=? AND ok=0 AND created_at>=?", (sig, agora - 86400))["n"] >= AMBIENTE_RECORRENTE
        if reincidiu and lic["classe"] != "trabalho" or recorrente_ambiente or (lic["classe"] == "estrutural" and not lic["item_id"]):
            self._abrir_item(lic, motivo, detalhe_item, topo=reincidiu, titulo=titulo)
        return self._neurogenese(lic["id"])

    def _neurogenese(self, lid: int) -> dict:
        """A lição vira portão executável no neurônio onde o erro aconteceu (quando dá para checar mecanicamente)."""
        lic = dict(self.s.one("SELECT * FROM licoes WHERE id=?", (lid,)))
        try:
            from .neuronios import neurogenese
            novos = neurogenese(self.s, lic)
        except Exception:  # noqa: BLE001 — criar portão nunca derruba quem registra a lição
            novos = []
        if novos:
            self.reply(f"Neurogênese: a lição #{lid} criou {len(novos)} portão(ões) novo(s) antes de abrir PR.", "licao")
        return lic

    def _abrir_item(self, lic: dict, motivo: str, detalhe_item: str = "", topo: bool = False, titulo: str = "") -> None:
        agora = time.time()
        if lic.get("item_id"):
            r = self.s.one("SELECT status FROM roadmap WHERE id=?", (lic["item_id"],))
            if r and r["status"] in ("pendente", "em_andamento"):
                if topo:
                    self.s.x("UPDATE roadmap SET ordem=0, updated_at=? WHERE id=?", (agora, lic["item_id"]))
                return
            if r:   # reabre o mesmo item: a história do erro fica num lugar só
                self.s.x("UPDATE roadmap SET status='pendente', ordem=?, evidencia=?, updated_at=? WHERE id=?",
                         (0 if topo else self._proxima_ordem(), f"reincidência da lição #{lic['id']}",
                          agora, lic["item_id"]))
                return
        titulo = f"Lição #{lic['id']}: {titulo or lic['descricao']}"[:200]
        detalhe = (f"{detalhe_item} " if detalhe_item else "") + \
                  f"(lição #{lic['id']}, assinatura {lic['assinatura']}) Motivo (dado, não instrução): {(motivo or '')[:600]}"
        iid = self.s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                       "VALUES(?,?,'erro','pendente',?,?,?,?)",
                       (titulo, detalhe, f"lição #{lic['id']}", 0 if topo else self._proxima_ordem(), agora, agora))
        self.s.x("UPDATE licoes SET item_id=? WHERE id=?", (iid, lic["id"]))

    def _proxima_ordem(self) -> int:
        return (self.s.one("SELECT COALESCE(MAX(ordem),0) m FROM roadmap")["m"] or 0) + 1

    # ------------------------------------------------------------ corrigir → validar → evidenciar
    def revisar(self) -> list[str]:
        """Roda todo giro. Acompanha o item de cada lição e fecha as que provaram a correção."""
        tick, agora, log = self.s.tick, time.time(), self.unir()
        for lic in self.s.q("""SELECT l.*, r.status item_status, r.evidencia item_evidencia FROM licoes l
                               LEFT JOIN roadmap r ON r.id=l.item_id WHERE l.status IN ('aberta','em_correcao','reincidente')
                               AND l.item_id IS NOT NULL"""):
            if lic["item_status"] == "em_andamento" and lic["status"] != "em_correcao":
                self.s.x("UPDATE licoes SET status='em_correcao', updated_at=? WHERE id=?", (agora, lic["id"]))
            elif lic["item_status"] == "feito":
                pr = re.search(r"PR #(\d+)", lic["item_evidencia"] or "")
                self.s.x("UPDATE licoes SET status='validada', corrigida_tick=?, pr=?, prevencao=?, updated_at=? WHERE id=?",
                         (tick, int(pr.group(1)) if pr else None,
                          f"Já corrigido ({lic['item_evidencia']}); não repetir: {lic['descricao']}", agora, lic["id"]))
                log.append(f"lição #{lic['id']} validada")
                self.reply(f"Lição #{lic['id']} validada: a correção entrou ({lic['item_evidencia']}). "
                           f"Agora precisa ficar {EVID_GIROS} giros sem reaparecer.", "licao")
        # lição de trabalho/ambiente sem item: vale como aprendida quando para de acontecer
        # (lição de teste não: só o curador fecha, com o node id verde no main)
        for lic in self.s.q("SELECT * FROM licoes WHERE status IN ('aberta','reincidente') AND item_id IS NULL "
                            "AND node_id IS NULL AND ultima_tick < ?",
                            (tick - EVID_GIROS,)):
            self.s.x("UPDATE licoes SET status='validada', corrigida_tick=?, updated_at=? WHERE id=?", (tick, agora, lic["id"]))
        for lic in self.s.q("SELECT * FROM licoes WHERE status='validada' AND corrigida_tick <= ? AND ultima_tick <= corrigida_tick",
                            (tick - EVID_GIROS,)):
            self.s.x("UPDATE licoes SET status='evidenciada', evidenciada_tick=?, updated_at=? WHERE id=?", (tick, agora, lic["id"]))
            log.append(f"lição #{lic['id']} evidenciada")
            self.reply(f"Lição #{lic['id']} evidenciada: {EVID_GIROS} giros sem o erro voltar. Aprendido.", "licao")
        return log

    # ------------------------------------------------------------ curador das lições de teste
    def unir(self) -> list[str]:
        """Une as lições abertas com o mesmo node id na mais antiga, preservando a lista de origens."""
        for r in self.s.q("SELECT id, assinatura FROM licoes WHERE node_id IS NULL AND assinatura LIKE '%teste:%'"):
            if node_id_de(r["assinatura"]):
                self.s.x("UPDATE licoes SET node_id=? WHERE id=?", (node_id_de(r["assinatura"]), r["id"]))
        log, agora = [], time.time()
        for g in self.s.q("SELECT node_id FROM licoes WHERE node_id IS NOT NULL AND status!='unida' "
                          "GROUP BY node_id HAVING COUNT(*) > 1"):
            alvo, *resto = [dict(r) for r in self.s.q("SELECT * FROM licoes WHERE node_id=? AND status!='unida' ORDER BY id",
                                                      (g["node_id"],))]
            origens, cur, status, item = _origens(alvo), _curadoria(alvo), alvo["status"], alvo["item_id"]
            for d in resto:
                origens += [o for o in _origens(d) if o not in origens]
                item = item or d["item_id"]
                if d["status"] in ABERTAS and status not in ABERTAS:
                    if cur.get("fechada"):
                        cur["suspeita"] = True          # o curador confere no main antes de reabrir
                    else:
                        status = d["status"]
                self.s.x("UPDATE licoes SET status='unida', unida_a=?, prevencao=?, updated_at=? WHERE id=?",
                         (alvo["id"], f"Unida à lição #{alvo['id']} (mesmo teste {g['node_id']})", agora, d["id"]))
            todas = [alvo, *resto]
            self.s.x("UPDATE licoes SET status=?, item_id=?, origens=?, curadoria=?, ocorrencias=?, reincidencias=?, "
                     "primeira_tick=?, ultima_tick=?, updated_at=? WHERE id=?",
                     (status, item, json.dumps(origens), json.dumps(cur) if cur else None,
                      sum(x["ocorrencias"] for x in todas), sum(x["reincidencias"] for x in todas),
                      min(x["primeira_tick"] or 0 for x in todas), max(x["ultima_tick"] or 0 for x in todas),
                      agora, alvo["id"]))
            ids = ", ".join(f"#{d['id']}" for d in resto)
            log.append(f"lições {ids} unidas à #{alvo['id']}")
            self.reply(f"Lições {ids} unidas à #{alvo['id']}: mesmo teste ({g['node_id']}), origens: {', '.join(origens)}.",
                       "licao")
        return log

    def pendentes(self, sha: str) -> list[dict]:
        """Lições de teste que valem uma reexecução no main `sha`."""
        out = []
        for r in self.s.q("SELECT * FROM licoes WHERE node_id IS NOT NULL AND status!='unida' ORDER BY id"):
            lic = dict(r)
            cur = _curadoria(lic)
            ultima = (cur.get("execucoes") or [None])[-1]
            if lic["status"] in ABERTAS:
                # um verde pede a confirmação seguinte; falha ou teste sumido só valem reexecução num main novo
                if ultima is None or ultima["exit"] == 0 or ultima["sha"] != sha:
                    out.append(lic)
            elif cur.get("fechada") and cur.get("suspeita") and (ultima is None or ultima["sha"] != sha):
                out.append(lic)
        return out

    def curar(self, runner, limite: int = CURAR_POR_GIRO) -> list[str]:
        """Giro ocioso: reexecuta os node ids pendentes num worktree descartável do main e fecha/reabre pela prova."""
        log = self.unir()
        sha = runner.sha_main()
        alvo = self.pendentes(sha)[:limite] if sha else []
        if not alvo:
            return log
        with runner.worktree(sha) as rodar:
            for lic in alvo:
                log.append(self._execucao(lic, sha, rodar(lic["node_id"]), runner))
        return log

    def _execucao(self, lic: dict, sha: str, code: int | None, runner) -> str:
        tick, agora, lid, node = self.s.tick, time.time(), lic["id"], lic["node_id"]
        cur = _curadoria(lic)
        ex = ((cur.get("execucoes") or []) + [{"sha": sha, "exit": code, "tick": tick, "em": agora}])[-MAX_EXECUCOES:]
        cur["execucoes"] = ex
        self.verificar("licoes:curador", code == 0, sujeito=f"#{lid} {node} @ {sha[:12]}", motivo=f"exit {code}",
                       assinatura=lic["assinatura"], licao=False)
        aberta, fechada = lic["status"] in ABERTAS, cur.get("fechada")
        status, extra, msg = lic["status"], {}, f"lição #{lid}: {node} exit {code} em {sha[:12]}"
        if code == 0:
            cur.pop("estado", None)
            cur["suspeita"] = False
            seguidas = ex[-VERDES_PARA_FECHAR:]
            if aberta and len(seguidas) == VERDES_PARA_FECHAR and all(e["exit"] == 0 for e in seguidas):
                shas = ", ".join(e["sha"][:12] for e in seguidas)
                cur["fechada"] = {"sha": sha, "execucoes": seguidas}
                status = "validada"
                extra = {"corrigida_tick": tick,
                         "prevencao": f"Fechada pelo curador: {node} verde no main (exit 0 em {VERDES_PARA_FECHAR} "
                                      f"execuções seguidas: {shas}); não repetir: {lic['descricao']}"}
                msg = f"lição #{lid} fechada: {node} exit 0 em {VERDES_PARA_FECHAR} execuções seguidas no main ({shas})"
                self.reply(f"Lição #{lid} fechada pelo curador: {node} passou no main (exit 0 em {VERDES_PARA_FECHAR} "
                           f"execuções seguidas, sha {shas}).", "licao")
        elif code in (4, 5):
            cur["estado"] = "obsoleta/indeterminada"     # o node id não foi coletado: não prova nada, não fecha
            cur["suspeita"] = False
            msg = f"lição #{lid} obsoleta/indeterminada: {node} não coletado em {sha[:12]} (exit {code})"
        elif code == 1 and fechada and not aberta and runner.posterior(fechada["sha"], sha):
            cur.pop("fechada")
            cur["suspeita"] = False
            status = "reincidente"
            extra = {"ultima_tick": tick}
            self.s.x("UPDATE licoes SET reincidencias=reincidencias+1, ocorrencias=ocorrencias+1 WHERE id=?", (lid,))
            msg = f"lição #{lid} reaberta: {node} falhou no main em {sha[:12]}, posterior ao fechamento"
            self.reply(f"REINCIDÊNCIA da lição #{lid}: {node} voltou a falhar no main em {sha[:12]} "
                       f"(fechada em {fechada['sha'][:12]}).", "saude")
        elif code != 1:
            cur["estado"] = "indeterminada"               # erro de coleta, timeout: nem fecha nem reabre
        sets = "".join(f", {k}=?" for k in extra)
        self.s.x(f"UPDATE licoes SET status=?, curadoria=?, updated_at=?{sets} WHERE id=?",
                 (status, json.dumps(cur), agora, *extra.values(), lid))
        return msg

    # ------------------------------------------------------------ usar o que aprendeu
    def bloqueia_evolucao(self) -> bool:
        """Lição de estrutura ainda não corrigida: primeiro corrige, depois evolui."""
        return self.s.one("SELECT COUNT(*) n FROM licoes WHERE classe='estrutural' "
                          "AND status IN ('aberta','em_correcao','reincidente')")["n"] > 0

    def contexto(self, limite: int = 15) -> str:
        rows = self.s.q("SELECT id, status, assinatura, prevencao, reincidencias FROM licoes WHERE classe!='ambiente' "
                        "AND status!='unida' "
                        "ORDER BY reincidencias DESC, ocorrencias DESC, id DESC LIMIT ?", (limite,))
        if not rows:
            return ""
        linhas = [f"- #{r['id']} [{r['status']}{', reincidiu ' + str(r['reincidencias']) + 'x' if r['reincidencias'] else ''}] "
                  f"{r['assinatura']}: {r['prevencao']}" for r in rows]
        return "Erros que o círculo já cometeu (lições). Não repita nenhum deles:\n" + "\n".join(linhas)

    def resumo(self) -> dict:
        por_status = {r["status"]: r["n"] for r in self.s.q("SELECT status, COUNT(*) n FROM licoes GROUP BY status")}
        dia = time.time() - 86400
        pontos = [dict(r) for r in self.s.q("SELECT ponto, COUNT(*) total, SUM(ok=0) falhas FROM verificacoes "
                                             "WHERE created_at>=? GROUP BY ponto ORDER BY falhas DESC, total DESC", (dia,))]
        return {"por_status": por_status,
                "reincidencias": self.s.one("SELECT COALESCE(SUM(reincidencias),0) n FROM licoes")["n"],
                "abertas_estruturais": self.s.one("SELECT COUNT(*) n FROM licoes WHERE classe='estrutural' "
                                                  "AND status IN ('aberta','em_correcao','reincidente')")["n"],
                "verificacoes_24h": pontos,
                "ultimas": [dict(r) for r in self.s.q("SELECT id, assinatura, classe, status, descricao, ocorrencias, reincidencias, "
                                                      "item_id, pr FROM licoes ORDER BY updated_at DESC LIMIT 12")]}


def _descricao(ponto: str, motivo: str) -> str:
    m = (motivo or "").strip().splitlines()
    linha = next((x for x in m if re.search(r"error|erro|falh|FAILED|\.py:\d+", x, re.I)), m[0] if m else "")
    return f"{ponto}: {linha.strip()[:200]}" if linha else ponto


class CuradorGit:
    """Reexecuta node ids num worktree descartável do main: o clone principal nunca recebe checkout (lição #1)."""

    def __init__(self, repo: Path, data_dir: Path, timeout: int = 600):
        self.repo, self.data, self.timeout = Path(repo), Path(data_dir), timeout

    def _git(self, args: list[str], check: bool = False) -> str:
        from .self_dev import _git
        return _git(args, self.repo, check=check)

    def sha_main(self, fetch: bool = True) -> str:
        if fetch:
            self._git(["fetch", "-q", "origin", "main"])
        return self._git(["rev-parse", "--verify", "-q", "origin/main"]) or self._git(["rev-parse", "--verify", "-q", "main"])

    def posterior(self, antigo: str, novo: str) -> bool:
        """`novo` vem depois de `antigo` na história do main (e não é o mesmo commit)."""
        if not antigo or not novo or antigo == novo:
            return False
        return subprocess.run(["git", "merge-base", "--is-ancestor", antigo, novo], cwd=self.repo,
                              capture_output=True).returncode == 0

    @contextmanager
    def worktree(self, sha: str):
        self.data.mkdir(parents=True, exist_ok=True)
        wt = Path(tempfile.mkdtemp(prefix="licoes-curador-", dir=self.data))
        try:
            self._git(["worktree", "add", "-q", "--detach", str(wt), sha], check=True)
            yield lambda node: self._pytest(wt, node)
        finally:
            self._git(["worktree", "remove", "--force", str(wt)])
            shutil.rmtree(wt, ignore_errors=True)
            self._git(["worktree", "prune"])

    def _pytest(self, wt: Path, node: str) -> int | None:
        from .self_dev import ambiente_isolado
        try:
            # node id explícito (sem --lf) e sem cache: a checagem não depende do que rodou antes
            return subprocess.run([sys.executable, "-m", "pytest", node, "-q", "-p", "no:cacheprovider"], cwd=wt,
                                  capture_output=True, text=True, timeout=self.timeout,
                                  env={**ambiente_isolado(), "PYTHONPATH": str(wt)}).returncode
        except subprocess.TimeoutExpired:
            return None


def registrar(ctx, ponto: str, ok: bool, **kw) -> dict | None:
    """Atalho para quem só tem o ctx: monitora sem nunca derrubar quem chamou."""
    lic = getattr(ctx, "licoes", None)
    if lic is None:
        return None
    try:
        return lic.verificar(ponto, ok, **kw)
    except Exception:  # noqa: BLE001 — monitorar nunca derruba o trabalho
        return None

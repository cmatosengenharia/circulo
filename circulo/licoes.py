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
"""
from __future__ import annotations

import re
import time

EVID_GIROS = 200            # sem reaparecer por tantos giros depois de corrigida = evidenciada
AMBIENTE_RECORRENTE = 5     # ocorrências de erro de ambiente em 24h que pedem código mais resiliente
MAX_VERIFICACOES = 20_000   # janela do monitoramento

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
        row = self.s.one("SELECT * FROM licoes WHERE assinatura=?", (sig,))
        descricao = _descricao(ponto, motivo)
        if row is None:
            lid = self.s.x("""INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,
                              primeira_tick,ultima_tick,created_at,updated_at) VALUES(?,?,?,?,?,'aberta',1,0,?,?,?,?)""",
                           (sig, ponto, classe, descricao, f"Não repetir: {descricao}", tick, tick, agora, agora))
            lic = dict(self.s.one("SELECT * FROM licoes WHERE id=?", (lid,)))
            self.reply(f"Erro novo registrado como lição #{lid} ({classe}): {descricao[:160]}", "licao")
            if classe == "estrutural":
                self._abrir_item(lic, motivo, detalhe_item, titulo=titulo)
            return dict(self.s.one("SELECT * FROM licoes WHERE id=?", (lid,)))
        lic = dict(row)
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
        tick, agora, log = self.s.tick, time.time(), []
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
        for lic in self.s.q("SELECT * FROM licoes WHERE status IN ('aberta','reincidente') AND item_id IS NULL AND ultima_tick < ?",
                            (tick - EVID_GIROS,)):
            self.s.x("UPDATE licoes SET status='validada', corrigida_tick=?, updated_at=? WHERE id=?", (tick, agora, lic["id"]))
        for lic in self.s.q("SELECT * FROM licoes WHERE status='validada' AND corrigida_tick <= ? AND ultima_tick <= corrigida_tick",
                            (tick - EVID_GIROS,)):
            self.s.x("UPDATE licoes SET status='evidenciada', evidenciada_tick=?, updated_at=? WHERE id=?", (tick, agora, lic["id"]))
            log.append(f"lição #{lic['id']} evidenciada")
            self.reply(f"Lição #{lic['id']} evidenciada: {EVID_GIROS} giros sem o erro voltar. Aprendido.", "licao")
        return log

    # ------------------------------------------------------------ usar o que aprendeu
    def bloqueia_evolucao(self) -> bool:
        """Lição de estrutura ainda não corrigida: primeiro corrige, depois evolui."""
        return self.s.one("SELECT COUNT(*) n FROM licoes WHERE classe='estrutural' "
                          "AND status IN ('aberta','em_correcao','reincidente')")["n"] > 0

    def contexto(self, limite: int = 15) -> str:
        rows = self.s.q("SELECT id, status, assinatura, prevencao, reincidencias FROM licoes WHERE classe!='ambiente' "
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


def registrar(ctx, ponto: str, ok: bool, **kw) -> dict | None:
    """Atalho para quem só tem o ctx: monitora sem nunca derrubar quem chamou."""
    lic = getattr(ctx, "licoes", None)
    if lic is None:
        return None
    try:
        return lic.verificar(ponto, ok, **kw)
    except Exception:  # noqa: BLE001 — monitorar nunca derruba o trabalho
        return None

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
7. Lição de teste (assinatura com `teste:<node id>`): a impressão digital é o node id. Falhas do mesmo node id em
   pontos diferentes (developer:testes, developer:abrir_pr…) são uma lição só, com a lista de origens. Ela fecha
   só pela reexecução do node id num worktree descartável do main: exit 0 em 2 execuções seguidas (sha e exit
   ficam registrados). Exit 4/5 (não coletado) vira `obsoleta` e não fecha. Reabre só se o node id falhar no main
   em um sha posterior ao do fechamento; falhar no worktree de um Developer não é falhar no main.
8. Lição sem node id cuja causa está em causas.py herda o node id do alias e o mesmo ciclo; como a checagem é
   emprestada, também reabre se o teste sumir do main ou mudar de corpo (impressão do AST no sha do main).
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .causas import node_por_causa

EVID_GIROS = 200            # sem reaparecer por tantos giros depois de corrigida = evidenciada
AMBIENTE_RECORRENTE = 5     # ocorrências de erro de ambiente em 24h que pedem código mais resiliente
MAX_VERIFICACOES = 20_000   # janela do monitoramento
VERDES_PARA_FECHAR = 2      # execuções seguidas com exit 0 no main
NAO_COLETADO = (4, 5)       # pytest: node id inválido / nada coletado
ABERTAS = ("aberta", "em_correcao", "reincidente", "obsoleta")
NODE_ID = re.compile(r"teste:(tests/[\w./-]+\.py::\S+)")
DO_ITEM = re.compile(r"(?:\.circulo-wt-|roteiro #)(\d+)$")   # o worktree e o rótulo do Developer levam o id do item

AMBIENTE = re.compile(r"\b429\b|rate[ _-]?limit|session limit|usage limit|hit your [a-z ]{0,20}limit|timed? ?out|"
                      r"timeout|connection (?:reset|refused|aborted)|temporar|urlerror|http(?: error:?)? ?5\d\d|bad gateway|"
                      r"service unavailable|gateway time|"
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
    m = NODE_ID.search(assinatura or "")
    return m.group(1) if m else None


def alvo_de(lic) -> str | None:
    """O node id que prova a lição: o próprio ou o do alias da causa."""
    return lic["node_id"] or node_por_causa(lic["assinatura"])


def licao_de(store, assinatura: str):
    """A lição da assinatura: lição de teste é achada pelo node id, as outras pela assinatura exata."""
    node = node_id_de(assinatura)
    if node:
        return store.one("SELECT * FROM licoes WHERE node_id=? AND status!='unida' ORDER BY id LIMIT 1", (node,))
    return store.one("SELECT * FROM licoes WHERE assinatura=?", (assinatura,))


def _git(repo: Path, *a, check=True) -> str:
    p = subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(a)}: {p.stderr.strip()[:300]}")
    return p.stdout.strip()


def sha_do_main(repo: str | Path) -> str:
    repo = Path(repo)
    _git(repo, "fetch", "-q", "origin", "main", check=False)
    return _git(repo, "rev-parse", "--verify", "-q", "origin/main", check=False) or _git(repo, "rev-parse", "main")


def impressao_no_main(repo: str | Path, sha: str, node_id: str) -> str | None:
    """Hash do AST do teste no sha do main (comentário e formato não contam); None se o teste não existe lá."""
    arquivo, *nomes = node_id.split("::")
    try:
        corpo = ast.parse(_git(Path(repo), "show", f"{sha}:{arquivo}", check=False))
    except SyntaxError:
        return None
    for nome in nomes:
        corpo = next((n for n in getattr(corpo, "body", []) if getattr(n, "name", None) == nome.split("[")[0]), None)
        if corpo is None:
            return None
    return hashlib.sha256(ast.dump(corpo).encode()).hexdigest()[:16] if nomes else None


def reexecutar_no_main(repo: str | Path, node_ids: list[str], sha: str | None = None, python: str | None = None,
                       timeout: int = 600) -> tuple[str, dict[str, int]]:
    """(sha do main, {node id: exit code}). Roda num worktree descartável: o clone principal não troca de branch."""
    repo = Path(repo)
    sha = sha or sha_do_main(repo)
    tmp = Path(tempfile.mkdtemp(prefix="circulo-licao-"))
    wt = tmp / "main"
    codigos = {}
    try:
        _git(repo, "worktree", "add", "--detach", "-q", str(wt), sha)
        amb = {**os.environ, "PYTHONPATH": str(wt), "PYTHONDONTWRITEBYTECODE": "1"}
        for node in node_ids:
            try:
                codigos[node] = subprocess.run([python or sys.executable, "-m", "pytest", "-q", node, "-p", "no:cacheprovider"],
                                               cwd=wt, capture_output=True, text=True, timeout=timeout, env=amb).returncode
            except subprocess.TimeoutExpired:
                pass                      # sem exit code não há prova nem para fechar nem para reabrir
    finally:
        _git(repo, "worktree", "remove", "--force", str(wt), check=False)
        shutil.rmtree(tmp, ignore_errors=True)
    return sha, codigos


def classificar(ponto: str, motivo: str) -> str:
    if AMBIENTE.search(motivo or ""):
        return "ambiente"
    if ponto.startswith(("developer:", "gate:ci", "missao")):
        return "trabalho"
    return "estrutural"


# Camadas de prevenção, da mais fraca para a mais forte (Lauren Tan, "corrigir na camada mais forte"):
# revisão humana < regra/portão aprendido (o agente pode pular) < CI (teste ou lint que barra) < arquitetura (o erro
# fica impossível de escrever). Lição que volta, ou que se repete muito, ainda não subiu de camada: sobe uma.
CAMADAS = ("revisao", "regra", "ci", "arquitetura")
NOME_CAMADA = {"revisao": "revisão humana", "regra": "regra (portão aprendido)", "ci": "CI (teste ou lint)",
               "arquitetura": "arquitetura (erro impossível)"}
REPETICOES_PARA_SUBIR = 5


def instrucao_camada(camada: str) -> str:
    return {"ci": "Subir de camada: a prevenção desta lição precisa virar um teste ou regra de lint que o CI roda e que "
                  "falha quando o padrão do erro aparece (ex.: tests/test_arquitetura.py), não só uma instrução.",
            "arquitetura": "Subir de camada: mude a estrutura do código para que este erro fique impossível de escrever "
                           "(uma única forma de fazer, tipos, fronteira de módulo), e remova o caminho antigo."}.get(camada, "")


def subir(camada: str | None) -> str:
    c = camada if camada in CAMADAS else "regra"
    return CAMADAS[min(len(CAMADAS) - 1, CAMADAS.index(c) + 1)]


class Licoes:
    def __init__(self, store, reply=None):
        self.s = store
        self.reply = reply or (lambda *a, **k: None)

    # ------------------------------------------------------------ monitorar todo ponto de verificação
    def verificar(self, ponto: str, ok: bool, sujeito: str = "", motivo: str = "", assinatura: str | None = None,
                  classe: str | None = None, licao: bool = True, detalhe_item: str = "", titulo: str = "",
                  item_id: int | None = None) -> dict | None:
        """Registra o resultado da verificação, com o item do roteiro em execução. Falha (com `licao=True`) vira ou
        reforça uma lição."""
        tick, agora = self.s.tick, time.time()
        sig = (assinatura or assinatura_de(ponto, motivo)) if not ok else assinatura
        item, item_titulo = item_de(self.s, sujeito, item_id)
        vid = self.s.x("INSERT INTO verificacoes(tick,ponto,sujeito,ok,assinatura,motivo,created_at,item_id,item_titulo) "
                       "VALUES(?,?,?,?,?,?,?,?,?)", (tick, ponto, (sujeito or "")[:200], int(bool(ok)), sig,
                                                     (motivo or "")[:1000], agora, item, item_titulo))
        if vid % 500 == 0:
            self.s.x("DELETE FROM verificacoes WHERE id <= ?", (vid - MAX_VERIFICACOES,))
        if ok or not licao:
            return None
        return self._aprender(ponto, sig, classe or classificar(ponto, motivo), motivo, sujeito, detalhe_item, titulo)

    # ------------------------------------------------------------ aprender
    def _aprender(self, ponto, sig, classe, motivo, sujeito, detalhe_item, titulo="") -> dict:
        tick, agora = self.s.tick, time.time()
        row = licao_de(self.s, sig)
        descricao = _descricao(ponto, motivo)
        node = node_id_de(sig)
        if row is None:
            lid = self.s.x("""INSERT INTO licoes(assinatura,ponto,classe,descricao,prevencao,status,ocorrencias,reincidencias,
                              primeira_tick,ultima_tick,created_at,updated_at,camada,node_id,origens)
                              VALUES(?,?,?,?,?,'aberta',1,0,?,?,?,?,'regra',?,?)""",
                           (sig, ponto, classe, descricao, f"Não repetir: {descricao}", tick, tick, agora, agora,
                            node, json.dumps([sig])))
            lic = dict(self.s.one("SELECT * FROM licoes WHERE id=?", (lid,)))
            self.reply(f"Erro novo registrado como lição #{lid} ({classe}): {descricao[:160]}", "licao")
            if classe == "estrutural":
                self._abrir_item(lic, motivo, detalhe_item, titulo=titulo)
            return self._neurogenese(lid)
        lic = dict(row)
        origens = json.loads(lic.get("origens") or "[]") or [lic["assinatura"]]
        if sig not in origens:
            self.s.x("UPDATE licoes SET origens=? WHERE id=?", (json.dumps(origens + [sig]), lic["id"]))
        # lição de teste só reincide pela reexecução no main (checar_testes), não pelo worktree de um Developer
        reincidiu = lic["status"] in ("validada", "evidenciada") and not alvo_de(lic)
        if reincidiu:
            self.s.x("UPDATE licoes SET status='reincidente', reincidencias=reincidencias+1, ocorrencias=ocorrencias+1, "
                     "ultima_tick=?, updated_at=? WHERE id=?", (tick, agora, lic["id"]))
            self.reply(f"REINCIDÊNCIA da lição #{lic['id']} ({lic['classe']}): {lic['descricao'][:160]}. "
                       "Um erro já corrigido voltou: prioridade máxima.", "saude")
        else:
            self.s.x("UPDATE licoes SET ocorrencias=ocorrencias+1, ultima_tick=?, updated_at=? WHERE id=?", (tick, agora, lic["id"]))
        lic = dict(self.s.one("SELECT * FROM licoes WHERE id=?", (lic["id"],)))
        repetiu = lic["classe"] != "ambiente" and lic["ocorrencias"] == REPETICOES_PARA_SUBIR and (lic.get("camada") or "regra") == "regra"
        if reincidiu or repetiu:
            # voltou (ou se repete): a prevenção atual não segura; sobe uma camada e o item pede a prevenção nela
            nova = subir(lic.get("camada"))
            if nova != lic.get("camada"):
                self.s.x("UPDATE licoes SET camada=?, prevencao=?, updated_at=? WHERE id=?",
                         (nova, f"{NOME_CAMADA[nova]}: {lic['descricao']}"[:500], agora, lic["id"]))
                self.reply(f"Lição #{lic['id']} subiu de camada: {NOME_CAMADA.get(lic.get('camada') or 'regra')} → {NOME_CAMADA[nova]} "
                           f"({'reincidiu' if reincidiu else f'repetiu {REPETICOES_PARA_SUBIR} vezes'}).", "licao")
                lic = dict(self.s.one("SELECT * FROM licoes WHERE id=?", (lic["id"],)))
                detalhe_item = (detalhe_item + " " if detalhe_item else "") + instrucao_camada(nova)
                if repetiu and not reincidiu:
                    self._abrir_item(lic, motivo, detalhe_item, titulo=titulo, forcar=True)
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

    def _abrir_item(self, lic: dict, motivo: str, detalhe_item: str = "", topo: bool = False, titulo: str = "",
                    forcar: bool = False) -> None:
        agora = time.time()
        if lic.get("item_id"):
            if detalhe_item and "Subir de camada" in detalhe_item:
                self.s.x("UPDATE roadmap SET detalhe=detalhe || ? WHERE id=? AND instr(detalhe, ?)=0",
                         ("\n" + detalhe_item[-600:], lic["item_id"], instrucao_camada(lic.get("camada") or "")[:60] or "@@"))
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
        log = self.unir_duplicatas()
        tick, agora = self.s.tick, time.time()
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
        for lic in self.s.q("SELECT * FROM licoes WHERE status IN ('aberta','reincidente') AND item_id IS NULL AND node_id IS NULL "
                            "AND ultima_tick < ?", (tick - EVID_GIROS,)):
            if node_por_causa(lic["assinatura"]):
                continue                  # o alias dá um teste à lição: ela só fecha pela reexecução
            self.s.x("UPDATE licoes SET status='validada', corrigida_tick=?, updated_at=? WHERE id=?", (tick, agora, lic["id"]))
        for lic in self.s.q("SELECT * FROM licoes WHERE status='validada' AND corrigida_tick <= ? AND ultima_tick <= corrigida_tick",
                            (tick - EVID_GIROS,)):
            self.s.x("UPDATE licoes SET status='evidenciada', evidenciada_tick=?, updated_at=? WHERE id=?", (tick, agora, lic["id"]))
            log.append(f"lição #{lic['id']} evidenciada")
            self.reply(f"Lição #{lic['id']} evidenciada: {EVID_GIROS} giros sem o erro voltar. Aprendido.", "licao")
        return log

    def unir_duplicatas(self) -> list[str]:
        """Lições gravadas antes da impressão digital por node id: o mesmo node id vira uma lição só (a mais antiga)."""
        for r in self.s.q("SELECT id, assinatura FROM licoes WHERE origens IS NULL"):
            self.s.x("UPDATE licoes SET node_id=?, origens=? WHERE id=?",
                     (node_id_de(r["assinatura"]), json.dumps([r["assinatura"]]), r["id"]))
        log, agora = [], time.time()
        for g in self.s.q("SELECT node_id FROM licoes WHERE node_id IS NOT NULL AND status!='unida' "
                          "GROUP BY node_id HAVING COUNT(*) > 1"):
            fica, *outras = [dict(r) for r in self.s.q("SELECT * FROM licoes WHERE node_id=? AND status!='unida' ORDER BY id",
                                                        (g["node_id"],))]
            origens = json.loads(fica["origens"])
            status = fica["status"]
            for o in outras:
                origens += [x for x in json.loads(o["origens"]) if x not in origens]
                if o["status"] in ABERTAS and status not in ABERTAS:
                    status = "aberta"
                self.s.x("UPDATE licoes SET status='unida', prevencao=?, updated_at=? WHERE id=?",
                         (f"Unida à lição #{fica['id']} (mesmo node id {g['node_id']})", agora, o["id"]))
            self.s.x("UPDATE licoes SET origens=?, status=?, ocorrencias=?, reincidencias=?, primeira_tick=?, ultima_tick=?, "
                     "updated_at=? WHERE id=?",
                     (json.dumps(origens), status, sum(x["ocorrencias"] for x in [fica, *outras]),
                      sum(x["reincidencias"] for x in [fica, *outras]),
                      min(x["primeira_tick"] or 0 for x in [fica, *outras]), max(x["ultima_tick"] or 0 for x in [fica, *outras]),
                      agora, fica["id"]))
            ids = ", ".join(f"#{o['id']}" for o in outras)
            log.append(f"lição #{fica['id']} unida a {ids}")
            self.reply(f"Lição #{fica['id']} absorveu {ids}: mesmo teste ({g['node_id']}), uma causa só.", "licao")
        return log

    # ------------------------------------------------------------ fechar lição de teste pela reexecução no main
    def _com_teste(self) -> list[dict]:
        return [lic for lic in map(dict, self.s.q("SELECT * FROM licoes WHERE status!='unida' ORDER BY id")) if alvo_de(lic)]

    def testes_a_checar(self) -> list[str]:
        return sorted({alvo_de(lic) for lic in self._com_teste()})

    def _a_rodar(self, sha: str) -> list[dict]:
        out = []
        for lic in self._com_teste():
            checagens = json.loads(lic.get("checagens") or "[]")
            # fechada: só um sha posterior ao já checado pode reabrir (a do alias é vigiada desde a primeira checagem)
            if lic["status"] in ABERTAS or (checagens[-1]["sha"] != sha if checagens else not lic["node_id"]):
                out.append(lic)
        return out

    def checar_no_main(self, repo: str | Path) -> list[str]:
        """Giro ocioso: reexecuta no main os node ids das lições de teste e fecha, marca obsoleta ou reabre."""
        self.unir_duplicatas()
        sha = sha_do_main(repo)
        nodes = sorted({alvo_de(lic) for lic in self._a_rodar(sha)})
        if not nodes:
            return []
        _, codigos = reexecutar_no_main(repo, nodes, sha)
        return self.checar_testes(sha, codigos.get, lambda node: impressao_no_main(repo, sha, node))

    def checar_testes(self, sha: str, rodar, impressao=None) -> list[str]:
        """`rodar(node_id)` devolve o exit code do pytest no main em `sha` (None = sem resultado);
        `impressao(node_id)`, a impressão do teste emprestado pelo alias (None = o teste não existe)."""
        tick, agora, log = self.s.tick, time.time(), []
        for lic in self._a_rodar(sha):
            checagens = json.loads(lic.get("checagens") or "[]")
            aberta = lic["status"] in ABERTAS
            node, alias = alvo_de(lic), not lic["node_id"]
            code = rodar(node)
            if code is None:
                continue
            checagem = {"sha": sha, "exit": int(code), "tick": tick, "em": agora}
            if alias:
                checagem["teste"] = impressao(node) if impressao else None
            mudou = alias and bool(checagens) and checagens[-1].get("teste") != checagem["teste"]
            checagens = (checagens + [checagem])[-10:]
            self.s.x("UPDATE licoes SET checagens=?, updated_at=? WHERE id=?", (json.dumps(checagens), agora, lic["id"]))
            ultimas = checagens[-VERDES_PARA_FECHAR:]
            if aberta and code in NAO_COLETADO and not alias:
                if lic["status"] != "obsoleta":
                    self.s.x("UPDATE licoes SET status='obsoleta' WHERE id=?", (lic["id"],))
                    log.append(f"lição #{lic['id']} obsoleta")
            elif aberta and len(ultimas) == VERDES_PARA_FECHAR and all(c["exit"] == 0 for c in ultimas) \
                    and len({c.get("teste") for c in ultimas}) == 1:
                self.s.x("UPDATE licoes SET status='validada', corrigida_tick=?, prevencao=? WHERE id=?",
                         (tick, f"Fechada: {node} passou no main (sha {sha[:12]}, exit 0 em {VERDES_PARA_FECHAR} "
                                f"execuções seguidas{', alias da causa' if alias else ''}); não repetir: {lic['descricao']}",
                          lic["id"]))
                log.append(f"lição #{lic['id']} fechada no sha {sha[:12]}")
                self.reply(f"Lição #{lic['id']} fechada: {node} passou no main {sha[:12]} "
                           f"{VERDES_PARA_FECHAR} vezes seguidas (exit 0).", "licao")
            elif aberta and code == 0 and lic["status"] == "obsoleta":
                self.s.x("UPDATE licoes SET status='aberta' WHERE id=?", (lic["id"],))
            elif not aberta and (code != 0 and (alias or code not in NAO_COLETADO) or mudou):
                self.s.x("UPDATE licoes SET status='reincidente', reincidencias=reincidencias+1, ultima_tick=? WHERE id=?",
                         (tick, lic["id"]))
                log.append(f"lição #{lic['id']} reaberta no sha {sha[:12]}")
                self.reply(f"REINCIDÊNCIA da lição #{lic['id']}: {node} "
                           f"{'mudou de corpo' if code == 0 else f'voltou a falhar (exit {code})'} no main {sha[:12]}.", "saude")
        return log

    # ------------------------------------------------------------ usar o que aprendeu
    def reclassificar_ambiente(self) -> list[int]:
        """Lição aberta como 'estrutural' cujo erro é de ambiente (GitHub 502, rede, limite) vira 'ambiente' e solta o
        item que abriu. No Mac (19/10) um 'HTTP Error 502: Bad Gateway' travou o planejador por ser lido como erro do loop."""
        ids = []
        for r in self.s.q("SELECT id, descricao, item_id FROM licoes WHERE classe!='ambiente' AND status IN ('aberta','em_correcao','reincidente')"):
            if not AMBIENTE.search(r["descricao"] or ""):
                continue
            agora = time.time()
            self.s.x("UPDATE licoes SET classe='ambiente', prevencao=?, updated_at=? WHERE id=?",
                     (f"Erro de ambiente (não é do loop): {r['descricao']}"[:500], agora, r["id"]))
            if r["item_id"]:
                self.s.x("UPDATE roadmap SET status='descartado', evidencia=?, updated_at=? WHERE id=? AND status='pendente'",
                         ("lição reclassificada como ambiente: não é erro do loop", agora, r["item_id"]))
            self.reply(f"Lição #{r['id']} reclassificada: era erro de ambiente, não do loop; não trava mais a evolução.", "licao")
            ids.append(r["id"])
        return ids

    def bloqueia_evolucao(self) -> bool:
        """Lição de estrutura ainda não corrigida: primeiro corrige, depois evolui."""
        try:
            self.reclassificar_ambiente()
        except Exception:  # noqa: BLE001 — reclassificar nunca impede de decidir
            pass
        return self.s.one("SELECT COUNT(*) n FROM licoes WHERE classe='estrutural' "
                          "AND status IN ('aberta','em_correcao','reincidente')")["n"] > 0

    def contexto(self, limite: int = 15) -> str:
        rows = self.s.q("SELECT id, status, assinatura, prevencao, reincidencias FROM licoes WHERE classe!='ambiente' AND status!='unida' "
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
                "ultimas": [dict(r) for r in self.s.q("SELECT id, assinatura, classe, status, descricao, ocorrencias, reincidencias, camada, "
                                                      "item_id, pr FROM licoes ORDER BY updated_at DESC LIMIT 12")]}


def _descricao(ponto: str, motivo: str) -> str:
    m = (motivo or "").strip().splitlines()
    linha = next((x for x in m if re.search(r"error|erro|falh|FAILED|\.py:\d+", x, re.I)), m[0] if m else "")
    return f"{ponto}: {linha.strip()[:200]}" if linha else ponto


def item_de(store, sujeito: str = "", item_id: int | None = None) -> tuple[int | None, str]:
    """(id, título) do item do roteiro: pelo id, pelo worktree `.circulo-wt-N`/`roteiro #N` ou pelo título exato."""
    if item_id is None and (m := DO_ITEM.search(sujeito or "")):
        item_id = int(m.group(1))
    r = (store.one("SELECT id, titulo FROM roadmap WHERE id=?", (item_id,)) if item_id is not None else
         store.one("SELECT id, titulo FROM roadmap WHERE titulo=? ORDER BY id DESC LIMIT 1", (sujeito,)) if sujeito else None)
    return (r["id"], r["titulo"]) if r else (None, "")


def registrar(ctx, ponto: str, ok: bool, **kw) -> dict | None:
    """Atalho para quem só tem o ctx: monitora sem nunca derrubar quem chamou."""
    lic = getattr(ctx, "licoes", None)
    if lic is None:
        return None
    try:
        return lic.verificar(ponto, ok, **kw)
    except Exception:  # noqa: BLE001 — monitorar nunca derruba o trabalho
        return None

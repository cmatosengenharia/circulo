"""Reparo do Developer antes do PR: passo determinístico primeiro, depois no máximo UMA rodada do agente.

Fica fora da constituição (estende o `SelfDeveloper`, sem mexer nele):
  1. developer:lint falhou → `ruff check --fix` (e `ruff format` nos arquivos novos) sem LLM, e reavalia.
     O que o autofix resolve não gasta token (Stripe Minions: nó determinístico antes do nó de agente).
  2. lint ou testes ainda falham → no máximo MAX_RODADAS_REPARO rodada do agente. O teto está aqui no código, não no
     prompt (Aider: contador de reflexões fixo). A entrada é a saída focada: resumo do pytest (`--tb=short -q`, ids dos
     testes que falharam) e o ruff conciso, truncados em ~LINHAS_FEEDBACK pelo final sem cortar o resumo.
  3. Cada rodada vira a verificação `developer:reparo`, com os tokens gastos.
  4. Falha que persiste depois da rodada: desiste sem PR e a lição fica registrada pela assinatura. A mesma assinatura
     não ganha outra rodada (Olausson et al., ICLR 2024: mais rodadas sem feedback melhor não pagam o custo).
  5. A constituição em camadas, em toda rodada do agente (a principal, o reparo e o conserto): somente leitura no SO
     antes (Codex: caminhos sensíveis read-only mesmo dentro da raiz gravável), restaurada do merge-base com a main
     depois (modificados, novos e apagados), cada reversão vira o evento `developer:constituicao_revertida`, e a lista
     vai no prompt do reparo. O gate do merge continua sendo a barreira independente.
  6. Teto de tokens por item, checado ANTES de cada chamada (o limite checado depois estoura: SWE-agent #1240):
     tokens já gastos no item + estimativa da próxima > max(2× a mediana dos PRs entregues em 24 h, piso fixo) →
     nenhuma chamada; o parcial fica guardado e o item vai para o fatiador, sem exceção. Os tetos contam no item raiz
     (os sub-itens herdam), no kv: o 2º seguido sem mudança de escopo bloqueia a árvore, com registro.
  7. A mesma falha 2x seguidas (node id + linha do erro normalizada, `assinatura_falha`) não ganha outra chamada:
     o item vai para o fatiador na hora, sem esperar as LIMITE falhas.
  8. Toda falha de developer:testes grava a causa normalizada (`causa_testes`: tipo de exceção + arquivo de teste, sem o
     caminho do worktree), para agregar falhas de testes diferentes.
  9. Pré-voo antes da 1ª chamada do item: os testes dos módulos que o item cita rodam na main limpa. Vermelhos lá, a
     base está quebrada: nenhuma chamada, lição `developer:base` com a causa, e o item volta para a fila (Agentless e
     SWE Atlas rodam os testes no código original antes de julgar o patch). A mesma base vermelha (`assinatura_falha`)
     2x seguidas no item → 'bloqueado_base', com um único evento por (item, assinatura) e o contador no kv; o item
     volta à fila quando a main muda, e o pré-voo decide de novo (pergunta #129: item #144 com 3786 falhas locais).
     Cada falha é upsert em `base_vermelha` por (item, assinatura, sha da main) com `ocorrencias` (Sentry); vermelha
     CONFIRMADA vezes no mesmo sha, o pré-voo só conta, sem rodar os testes de novo (item #163).
  10. Com o pytest do loop, `pytest --collect-only -q` roda antes da suíte (lição #9): erro de coleta barra ali, como
     developer:testes, e a lição sai assinada pelo módulo e pela exceção (`licoes.coletas`).
  11. Disjuntor do developer:abrir_pr (pergunta #55): cada barra grava no item a assinatura da causa
     (`licoes.assinatura_de`). A mesma 2x seguidas → o item vai para 'bloqueado', sem nova chamada ao agente nem ao
     pytest. A sonda de reabertura, no início de cada giro, devolve o item à fila quando os arquivos citados na barra
     (ou a main inteira, se ela não cita arquivo) mudam. Falha de lint/testes repetida segue para o fatiador (item 7).
  12. developer:abrir_pr:adiar com teto (pergunta #296, 13 falhas em 13): cada adiamento grava a causa normalizada
     (`adiado_do_item`) na tarefa pela impressão digital do título, não pelo id: o mesmo pedido recriado com outro id
     seguia adiando (pergunta #309). A mesma causa LIMITE_ADIAR vezes seguidas → a tarefa sai da fila como 'escalada'
     e abre um incidente por impressão (título + causa), sem novo adiamento (dead-letter queue com maxReceiveCount);
     causa diferente ou PR aberto zeram. 'escalada' não é 'bloqueado': a sonda do disjuntor não a reabre (pergunta #300).

`ruff format` só roda em arquivos criados pela mudança: o repositório não segue o `ruff format` e formatar um arquivo
existente reescreveria o arquivo inteiro (diff gigante, estilo da casa perdido, portão de tamanho estourado).
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import statistics
import subprocess
import sys
import time
from pathlib import Path

from . import pedido_claro
from .fatiador import CORTES
from .merge_gate import CONSTITUICAO
from .self_dev import (CORRECAO_LOCAL, LINT_CMD, DevResult, SelfDeveloper, _git, ambiente_isolado, build_self_dev,
                       garantir_ruff)

REPARO = "developer:reparo"
REVERTIDA = "developer:constituicao_revertida"
BASE = "developer:base"
TETO, REPETIDA = CORTES
PISO_TETO = 100_000
JANELA_TETO = 86400
ULTIMA_FALHA = "developer_ultima_falha"         # {worktree do item: assinatura_falha da última falha local}
PREFIXO_TITULO = re.compile(r"^(?:reparo|conserto do PR #\d+): ")
FALHA_PYTEST = re.compile(r"^(?:FAILED|ERROR) (\S+)(?: - (.*))?$", re.M)
FALHA_LINT = re.compile(r"^(\S+\.py):\d+:\d+: ([A-Z]+\d+\b.*)$", re.M)
PROTEGIDOS = (f"\nNUNCA altere a constituição (somente leitura; o que mudar nela é revertido antes do PR): "
              f"{', '.join(CONSTITUICAO)}.")
MAX_RODADAS_REPARO = 1
LINHAS_FEEDBACK = 60
ALTERADOS, NOVOS = "{alterados}", "{novos}"      # marcadores nos comandos de autofix: viram a lista de arquivos .py
SELECAO_CI = LINT_CMD[LINT_CMD.index("--select"):]  # --select E,F,W,B --ignore E501
RUFF_FIX = [[sys.executable, "-m", "ruff", "check", "--fix", *SELECAO_CI, ALTERADOS],
            [sys.executable, "-m", "ruff", "format", NOVOS]]
ERRO_LINT = re.compile(r":\d+:\d+: [A-Z]+\d+")
RESUMO_PYTEST = re.compile(r"^=+ short test summary info =+$")
BLOQUEADO = "bloqueado"
DISJUNTOR = "developer_disjuntor"               # {item: {"sig", "n", "chave", "texto"}}: a última barra do abrir_pr
BLOQUEADO_BASE = "bloqueado_base"
BASE_VERMELHA = "developer_base_vermelha"       # {item: {"sig", "n", "chave"}}: a última base vermelha do pré-voo
TETO_RAIZ = "developer_teto_raiz"              # {item raiz: {"n", "escopo"}}: tetos seguidos do item e dos sub-itens
CONFIRMADA = 2                                 # execuções vermelhas no mesmo sha da main até o pré-voo parar de rodar
ADIADO = "developer_adiado"                    # {título normalizado: {"causa", "n"}}: os adiamentos seguidos do abrir_pr
LIMITE_ADIAR = 3
ESCALADA = "escalada"
ARQUIVO_CITADO = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w-]+\.py)\b")


def tokens_do_item(store, titulo: str) -> tuple[int, int]:
    """(tokens, chamadas) do Developer no item: a rodada principal, o reparo e o conserto do PR."""
    item = PREFIXO_TITULO.sub("", titulo)
    gastos = [int(r["tokens"] or 0) for r in store.q("SELECT entrada, tokens FROM llm_calls WHERE papel='developer' "
                                                     "AND instr(entrada, ?) > 0", (item,))
              if PREFIXO_TITULO.sub("", r["entrada"] or "") == item]
    return sum(gastos), len(gastos)


def raiz_do_item(store, item_id: int) -> dict | None:
    """O item raiz da divisão: os sub-itens do fatiador (coluna `pai`) herdam dele a contagem de tetos."""
    r, vistos = store.one("SELECT id, pai, titulo, detalhe FROM roadmap WHERE id=?", (item_id,)), set()
    while r is not None and r["pai"] is not None and r["id"] not in vistos:
        vistos.add(r["id"])
        r = store.one("SELECT id, pai, titulo, detalhe FROM roadmap WHERE id=?", (r["pai"],)) or r
    return dict(r) if r else None


def teto_do_item(store, item_id: int) -> tuple[int, int]:
    """Conta mais um teto no item raiz, no kv (as `verificacoes` são podadas). (id da raiz, tetos seguidos): mudar o
    título ou o detalhe da raiz é mudar o escopo e zera a contagem."""
    raiz = raiz_do_item(store, item_id) or {"id": item_id, "titulo": "", "detalhe": ""}
    escopo = hashlib.sha1(f"{raiz['titulo']}\n{raiz['detalhe']}".encode()).hexdigest()
    todos = store.get(TETO_RAIZ) or {}
    antes = todos.get(str(raiz["id"])) or {}
    n = antes.get("n", 0) + 1 if antes.get("escopo") == escopo else 1
    store.set(TETO_RAIZ, {**todos, str(raiz["id"]): {"n": n, "escopo": escopo}})
    return raiz["id"], n


def bloquear_arvore(store, raiz: int, evidencia: str) -> None:
    """A raiz e os sub-itens não feitos saem da fila como 'bloqueado', todos com o registro do bloqueio."""
    store.x("WITH RECURSIVE arvore(id) AS (SELECT ? UNION SELECT r.id FROM roadmap r JOIN arvore a ON r.pai = a.id) "
            "UPDATE roadmap SET status=?, desativado=1, evidencia=?, updated_at=? "
            "WHERE id IN (SELECT id FROM arvore) AND status!='feito'", (raiz, BLOQUEADO, evidencia, time.time()))


def barra_do_item(store, item_id: int, sig: str, chave: str, texto: str = "") -> bool:
    """Grava a barra do abrir_pr no item. True = a mesma assinatura 2x seguidas: o disjuntor abre."""
    todos = store.get(DISJUNTOR) or {}
    antes = todos.get(str(item_id)) or {}
    n = antes.get("n", 0) + 1 if antes.get("sig") == sig else 1
    store.set(DISJUNTOR, {**todos, str(item_id): {"sig": sig, "n": n, "chave": chave, "texto": texto[:2000]}})
    return n >= 2


def adiado_do_item(store, chave, causa: str | None) -> int:
    """Conta mais um adiamento da tarefa (`chave`) com a causa; devolve os seguidos com ela. `causa=None` (o PR passou
    do adiamento) zera a contagem."""
    todos = store.get(ADIADO) or {}
    antes = todos.pop(str(chave), None) or {}
    n = 0 if causa is None else antes.get("n", 0) + 1 if antes.get("causa") == causa else 1
    store.set(ADIADO, {**todos, **({str(chave): {"causa": causa, "n": n}} if n else {})})
    return n


def incidente_de_adiamento(store, digital: str, titulo: str, motivo: str) -> None:
    """Abre (ou soma no aberto) o incidente da tarefa escalada: um por impressão digital."""
    from .pre_pr import ADIAR_PONTO
    agora, tick = time.time(), store.tick
    store.x("INSERT INTO incidents(fingerprint,stage,kind,message,count,first_seen,last_seen,first_tick,last_tick,status) "
            "VALUES(?,?,'Escalada',?,1,?,?,?,?,'aberto') ON CONFLICT(fingerprint) DO UPDATE SET count=count+1, "
            "last_seen=excluded.last_seen, last_tick=excluded.last_tick, status='aberto'",
            (f"adiar:{digital}", ADIAR_PONTO, f"{titulo}: {motivo}"[:500], agora, agora, tick, tick))


def registrar_base(store, item_id: int, sig: str, sha: str, causa: str = "") -> int:
    """Upsert da falha local de base vermelha por (item, assinatura, sha da main): a chave repetida soma `ocorrencias` e
    atualiza `ultima_vez`, sem linha nova. Devolve as ocorrências da chave."""
    agora = time.time()
    store.x("INSERT INTO base_vermelha(item_id,assinatura,sha,causa,ocorrencias,primeira_vez,ultima_vez) "
            "VALUES(?,?,?,?,1,?,?) ON CONFLICT(item_id,assinatura,sha) "
            "DO UPDATE SET ocorrencias=ocorrencias+1, ultima_vez=excluded.ultima_vez",
            (item_id, sig, sha, (causa or "")[:300], agora, agora))
    return store.one("SELECT ocorrencias FROM base_vermelha WHERE item_id=? AND assinatura=? AND sha=?",
                     (item_id, sig, sha))["ocorrencias"]


def base_confirmada(store, item_id: int, sha: str) -> dict | None:
    """A base vermelha que já falhou CONFIRMADA vezes neste sha da main: o resultado é conhecido, os testes não rodam."""
    r = store.one("SELECT assinatura, causa FROM base_vermelha WHERE item_id=? AND sha=? AND ocorrencias>=? "
                  "ORDER BY ultima_vez DESC LIMIT 1", (item_id, sha, CONFIRMADA))
    return dict(r) if r else None


def saida_focada(texto: str, limite: int = LINHAS_FEEDBACK) -> str:
    """As últimas `limite` linhas, mas o resumo do pytest (ids dos testes que falharam) entra sempre inteiro."""
    linhas = (texto or "").rstrip().splitlines()
    i = next((n for n in range(len(linhas) - 1, -1, -1) if RESUMO_PYTEST.match(linhas[n].strip())), None)
    if i is None:
        return "\n".join(linhas[-limite:])
    corpo, resumo = linhas[:i], linhas[i:]
    resto = max(0, limite - len(resumo))
    return "\n".join((corpo[-resto:] if resto else []) + resumo)


def _normal(linha: str) -> str:
    linha = re.sub(r"0x[0-9a-f]+", "0x?", linha, flags=re.I)
    linha = re.sub(r"(?<![\w.])/(?:[^/\s:]+/)+", "", linha)          # diretórios absolutos (tmp) mudam a cada rodada
    return re.sub(r"\s+", " ", linha).strip()


def assinatura_falha(saida: str) -> str:
    """Node id + linha do erro normalizada de cada falha do pytest; arquivo + código + mensagem de cada erro do ruff
    (sem linha e coluna, que mudam com a edição). '' = falha sem formato reconhecido (nunca conta como repetida)."""
    falhas = [f"{n} - {m}" for n, m in FALHA_PYTEST.findall(saida or "")]
    falhas += [f"{p}: {e}" for p, e in FALHA_LINT.findall(saida or "")]
    return "\n".join(sorted({_normal(f) for f in falhas}))


def _excecao(mensagem: str) -> str:
    m = re.match(r"(?:[\w.]+\.)?([A-Z]\w*(?:Error|Exception|Exit|Interrupt|Timeout))\b", mensagem or "")
    return m.group(1) if m else "AssertionError" if (mensagem or "").startswith("assert") else "Falha"


def causa_testes(saida: str) -> str:
    """Tipo de exceção + arquivo de teste de cada falha do pytest, sem o caminho do worktree (`.circulo-wt-*`) nem
    diretórios absolutos. 'sem_resumo' = a saída não tem o resumo do pytest (timeout, coleta abortada)."""
    causas = set()
    for node, msg in FALHA_PYTEST.findall(saida or ""):
        arquivo = re.sub(r"^.*/\.circulo-wt-[^/]+/", "", node.split("::")[0])
        causas.add(f"{_excecao(msg)}@{_normal(arquivo)}")
    return ", ".join(sorted(causas)) or "sem_resumo"


def _ambiente() -> dict:
    """O ambiente isolado dos portões, sem bytecode: o `git add -A` levaria o `__pycache__` dos testes para o PR."""
    return {**ambiente_isolado(), "PYTHONDONTWRITEBYTECODE": "1"}


class DeveloperComReparo(SelfDeveloper):
    def __init__(self, *a, fix_cmds: list[list[str]] | None = None, piso_teto: int = PISO_TETO, **kw):
        auto_testes = kw.get("test_cmd") is None
        super().__init__(*a, **kw)
        if auto_testes:
            self.test_cmd = [*self.test_cmd, "--tb=short"]
        # lição #9: com o pytest do loop, a coleta é um portão antes da suíte (barato: só importa os módulos de teste)
        self.coleta_cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q"] if auto_testes else None
        self.fix_cmds = fix_cmds        # None = automático: o ruff --fix do CI quando o lint é o ruff do CI
        self.piso_teto = piso_teto
        self._base: str | None = None
        self._rodada = 0
        self._item_id: int | None = None   # item no portão do PR (o reparo guarda o parcial dele ao cortar)
        self._consertando = False
        self._repetida = False
        self._cortado = ""
        self._base_quebrada = ""
        self._base_status = "pendente"
        self._disjuntor = self._escalada = ""
        self._teto_bloqueado: tuple[int, str] | None = None

    def run_once(self, item_id: int | None = None, autorizado: bool = False) -> DevResult:
        self._reabrir()
        self._reabrir_base()
        bloqueado = self.s.one("SELECT status, evidencia FROM roadmap WHERE id=? AND status IN (?,?,?)",
                               (item_id, BLOQUEADO, BLOQUEADO_BASE, ESCALADA))
        if bloqueado:
            return DevResult(item_id, bloqueado["status"], bloqueado["evidencia"])
        item = self.pick(item_id)
        if item:
            pedido_claro.registrar(self.s, item)        # só mede quantos pedidos chegam sem os 3 campos; não bloqueia
        pedido_claro.registrar_sem_veredito(self.s)
        veto = self._vetar(item) if item else None
        if veto:
            return veto
        self._rodada, self._cortado, self._base_quebrada, self._disjuntor, self._escalada = 0, "", "", "", ""
        self._teto_bloqueado = None
        r = super().run_once(item_id=item_id, autorizado=autorizado)
        if self._teto_bloqueado:                 # o SelfDeveloper devolveu o item à fila depois do corte: bloqueia de novo
            bloquear_arvore(self.s, *self._teto_bloqueado)
            return DevResult(r.item_id, BLOQUEADO, self._teto_bloqueado[1])
        if r.status == "proposto" and r.item_id is not None:
            todos = self.s.get(TETO_RAIZ) or {}
            if todos.pop(str((raiz_do_item(self.s, r.item_id) or {"id": r.item_id})["id"]), None):
                self.s.set(TETO_RAIZ, todos)     # entregou: os tetos deixam de ser seguidos
        if self._escalada and r.status == "testes_falharam":
            self._set_item(r.item_id, ESCALADA, self._escalada[:300])
            return r
        if self._disjuntor and r.status == "testes_falharam":
            self._set_item(r.item_id, BLOQUEADO, self._disjuntor[:300])
            return r
        if self._base_quebrada and r.status == "agente_falhou" and not r.pr:
            self._set_item(r.item_id, self._base_status, self._base_quebrada[:300])
            return DevResult(r.item_id, "base_quebrada", self._base_quebrada)
        if self._cortado and r.status == "agente_falhou" and not r.pr:
            self._set_item(r.item_id, "pendente", f"{self._cortado}; vai para o fatiador")
            return DevResult(r.item_id, "teto", self._cortado)
        return r

    # ------------------------------------------------------------ disjuntor do abrir_pr
    def _chave(self, texto: str) -> str:
        """O que precisa mudar para a barra deixar de ser a mesma: os arquivos que ela cita, na main; sem arquivo, a main."""
        ref = "origin/main" if _git(["rev-parse", "--verify", "-q", "origin/main"], self.repo, check=False) else "HEAD"
        limpo = re.sub(r"\S*/\.circulo-wt-[^/\s]+/", "", texto or "")
        citados = sorted(set(ARQUIVO_CITADO.findall(limpo)))
        if not citados:
            return _git(["rev-parse", f"{ref}^{{tree}}"], self.repo, check=False)
        return " ".join(f"{c}={_git(['rev-parse', f'{ref}:{c}'], self.repo, check=False)}" for c in citados)

    def _reabrir(self) -> None:
        """Sonda do disjuntor: o item bloqueado volta para a fila quando o que a barra cita mudou na main."""
        todos = self.s.get(DISJUNTOR) or {}
        for r in self.s.q("SELECT id FROM roadmap WHERE status=?", (BLOQUEADO,)):
            d = todos.get(str(r["id"]))
            if d is None or self._chave(d.get("texto", "")) == d.get("chave"):
                continue                      # sem barra do abrir_pr: o bloqueio é do disjuntor do roadmap
            todos.pop(str(r["id"]), None)
            self.s.set(DISJUNTOR, todos)
            self._set_item(r["id"], "pendente", "disjuntor fechado: o que a barra do abrir_pr citava mudou na main")

    def _reabrir_base(self) -> None:
        """O item de base vermelha volta à fila quando a main muda: o pré-voo roda de novo (verde segue; a mesma falha
        bloqueia na hora, porque o contador continua)."""
        vermelhas = self.s.get(BASE_VERMELHA) or {}
        for r in self.s.q("SELECT id FROM roadmap WHERE status=?", (BLOQUEADO_BASE,)):
            d = vermelhas.get(str(r["id"]))
            if d is None or self._chave("") != d.get("chave"):
                self._set_item(r["id"], "pendente", "a main mudou desde a base vermelha: o pré-voo roda de novo")

    def _vetar(self, item: dict) -> DevResult | None:
        """Portão de reincidência antes de qualquer gasto: o item vai para 'descartado' com a causa; só o redrive reabre."""
        from .licoes import registrar as monitorar
        from .portao_previo import DESCARTADO, LIMIAR, VETAR, VETO_PONTO, decidir, fechados_sem_merge, normalizar
        fechados = fechados_sem_merge(self.s)
        d = decidir(item["titulo"], fechados)
        if d.acao != VETAR:
            return None
        checks = next(c for t, c in fechados if normalizar(t) == normalizar(item["titulo"]))
        texto = (f"descartado ({d.causa}): os últimos {LIMIAR} PRs deste título fecharam sem merge com os mesmos checks "
                 f"falhando ({', '.join(sorted(checks))}); reabra com `circulo redrive --item {item['id']}`")
        monitorar(self.ctx, VETO_PONTO, False, sujeito=item["titulo"][:120], motivo=texto, causa=d.causa, licao=False)
        self._set_item(item["id"], DESCARTADO, texto[:300])
        return DevResult(item["id"], VETAR, texto)

    def consertar(self):
        self._consertando = True
        try:
            return super().consertar()
        finally:
            self._consertando = False

    # ------------------------------------------------------------ teto de tokens por item
    def _tokens_do_item(self, titulo: str) -> tuple[int, int]:
        return tokens_do_item(self.s, titulo)

    def teto(self) -> int:
        """max(2× a mediana de tokens dos PRs entregues em 24 h, piso): um dia ruim não encolhe o teto abaixo do piso."""
        por_pr = [self._tokens_do_item(r["titulo"])[0]
                  for r in self.s.q("SELECT titulo FROM prs WHERE status='mergeado' AND updated_at>=?",
                                    (time.time() - JANELA_TETO,))]
        return max(2 * int(statistics.median(por_pr)) if por_pr else 0, self.piso_teto)

    def _estimativa(self, tokens: int, chamadas: int) -> int:
        """A próxima chamada custa a média das anteriores do item (ou do Developer em 24 h, se é a primeira)."""
        if chamadas:
            return tokens // chamadas
        r = self.s.one("SELECT AVG(tokens) t FROM llm_calls WHERE papel='developer' AND tokens > 0 AND created_at>=?",
                       (time.time() - JANELA_TETO,))
        return int(r["t"] or 0)

    def _cortar(self, wt: Path, motivo: str) -> dict:
        """Sem chamada: o item vai para o fatiador. No reparo o parcial vira commit local da branch (a rodada principal
        já guarda o dela; o conserto está num PR empurrado)."""
        from .licoes import registrar as monitorar
        monitorar(self.ctx, TETO, False, sujeito=wt.name, licao=False, motivo=motivo)
        self._fora_da_fila_se_preso(wt.name, motivo)
        if self._item_id is not None and not self._consertando:
            wip = (self.s.get("self_dev_wip") or {}).get(str(self._item_id))
            self._guardar_parcial(self._item_id, _git(["rev-parse", "--abbrev-ref", "HEAD"], wt), wt, wip)
        self._cortado = motivo
        return {"ok": False, "tokens": 0, "log": motivo, "teto": True}

    def _fora_da_fila_se_preso(self, sujeito: str, motivo: str) -> None:
        """O teto do item é acumulado e não volta a cair: um item cortado de novo nunca mais anda. Antes, como itens de
        erro vêm primeiro na fila, ele era pego a cada hora, cortado sem chamar o agente e devolvido — e a fila inteira
        parava atrás dele (22→23/10: 17 h, item #144). A contagem é do item raiz (`teto_do_item`), no kv: contada pelo
        nome do worktree nas `verificacoes`, cada sub-item do fatiador zerava e a poda apagava (859 tetos em 24 h).
        No 2º teto seguido a árvore inteira vai para 'bloqueado', com registro, e espera a divisão pelo Arquiteto."""
        from .licoes import registrar as monitorar
        from .roadmap import PONTO
        item_id = self._item_id
        if item_id is None and sujeito.startswith(".circulo-wt-") and sujeito[12:].isdigit():
            item_id = int(sujeito[12:])                 # o corte vem antes do portão: o id está no nome do worktree
        if item_id is None or self._consertando:
            return
        raiz, n = teto_do_item(self.s, item_id)
        if n < 2:
            return
        texto = (f"depende de você: bloqueado pelo disjuntor do teto, {n} tetos seguidos no item #{raiz} e nos sub-itens "
                 f"({motivo[:120]}); nenhuma chamada nova ao Developer até o Arquiteto dividir o item")[:300]
        self._teto_bloqueado = (raiz, texto)
        bloquear_arvore(self.s, raiz, texto)
        monitorar(self.ctx, PONTO, False, sujeito=f"roteiro #{raiz}", item_id=raiz, motivo=texto, causa="teto", licao=False)
        if callable(getattr(self.ctx, "reply", None)):
            self.ctx.reply(f"Developer: o item #{raiz} bateu o teto de tokens {n}× seguidas (contando os sub-itens) e foi "
                           "bloqueado; precisa ser dividido. O resto da fila segue.", "saude")

    def _mesma_falha(self, wt: Path, saida: str) -> bool:
        """A falha é a mesma da rodada anterior do item: pede a divisão em vez de outra chamada."""
        from .licoes import registrar as monitorar
        sig, todas = assinatura_falha(saida), self.s.get(ULTIMA_FALHA) or {}
        repetida = bool(sig) and todas.get(wt.name) == sig
        self.s.set(ULTIMA_FALHA, {**todas, wt.name: sig})
        if repetida:
            monitorar(self.ctx, REPETIDA, False, sujeito=wt.name, licao=False,
                      motivo=f"repetiu a mesma falha da rodada anterior: {sig[:300]}")
        return repetida

    # ------------------------------------------------------------ constituição em camadas
    def _travar(self, wt: Path) -> dict[Path, int]:
        """Somente leitura no SO para os caminhos protegidos (pastas inclusive: nada novo nem apagado dentro).
        Devolve os modos originais, para destravar depois."""
        modos: dict[Path, int] = {}
        for nome in CONSTITUICAO:
            raiz = wt / nome
            if not raiz.exists():
                continue
            caminhos = [raiz, *raiz.rglob("*")] if raiz.is_dir() else [raiz]
            for p in sorted(caminhos, key=lambda p: len(p.parts), reverse=True):   # de dentro para fora
                if p.is_symlink():
                    continue
                modos[p] = stat.S_IMODE(p.stat().st_mode)
                os.chmod(p, modos[p] & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        return modos

    @staticmethod
    def _destravar(modos: dict[Path, int]) -> None:
        for p, modo in sorted(modos.items(), key=lambda x: len(x[0].parts)):     # de fora para dentro
            try:
                os.chmod(p, modo)
            except FileNotFoundError:
                pass

    def _merge_base(self, wt: Path) -> str:
        if self._base:
            return self._base
        for ref in ("origin/main", "main"):
            mb = _git(["merge-base", "HEAD", ref], wt, check=False)
            if mb:
                return mb
        return "HEAD"

    def _reverter(self, wt: Path, titulo: str) -> list[str]:
        """Restaura a constituição do merge-base com a main: modificados, apagados, novos no índice e soltos."""
        base = self._merge_base(wt)
        rastreados = _git(["diff", "--name-only", base, "--", *CONSTITUICAO], wt, check=False).splitlines()
        soltos = _git(["ls-files", "--others", "--exclude-standard", "--", *CONSTITUICAO], wt, check=False).splitlines()
        if rastreados:
            _git(["restore", f"--source={base}", "--staged", "--worktree", "--", *rastreados], wt, check=False)
        if soltos:
            _git(["clean", "-fdq", "--", *CONSTITUICAO], wt, check=False)
        caminhos = sorted(set(rastreados + soltos))
        if caminhos:
            from .licoes import registrar as monitorar
            monitorar(self.ctx, REVERTIDA, True, sujeito=titulo[:120], licao=False,
                      motivo=f"rodada {self._rodada}: {', '.join(caminhos)} restaurados de {base[:12]}")
        return caminhos

    # ------------------------------------------------------------ pré-voo na main limpa
    @staticmethod
    def _testes_afetados(wt: Path, texto: str) -> list[str]:
        """Os arquivos de teste (`test_<módulo>.py`, `test_<módulo>_*.py`) dos módulos que o texto do item cita."""
        arquivos = _git(["ls-files", "*.py"], wt, check=False).splitlines()
        testes = [f for f in arquivos if Path(f).name.startswith("test_")]
        modulos = {Path(f).stem for f in arquivos if f not in testes} - {"__init__", "conftest"}
        citados = {m for m in modulos if re.search(rf"(?<![\w-]){re.escape(m)}(?:\.py)?\b", texto)}
        return sorted(t for t in testes if any(Path(t).stem == f"test_{m}" or Path(t).stem.startswith(f"test_{m}_")
                                               for m in citados))

    def _preflight(self, wt: Path, titulo: str) -> str:
        """Roda na main limpa só os testes dos módulos que o item cita. Vermelhos: a lição `developer:base` com a causa
        e o motivo para não chamar o agente. '' = segue (verdes, nada a rodar, ou o worktree já não é a main limpa)."""
        if _git(["status", "--porcelain"], wt, check=False) or _git(["rev-parse", "HEAD"], wt) != self._merge_base(wt):
            return ""
        r = self.s.one("SELECT id, detalhe FROM roadmap WHERE titulo=? ORDER BY updated_at DESC LIMIT 1", (titulo,))
        testes = self._testes_afetados(wt, f"{titulo}\n{r['detalhe'] if r else ''}")
        if not testes:
            return ""
        sha, vermelhas, chave = _git(["rev-parse", "HEAD"], wt), self.s.get(BASE_VERMELHA) or {}, str(r["id"]) if r else ""
        conhecida = base_confirmada(self.s, r["id"], sha) if r else None
        if conhecida:
            saida, causa, sig = "", conhecida["causa"], conhecida["assinatura"]
        else:
            try:
                p = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=short", *testes], cwd=wt,
                                   capture_output=True, text=True, timeout=900, env=_ambiente())
            except subprocess.TimeoutExpired:
                return ""
            if p.returncode in (0, 5):               # 5 = nenhum teste coletado
                if vermelhas.pop(chave, None):
                    self.s.set(BASE_VERMELHA, vermelhas)
                return ""
            saida = p.stdout + p.stderr
            causa = causa_testes(saida)
            sig = assinatura_falha(saida) or causa
        from .licoes import registrar as monitorar
        antes = vermelhas.get(chave) or {}
        n = antes.get("n", 0) + 1 if r and antes.get("sig") == sig else 1
        if r:
            self.s.set(BASE_VERMELHA, {**vermelhas, chave: {"sig": sig, "n": n, "chave": self._chave("")}})
            registrar_base(self.s, r["id"], sig, sha, causa)
        if n == 1:                                   # um evento por (item, assinatura); as repetições ficam no contador
            monitorar(self.ctx, BASE, False, sujeito=titulo[:120], motivo=saida_focada(saida) or causa, causa=causa,
                      item_id=r["id"] if r else None)
        self._base_status = BLOQUEADO_BASE if n >= 2 else "pendente"
        self._base_quebrada = (f"base quebrada: {causa} já falha na main; nenhuma chamada ao agente"
                               + (f"; a mesma falha {n}x seguidas: fora da fila até a main mudar" if n >= 2 else ""))
        return self._base_quebrada

    def _agente(self, task: str, wt: Path, titulo: str, papel: str = "developer", item_id: int | None = None) -> dict:
        if self._rodada == 0 and papel == "developer" and not self._consertando and not PREFIXO_TITULO.match(titulo):
            quebrada = self._preflight(wt, titulo)
            if quebrada:
                return {"ok": False, "tokens": 0, "log": quebrada}
        tokens, chamadas = self._tokens_do_item(titulo)
        estimativa, teto = self._estimativa(tokens, chamadas), self.teto()
        if tokens + estimativa > teto:
            return self._cortar(wt, f"teto de tokens do item: {tokens} gastos + ~{estimativa} da próxima chamada > {teto}")
        self._rodada += 1
        modos = self._travar(wt)
        try:
            return super()._agente(task, wt, titulo, papel, item_id=item_id)
        finally:
            self._destravar(modos)
            self._reverter(wt, titulo)

    # ------------------------------------------------------------ passo determinístico
    def _resolver_lint(self) -> None:
        if self.lint_cmd is None:
            self.lint_cmd = [sys.executable, *LINT_CMD, "--output-format", "concise"] if garantir_ruff() else []
        if self.fix_cmds is None:
            self.fix_cmds = RUFF_FIX if self.lint_cmd[1:1 + len(LINT_CMD)] == LINT_CMD else []

    def _arquivos_py(self, wt: Path) -> tuple[list[str], list[str]]:
        # sem `git add`: no conserto pode haver um merge com conflito em andamento, que não pode ser dado por resolvido
        base = self._base or "HEAD"
        soltos = _git(["ls-files", "--others", "--exclude-standard"], wt, check=False).splitlines()
        alterados = _git(["diff", "--name-only", "--diff-filter=AM", base], wt, check=False).splitlines() + soltos
        novos = _git(["diff", "--name-only", "--diff-filter=A", base], wt, check=False).splitlines() + soltos
        return [f for f in alterados if f.endswith(".py")], [f for f in novos if f.endswith(".py")]

    def _autofix(self, wt: Path) -> bool:
        """Aplica os autofixes sem LLM nos arquivos da mudança. True se algum comando rodou."""
        alterados, novos = self._arquivos_py(wt)
        rodou = False
        for cmd in self.fix_cmds or []:
            argv = []
            for x in cmd:
                argv += alterados if x == ALTERADOS else novos if x == NOVOS else [x]
            if (ALTERADOS in cmd and not alterados) or (NOVOS in cmd and not novos):
                continue
            subprocess.run(argv, cwd=wt, capture_output=True, text=True, timeout=300, env=_ambiente())
            rodou = True
        return rodou

    def verificar(self, wt: Path, registrar: bool = True) -> tuple[bool, str]:
        """O mesmo que o CI (lint e testes), com o autofix do lint antes de dar o lint por reprovado.
        A saída que volta é a focada (é ela que alimenta a rodada do agente)."""
        self._resolver_lint()
        etapas = ([("lint", self.lint_cmd)] if self.lint_cmd else []) + \
            ([("coleta", self.coleta_cmd)] if self.coleta_cmd else []) + [("testes", self.test_cmd)]
        from .licoes import registrar as monitorar

        def rodar(cmd):
            return subprocess.run(cmd, cwd=wt, capture_output=True, text=True, timeout=900, env=_ambiente())

        for nome, cmd in etapas:
            p = rodar(cmd)
            if p.returncode != 0 and nome == "lint" and self._autofix(wt):
                antes = len(ERRO_LINT.findall(p.stdout + p.stderr))
                p = rodar(cmd)
                depois = len(ERRO_LINT.findall(p.stdout + p.stderr)) if p.returncode != 0 else 0
                if registrar:
                    monitorar(self.ctx, "developer:autofix", p.returncode == 0, sujeito=str(wt.name), licao=False,
                              motivo=f"ruff --fix sem LLM: {antes} erro(s) de lint antes, {depois} depois")
            if p.returncode != 0:
                saida = saida_focada(p.stdout + p.stderr)
                if registrar:
                    self._repetida = self._mesma_falha(wt, saida) or self._repetida
                    monitorar(self.ctx, f"developer:{'lint' if nome == 'lint' else 'testes'}", False, sujeito=str(wt.name),
                              motivo=saida, causa=causa_testes(p.stdout + p.stderr) if nome != "lint" else None)
                return False, saida
            if registrar and nome != "coleta":
                monitorar(self.ctx, f"developer:{nome}", True, sujeito=str(wt.name))
        if registrar:
            self.s.set(ULTIMA_FALHA, {**(self.s.get(ULTIMA_FALHA) or {}), wt.name: ""})   # verde: nada a repetir
        return True, ""

    # ------------------------------------------------------------ portão de abrir PR com 1 rodada de reparo
    def _ja_desistiu(self, sig: str) -> bool:
        """Essa falha já resistiu a uma rodada de reparo e a lição segue aberta: outra rodada não paga o custo."""
        from .licoes import licao_de
        lic = licao_de(self.s, sig)
        return lic is not None and lic["status"] in ("aberta", "em_correcao", "reincidente")

    def _adiar(self, item_id: int | None, titulo: str) -> str:
        """Portão pré-PR: o motivo do adiamento ('' = abre). Na LIMITE_ADIAR-ésima vez seguida com a mesma causa, o
        disjuntor manda o item para triagem."""
        from .licoes import registrar as monitorar
        from .merge_gate import required_checks
        from .impressao_pr import impressao
        from .pre_pr import ADIAR, ADIAR_PONTO, checks_dos_prs, conserta_main, decidir, ler_main
        d = decidir(*ler_main(self.gh), conserta_main=conserta_main(self.s, item_id),
                    historico=checks_dos_prs(self.s, time.time()), obrigatorios=required_checks())
        tarefa = PREFIXO_TITULO.sub("", titulo)          # o mesmo pedido recriado com outro id segue a mesma contagem
        n = adiado_do_item(self.s, impressao(tarefa, ()), d.causa if d.acao == ADIAR else None)
        if d.acao != ADIAR:
            return ""
        texto = (f"- CI da main ou dos últimos PRs: adiado ({d.causa}, {n}/{LIMITE_ADIAR} seguidas); um PR agora "
                 "falharia por motivo externo, nada foi enviado")
        if n >= LIMITE_ADIAR:
            self._escalada = f"escalada para triagem: adiado {n}x seguidas pela mesma causa ({d.causa}); não adia de novo"
            texto += f"\n({self._escalada})"
            incidente_de_adiamento(self.s, impressao(tarefa, (d.causa,)), tarefa, self._escalada)
        if n <= LIMITE_ADIAR:
            monitorar(self.ctx, ADIAR_PONTO, False, sujeito=titulo, motivo=texto, causa=d.causa, licao=False)
        return texto

    def portao_pr(self, wt: Path, base: str, item_id: int | None, titulo: str) -> tuple[bool, str]:
        from .licoes import assinatura_de
        from .licoes import registrar as monitorar
        from .neuronios import (ABRIR_PR, Resultado, avaliar_aprendidos, causa_da_falha, diff_do_worktree, portoes_natos_pr,
                                registrar)
        adiado = self._adiar(item_id, titulo)
        if adiado:
            return False, adiado
        self._base, self._item_id, self._repetida = base, item_id, False
        texto, rodada = "", None          # rodada = {"sig", "tokens"} depois que o agente reparou
        try:
            for tentativa in range(1 + MAX_RODADAS_REPARO):
                arquivos, adicionadas = diff_do_worktree(wt, base, _git)
                falhas = registrar(self.ctx, ABRIR_PR, portoes_natos_pr(arquivos, adicionadas), titulo)
                if not falhas:
                    ok, saida = self.verificar(wt)
                    falhas = [] if ok else [Resultado("lint e testes (iguais ao CI)", False, saida)]
                if not falhas:
                    # reprodução primeiro, igual ao SelfDeveloper (este override pulava o portão: "Reprodução: n/a" nos PRs)
                    from .reproducao import reproduz
                    try:
                        ok, det, _ = reproduz(wt, base, None, env=_ambiente())
                    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:   # sem conseguir conferir, não prova: barra
                        ok, det = False, f"não consegui montar o código antigo para reproduzir: {exc}"
                    falhas = registrar(self.ctx, ABRIR_PR, [Resultado("reprodução primeiro", ok, "" if ok else det)], titulo)
                    self.evidencia_pr = det.splitlines()[0] if ok else ""
                if not falhas:
                    falhas = registrar(self.ctx, ABRIR_PR, avaliar_aprendidos(self.s, ABRIR_PR, wt, adicionadas,
                                                                              _ambiente(), item_id), titulo)
                if not falhas:
                    if rodada:
                        monitorar(self.ctx, REPARO, True, sujeito=titulo, assinatura=rodada["sig"],
                                  motivo=f"rodada 1/{MAX_RODADAS_REPARO} resolveu; {rodada['tokens']} tokens")
                    monitorar(self.ctx, ABRIR_PR, True, sujeito=titulo)
                    return True, ""
                # a saída de lint/testes já vem focada (resumo inteiro); os outros portões são curtos
                texto = "\n".join(f"- {f.portao}: {f.motivo if f.portao.startswith('lint e testes') else f.motivo[-700:]}"
                                  for f in falhas)
                if rodada:
                    # a falha persistiu depois da rodada: desiste e a lição fica com a assinatura de antes do reparo
                    monitorar(self.ctx, REPARO, False, sujeito=titulo, assinatura=rodada["sig"],
                              motivo=f"rodada 1/{MAX_RODADAS_REPARO} não resolveu; {rodada['tokens']} tokens\n{texto}")
                    break
                sig = assinatura_de(REPARO, texto)
                if tentativa == MAX_RODADAS_REPARO or self._repetida or self._ja_desistiu(sig):
                    if self._repetida:
                        texto += "\n(reparo não repetido: a mesma falha da rodada anterior; o item vai para o fatiador)"
                    elif tentativa < MAX_RODADAS_REPARO:
                        texto += f"\n(reparo não repetido: a mesma falha já resistiu a uma rodada; lição {sig})"
                    break
                out = self._agente(CORRECAO_LOCAL.format(titulo=titulo, falhas=texto, licoes=self._licoes_txt(item_id))
                                   + PROTEGIDOS, wt, f"reparo: {titulo}")
                if out.get("teto"):
                    texto += f"\n(reparo não chamado: {out['log']}; o item vai para o fatiador)"
                    break
                rodada = {"sig": sig, "tokens": int(out.get("tokens") or 0)}
                if not out.get("ok"):
                    # agente que parou (limite da conta, máximo de passos) não prova que a falha resiste: sem lição
                    monitorar(self.ctx, REPARO, False, sujeito=titulo, assinatura=sig, licao=False,
                              motivo=f"o agente terminou com erro na rodada; {rodada['tokens']} tokens")
                    break
            monitorar(self.ctx, ABRIR_PR, False, sujeito=titulo, motivo=texto, causa=causa_da_falha(falhas))
            if item_id is not None and not self._consertando:
                sig = assinatura_de(ABRIR_PR, texto)
                # a mesma falha de lint/testes 2x já pede a divisão ao fatiador: bloquear tiraria o item de lá
                if barra_do_item(self.s, item_id, sig, self._chave(texto), texto) and not (self._repetida or self._cortado):
                    self._disjuntor = f"disjuntor: a mesma barra 2x seguidas ({sig}); só volta quando o que ela cita mudar"
                    texto += f"\n({self._disjuntor})"
            return False, texto
        finally:
            self._base = self._item_id = None


def build_developer(ctx) -> DeveloperComReparo | None:
    """O Developer do loop, com o reparo limitado. Mesmas condições do `build_self_dev` (nunca dentro de testes)."""
    dev = build_self_dev(ctx)
    return None if dev is None else DeveloperComReparo(ctx, dev.repo, dev.agent, dev.gh, test_cmd=dev.test_cmd, lint_cmd=dev.lint_cmd)

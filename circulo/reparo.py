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
     nenhuma chamada; o parcial fica guardado e o item vai para o fatiador, sem exceção.
  7. A mesma falha 2x seguidas (node id + linha do erro normalizada, `assinatura_falha`) não ganha outra chamada:
     o item vai para o fatiador na hora, sem esperar as LIMITE falhas.

`ruff format` só roda em arquivos criados pela mudança: o repositório não segue o `ruff format` e formatar um arquivo
existente reescreveria o arquivo inteiro (diff gigante, estilo da casa perdido, portão de tamanho estourado).
"""
from __future__ import annotations

import os
import re
import stat
import statistics
import subprocess
import sys
import time
from pathlib import Path

from .fatiador import CORTES
from .merge_gate import CONSTITUICAO
from .self_dev import (CORRECAO_LOCAL, LINT_CMD, DevResult, SelfDeveloper, _git, ambiente_isolado, build_self_dev,
                       garantir_ruff)

REPARO = "developer:reparo"
REVERTIDA = "developer:constituicao_revertida"
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


def _ambiente() -> dict:
    """O ambiente isolado dos portões, sem bytecode: o `git add -A` levaria o `__pycache__` dos testes para o PR."""
    return {**ambiente_isolado(), "PYTHONDONTWRITEBYTECODE": "1"}


class DeveloperComReparo(SelfDeveloper):
    def __init__(self, *a, fix_cmds: list[list[str]] | None = None, piso_teto: int = PISO_TETO, **kw):
        auto_testes = kw.get("test_cmd") is None
        super().__init__(*a, **kw)
        if auto_testes:
            self.test_cmd = [*self.test_cmd, "--tb=short"]
        self.fix_cmds = fix_cmds        # None = automático: o ruff --fix do CI quando o lint é o ruff do CI
        self.piso_teto = piso_teto
        self._base: str | None = None
        self._rodada = 0
        self._item_id: int | None = None   # item no portão do PR (o reparo guarda o parcial dele ao cortar)
        self._consertando = False
        self._repetida = False
        self._cortado = ""

    def run_once(self, *a, **kw):
        self._rodada, self._cortado = 0, ""
        r = super().run_once(*a, **kw)
        if self._cortado and r.status == "agente_falhou" and not r.pr:
            self._set_item(r.item_id, "pendente", f"{self._cortado}; vai para o fatiador")
            return DevResult(r.item_id, "teto", self._cortado)
        return r

    def consertar(self):
        self._consertando = True
        try:
            return super().consertar()
        finally:
            self._consertando = False

    # ------------------------------------------------------------ teto de tokens por item
    def _tokens_do_item(self, titulo: str) -> tuple[int, int]:
        """(tokens, chamadas) do Developer no item: a rodada principal, o reparo e o conserto do PR."""
        item = PREFIXO_TITULO.sub("", titulo)
        gastos = [int(r["tokens"] or 0) for r in self.s.q("SELECT entrada, tokens FROM llm_calls WHERE papel='developer' "
                                                          "AND instr(entrada, ?) > 0", (item,))
                  if PREFIXO_TITULO.sub("", r["entrada"] or "") == item]
        return sum(gastos), len(gastos)

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
        if self._item_id is not None and not self._consertando:
            wip = (self.s.get("self_dev_wip") or {}).get(str(self._item_id))
            self._guardar_parcial(self._item_id, _git(["rev-parse", "--abbrev-ref", "HEAD"], wt), wt, wip)
        self._cortado = motivo
        return {"ok": False, "tokens": 0, "log": motivo, "teto": True}

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

    def _agente(self, task: str, wt: Path, titulo: str, papel: str = "developer") -> dict:
        tokens, chamadas = self._tokens_do_item(titulo)
        estimativa, teto = self._estimativa(tokens, chamadas), self.teto()
        if tokens + estimativa > teto:
            return self._cortar(wt, f"teto de tokens do item: {tokens} gastos + ~{estimativa} da próxima chamada > {teto}")
        self._rodada += 1
        modos = self._travar(wt)
        try:
            return super()._agente(task, wt, titulo, papel)
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
        etapas = ([("lint", self.lint_cmd)] if self.lint_cmd else []) + [("testes", self.test_cmd)]
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
                    monitorar(self.ctx, f"developer:{nome}", False, sujeito=str(wt.name), motivo=saida)
                return False, saida
            if registrar:
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

    def portao_pr(self, wt: Path, base: str, item_id: int | None, titulo: str) -> tuple[bool, str]:
        from .licoes import assinatura_de
        from .licoes import registrar as monitorar
        from .neuronios import (ABRIR_PR, Resultado, avaliar_aprendidos, causa_da_falha, diff_do_worktree, portoes_natos_pr,
                                registrar)
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
            return False, texto
        finally:
            self._base = self._item_id = None


def build_developer(ctx) -> DeveloperComReparo | None:
    """O Developer do loop, com o reparo limitado. Mesmas condições do `build_self_dev` (nunca dentro de testes)."""
    dev = build_self_dev(ctx)
    return None if dev is None else DeveloperComReparo(ctx, dev.repo, dev.agent, dev.gh)

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

`ruff format` só roda em arquivos criados pela mudança: o repositório não segue o `ruff format` e formatar um arquivo
existente reescreveria o arquivo inteiro (diff gigante, estilo da casa perdido, portão de tamanho estourado).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from .self_dev import CORRECAO_LOCAL, LINT_CMD, SelfDeveloper, _git, ambiente_isolado, build_self_dev, garantir_ruff

REPARO = "developer:reparo"
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


class DeveloperComReparo(SelfDeveloper):
    def __init__(self, *a, fix_cmds: list[list[str]] | None = None, **kw):
        auto_testes = kw.get("test_cmd") is None
        super().__init__(*a, **kw)
        if auto_testes:
            self.test_cmd = [*self.test_cmd, "--tb=short"]
        self.fix_cmds = fix_cmds        # None = automático: o ruff --fix do CI quando o lint é o ruff do CI
        self._base: str | None = None

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
            subprocess.run(argv, cwd=wt, capture_output=True, text=True, timeout=300, env=ambiente_isolado())
            rodou = True
        return rodou

    def verificar(self, wt: Path, registrar: bool = True) -> tuple[bool, str]:
        """O mesmo que o CI (lint e testes), com o autofix do lint antes de dar o lint por reprovado.
        A saída que volta é a focada (é ela que alimenta a rodada do agente)."""
        self._resolver_lint()
        etapas = ([("lint", self.lint_cmd)] if self.lint_cmd else []) + [("testes", self.test_cmd)]
        from .licoes import registrar as monitorar

        def rodar(cmd):
            return subprocess.run(cmd, cwd=wt, capture_output=True, text=True, timeout=900, env=ambiente_isolado())

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
                    monitorar(self.ctx, f"developer:{nome}", False, sujeito=str(wt.name), motivo=saida)
                return False, saida
            if registrar:
                monitorar(self.ctx, f"developer:{nome}", True, sujeito=str(wt.name))
        return True, ""

    # ------------------------------------------------------------ portão de abrir PR com 1 rodada de reparo
    def _ja_desistiu(self, sig: str) -> bool:
        """Essa falha já resistiu a uma rodada de reparo e a lição segue aberta: outra rodada não paga o custo."""
        return self.s.one("SELECT 1 FROM licoes WHERE assinatura=? AND status IN ('aberta','em_correcao','reincidente')",
                          (sig,)) is not None

    def portao_pr(self, wt: Path, base: str, item_id: int | None, titulo: str) -> tuple[bool, str]:
        from .licoes import assinatura_de
        from .licoes import registrar as monitorar
        from .neuronios import ABRIR_PR, Resultado, avaliar_aprendidos, diff_do_worktree, portoes_natos_pr, registrar
        self._base = base
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
                                                                              ambiente_isolado(), item_id), titulo)
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
                if tentativa == MAX_RODADAS_REPARO or self._ja_desistiu(sig):
                    if tentativa < MAX_RODADAS_REPARO:
                        texto += f"\n(reparo não repetido: a mesma falha já resistiu a uma rodada; lição {sig})"
                    break
                out = self._agente(CORRECAO_LOCAL.format(titulo=titulo, falhas=texto, licoes=self._licoes_txt(item_id)),
                                   wt, f"reparo: {titulo}")
                rodada = {"sig": sig, "tokens": int(out.get("tokens") or 0)}
                if not out.get("ok"):
                    # agente que parou (limite da conta, máximo de passos) não prova que a falha resiste: sem lição
                    monitorar(self.ctx, REPARO, False, sujeito=titulo, assinatura=sig, licao=False,
                              motivo=f"o agente terminou com erro na rodada; {rodada['tokens']} tokens")
                    break
            monitorar(self.ctx, ABRIR_PR, False, sujeito=titulo, motivo=texto)
            return False, texto
        finally:
            self._base = None


def build_developer(ctx) -> DeveloperComReparo | None:
    """O Developer do loop, com o reparo limitado. Mesmas condições do `build_self_dev` (nunca dentro de testes)."""
    dev = build_self_dev(ctx)
    return None if dev is None else DeveloperComReparo(ctx, dev.repo, dev.agent, dev.gh)

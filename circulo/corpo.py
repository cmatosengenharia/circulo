"""Corpo: o loop passa a rodar o código que ele mesmo evoluiu, com evidência antes e depois.

Sem isto, um PR mergeado pelo gate só existia no GitHub: a máquina do loop seguia com o código antigo até alguém
atualizar à mão. Neurônio `corpo:atualizar`:
  estímulo: a main andou (merge novo ou checagem periódica)
  → portões ANTES de trocar o corpo, num worktree separado com o código novo: importa os módulos do serviço
    e roda a suíte de testes. Reprovou: o corpo não muda e a falha vira lição (estrutural);
  → troca: o que houver de mudança local fica guardado em patch na pasta de dados; o código vai para a main
  → reinício limpo (o serviço 24/7 sobe de novo já no código novo)
  → EVIDÊNCIA depois: os primeiros VALIDAR_GIROS giros precisam rodar sem erro. Se errar: volta para o código
    anterior, reinicia e registra a lição. É o rollback do próprio corpo.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

CHECAR_A_CADA_S = 600       # segundos entre checagens da main (além de logo depois de um merge); em giros, o descanso
                            # longo (300 s) faria a checagem levar horas
VALIDAR_GIROS = 5           # giros sem erro depois de trocar o corpo = atualização evidenciada
MAX_ERROS_NA_VALIDACAO = 2
JANELA_PREEXISTENTE = 300      # giros antes da troca em que um erro igual absolve o código novo
SMOKE = "import circulo.cli, circulo.loop, circulo.painel, circulo.self_dev, circulo.merge_gate"


class Corpo:
    def __init__(self, ctx, repo_dir: Path | None, data_dir: Path, validacao: list[list[str]] | None = None):
        self.ctx = ctx
        self.s = ctx.store
        self.repo = Path(repo_dir) if repo_dir else None
        self.data = Path(data_dir)
        self.validacao = validacao
        self.reiniciar: str | None = None

    # ------------------------------------------------------------ git
    def _git(self, args, cwd=None, check=True) -> str:
        from .self_dev import _git
        return _git(args, Path(cwd or self.repo), check=check)

    @property
    def disponivel(self) -> bool:
        return bool(self.repo and (self.repo / ".git").exists() and self._git(["remote"], check=False))

    def estado(self) -> dict:
        return self.s.get("corpo") or {}

    def _set(self, **kw) -> None:
        self.s.set("corpo", {**self.estado(), **kw})

    # ------------------------------------------------------------ quando atualizar
    def precisa(self) -> bool:
        if not self.disponivel or self.estado().get("estado") == "validando":
            return False
        st = self.estado()
        ultimo_merge = (self.s.one("SELECT MAX(id) m FROM merges WHERE merged=1") or {"m": None})["m"] or 0
        devido = ultimo_merge > int(st.get("merge_visto", 0)) or time.time() - float(st.get("checado_em", 0)) >= CHECAR_A_CADA_S
        if devido:
            remoto = self._git(["ls-remote", "origin", "refs/heads/main"], check=False).split("\t")[0].strip()
            self._set(checado_tick=self.s.tick, checado_em=time.time(), merge_visto=ultimo_merge, remoto=remoto)
        st = self.estado()
        remoto = st.get("remoto")
        local = self._git(["rev-parse", "HEAD"], check=False)
        return bool(remoto) and remoto != local and remoto not in (st.get("reprovados") or [])

    # ------------------------------------------------------------ trocar o corpo, com portões antes
    def run(self) -> dict:
        from .licoes import registrar as monitorar
        from .self_dev import ambiente_isolado
        self._git(["fetch", "origin", "main"])
        alvo = self._git(["rev-parse", "origin/main"])
        anterior = self._git(["rev-parse", "HEAD"])
        if alvo == anterior and not self._git(["status", "--porcelain"], check=False):
            return {"status": "em_dia"}
        wt = self.data / "corpo-validacao"
        if wt.exists():
            self._git(["worktree", "remove", "--force", str(wt)], check=False)
            shutil.rmtree(wt, ignore_errors=True)
        self._git(["worktree", "add", "--detach", str(wt), alvo])
        try:
            env = {**ambiente_isolado(), "PYTHONPATH": str(wt)}
            cmds = self.validacao or [[sys.executable, "-c", SMOKE], [sys.executable, "-m", "pytest", "-q", "-x"]]
            for cmd in cmds:
                p = subprocess.run(cmd, cwd=wt, capture_output=True, text=True, timeout=1200, env=env)
                if p.returncode != 0:
                    motivo = (p.stdout + p.stderr)[-1500:]
                    st = self.estado()
                    self._set(reprovados=((st.get("reprovados") or []) + [alvo])[-20:])
                    monitorar(self.ctx, "corpo:atualizar", False, sujeito=alvo[:12], motivo=motivo, classe="estrutural",
                              assinatura="corpo:validacao_falhou")
                    self.ctx.reply(f"Corpo: o código novo ({alvo[:7]}) não passou na validação local; sigo no {anterior[:7]}.", "saude")
                    return {"status": "reprovado", "alvo": alvo, "motivo": motivo}
        finally:
            self._git(["worktree", "remove", "--force", str(wt)], check=False)
            shutil.rmtree(wt, ignore_errors=True)
        # nada se perde: mudança local (ex.: cópia manual) fica guardada antes da troca
        sujo = self._git(["status", "--porcelain"], check=False)
        patch = None
        if sujo:
            self._git(["add", "-A"])
            diff = self._git(["diff", "--cached", "HEAD"], check=False)
            self._git(["reset", "-q"], check=False)
            patch = self.data / f"corpo-local-{int(time.time())}.patch"
            patch.write_text(diff + "\n", encoding="utf-8")
        # -f: arquivo não rastreado no caminho do código novo (ex.: cópia manual) já está guardado no patch acima
        # (lição #1 da máquina do loop: sem -f, o checkout recusava e a troca nunca acontecia)
        from .guardrails import esquema_hash, snapshot
        snap = snapshot(self.s, self.data, "mudanca")          # o banco de antes da troca: o rollback de dados parte daqui
        esquema = esquema_hash(self.s)
        self._git(["checkout", "-q", "-f", "-B", "main", alvo])
        self._git(["reset", "-q", "--hard", alvo])   # (sem `git clean`: arquivo não rastreado nunca é apagado)
        self._set(estado="validando", sha=alvo, anterior=anterior, desde_tick=self.s.tick, giros_ok=0, erros=0,
                  patch=str(patch) if patch else None, snapshot=str(snap) if snap else None, esquema=esquema)
        monitorar(self.ctx, "corpo:atualizar", True, sujeito=alvo[:12])
        self._rastrear(anterior, alvo)
        self.ctx.reply(f"Corpo atualizado: {anterior[:7]} → {alvo[:7]} (validado antes: importação e testes). "
                       f"Reiniciando; os próximos {VALIDAR_GIROS} giros são a prova.", "merge")
        self.reiniciar = f"código atualizado para {alvo[:7]}"
        return {"status": "atualizado", "alvo": alvo, "anterior": anterior, "patch": str(patch) if patch else None}

    def _rollback_de_dados(self, st: dict) -> None:
        """Código voltou; os dados voltam junto só se a versão reprovada mudou o esquema do banco (o código antigo pode
        não ler o novo). Senão, o que o loop aprendeu nesses giros fica."""
        from .guardrails import esquema_hash, pedir_restauracao
        snap = st.get("snapshot")
        if not snap or not Path(snap).exists():
            return
        if st.get("esquema") and esquema_hash(self.s) == st["esquema"]:
            self.ctx.reply("Corpo: o esquema do banco não mudou na versão reprovada; os dados ficam.", "saude")
            return
        pedir_restauracao(self.data, Path(snap), f"rollback de dados junto com o de código ({str(st.get('sha', ''))[:7]} mudou o esquema)")
        self.ctx.reply(f"Corpo: a versão reprovada mudou o esquema do banco; ao reiniciar, o banco volta ao snapshot de antes da troca ({Path(snap).name}).", "saude")

    def _rastrear(self, anterior: str, alvo: str) -> None:
        """Elo exato PR → versão: o gate faz squash com o título terminando em (#N), então o git diz quais PRs entraram."""
        import re
        from .rastro import elo
        try:
            titulos = self._git(["log", "--format=%s", f"{anterior}..{alvo}"], check=False).splitlines()
        except Exception:  # noqa: BLE001
            return
        for t in titulos:
            m = re.search(r"\(#(\d+)\)\s*$", t)
            if m:
                elo(self.s, f"pr:{m.group(1)}", f"versao:{alvo[:12]}", "entrou_em", {"de": anterior[:12]})

    # ------------------------------------------------------------ evidência depois: os primeiros giros
    def _preexistente(self, erro: str, desde_tick: int) -> bool:
        """Erro que já acontecia com o código anterior não é prova contra o código novo (lição: o worktree órfão do
        item 95 reprovou e1c3d1a e e9a1e1f). Compara só as letras da mensagem, sem números, caminhos e pontuação."""
        if desde_tick <= 0:
            return False
        texto = re.sub(r"[\d\W_]+", "", erro)
        try:
            linhas = self.s.q("SELECT DISTINCT message FROM run_errors WHERE tick < ? AND tick >= ?",
                              (desde_tick, desde_tick - JANELA_PREEXISTENTE))
        except sqlite3.Error:      # banco sem a tabela: nada é pré-existente
            return False
        for r in linhas:
            chave = re.sub(r"[\d\W_]+", "", str(r["message"] or "").splitlines()[0] if r["message"] else "")[:40]
            if len(chave) >= 20 and chave in texto:     # 40 letras: o começo da mensagem, antes de ids e caminhos
                return True
        return False

    def validar(self, erros: list) -> str | None:
        st = self.estado()
        if st.get("estado") != "validando":
            return None
        from .licoes import registrar as monitorar
        erros = [e for e in erros if not self._preexistente(e, int(st.get("desde_tick") or 0))]
        if erros:
            st["erros"] = int(st.get("erros", 0)) + 1
            self._set(erros=st["erros"])
            if st["erros"] >= MAX_ERROS_NA_VALIDACAO and self.disponivel and st.get("anterior"):
                self._git(["reset", "-q", "--hard", st["anterior"]], check=False)
                self._set(estado="revertido", reprovados=((st.get("reprovados") or []) + [st["sha"]])[-20:])
                self._rollback_de_dados(st)
                from .rastro import elo
                elo(self.s, f"versao:{str(st.get('sha', ''))[:12]}", f"versao:{str(st.get('anterior'))[:12]}", "revertida")
                monitorar(self.ctx, "corpo:evidencia", False, sujeito=str(st.get("sha", ""))[:12],
                          motivo=f"erros nos primeiros giros do código novo: {str(erros)[:800]}", classe="estrutural",
                          assinatura="corpo:regressao_pos_atualizacao")
                self.ctx.reply(f"Corpo: o código {str(st.get('sha'))[:7]} errou nos primeiros giros; voltei para "
                               f"{str(st.get('anterior'))[:7]} e registrei a lição.", "saude")
                self.reiniciar = "rollback do código"
                return "revertido"
            return None
        st["giros_ok"] = int(st.get("giros_ok", 0)) + 1
        self._set(giros_ok=st["giros_ok"])
        if st["giros_ok"] >= VALIDAR_GIROS:
            self._set(estado="ok")
            from .rastro import elo
            elo(self.s, f"versao:{str(st.get('sha', ''))[:12]}", f"giro:{self.s.get('run_id') or 'fora_do_giro'}", "evidenciada",
                {"giros_ok": st["giros_ok"]})
            monitorar(self.ctx, "corpo:evidencia", True, sujeito=str(st.get("sha", ""))[:12])
            self.ctx.reply(f"Corpo {str(st.get('sha'))[:7]} evidenciado: {VALIDAR_GIROS} giros sem erro no código novo.", "merge")
            return "ok"
        return None


def build_corpo(ctx, data_dir: Path) -> Corpo | None:
    if os.environ.get("CIRCULO_SEM_DEVELOPER") == "1" or os.environ.get("PYTEST_CURRENT_TEST"):
        return None              # testes nunca trocam o código de verdade
    repo = os.environ.get("CIRCULO_REPO_DIR")
    if not repo or not (Path(repo) / ".git").exists():
        return None
    return Corpo(ctx, Path(repo), data_dir)

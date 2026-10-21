"""Conta do Claude: o loop roda na assinatura (Max/Pro) em vez da API, e cuida sozinho da sessão.

`CIRCULO_CONTA=max` (ou um `CLAUDE_CODE_OAUTH_TOKEN` cadastrado) liga o modo assinatura:
- toda chamada de LLM vai pelo `claude -p` com o login da conta (`llm.AssinaturaLLM`), e o Developer também;
- a `ANTHROPIC_API_KEY` sai do ambiente desses processos: no Claude Code ela tem precedência sobre a assinatura.

Guardião da sessão (`vigiar`, a cada passagem do SRE, no máximo a cada CHECAR s ou na hora se o Developer acusou
"deslogado"):
1. `claude auth status` (JSON; sai 1 sem login). Logado → se antes estava caído, libera o Developer e avisa.
2. Caiu → confere de novo depois de RECHECAR s (o próprio Claude Code renova o login sozinho na maioria das vezes).
3. Continua caído → abre o login no Mac (Terminal com `claude auth login`, ou `claude setup-token` se o que venceu
   foi o token de 1 ano), no máximo a cada REABRIR s, e põe em "Precisa de você": é só autorizar no navegador.
   O loop percebe sozinho na passagem seguinte e retoma. Login sem nenhum clique não existe (o consentimento é
   no navegador), por isso o caminho recomendado é o token de 1 ano: `claude setup-token` uma vez, valor no painel.
4. Token de 1 ano: guarda só a impressão (sha256, 12 caracteres) e quando apareceu; avisa AVISO_TOKEN dias antes.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

CHAVE = "conta_sessao"
CHECAR = 300
RECHECAR = 60
REABRIR = 2 * 3600
VALIDADE_TOKEN = 365 * 86400
AVISO_TOKEN = 30 * 86400
CHAVES_DA_API = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_WORKSPACE_ID")
ERRO_LOGIN = re.compile(r"Failed to authenticate|OAuth (session|token) (has )?(expired|revoked)|token revoked|not logged in|"
                        r"login expired|please run /login|Invalid authentication credentials|authentication_failed", re.I)
DESLOGADO = "Claude Code deslogado"


def assinatura() -> bool:
    """O loop roda na assinatura (Max/Pro), não na API."""
    return os.environ.get("CIRCULO_CONTA", "").strip().lower() in ("max", "pro", "assinatura") \
        or bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))


def ambiente(base: dict | None = None) -> dict:
    """Ambiente para o `claude` usar a assinatura: sem as chaves da API (elas venceriam o login)."""
    env = dict(os.environ if base is None else base)
    for k in CHAVES_DA_API:
        env.pop(k, None)
    return env


def erro_de_login(texto: str) -> bool:
    return bool(ERRO_LOGIN.search(texto or ""))


def status(cmd: str = "claude", timeout: float = 30.0) -> dict:
    """{'logado': bool, 'metodo': str, 'erro': str}. Nunca devolve token nem e-mail."""
    if not shutil.which(cmd):
        return {"logado": False, "metodo": "sem_cli", "erro": f"`{cmd}` não está instalado no PATH do serviço"}
    try:
        p = subprocess.run([cmd, "auth", "status"], capture_output=True, text=True, timeout=timeout, env=ambiente())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"logado": False, "metodo": "?", "erro": f"auth status: {exc}"[:200], "transitorio": True}
    try:
        d = json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        d = {}
    metodo = str(d.get("authMethod") or ("?" if p.returncode == 0 else "none"))
    logado = p.returncode == 0 and metodo not in ("none", "api_key", "api_key_helper")
    return {"logado": logado, "metodo": metodo, "erro": "" if logado else (p.stderr or p.stdout or "")[-200:].strip()}


def impressao(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:12]


def abrir_login(token_venceu: bool, pasta: Path | None = None) -> str | None:
    """Abre o login no Mac (um .command no Terminal: funciona a partir do launchd, sem permissão de automação).
    Devolve o comando aberto, ou None fora do macOS."""
    if platform.system() != "Darwin" or not shutil.which("open"):
        return None
    comando = "claude setup-token" if token_venceu else "claude auth login"
    roteiro = Path(pasta or tempfile.gettempdir()) / "circulo-login.command"
    dica = ("echo 'Copie o token e cole no painel do loop: Integrações → CLAUDE_CODE_OAUTH_TOKEN.'" if token_venceu
            else "echo 'Autorize no navegador. O loop percebe sozinho e retoma.'")
    roteiro.write_text("#!/bin/zsh\nunset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN\n"
                       f"echo 'Círculo: login da conta Claude (assinatura).'\n{dica}\n{comando}\n", encoding="utf-8")
    roteiro.chmod(0o700)
    subprocess.Popen(["open", str(roteiro)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return comando


def _espera(store, agora: float, motivo: str) -> None:
    from datetime import datetime
    store.set("self_dev_espera", {"ate": agora + CHECAR * 2, "hora": datetime.fromtimestamp(agora + CHECAR * 2).strftime("%H:%M"),
                                  "motivo": motivo, "precisa_de_voce": True})


def _liberar(store) -> None:
    e = store.get("self_dev_espera") or {}
    if str(e.get("motivo", "")).startswith(DESLOGADO):
        store.set("self_dev_espera", None)


def _token(store, reply, agora: float, st: dict) -> None:
    tok = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    if not tok:
        st.pop("token", None)
        return
    t = st.get("token") or {}
    imp = impressao(tok)
    if t.get("impressao") != imp:
        t = {"impressao": imp, "visto_em": agora}
    vence = float(t["visto_em"]) + VALIDADE_TOKEN
    t["vence_em"] = vence
    if vence - agora < AVISO_TOKEN and not t.get("avisado"):
        t["avisado"] = agora
        reply(f"O token de 1 ano do Claude Code vence em {max(0, int((vence - agora) / 86400))} dia(s). Rode "
              "`claude setup-token` no Mac e troque CLAUDE_CODE_OAUTH_TOKEN no painel.", "saude")
    st["token"] = t


def vigiar(store, reply, agora: float | None = None, consultar=status, abrir=abrir_login) -> dict | None:
    """Uma passagem do guardião. Fora do modo assinatura não faz nada."""
    if not assinatura():
        return None
    agora = agora or time.time()
    st = dict(store.get(CHAVE) or {})
    espera = store.get("self_dev_espera") or {}
    acusou = str(espera.get("motivo", "")).startswith(DESLOGADO) and not st.get("caiu_em")
    prazo = RECHECAR if st.get("caiu_em") else CHECAR
    if not acusou and agora - float(st.get("checado_em", 0)) < prazo:
        return st
    r = consultar()
    st.update(checado_em=agora, metodo=r.get("metodo"), logado=bool(r.get("logado")))
    _token(store, reply, agora, st)
    if r.get("logado"):
        if acusou:
            _liberar(store)                 # o Developer acusou, mas a sessão está de pé: falso alarme, segue
        if st.get("caiu_em"):
            reply(f"Sessão do Claude de volta ({r.get('metodo')}) depois de {int((agora - float(st['caiu_em'])) / 60)} min; "
                  "o Developer e a LLM retomam sozinhos.", "saude")
            _liberar(store)
        st.update(caiu_em=None, tentativas=0, erro="")
    elif not r.get("transitorio"):
        st["caiu_em"] = st.get("caiu_em") or agora
        st["tentativas"] = int(st.get("tentativas", 0)) + 1
        st["erro"] = str(r.get("erro", ""))[:200]
        venceu = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
        if st["tentativas"] >= 2:          # a primeira queda pode ser só a renovação do login em curso
            if agora - float(st.get("abriu_em", 0)) >= REABRIR:
                aberto = abrir(venceu)
                st["abriu_em"] = agora
                reply(("Sessão do Claude caiu: abri o Terminal no Mac com `" + aberto + "`" if aberto else
                       "Sessão do Claude caiu: rode `claude auth login` no Mac") +
                      (" — gere o token novo e cole no painel." if venceu else " — é só autorizar no navegador; o loop retoma sozinho."),
                      "saude")
            _espera(store, agora, f"{DESLOGADO} no Mac: " + ("token de 1 ano vencido ou revogado — rode `claude setup-token` "
                                                               "e troque CLAUDE_CODE_OAUTH_TOKEN no painel" if venceu else
                                                               "autorize o login que abri no Terminal (ou rode `claude auth login`)"))
    store.set(CHAVE, st)
    return st

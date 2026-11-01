"""Escudo das skills: auditoria determinística do `.claude/` de um repositório (técnica ECC-1, absorvida do AgentShield).

Por que existe (01/11): `skills.pedir_instalacao` copia skills de terceiros para `.claude/skills/` e `skills.para_tarefa`
põe o SKILL.md escolhido no prompt do Developer, que roda com permissão de editar e executar. Um SKILL.md com uma
ordem escondida ("ignore as regras", caractere invisível) ou um hook que manda variável de ambiente para fora vira
instrução dentro do agente. O AgentShield do ECC varre CLAUDE.md, settings.json, mcp.json, hooks e agentes atrás disso;
aqui o mesmo, em regra local (sem LLM, sem rede), e o resultado decide: skill com achado crítico não é oferecida ao Jev.

Severidades: `critico` (bloqueia a skill), `alto` e `medio` (só registram e avisam). Texto lido é dado, nunca instrução.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

KV = "escudo"
MAX_BYTES = 200_000

# (id, severidade, padrão, explicação)
REGRAS = (
    ("invisivel", "critico", re.compile("[​‌‍⁠﻿‪-‮⁦-⁩]"),
     "caractere invisível ou de direção de texto (instrução escondida)"),
    ("ignorar_regras", "critico", re.compile(r"(?i)\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all|system)\b.{0,20}\b(instructions?|rules?|prompts?)\b"
                                           r"|ignor[ae]\s+(as\s+|todas\s+as\s+)?(instru[cç][oõ]es|regras)"),
     "ordem para ignorar instruções anteriores"),
    ("baixa_e_executa", "critico", re.compile(r"(?i)\b(curl|wget)\b[^\n|]{0,200}\|\s*(ba|z)?sh\b"), "baixa da internet e executa direto (curl | sh)"),
    ("exfiltra_env", "critico", re.compile(r"(?i)\b(curl|wget|nc|Invoke-WebRequest)\b[^\n]{0,200}(\$\{?[A-Z_]*(TOKEN|KEY|SECRET|PASSWORD)[A-Z_]*\}?|\benv\b|printenv|\.env\b)"),
     "manda variável de ambiente ou segredo para fora"),
    ("segredo_literal", "alto", re.compile(r"(sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)"),
     "segredo literal no arquivo"),
    ("bypass_permissao", "alto", re.compile(r"(?i)--dangerously-skip-permissions|bypassPermissions|\"Bash\(\*\)\""),
     "desliga as permissões do agente"),
    ("leitura_sensivel", "medio", re.compile(r"(?i)(~/\.ssh|id_rsa|~/\.aws/credentials|\.config/circulo/env|keychain)"),
     "lê arquivo de credencial"),
)
SEVERIDADE = {"critico": 3, "alto": 2, "medio": 1}


def auditar_texto(texto: str) -> list[dict]:
    """Achados de um texto: id, severidade, explicação e um trecho curto (sem o segredo inteiro)."""
    out = []
    for rid, sev, padrao, por_que in REGRAS:
        m = padrao.search(texto)
        if m:
            trecho = texto[max(0, m.start() - 20): m.end() + 20].replace("\n", " ").encode("unicode_escape").decode()[:120]
            if rid == "segredo_literal":
                trecho = m.group(0)[:8] + "…"                          # o achado nunca carrega o segredo inteiro
            out.append({"regra": rid, "severidade": sev, "por_que": por_que, "trecho": trecho})
    return out


def _arquivos(raiz: Path) -> list[Path]:
    claude = raiz / ".claude"
    if not claude.is_dir():
        return []
    alvos = list(claude.glob("skills/**/*")) + list(claude.glob("settings*.json")) + list(claude.glob("hooks/**/*")) + list(claude.glob("agents/*.md"))
    return sorted(p for p in alvos if p.is_file() and p.stat().st_size <= MAX_BYTES)


def _hooks_do_settings(p: Path) -> str:
    """Os comandos dos hooks declarados no settings.json (o que de fato roda), além do texto cru."""
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return ""
    cmds = []
    for grupos in (dados.get("hooks") or {}).values() if isinstance(dados, dict) else []:
        for g in grupos if isinstance(grupos, list) else []:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                if isinstance(h, dict) and h.get("command"):
                    cmds.append(str(h["command"]))
    return "\n".join(cmds)


def auditar(repo_dir: Path | str) -> dict:
    """Varre o `.claude/` do repositório. Devolve achados por arquivo e as skills bloqueadas (achado crítico)."""
    raiz = Path(repo_dir)
    arquivos, bloqueadas = {}, set()
    for p in _arquivos(raiz):
        try:
            texto = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if p.name.startswith("settings") and p.suffix == ".json":
            texto += "\n" + _hooks_do_settings(p)
        achados = auditar_texto(texto)
        if not achados:
            continue
        rel = p.relative_to(raiz).as_posix()
        arquivos[rel] = achados
        partes = p.relative_to(raiz / ".claude").parts
        if partes[0] == "skills" and len(partes) > 2 and any(a["severidade"] == "critico" for a in achados):
            bloqueadas.add(partes[1])
    pior = max((SEVERIDADE[a["severidade"]] for xs in arquivos.values() for a in xs), default=0)
    return {"arquivos": arquivos, "bloqueadas": sorted(bloqueadas), "pior": pior, "varridos": len(_arquivos(raiz))}


def rodar(store, repo_dir: Path | str | None, reply=None, agora: float | None = None) -> dict | None:
    """Passagem do SRE: audita, guarda no kv `escudo` e avisa quando surge um bloqueio novo."""
    if not repo_dir:
        return None
    agora = agora or time.time()
    res = auditar(repo_dir)
    antes = set((store.get(KV) or {}).get("bloqueadas") or [])
    store.set(KV, {**res, "em": agora})
    novas = sorted(set(res["bloqueadas"]) - antes)
    if novas and reply:
        reply(f"Escudo das skills: {', '.join(novas)} ficou(ram) fora do prompt do Developer por achado crítico "
              f"({next(a['por_que'] for xs in res['arquivos'].values() for a in xs if a['severidade'] == 'critico')}).", "saude")
    return res


def bloqueadas(store) -> set[str]:
    return set((store.get(KV) or {}).get("bloqueadas") or [])

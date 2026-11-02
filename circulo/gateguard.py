"""GateGuard (ADR 0001, ECC-5): hook PreToolUse do Claude Code no worktree do Developer.

A primeira Edit/Write de um arquivo que já existe é negada até o transcript mostrar quem o importa: um Grep (ou
`grep`/`rg` no Bash) com o nome do módulo. Arquivo novo e sessão fora de `.circulo-wt-*` passam direto.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _buscas(transcript: str) -> list[str]:
    """O texto de cada busca (Grep, ou grep/rg no Bash) que o agente já fez nesta sessão."""
    out = []
    try:
        linhas = Path(transcript).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for linha in linhas:
        try:
            conteudo = json.loads(linha).get("message", {}).get("content")
        except (json.JSONDecodeError, AttributeError):
            continue
        for b in conteudo if isinstance(conteudo, list) else []:
            if not isinstance(b, dict) or b.get("type") != "tool_use":
                continue
            entrada = b.get("input") or {}
            if b.get("name") == "Grep":
                out.append(str(entrada.get("pattern", "")))
            elif b.get("name") == "Bash" and any(c in str(entrada.get("command", "")) for c in ("grep", "rg ")):
                out.append(str(entrada["command"]))
    return out


def decidir(evento: dict) -> str | None:
    """None libera; o texto é o motivo da recusa que o agente lê."""
    if evento.get("tool_name") not in ("Edit", "Write", "MultiEdit") or ".circulo-wt-" not in str(evento.get("cwd", "")):
        return None
    arquivo = Path(str((evento.get("tool_input") or {}).get("file_path", "")))
    if not arquivo.is_file():
        return None
    if any(arquivo.stem in b for b in _buscas(str(evento.get("transcript_path", "")))):
        return None
    return (f"GateGuard: antes de editar {arquivo.name}, liste os fatos: quem importa `{arquivo.stem}` "
            f"(ex.: grep -rn \"{arquivo.stem}\" circulo tests), o contrato que você vai mudar e o dado real que o mostra. "
            "Depois tente a edição de novo.")


def main() -> None:
    try:
        evento = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return
    motivo = decidir(evento) if isinstance(evento, dict) else None
    if motivo:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": motivo}}, ensure_ascii=False))


if __name__ == "__main__":
    main()

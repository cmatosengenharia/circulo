"""Gate determinístico de segredos no diff do PR (pedido #827, fatia 1).

Só as linhas que o PR ADICIONA são lidas. Duas camadas, as duas sem LLM:

1. regras internas (regex de formatos conhecidos: AWS, GitHub, Anthropic, OpenAI, Slack, Google, Stripe, chave
   privada PEM e atribuição `senha/token/api_key = "…"` com valor de cara real). Rodam sempre, também no portão antes
   do PR (`neuronios.portoes_natos_pr`): a correção local do Developer não deixa o segredo passar.
2. gitleaks, se instalado (`gitleaks dir` sobre as linhas adicionadas). Ausente: aviso registrado em
   `validador:scanner_segredos` e o loop segue só com as regras internas.

Qualquer achado reprova o PR; o problema mostra arquivo, regra e o trecho com o valor mascarado (nunca o segredo).
"""
from __future__ import annotations

import contextlib
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

PONTO = "validador:segredos"
PONTO_SCANNER = "validador:scanner_segredos"
SEM_SCANNER = "gitleaks não instalado: o diff passou só pelas regras internas de segredo"
TIMEOUT_S = 120
REGRAS = (
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}|\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("stripe-key", re.compile(r"\b[rs]k_live_[0-9A-Za-z]{20,}")),
    ("chave-privada", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    ("atribuicao", re.compile(r"""(?i)\w*(?:password|passwd|senha|secret|token|api_?key)\w*["']?\s*[:=]\s*["']([^"'\s]{16,})["']""")),
)
MARCADOR = re.compile(r"(?i)example|exemplo|xxxx|dummy|fake|changeme|placeholder|your|sua|<|\$\{|\{\{|\*\*\*")

Externo = Callable[[dict[str, list[str]]], "list[dict] | None"]


def mascarar(valor: str) -> str:
    return valor[:4] + "*" * min(max(len(valor) - 4, 4), 12)


def _trecho(linha: str, segredo: str) -> str:
    return (linha.replace(segredo, mascarar(segredo)) if segredo else linha).strip()[:160]


def _real(valor: str) -> bool:
    """Valor de atribuição com cara de segredo: letras e dígitos, sem marcador de exemplo."""
    return bool(re.search(r"[A-Za-z]", valor) and re.search(r"\d", valor)) and not MARCADOR.search(valor)


def internas(adicionadas: dict[str, list[str]]) -> list[dict]:
    """Achados das regras internas: [{arquivo, regra, trecho}] com o valor mascarado no trecho."""
    achados = []
    for arquivo, linhas in adicionadas.items():
        for linha in linhas:
            for regra, rx in REGRAS:
                m = rx.search(linha)
                if m is None or (m.groups() and not _real(m.group(1))):
                    continue
                segredo = "" if regra == "chave-privada" else (m.group(1) if m.groups() else m.group(0))
                achados.append({"arquivo": arquivo, "regra": regra, "trecho": _trecho(linha, segredo)})
                break
    return achados


def gitleaks(adicionadas: dict[str, list[str]]) -> list[dict] | None:
    """Achados do gitleaks sobre as linhas adicionadas: [{arquivo, regra, linha, segredo}]; None se não está instalado
    ou não rodou."""
    exe = shutil.which("gitleaks")
    if exe is None:
        return None
    with tempfile.TemporaryDirectory() as d:
        raiz, rel = Path(d) / "diff", Path(d) / "relatorio.json"
        for arquivo, linhas in adicionadas.items():
            alvo = raiz / arquivo
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        p = subprocess.run([exe, "dir", str(raiz.resolve()), "--no-banner", "--exit-code", "0", "--report-format", "json",
                            "--report-path", str(rel)], capture_output=True, text=True, timeout=TIMEOUT_S)
        if p.returncode != 0 or not rel.exists():
            return None
        dados = json.loads(rel.read_text(encoding="utf-8") or "[]")
        return [{"arquivo": str(Path(x["File"]).resolve().relative_to(raiz.resolve())), "regra": f"gitleaks:{x.get('RuleID', '?')}", "linha": int(x.get("StartLine") or 0),
                 "segredo": str(x.get("Secret") or "")} for x in dados]


def varrer(adicionadas: dict[str, list[str]], externo: Externo = gitleaks) -> tuple[list[dict], str]:
    """(achados das regras internas + do scanner externo, aviso). Sem scanner externo o aviso diz isso."""
    achados = internas(adicionadas)
    ext = None
    with contextlib.suppress(Exception):          # scanner quebrado é o mesmo que ausente: nunca trava o loop
        ext = externo(adicionadas)
    for x in ext or []:
        linhas = adicionadas.get(x["arquivo"], [])
        linha = linhas[x["linha"] - 1] if 0 < x["linha"] <= len(linhas) else ""
        trecho = _trecho(linha, x["segredo"]) if x["segredo"] in linha else mascarar(x["segredo"])
        if not any(a["arquivo"] == x["arquivo"] and a["trecho"] == trecho for a in achados):
            achados.append({"arquivo": x["arquivo"], "regra": x["regra"], "trecho": trecho})
    return achados, "" if ext is not None else SEM_SCANNER


def problemas(achados: list[dict]) -> list[str]:
    return [f"segredo em claro ({a['regra']}) em {a['arquivo']}: {a['trecho']}"[:300] for a in achados]


def verificar(ctx, adicionadas: dict[str, list[str]], externo: Externo = gitleaks, sujeito: str = "") -> list[str]:
    """O gate no Validador: os problemas (um por achado, valor mascarado); [] = nenhum segredo. Registra o veredito e,
    sem scanner externo, o aviso; nenhum dos dois vira lição."""
    achados, aviso = varrer(adicionadas, externo)
    out = problemas(achados)
    with contextlib.suppress(Exception):
        from .licoes import registrar as monitorar
        monitorar(ctx, PONTO_SCANNER, not aviso, sujeito=sujeito, licao=False, motivo=aviso)
        monitorar(ctx, PONTO, not out, sujeito=sujeito, licao=False, motivo="; ".join(out)[:400])
    return out

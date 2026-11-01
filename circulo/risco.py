"""Confirmação por risco das ações do Developer (porte do SecurityAnalyzer + ConfirmRisky de OpenHands).

O analisador só classifica: `classificar_risco` lê a ação (um comando ou "editar <arquivo>") por regex de assinaturas
conhecidas, no estilo do gate de segredos, e devolve LOW, MEDIUM, HIGH ou UNKNOWN (nada reconhecido). Um comando composto
(`&&`, `;`, `|`) fica com o maior risco dos trechos, e um trecho desconhecido vale mais que LOW e MEDIUM: o que não se
sabe avaliar não passa por baixo. A política decide: `exige_confirmacao` pede a sua aprovação do LIMIAR (HIGH) para
cima e sempre em UNKNOWN (confirm_unknown=True).

Ligado em `developer.GitHubComConvencoes.create_pr`: as ações do PR (abrir o PR e editar cada arquivo da lista) passam
por `portao`. Acima do limiar o PR não abre e a ação espera em "Precisa de você" (aprovar ou rejeitar com motivo);
toda decisão, também a automática, fica em DECISOES com o risco, e o corpo do PR leva a linha do risco.
Métrica: `high_sem_decisao` (alvo: zero em 7 dias).
"""
from __future__ import annotations

import hashlib
import re
import time

LOW, MEDIUM, HIGH, UNKNOWN = "LOW", "MEDIUM", "HIGH", "UNKNOWN"
NIVEIS = (LOW, MEDIUM, HIGH)
ORDEM = (LOW, MEDIUM, UNKNOWN, HIGH)       # dentro de uma ação: o trecho desconhecido pesa mais que LOW e MEDIUM
LIMIAR = HIGH
DECISOES = "acoes_risco"                   # kv: ref -> {titulo, head, item, acoes, risco, status, motivo, executada, em}
MAX_REGISTROS = 300
SEM_MOTIVO = "rejeitada no console, sem motivo escrito"

ALTO = (
    ("rm-rf", re.compile(r"\brm\s+(?:-[a-zA-Z]*[rR][a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*[rR]|-[rR]\s+-f|-f\s+-[rR])\b|\brm\b.*--recursive")),
    ("workflow", re.compile(r"\.github/workflows/")),
    ("curl-sh", re.compile(r"\b(?:curl|wget)\b[^;&]*\|\s*(?:sudo\s+)?(?:ba|z|da|k)?sh\b")),
    ("env", re.compile(r"(?:^|[\s/'\"=<])\.env(?!\.example\b|\.sample\b)(?:\.[\w-]+)?(?=$|[\s'\";|&)])")),
    ("force-push", re.compile(r"\bgit\s+push\b[^;&|]*(?:\s--force(?:-with-lease)?\b|\s-f\b|\s\+[\w/.-]+)")),
    ("sudo", re.compile(r"(?:^|[;&|]\s*)sudo\b")),
    ("escrita-fora", re.compile(r">>?\s*(?:~|\$HOME|/(?!tmp/|dev/null))")),
    ("apaga-branch", re.compile(r"\bgit\s+(?:branch\s+(?:-D|--delete\s+--force)|push\s+\S+\s+(?:--delete\s|:))")),
)
MEDIO = re.compile(r"^(?:git\s+push\b|git\s+(?:reset\s+--hard|clean|rebase|checkout\s+--)\b|rm\s|(?:pip3?|npm|uv|poetry)\s+(?:install|add)\b"
                   r"|python[\d.]*\s+-m\s+pip\s+install\b|(?:curl|wget)\b|gh\s|find\b.*\s-delete\b"
                   r"|editar\s+(?:pyproject\.toml|requirements[\w.-]*\.txt|setup\.(?:py|cfg)|AGENTS\.md|\.claude/))")
BAIXO = re.compile(r"^(?:ls|cat|head|tail|grep|rg|find|wc|echo|pwd|cd|which|diff|sed\s+-n|pytest|ruff|abrir\s+PR|editar|ler)\b"
                   r"|^python[\d.]*\s+-m\s+(?:pytest|ruff|circulo(?:\.\w+)?)\b"
                   r"|^git\s+(?:status|diff|log|show|add|commit|branch|fetch|rev-parse|worktree)\b")
TRECHOS = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")


def padroes_altos(acao: str) -> list[str]:
    return [nome for nome, rx in ALTO if rx.search(acao or "")]


def _trecho(t: str) -> str:
    if padroes_altos(t):
        return HIGH
    if MEDIO.search(t):
        return MEDIUM
    return LOW if BAIXO.search(t) else UNKNOWN


def classificar_risco(acao: str) -> str:
    """LOW, MEDIUM, HIGH ou UNKNOWN de um comando ou de "editar <arquivo>"."""
    if padroes_altos(acao):
        return HIGH
    trechos = [t for t in TRECHOS.split((acao or "").strip()) if t]
    return max((_trecho(t) for t in trechos), key=ORDEM.index) if trechos else UNKNOWN


def exige_confirmacao(risco: str, limiar: str = LIMIAR, confirmar_unknown: bool = True) -> bool:
    """A ConfirmRisky: espera aprovação do limiar para cima; UNKNOWN conforme `confirmar_unknown`."""
    if risco not in NIVEIS:
        return confirmar_unknown
    return NIVEIS.index(risco) >= NIVEIS.index(limiar)


def acoes_do_pr(head: str, corpo: str) -> list[str]:
    """Abrir o PR e editar cada arquivo da linha "Arquivos:" do corpo."""
    m = re.search(r"^Arquivos:\s*(.*)$", corpo or "", re.M)
    arquivos = [a.strip() for a in (m.group(1).split(",") if m else []) if a.strip()]
    return [f"abrir PR {head}"] + [f"editar {a}" for a in arquivos]


def _gravar(store, ref: str, **campos) -> dict:
    reg = store.get(DECISOES) or {}
    reg[ref] = {**reg.get(ref, {}), **campos}
    store.set(DECISOES, dict(sorted(reg.items(), key=lambda kv: kv[1].get("em", 0))[-MAX_REGISTROS:]))
    return reg[ref]


def portao(store, titulo: str, head: str, acoes: list[str], item: int | None = None) -> str:
    """A linha do risco para o corpo do PR; levanta RuntimeError se a ação espera (ou recebeu) a sua decisão."""
    riscos = {a: classificar_risco(a) for a in acoes}
    acima = sorted(a for a, r in riscos.items() if exige_confirmacao(r))
    risco = max(riscos.values(), key=ORDEM.index) if riscos else UNKNOWN
    ref = hashlib.sha256("\n".join([titulo, *(acima or sorted(riscos))]).encode("utf-8")).hexdigest()[:12]
    linha = f"Risco da ação: {risco} (limiar {LIMIAR}; UNKNOWN pede confirmação)"
    anterior = (store.get(DECISOES) or {}).get(ref, {})
    base = {"titulo": titulo[:160], "head": head, "item": item, "risco": risco,
            "acoes": [f"{a} [{riscos[a]}]" for a in (acima or acoes)][:20], "em": anterior.get("em", time.time())}
    if not acima:
        _gravar(store, ref, **base, status="automatica", executada=True)
        return linha
    status = anterior.get("status")
    if status == "aprovada" and not anterior.get("executada"):        # a aprovação vale uma vez: o próximo PR igual pede outra
        _gravar(store, ref, **base, executada=True)
        return f"{linha} · aprovada por você"
    if status == "rejeitada":
        raise RuntimeError(f"PR não aberto: ação {risco} rejeitada por você: {anterior.get('motivo', '')} · depende de você")
    _gravar(store, ref, **{**base, "em": time.time()}, status="pendente", executada=False, motivo="")
    raise RuntimeError(f"PR não aberto: ação {risco} ({', '.join(acima)[:200]}) aguarda sua aprovação em Precisa de você "
                       "· depende de você")


def pendentes(store) -> list[tuple[str, dict]]:
    return [(ref, d) for ref, d in (store.get(DECISOES) or {}).items() if d.get("status") == "pendente"]


def _item(store, d: dict, evidencia: str) -> None:
    if d.get("item"):
        store.x("UPDATE roadmap SET evidencia=?, updated_at=? WHERE id=? AND status='pendente'",
                (evidencia[:300], time.time(), int(d["item"])))


def decidir(store, ref: str, aprovar: bool, motivo: str = "") -> dict:
    """Aprovar devolve o item à fila (o Developer refaz e abre o PR, uma vez); rejeitar grava o motivo (o padrão, se o
    console não mandou um) e deixa o item com você."""
    d = (store.get(DECISOES) or {}).get(str(ref))
    if not d or d.get("status") != "pendente":
        return {"ok": False, "erro": "ação não está esperando decisão"}
    motivo = (motivo or "").strip() or ("" if aprovar else SEM_MOTIVO)
    _gravar(store, str(ref), status="aprovada" if aprovar else "rejeitada", motivo=motivo[:300], decidida_em=time.time())
    if aprovar:
        _item(store, d, f"ação {d['risco']} aprovada por você; o Developer refaz e abre o PR")
        return {"ok": True, "feito": f"ação {d['risco']} aprovada: {d['titulo'][:80]}"}
    _item(store, d, f"ação {d['risco']} rejeitada por você: {motivo} · depende de você")
    return {"ok": True, "feito": f"ação {d['risco']} rejeitada: {motivo[:80]}"}


def high_sem_decisao(store, desde: float = 0.0) -> int:
    """Ações HIGH executadas sem a sua aprovação registrada (alvo: zero)."""
    return sum(1 for d in (store.get(DECISOES) or {}).values()
               if d.get("risco") == HIGH and d.get("executada") and d.get("status") != "aprovada" and d.get("em", 0) >= desde)

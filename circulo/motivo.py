"""Motivo tipado de recusa/parada (pergunta #269): por que um PR foi recusado ou um item parou, em três campos.

O registro sai do estado local do loop (o veredito que o gate gravou em `merges` e a evidência do item no roteiro),
nunca do GitHub depois: `Codigo` é o enum (como o dequeue-reason do Mergify), `check` é o check ou portão que barrou,
`causa` é a linha que o gate escreveu e `proxima_acao` diz o que acontece agora. O que não casa com nenhum código
conhecido vira `sem_motivo` com campos vazios e um alerta: o console nunca inventa texto.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from enum import Enum

from .gate_causa import checks_falhando


class Codigo(str, Enum):
    CHECK_FALHOU = "check_falhou"
    CI_INDISPONIVEL = "ci_indisponivel"
    CONFLITO = "conflito"
    SEM_TESTE = "sem_teste"
    PR_GRANDE = "pr_grande"
    FORA_DO_ALCANCE = "fora_do_alcance"
    REVISOR = "revisor"
    REVIEWER_CODE = "reviewer_code"
    MERGE_RECUSADO = "merge_recusado"
    ERRO_API = "erro_api"
    AGUARDA_PR = "aguarda_pr"
    BARRADO_PORTOES = "barrado_portoes"
    DEPENDE_HUMANO = "depende_humano"
    LIMITE_USO = "limite_uso"
    SEM_MOTIVO = "sem_motivo"


@dataclass(frozen=True)
class Motivo:
    codigo: Codigo
    check: str
    causa: str
    proxima_acao: str

    def dict(self) -> dict:
        return {**asdict(self), "codigo": self.codigo.value}


SEM_MOTIVO = Motivo(Codigo.SEM_MOTIVO, "", "", "")
ESPERA = ("checks em andamento", "checks ausentes", "rascunho", "PR humano", "todos os gates passaram", "documentação: só docs/")

# prefixo do veredito do gate (merge_gate.Verdict.reason) → código, portão que barrou, próxima ação
_GATE: tuple[tuple[str, Codigo, str, str], ...] = (
    ("checks falhando", Codigo.CHECK_FALHOU, "", "o Developer conserta na mesma branch"),
    ("check obrigatório", Codigo.CHECK_FALHOU, "check obrigatório", "o Developer conserta na mesma branch"),
    ("CI não iniciou", Codigo.CI_INDISPONIVEL, "CI do GitHub", "o gate tenta de novo quando o CI voltar"),
    ("conflito com a main", Codigo.CONFLITO, "gate: conflito com a main", "o Developer traz a main para a branch"),
    ("PR do Developer sem teste", Codigo.SEM_TESTE, "gate: teste novo", "o Developer escreve o teste de regressão"),
    ("PR grande demais", Codigo.PR_GRANDE, "gate: tamanho", "o item é dividido em partes menores"),
    ("fora do alcance", Codigo.FORA_DO_ALCANCE, "gate: alcance", "o item segue por outro caminho, sem tocar a área protegida"),
    ("Revisor:", Codigo.REVISOR, "Revisor do círculo", "o item volta para a fila e é refeito sobre a main nova"),
    ("Reviewer Code", Codigo.REVIEWER_CODE, "Reviewer Code (Jev)", "o Developer ajusta o PR conforme a revisão"),
    ("GitHub recusou o merge", Codigo.MERGE_RECUSADO, "merge no GitHub", "o gate tenta o merge de novo no próximo giro"),
    ("erro ao avaliar", Codigo.ERRO_API, "API do GitHub", "o gate avalia de novo no próximo giro"),
)
# prefixo da evidência do item parado no roteiro → código, portão, próxima ação
_ITEM: tuple[tuple[str, Codigo, str, str], ...] = (
    ("aguarda PR", Codigo.AGUARDA_PR, "Revisor do círculo", "espera o PR citado entrar ou fechar"),
    ("revisor:", Codigo.REVISOR, "Revisor do círculo (antes do PR)", "o Developer refaz sem colidir com os PRs abertos"),
    ("barrado", Codigo.BARRADO_PORTOES, "portões antes do PR", "o Developer tenta de novo com o erro dos portões"),
    ("aguardando o limite", Codigo.LIMITE_USO, "limite do Claude Code", "o item volta sozinho quando o limite renovar"),
)


def do_gate(reason: str | None) -> Motivo | None:
    """O motivo tipado de um veredito do gate; None quando o gate só espera (CI rodando, rascunho, aprovado)."""
    texto = (reason or "").strip()
    if texto.startswith(ESPERA) or "atrás da main" in texto:
        return None
    causa = texto.split("\n", 1)[0][:200]
    for prefixo, codigo, check, prox in _GATE:
        if texto.startswith(prefixo):
            if codigo is Codigo.CHECK_FALHOU and not check:
                check = ", ".join(sorted(checks_falhando(texto) or ()))
            return Motivo(codigo, check, causa, prox)
    return SEM_MOTIVO


def _ultimo_veredito(store, pr: int) -> str | None:
    r = store.one("SELECT reason FROM merges WHERE pr=? AND merged=0 ORDER BY id DESC LIMIT 1", (pr,))
    return r["reason"] if r else None


def do_item(store, evidencia: str | None, pr: int | None, parado: bool) -> Motivo | None:
    """O motivo de um item do quadro: pela evidência que o loop gravou no roteiro ou pelo último veredito do gate
    sobre o PR dele. Item parado sem motivo conhecido vira SEM_MOTIVO; item andando sem recusa não tem motivo."""
    ev = (evidencia or "").strip()
    for prefixo, codigo, check, prox in _ITEM:
        if ev.startswith(prefixo):
            return Motivo(codigo, check, ev[:200], prox)
    if "depende de você" in ev:
        return Motivo(Codigo.DEPENDE_HUMANO, "decisão humana", ev[:200], "você decide em “Precisa de você”")
    m = do_gate(_ultimo_veredito(store, pr)) if pr else None
    if m is None and parado:
        return SEM_MOTIVO
    return m


def alertar_sem_motivo(store, item_ids: list[int]) -> None:
    """Um alerta por item parado sem motivo conhecido (a meta é sem_motivo = 0); não repete o mesmo item."""
    vistos = set(store.get("sem_motivo_alertados") or [])
    novos = [i for i in item_ids if i not in vistos]
    for i in novos:
        store.x("INSERT INTO alerts(kind,message,created_at,delivered) VALUES('sem_motivo',?,?,0)",
                (f"O item #{i} parou sem motivo tipado registrado: o gate ou o roteiro não gravou o porquê.", time.time()))
    if novos:
        store.set("sem_motivo_alertados", sorted(vistos | set(novos))[-500:])

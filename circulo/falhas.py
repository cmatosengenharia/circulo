"""Classe da falha do agente, por regra, antes de tentar de novo (Retry pattern: só a transitória se repete).

`classificar_saida_agente(texto)` é pura e devolve:
- TRANSITORIA: sobrecarga, limite de taxa, 5xx, rede; volta sozinha e pode ser repetida;
- CONFIGURACAO: uma assinatura de NAO_REPETIVEIS e nenhuma causa nomeada no texto; repetir só gasta tentativa e PR
  (lições #18, #42 e #69: 3 PRs abandonados, #73, #75 e #85). O disjuntor abre na 1ª e fecha quando a configuração muda;
- FALHA: o resto, que segue o caminho de sempre (reparo, fatiador).
O metadado `sdk_opt_in_required` vem em toda linha `result` do Claude Code: quando o texto nomeia a causa (máximo de
passos, erro de API, deslogado, …) é ela que vale, e não a configuração.

`digital_configuracao(env)` é a impressão digital das chaves do `circulo configurar` (só o hash de cada valor) e do
comando do agente: é ela que fecha o disjuntor, não o relógio.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from typing import Mapping

from .configuracao import CHAVES
from .licoes import causa_de_json

CONFIGURACAO, TRANSITORIA, FALHA = "configuracao", "transitoria", "falha"
PAUSA = "pausa_configuracao"
SEM_CAUSA = (None, "log_cortado", "agente_falhou")
TRANSITORIAS = re.compile(r"overloaded|rate[ _]limit|too many requests|\b(?:429|5\d\d)\b|timed? ?out|ECONNRESET|"
                          r"ECONNREFUSED|connection (?:reset|refused|error)|temporarily unavailable", re.I)
# (nome, todas as assinaturas que precisam aparecer)
NAO_REPETIVEIS = (
    ("sdk_opt_in_required", (re.compile(r'fast_mode_disabled_reason"?:\s*"?sdk_opt_in_required|d_reason"?:\s*"sdk_opt_in_required'),
                             re.compile(r'"spawned"?:\s*0\b'))),
)


def assinatura_nao_repetivel(texto: str) -> str | None:
    return next((nome for nome, regras in NAO_REPETIVEIS if all(r.search(texto) for r in regras)), None)


def classificar_saida_agente(texto: str) -> str:
    texto = texto or ""
    if TRANSITORIAS.search(texto):
        return TRANSITORIA
    if assinatura_nao_repetivel(texto) and causa_de_json(texto) in SEM_CAUSA:
        return CONFIGURACAO
    return FALHA


def digital_configuracao(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    agente = env.get("CIRCULO_CODE_AGENT", "claude")
    partes = [f"{nome}={hashlib.sha256(env.get(nome, '').encode()).hexdigest()}" for nome, _ in CHAVES]
    partes.append(f"agente={agente}:{shutil.which(agente) or ''}")
    return hashlib.sha256("\n".join(partes).encode()).hexdigest()

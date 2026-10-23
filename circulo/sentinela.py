"""Sentinela da entrega: olha o RESULTADO (o que entrou na main), não os erros.

Três vezes a fila parou sem nenhum erro visível (CI recusado em 20/10, testes com o Graft real em 22/10, item preso
no teto de tokens em 22→23/10): cada etapa "funcionava", só que nada era entregue. A sentinela pergunta uma coisa só:
há itens prontos na fila e nada entrou na main há LIMITE_H horas? Se sim:
- avisa (alerta "saude"), põe no topo do "Precisa de você" e manda uma notificação do macOS;
- junta o diagnóstico do período: espera do Developer, o aviso do Developer que mais se repetiu, chamadas de LLM, corpo;
- repete o aviso a cada REAVISAR_H enquanto durar e avisa quando a entrega volta.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from collections import Counter

CHAVE = "entrega_parada"
LIMITE_H = 4.0
REAVISAR_H = 6.0


def _prontos(store) -> int:
    return int(store.one("SELECT COUNT(*) n FROM roadmap WHERE status IN ('pendente','em_andamento') AND COALESCE(desativado,0)=0 "
                         "AND COALESCE(evidencia,'') NOT LIKE '%depende de você%'")["n"])


def _ultima_entrega(store) -> float:
    a = store.one("SELECT MAX(updated_at) m FROM prs WHERE status='mergeado'")["m"] or 0
    b = store.one("SELECT MAX(created_at) m FROM alerts WHERE message LIKE 'Merge automático%'")["m"] or 0
    return float(max(a, b))


def diagnostico(store, desde: float) -> dict:
    """O que aconteceu desde a última entrega, em números e numa frase."""
    msgs = [r["message"] for r in store.q("SELECT message FROM alerts WHERE created_at>? AND (message LIKE 'Developer%' OR message LIKE 'Corpo%' "
                                          "OR message LIKE 'PR #%' OR message LIKE 'Médico%') ORDER BY id DESC LIMIT 2000", (desde,))]
    norm = Counter(re.sub(r"\d[\d.,]*", "N", m)[:160] for m in msgs)
    repetido, vezes = norm.most_common(1)[0] if norm else ("", 0)
    exemplo = next((m for m in msgs if re.sub(r"\d[\d.,]*", "N", m)[:160] == repetido), "")
    llm = store.one("SELECT COUNT(*) n, COALESCE(SUM(tokens),0) t FROM llm_calls WHERE created_at>? AND papel='developer'", (desde,))
    espera = store.get("self_dev_espera") or {}
    corpo = store.get("corpo") or {}
    partes = []
    if espera and float(espera.get("ate", 0)) > time.time():
        partes.append(f"Developer em espera: {str(espera.get('motivo', ''))[:120]}")
    if vezes >= 3:
        partes.append(f"repetiu {vezes}×: {exemplo[:160]}")
    if not int(llm["n"]):
        partes.append("o Developer não chamou o Claude Code nenhuma vez")
    if corpo.get("estado") not in (None, "ok"):
        partes.append(f"corpo {corpo.get('estado')} em {str(corpo.get('sha', ''))[:7]}")
    return {"repetido": exemplo[:200], "vezes": vezes, "chamadas_developer": int(llm["n"]), "tokens_developer": int(llm["t"]),
            "frase": "; ".join(partes) or "sem causa óbvia nos avisos: veja a Equipe ao vivo"}


def notificar_mac(titulo: str, texto: str) -> bool:
    """Notificação do macOS (a sentinela também fala fora do painel). CIRCULO_NOTIFICAR=0 desliga."""
    if os.environ.get("CIRCULO_NOTIFICAR", "1") == "0" or platform.system() != "Darwin" or not shutil.which("osascript"):
        return False
    def limpo(s: str) -> str:
        return s.replace("\\", " ").replace('"', "'")[:220]
    try:
        subprocess.run(["osascript", "-e", f'display notification "{limpo(texto)}" with title "{limpo(titulo)}"'],
                       capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def checar(store, reply, agora: float | None = None, notificar=notificar_mac) -> dict | None:
    """Uma passagem (o SRE chama a cada minuto). Devolve o estado da parada, ou None quando a entrega está andando."""
    agora = agora or time.time()
    st = store.get(CHAVE) or {}
    prontos = _prontos(store)
    ultima = _ultima_entrega(store)
    parado_h = (agora - ultima) / 3600 if ultima else None
    if not prontos or parado_h is None or parado_h < LIMITE_H:
        if st:
            reply(f"Entrega voltou: a main recebeu código de novo depois de {round((agora - float(st['desde'])) / 3600, 1)} h parada."
                  if prontos else "Sentinela: a fila esvaziou; nada para entregar agora.", "saude")
            store.set(CHAVE, None)
        return None
    if st and agora - float(st.get("avisado_em", 0)) < REAVISAR_H * 3600:
        return st
    d = diagnostico(store, ultima)
    texto = f"Entrega parada há {parado_h:.0f} h com {prontos} item(ns) prontos na fila. {d['frase']}."
    reply(f"Sentinela: {texto}", "saude")
    notificar("Círculo: entrega parada", texto)
    st = {"desde": st.get("desde", ultima), "avisado_em": agora, "horas": round(parado_h, 1), "prontos": prontos, **d}
    store.set(CHAVE, st)
    return st

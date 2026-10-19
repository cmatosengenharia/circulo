"""Jardineiro: vigia padrões ruins se espalhando pelo próprio código (Lauren Tan: "assign a gardener").

Agentes copiam o que já existe no repositório, inclusive gambiarras. O jardineiro mede, de tempos em tempos, os
indicadores do código que está rodando e compara com a medição de uma semana antes:
- `except Exception` (engolir erro), `noqa` (silenciar o lint), funções longas (> 80 linhas), módulos grandes
  (> 900 linhas), TODO/FIXME e comentários de gambiarra;
- se um indicador cresce além da tolerância, o crescimento vira item do roteiro (origem loop, com a evidência) para
  o Developer podar. Primeiro para de crescer, depois limpa.

Só leitura do código; uma medição a cada INTERVALO. Aparece no fluxo como o agente "jardinagem".
"""
from __future__ import annotations

import ast
import re
import time
from pathlib import Path

INTERVALO = 6 * 3600
FUNCAO_LONGA = 80
MODULO_GRANDE = 900
TOLERANCIA = 0.10          # crescimento relativo aceito em uma semana
MINIMO_ABSOLUTO = 3        # e pelo menos isso em número absoluto (não abre item por 1 ocorrência)
INDICADORES = {"except_exception": "blocos `except Exception` (erros engolidos)", "noqa": "linhas com `noqa` (lint silenciado)",
               "funcoes_longas": f"funções com mais de {FUNCAO_LONGA} linhas", "modulos_grandes": f"módulos com mais de {MODULO_GRANDE} linhas",
               "todo": "TODO/FIXME/gambiarra no código"}


def _engole_exception(h: ast.ExceptHandler) -> bool:
    """`except Exception` (ou numa tupla) que não termina em raise: o erro some ali."""
    tipos = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
    return any(isinstance(t, ast.Name) and t.id == "Exception" for t in tipos) and not isinstance(h.body[-1], ast.Raise)


def medir(pasta: str | Path | None = None) -> dict:
    pasta = Path(pasta) if pasta else Path(__file__).parent
    tot = dict.fromkeys(INDICADORES, 0)
    por_arquivo: dict[str, dict] = {}
    for p in sorted(pasta.glob("*.py")):
        txt = p.read_text(encoding="utf-8")
        linhas = txt.splitlines()
        d = {"except_exception": 0, "noqa": sum("noqa" in ln for ln in linhas),
             "todo": len(re.findall(r"#.*\b(TODO|FIXME|XXX|gambiarra|hack)\b", txt, re.I)),
             "modulos_grandes": int(len(linhas) > MODULO_GRANDE), "funcoes_longas": 0}
        try:
            for n in ast.walk(ast.parse(txt)):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and (n.end_lineno or n.lineno) - n.lineno + 1 > FUNCAO_LONGA:
                    d["funcoes_longas"] += 1
                elif isinstance(n, ast.ExceptHandler) and _engole_exception(n):
                    d["except_exception"] += 1
        except SyntaxError:
            pass
        por_arquivo[p.name] = d
        for k, v in d.items():
            tot[k] += v
    return {"em": time.time(), "total": tot, "arquivos": por_arquivo}


def precisa(store, now: float | None = None) -> bool:
    j = store.get("jardim") or {}
    return (now or time.time()) - float(j.get("em", 0)) >= INTERVALO


def podar(store, reply=None, pasta: str | Path | None = None, now: float | None = None) -> list[str]:
    """Mede, guarda a série e transforma crescimento acima da tolerância em item do roteiro. Devolve os achados."""
    now = now or time.time()
    m = medir(pasta)
    j = store.get("jardim") or {"historico": []}
    hist = [h for h in j.get("historico", []) if now - h["em"] <= 30 * 86400]
    ref = next((h for h in hist if now - h["em"] >= 6 * 86400), hist[0] if hist else None)   # ~uma semana antes
    achados = []
    if ref:
        for k, nome in INDICADORES.items():
            antes, agora = int(ref["total"].get(k, 0)), int(m["total"][k])
            if agora - antes >= MINIMO_ABSOLUTO and agora > antes * (1 + TOLERANCIA):
                piores = sorted(((a, d[k]) for a, d in m["arquivos"].items() if d[k]), key=lambda x: -x[1])[:5]
                achados.append(f"{nome}: {antes} → {agora}. Onde mais: " + ", ".join(f"{a} ({n})" for a, n in piores))
    hist.append({"em": now, "total": m["total"]})
    store.set("jardim", {"em": now, "total": m["total"], "historico": hist[-60:], "achados": achados})
    for a in achados:
        _item(store, a, reply)
    return achados


def _item(store, achado: str, reply=None) -> None:
    titulo = f"Jardineiro: podar {achado.split(':')[0]}"[:200]
    if store.one("SELECT 1 FROM roadmap WHERE titulo=? AND status IN ('pendente','em_andamento')", (titulo,)):
        return
    agora = time.time()
    ordem = (store.one("SELECT COALESCE(MAX(ordem),0) m FROM roadmap")["m"] or 0) + 1
    detalhe = (f"O padrão está se espalhando no código (medido pelo jardineiro): {achado}. Primeiro impedir que cresça "
               "(um teste em tests/test_arquitetura.py que trave o número atual), depois reduzir nos arquivos citados, "
               "sem mudar comportamento.\nSucesso: o indicador para de crescer na próxima medição e cai em relação a hoje.")
    iid = store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
                  "VALUES(?,?,'loop','pendente',?,?,?,?)", (titulo, detalhe, "medido pelo jardineiro", ordem, agora, agora))
    if reply:
        reply(f"Jardineiro: {achado}. Virou o item #{iid} do roteiro.", "roteiro")

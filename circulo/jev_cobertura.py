"""Cobertura do Jev: o loop confere, no próprio código, se cada pergunta ao Jev usa tudo o que a API oferece.

A documentação da TypeSafe (docs.typesafe.ai/api e /primitives) diz o que uma pergunta bem feita tem:
- Noul: `criteria` com `true` e `false` descrevendo a situação de cada lado (opcional na API, mas sobe a precisão);
- Choice: cada opção com uma descrição (situação), não só a chave repetida;
- Score: níveis que descrevem situações, nunca graus ("baixo/médio/alto") nem só números;
- a resposta traz `probabilities` e `legend`: quem lê só o valor joga informação fora;
- várias perguntas independentes vão na mesma chamada;
- inglês é a língua em que o Jev acerta mais.

Este módulo lê as perguntas do código (ast) e mede a cobertura por regra. O teste tests/test_jev_cobertura.py trava o
piso: nenhuma pergunta nova entra sem critérios. O painel (aba Decisões e Jev) mostra a cobertura ao vivo.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

GRAUS = re.compile(r"^(muito\s+)?(baix[oa]|m[ée]di[oa]|alt[oa]|low|medium|high|pouco|bastante|moderad\w*)$", re.I)
PACOTE = Path(__file__).parent


def _str(n) -> str | None:
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return n.value
    if isinstance(n, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{…}" for v in n.values)
    return None


def _criteria(n) -> dict:
    """Resumo estático do argumento `criteria`: forma e qualidade, sem executar o código."""
    if n is None:
        return {"presente": False}
    if isinstance(n, ast.Dict):
        chaves = [_str(k) for k in n.keys]
        valores = [_str(v) for v in n.values]
        descritas = sum(1 for k, v in zip(chaves, valores, strict=True) if v and k and v.strip() and v.strip().lower() != k.replace("_", " ").lower())
        return {"presente": True, "forma": "dict", "n": len(chaves), "descritas": descritas,
                "chaves": [k for k in chaves if k], "ok": len(chaves) > 0 and descritas == len(chaves)}
    if isinstance(n, (ast.Tuple, ast.List)):
        niveis = [_str(v) for v in n.elts]
        graus = [x for x in niveis if x and GRAUS.match(x.strip())]
        return {"presente": True, "forma": "lista", "n": len(niveis), "graus": graus,
                "ok": len(niveis) >= 2 and not graus and all(x and len(x) > 12 for x in niveis)}
    if isinstance(n, ast.DictComp):
        # {k: f(k) for k in ...}: descrição derivada da chave (ex.: só troca _ por espaço) não conta como descrição
        src = ast.unparse(n)
        derivada = bool(re.search(r"\.replace\(|\bfor (\w+) in .*:\s*\1\b", src)) and not re.search(r"\.get\(|\[", src.split(" for ")[0])
        return {"presente": True, "forma": "compreensao", "ok": not derivada, "fonte": src[:120]}
    return {"presente": True, "forma": type(n).__name__, "ok": True}


def perguntas(pasta: Path | None = None) -> list[dict]:
    """Toda `Question(...)` do pacote: arquivo, linha, tipo, instrução (resumo) e análise dos critérios."""
    out = []
    for p in sorted((pasta or PACOTE).glob("*.py")):
        try:
            arv = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for n in ast.walk(arv):
            if not (isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "Question"):
                continue
            args = list(n.args)
            kw = {k.arg: k.value for k in n.keywords}
            tipo = _str(args[0]) if args else _str(kw.get("kind"))
            instr = _str(args[1]) if len(args) > 1 else _str(kw.get("instructions"))
            crit = args[2] if len(args) > 2 else kw.get("criteria")
            if tipo not in ("noul", "choice", "score"):
                continue
            c = _criteria(crit)
            ingles = bool(instr) and bool(re.search(r"\b(the|is|does|which|answer)\b", instr, re.I)) and not re.search(r"[ãõçéê]", instr)
            out.append({"arquivo": p.name, "linha": n.lineno, "tipo": tipo, "instrucao": (instr or "")[:120], "criteria": c,
                        "ingles": ingles, "referencia_estado": bool(instr) and "`" in instr})
    return out


def regras(q: dict) -> dict[str, bool]:
    """Uma pergunta cumpre cada regra da doc?"""
    c = q["criteria"]
    if q["tipo"] == "noul":
        crit_ok = c.get("presente") and (c.get("forma") != "dict" or set(c.get("chaves", [])) >= {"true", "false"})
    elif q["tipo"] == "choice":
        crit_ok = bool(c.get("presente") and c.get("ok"))
    else:
        crit_ok = bool(c.get("presente") and c.get("ok"))
    return {"criterios": bool(crit_ok), "ingles": q["ingles"], "referencia_estado": q["referencia_estado"]}


def cobertura(pasta: Path | None = None) -> dict:
    qs = perguntas(pasta)
    for q in qs:
        q["regras"] = regras(q)
    n = len(qs) or 1
    por_regra = {r: round(sum(q["regras"][r] for q in qs) / n, 3) for r in ("criterios", "ingles", "referencia_estado")}
    faltam = [{"onde": f"{q['arquivo']}:{q['linha']}", "tipo": q["tipo"], "instrucao": q["instrucao"],
               "falta": [r for r, ok in q["regras"].items() if not ok]} for q in qs if not all(q["regras"].values())]
    return {"total": len(qs), "por_tipo": {t: sum(q["tipo"] == t for q in qs) for t in ("noul", "choice", "score")},
            "por_regra": por_regra, "com_criterios": sum(q["regras"]["criterios"] for q in qs), "faltam": faltam}

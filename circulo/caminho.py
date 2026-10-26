"""O caminho de um pedido feito pelo console: pedido → item → estudo → PR → CI → merge, com o tempo de cada etapa e o
que está esperando agora.

`circulo pedir "<uma frase>"` deixa o pedido como arquivo na caixa de entrada (caixa.py): o console nunca escreve no
banco. `circulo caminho [<arquivo>|ev<N>]` lê o banco e costura o fio pelo que já existe: o evento que a caixa criou
(o nome do arquivo vai no payload), o elo pedido → item e o fio do item no rastro (rastro.cadeia_item).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import caixa
from .rastro import cadeia_item

PREFIXO = "console-"
ETAPAS = ("pedido", "item", "estudo", "pr", "ci", "merge")
ESPERA = {"item": "o loop ler a caixa e anotar no roteiro", "estudo": "o estudo do item",
          "pr": "o Developer abrir o PR", "ci": "o CI do PR", "merge": "o gate mergear o PR"}
CI_EM_CURSO = ("checks em andamento", "checks ausentes")


def pedir(data_dir, texto: str, agora: float | None = None) -> Path:
    """Grava o pedido na caixa de entrada; o loop o transforma em evento no próximo giro."""
    texto = (texto or "").strip()
    if len(texto) < caixa.MIN_TEXTO:
        raise ValueError(f"pedido curto demais: escreva ao menos {caixa.MIN_TEXTO} caracteres")
    ms = int((agora if agora is not None else time.time()) * 1000)
    pasta = Path(data_dir) / caixa.PASTA
    pasta.mkdir(parents=True, exist_ok=True)
    while (arq := pasta / f"{PREFIXO}{ms}.md").exists():
        ms += 1
    arq.write_text(texto[:caixa.MAX_TEXTO] + "\n", encoding="utf-8")
    return arq


def _em_do_nome(nome: str) -> float | None:
    m = re.fullmatch(rf"{PREFIXO}(\d+)\.md", nome)
    return int(m.group(1)) / 1000 if m else None


def _ultimo(store, data_dir) -> str | None:
    nomes = [p.name for p in (Path(data_dir) / caixa.PASTA).glob(f"{PREFIXO}*.md")]
    r = store.one("SELECT json_extract(payload,'$.arquivo') a FROM events WHERE json_extract(payload,'$.arquivo') LIKE ? "
                  "ORDER BY id DESC LIMIT 1", (f"{PREFIXO}%",))
    if r and r["a"]:
        nomes.append(r["a"])
    return max(nomes, key=lambda n: (_em_do_nome(n) or 0, n), default=None)


def _etapa(etapa, titulo, em, feita=True, detalhe=""):
    return {"etapa": etapa, "titulo": titulo, "em": em, "feita": feita, "detalhe": detalhe or "", "dur_s": None}


def caminho(store, ref: str | None = None, data_dir=None, now: float | None = None) -> dict | None:
    """O fio do pedido: `ref` é o nome do arquivo da caixa ou `ev<N>`; sem `ref`, o último pedido do console."""
    now = now or time.time()
    ref = (ref or "").strip() or (_ultimo(store, data_dir) if data_dir is not None else None)
    if not ref:
        return None
    if m := re.fullmatch(r"(?:ev)?(\d+)", ref):
        ev = store.one("SELECT * FROM events WHERE id=?", (int(m.group(1)),))
    else:
        ev = store.one("SELECT * FROM events WHERE json_extract(payload,'$.arquivo')=? ORDER BY id DESC LIMIT 1", (ref,))
    if ev is None:
        arq = Path(data_dir) / caixa.PASTA / ref if data_dir is not None else None
        if arq is None or not arq.is_file():
            return None
        texto, em, item, it_em, falha = arq.read_text(encoding="utf-8").strip(), _em_do_nome(ref) or arq.stat().st_mtime, None, None, None
    else:
        payload = json.loads(ev["payload"])
        texto = str(payload.get("text") or payload.get("pedido") or "")
        em = _em_do_nome(payload.get("arquivo") or "") or ev["created_at"]
        e = store.one("SELECT para, em FROM elos WHERE de=? AND relacao='virou_item' LIMIT 1", (f"pedido:{ev['id']}",))
        item, it_em = (int(e["para"].split(":")[1]), e["em"]) if e else (None, None)
        falha = f"o pedido falhou ao virar item: {ev['error'] or '?'}" if ev["status"] == "failed" else None

    etapas = [_etapa("pedido", "Pedido", em)]
    fim = None
    c = cadeia_item(store, item, now) if item is not None else None
    if c is None:
        etapas += [_etapa(e, "", None, False) for e in ETAPAS[1:]]
    else:
        passos = c["passos"]
        estudo = next((p for p in passos if p["etapa"] == "estudo" and p["estado"] != "pendente"), None)
        pr = next((p for p in passos if p["etapa"] == "pr"), None)
        gates = [p for p in passos if p["etapa"] == "gate"]
        ci = next((g for g in gates if not g["detalhe"].startswith(CI_EM_CURSO)), None)
        merge = next((g for g in gates if g["titulo"] == "Gate mergeou"), None)
        n = pr["no"].split(":")[1] if pr else ""
        etapas += [_etapa("item", f"virou item #{item}", it_em),
                   _etapa("estudo", estudo["titulo"], estudo["em"], detalhe=estudo["detalhe"]) if estudo else _etapa("estudo", "", None, False),
                   _etapa("pr", f"PR #{n} aberto", pr["em"]) if pr else _etapa("pr", "", None, False),
                   _etapa("ci", f"CI: {ci['detalhe'][:80]}", ci["em"]) if ci else _etapa("ci", "", None, False),
                   _etapa("merge", f"PR #{n} mergeado", merge["em"]) if merge else _etapa("merge", "", None, False)]
        fim = next((p for p in reversed(passos) if p["etapa"] == "fim" and p["estado"] == "falha"), None)
        if gates and not merge:
            fim = fim or {"titulo": gates[-1]["detalhe"][:200]}

    anterior = None
    for e in etapas:
        if e["em"] is not None:
            if anterior is not None:
                e["dur_s"] = round(e["em"] - anterior, 3)
            anterior = e["em"]
    ultima = max((i for i, e in enumerate(etapas) if e["feita"]), default=0)
    esperando = None
    if ultima + 1 < len(etapas):
        prox = etapas[ultima + 1]["etapa"]
        esperando = {"etapa": prox, "o_que": ESPERA[prox], "ha_s": round(now - anterior) if anterior else None,
                     "motivo": falha or (fim["titulo"] if fim else "")}
    return {"ref": ref, "texto": texto, "evento": ev["id"] if ev else None, "item": item, "etapas": etapas,
            "esperando": esperando, "total_s": round(anterior - em, 3) if anterior else 0}


def _dur(s: float | None) -> str:
    if s is None:
        return ""
    s = int(s)
    if s < 60:
        return f"{s} s"
    h, m = divmod(s // 60, 60)
    return f"{h // 24} d {h % 24} h" if h >= 24 else f"{h} h {m} min" if h else f"{m} min"


def texto(c: dict) -> str:
    linhas = [f"Pedido {c['ref']}: \"{c['texto'][:120]}\""]
    for e in c["etapas"]:
        quando = time.strftime("%d/%m %H:%M", time.localtime(e["em"])) if e["em"] else ""
        marca = "✓" if e["feita"] else "·"
        titulo = e["titulo"] or f"{e['etapa']}: ainda não"
        linhas.append(f"  {marca} {titulo[:60]:<60} {quando:<11} {'+' + _dur(e['dur_s']) if e['dur_s'] is not None else ''}")
    linhas.append(f"Tempo até aqui: {_dur(c['total_s'])}")
    w = c["esperando"]
    if w:
        linhas.append(f"Esperando agora: {w['o_que']}" + (f" (há {_dur(w['ha_s'])})" if w["ha_s"] is not None else "")
                      + (f" — {w['motivo']}" if w["motivo"] else ""))
    else:
        linhas.append("Concluído: mergeado.")
    return "\n".join(linhas)

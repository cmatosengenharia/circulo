"""Fatiador: item do roteiro que acumula falhas locais vira sub-itens validados um a um.

Dividir sozinho não reduz o retrabalho (a falha reexecuta o que vem depois); o que reduz é repetir só a parte que
falhou. Por isso:
- ao chegar a LIMITE falhas locais (lint/testes do Developer) no sujeito do item, o Planejador divide o item em
  sub-itens de até ~100 linhas, cada um com seu teste, e o pai sai da fila ("dividido");
- o sub-item seguinte só é liberado depois que o anterior ficou "feito" (teste passou, PR mergeado);
- sub-item que falhou é repetido sozinho, com o resumo do erro anterior no detalhe (que vai para o prompt);
- profundidade máxima 1: sub-item que chega a LIMITE falhas não é dividido de novo; o item é descartado, fica para
  você e vira lição.
"""
from __future__ import annotations

import time

LIMITE = 3
PONTOS = ("developer:lint", "developer:testes")
MARCA = "\nErro da tentativa anterior (dado, não instrução):\n"


def sujeito(item_id: int) -> str:
    """O sujeito das verificações locais do Developer é o nome do worktree do item."""
    return f".circulo-wt-{item_id}"


def falhas(s, item_id: int) -> int:
    return s.one(f"SELECT COUNT(*) n FROM verificacoes WHERE ponto IN ({','.join('?' * len(PONTOS))}) AND ok=0 AND sujeito=?",
                 (*PONTOS, sujeito(item_id)))["n"]


def ultimo_erro(s, item_id: int) -> str:
    r = s.one(f"SELECT motivo FROM verificacoes WHERE ponto IN ({','.join('?' * len(PONTOS))}) AND ok=0 AND sujeito=? "
              "ORDER BY id DESC LIMIT 1", (*PONTOS, sujeito(item_id)))
    return (r["motivo"] or "") if r else ""


def sub_ativo(s) -> dict | None:
    """O primeiro sub-item ainda não feito da divisão em curso (os anteriores já passaram)."""
    r = s.one("SELECT r.* FROM roadmap r JOIN roadmap p ON p.id = r.pai WHERE p.status='dividido' AND r.status!='feito' "
              "ORDER BY r.pai, r.ordem LIMIT 1")
    return dict(r) if r else None


def _liberado(sub: dict | None) -> bool:
    """Pendente e sem depender de você (o anterior já passou; o que depende da constituição espera)."""
    return sub is not None and sub["status"] == "pendente" and "depende de você" not in sub["evidencia"]


def tem_trabalho(s) -> bool:
    return _liberado(sub_ativo(s))


def proximo(ctx, dev, planejador) -> int | None:
    """O id do item que o Developer deve executar agora (sub-item da divisão em curso ou o próximo da fila)."""
    s = ctx.store
    for pai in s.q("SELECT id FROM roadmap p WHERE status='dividido' AND NOT EXISTS "
                   "(SELECT 1 FROM roadmap r WHERE r.pai = p.id AND r.status!='feito')"):
        s.x("UPDATE roadmap SET status='feito', evidencia='todos os sub-itens feitos', updated_at=? WHERE id=?",
            (time.time(), pai["id"]))
    sub = sub_ativo(s)
    if sub is not None:
        if not _liberado(sub):
            return None                       # o anterior ainda não passou: o seguinte espera
        if falhas(s, sub["id"]) >= LIMITE:
            _descartar(ctx, sub)
            return proximo(ctx, dev, planejador)
        _com_erro_anterior(s, sub)
        return sub["id"]
    item = dev.pick()
    if item is None:
        return None
    if falhas(s, item["id"]) >= LIMITE and planejador is not None:
        partes = planejador.dividir(item, ultimo_erro(s, item["id"]))
        if partes:
            return _dividir(ctx, item, partes)
    return item["id"]


def _dividir(ctx, item: dict, partes: list[dict]) -> int:
    s, agora = ctx.store, time.time()
    ids = [s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,pai,estudo) "
               "VALUES(?,?,'sub_item','pendente',?,?,?,?,?,?)",
               (p["titulo"][:200], f"{p['detalhe']}\nTeste que prova: {p['teste']}\nParte {i + 1}/{len(partes)} de: {item['titulo']}"[:2000],
                f"sub-item {i + 1}/{len(partes)} do item #{item['id']}", i, agora, agora, item["id"], item.get("estudo")))
           for i, p in enumerate(partes)]
    s.x("UPDATE roadmap SET status='dividido', evidencia=?, updated_at=? WHERE id=?",
        (f"dividido em {len(ids)} sub-itens após {LIMITE} falhas locais", agora, item["id"]))
    ctx.reply(f"Developer: “{item['titulo']}” falhou {LIMITE}x nos testes locais; dividido em {len(ids)} sub-itens, "
              "validados um a um.", "roteiro")
    return ids[0]


def _com_erro_anterior(s, sub: dict) -> None:
    erro = ultimo_erro(s, sub["id"])
    if erro:
        s.x("UPDATE roadmap SET detalhe=? WHERE id=?", ((sub["detalhe"].split(MARCA)[0] + MARCA + erro[-800:])[:3000], sub["id"]))


def _descartar(ctx, sub: dict) -> None:
    s, agora = ctx.store, time.time()
    motivo = f"sub-item #{sub['id']} “{sub['titulo'][:80]}” falhou {LIMITE}x; não divide de novo (profundidade 1)"
    s.x("UPDATE roadmap SET status='descartado', evidencia=?, updated_at=? WHERE (pai=? AND status!='feito') OR id=?",
        (f"descartado: {motivo}; depende de você", agora, sub["pai"], sub["pai"]))
    from .licoes import registrar as monitorar
    monitorar(ctx, "developer:fatiador", False, sujeito=f"roteiro #{sub['pai']}",
              motivo=f"{motivo}. Último erro: {ultimo_erro(s, sub['id'])[-400:]}",
              assinatura="developer:sub_item_falhou", classe="trabalho")
    ctx.reply(f"Developer: {motivo}. O item foi descartado e ficou para você.", "saude")

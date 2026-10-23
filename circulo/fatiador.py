"""Fatiador: item do roteiro que acumula falhas locais vira sub-itens validados um a um.

Dividir sozinho não reduz o retrabalho (a falha reexecuta o que vem depois); o que reduz é repetir só a parte que
falhou. Por isso:
- ao chegar a LIMITE falhas locais (lint/testes do Developer) no sujeito do item, o Planejador divide o item em
  sub-itens de até ~100 linhas, cada um com seu teste, e o pai sai da fila ("dividido");
- o Developer também pede a divisão na hora (CORTES): teto de tokens do item estourado ou a mesma falha 2x seguidas;
- o sub-item seguinte só é liberado depois que o anterior ficou "feito" (teste passou, PR mergeado);
- sub-item que falhou é repetido sozinho, com o resumo do erro anterior no detalhe (que vai para o prompt);
- profundidade máxima 1: sub-item que chega a LIMITE falhas (ou a um corte) não é dividido de novo; o item é
  descartado, fica para você e vira lição.

Pré-divisão (antes de qualquer chamada): item planejado que cita mais de LIMITE_MODULOS módulos ou LIMITE_SIMBOLOS
funções/testes vira um sub-item por módulo, por regra, sem a LLM (o sub-item #60 gastou 94705 tokens inteiro). Os
limites são um palpite inicial: a estimativa de cada fatia fica guardada e `medicoes` a compara com os tokens reais,
para recalibrar. O teto de tokens segue como rede de segurança: a fatia que ainda é cortada (ADaPT: dividir quando a
execução falha) é redividida sozinha pelo Planejador, uma vez, e as outras fatias seguem.
"""
from __future__ import annotations

import re
import time

LIMITE = 3
PONTOS = ("developer:lint", "developer:testes")
CORTES = ("developer:teto", "developer:falha_repetida")
MARCA = "\nErro da tentativa anterior (dado, não instrução):\n"

LIMITE_MODULOS, LIMITE_SIMBOLOS = 2, 5
LINHAS_POR_MODULO, LINHAS_POR_SIMBOLO = 40, 15
PRE_ORIGENS = ("loop", "pedido_cassio")          # itens planejados; o texto de um erro cita os arquivos do traceback
ESTIMATIVAS = "fatiador_estimativas"             # kv: id do sub-item pré-dividido -> estimativa
_CITACAO = re.compile(r"(?P<mod>[\w./-]+\.py)\b|(?P<sim>\btest_\w+|\b[a-z_]\w*(?=\())")
_LINHAS = re.compile(r"(\d+)\s*linhas")


def estimar_tamanho(titulo: str, detalhe: str) -> dict:
    """Módulos (.py fora de tests/), símbolos (funções e testes) e testes citados, com o trecho do detalhe de cada
    módulo e os símbolos que vêm depois dele (localização por regra, como o Agentless), e as linhas estimadas."""
    modulos, simbolos, testes, trechos, simbolos_de = [], [], [], {}, {}
    atual, inicio = None, 0
    texto = f"{titulo}\n{detalhe}"
    for m in _CITACAO.finditer(texto):
        nome = m.group("mod") or m.group("sim")
        if m.group("mod") and nome.startswith("tests/"):
            testes += [nome] if nome not in testes else []
        elif m.group("mod"):
            if atual is not None:
                trechos[atual] += texto[inicio:m.start()]
            atual, inicio = nome, m.start()
            if nome not in modulos:
                modulos.append(nome)
                trechos[nome], simbolos_de[nome] = "", []
        elif nome not in simbolos:
            simbolos.append(nome)
            if atual is not None:
                simbolos_de[atual].append(nome)
    if atual is not None:
        trechos[atual] += texto[inicio:]
    citadas = sum(int(n) for n in _LINHAS.findall(texto))
    return {"modulos": modulos, "simbolos": simbolos, "testes": testes, "trechos": trechos, "simbolos_de": simbolos_de,
            "linhas": citadas or LINHAS_POR_MODULO * len(modulos) + LINHAS_POR_SIMBOLO * len(simbolos)}


def grande_demais(est: dict) -> bool:
    return len(est["modulos"]) > LIMITE_MODULOS or len(est["simbolos"]) > LIMITE_SIMBOLOS


def _fatias(item: dict, est: dict) -> list[tuple[dict, dict]]:
    """Um sub-item por módulo citado, com o seu trecho e o seu teste; [] = pequeno ou um módulo só."""
    if not grande_demais(est) or len(est["modulos"]) < 2:
        return []
    out = []
    for mod in est["modulos"]:
        trecho, sims = est["trechos"][mod].strip(), est["simbolos_de"][mod]
        teste = next((t for t in est["testes"] if t in trecho), None) or f"tests/test_{mod.rsplit('/', 1)[-1]}"
        out.append(({"titulo": f"{mod}: {item['titulo']}", "detalhe": f"Só {mod}: {trecho}", "teste": teste},
                    {"modulos": 1, "simbolos": len(sims),
                     "linhas": LINHAS_POR_MODULO + LINHAS_POR_SIMBOLO * len(sims)}))
    return out


def medicoes(s) -> list[dict]:
    """Estimativa x tokens reais de cada sub-item pré-dividido, para recalibrar LIMITE_MODULOS/LIMITE_SIMBOLOS."""
    from .reparo import tokens_do_item
    est = s.get(ESTIMATIVAS) or {}
    if not est:
        return []
    rows = s.q(f"SELECT id, titulo FROM roadmap WHERE id IN ({','.join('?' * len(est))}) ORDER BY id", tuple(map(int, est)))
    return [{"id": r["id"], **est[str(r["id"])], "tokens": tokens_do_item(s, r["titulo"])[0]} for r in rows]


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


def motivo_de_dividir(s, item_id: int) -> str:
    """Por que o item deve ser dividido agora: o corte que o Developer pediu ou LIMITE falhas locais. '' = não deve."""
    r = s.one(f"SELECT motivo FROM verificacoes WHERE ponto IN ({','.join('?' * len(CORTES))}) AND ok=0 AND sujeito=? "
              "ORDER BY id DESC LIMIT 1", (*CORTES, sujeito(item_id)))
    if r:
        return r["motivo"] or "corte pedido pelo Developer"
    return f"falhou {LIMITE}x nos testes locais" if falhas(s, item_id) >= LIMITE else ""


def sub_ativo(s) -> dict | None:
    """O primeiro sub-item ainda não feito da divisão em curso (os anteriores já passaram)."""
    r = s.one("SELECT r.* FROM roadmap r JOIN roadmap p ON p.id = r.pai WHERE p.status='dividido' "
              "AND r.status NOT IN ('feito','dividido') "
              "ORDER BY r.pai, r.ordem LIMIT 1")
    return dict(r) if r else None


def _liberado(sub: dict | None) -> bool:
    """Pendente e sem depender de você (o anterior já passou; o que depende da constituição espera)."""
    return sub is not None and sub["status"] == "pendente" and "depende de você" not in sub["evidencia"]


def tem_trabalho(s) -> bool:
    return _liberado(sub_ativo(s))


def proximo(ctx, dev, planejador) -> int | None:
    """O id do item que o Developer deve executar agora (sub-item da divisão em curso ou o próximo da fila)."""
    from . import roadmap
    s, repo = ctx.store, getattr(dev, "repo", None)
    roadmap.reabrir(s)
    for pai in s.q("SELECT id FROM roadmap p WHERE status='dividido' AND NOT EXISTS "
                   "(SELECT 1 FROM roadmap r WHERE r.pai = p.id AND r.status NOT IN ('feito','dividido'))"):
        s.x("UPDATE roadmap SET status='feito', evidencia='todos os sub-itens feitos', updated_at=? WHERE id=?",
            (time.time(), pai["id"]))
    sub = sub_ativo(s)
    if sub is not None:
        if not _liberado(sub):                # o anterior ainda não passou: o seguinte espera, mas a fila normal não para
            item = dev.pick()
            return item["id"] if item else None
        if roadmap.fora_da_fila(ctx, sub, repo):
            return proximo(ctx, dev, planejador)
        motivo = motivo_de_dividir(s, sub["id"])
        if motivo and str(sub["id"]) in (s.get(ESTIMATIVAS) or {}) and planejador is not None:
            partes = planejador.dividir(sub, ultimo_erro(s, sub["id"]) or motivo)
            if partes:                        # a fatia feita por regra ainda estourou: só ela vai à LLM, uma vez
                return _dividir(ctx, sub, partes, motivo, irmaos=True)[0]
        if motivo:
            _descartar(ctx, sub, motivo)
            return proximo(ctx, dev, planejador)
        _com_erro_anterior(s, sub)
        return sub["id"]
    item = dev.pick()
    if item is None:
        return None
    if roadmap.fora_da_fila(ctx, item, repo):
        return proximo(ctx, dev, planejador)
    motivo = motivo_de_dividir(s, item["id"])
    if motivo:
        partes = planejador.dividir(item, ultimo_erro(s, item["id"]) or motivo) if planejador is not None else []
        if partes:
            return _dividir(ctx, item, partes, motivo)[0]
        # precisa dividir e ninguém dividiu (sem LLM, JSON inválido): o item sai da fila com o motivo, em vez de ser
        # pego a cada giro, cortado sem chamar o agente e devolvido (gastava uma divisão por tentativa, ou travava a fila)
        s.x("UPDATE roadmap SET status='pendente', evidencia=?, desativado=1, updated_at=? WHERE id=?",
            (f"depende de você: precisa ser dividido ({motivo[:160]}) e o Planejador não conseguiu", time.time(), item["id"]))
        if callable(getattr(ctx, "reply", None)):
            ctx.reply(f"Developer: “{item['titulo'][:80]}” precisa ser dividido ({motivo[:100]}) e o Planejador não conseguiu; "
                      "o item ficou desativado para você decidir.", "saude")
        return None
    if item["origem"] in PRE_ORIGENS:
        est = estimar_tamanho(item["titulo"], item["detalhe"])
        fatias = _fatias(item, est)
        if fatias:
            ids = _dividir(ctx, item, [p for p, _ in fatias], f"cita {len(est['modulos'])} módulos e "
                           f"{len(est['simbolos'])} símbolos (~{est['linhas']} linhas): um sub-item por módulo, sem a LLM")
            s.set(ESTIMATIVAS, {**(s.get(ESTIMATIVAS) or {}), **{str(i): e for i, (_, e) in zip(ids, fatias, strict=True)}})
            return ids[0]
    return item["id"]


def _dividir(ctx, item: dict, partes: list[dict], motivo: str, irmaos: bool = False) -> list[int]:
    """Grava os sub-itens. irmaos=True: o item já é sub-item; as partes entram no lugar dele, sob o mesmo pai."""
    s, agora = ctx.store, time.time()
    pai, ordem = (item["pai"], item["ordem"] + 1) if irmaos else (item["id"], 0)
    if irmaos:
        s.x("UPDATE roadmap SET ordem=ordem+? WHERE pai=? AND ordem>?", (len(partes), pai, item["ordem"]))
    ids = [s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,pai,estudo) "
               "VALUES(?,?,'sub_item','pendente',?,?,?,?,?,?)",
               (p["titulo"][:200], f"{p['detalhe']}\nTeste que prova: {p['teste']}\nParte {i + 1}/{len(partes)} de: {item['titulo']}"[:2000],
                f"sub-item {i + 1}/{len(partes)} do item #{item['id']}", ordem + i, agora, agora, pai, item.get("estudo")))
           for i, p in enumerate(partes)]
    s.x("UPDATE roadmap SET status='dividido', evidencia=?, updated_at=? WHERE id=?",
        (f"dividido em {len(ids)} sub-itens: {motivo[:200]}", agora, item["id"]))
    ctx.reply(f"Developer: “{item['titulo']}” {motivo[:200]}; dividido em {len(ids)} sub-itens, "
              "validados um a um.", "roteiro")
    return ids


def _com_erro_anterior(s, sub: dict) -> None:
    erro = ultimo_erro(s, sub["id"])
    if erro:
        s.x("UPDATE roadmap SET detalhe=? WHERE id=?", ((sub["detalhe"].split(MARCA)[0] + MARCA + erro[-800:])[:3000], sub["id"]))


def _descartar(ctx, sub: dict, causa: str) -> None:
    s, agora = ctx.store, time.time()
    motivo = f"sub-item #{sub['id']} “{sub['titulo'][:80]}” {causa[:200]}; não divide de novo (profundidade 1)"
    s.x("UPDATE roadmap SET status='descartado', evidencia=?, updated_at=? WHERE (pai=? AND status!='feito') OR id=?",
        (f"descartado: {motivo}; depende de você", agora, sub["pai"], sub["pai"]))
    from .licoes import registrar as monitorar
    monitorar(ctx, "developer:fatiador", False, sujeito=f"roteiro #{sub['pai']}",
              motivo=f"{motivo}. Último erro: {ultimo_erro(s, sub['id'])[-400:]}",
              assinatura="developer:sub_item_falhou", classe="trabalho")
    ctx.reply(f"Developer: {motivo}. O item foi descartado e ficou para você.", "saude")

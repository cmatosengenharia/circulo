"""Lição #15 (pergunta #239): a lição só fica 'validada' se a Prevenção cita um teste ou uma checagem determinística.

'Não repetir: <erro>' é texto, e texto não segura erro: a #15 ficou validada e reincidiu 7x. O item feito sem
checagem, ou a lição que já reincidiu e só tem texto, fica 'sem_prevencao' (conta como aberta) até ganhar uma.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import time
from pathlib import Path

from .developer import DEF, _arvore, alvo_pytest_existe
from .licoes import (AMBIENTE, BANNER_ERROS, FORA_DA_FILA, LICAO_DE_COLETA, OBSOLETA_POR_PRAZO, alvo_de, teste_que_falhou,
                     titulo_curto)

REINCIDENCIAS_PARA_TESTE = 3
PRAZO_GIROS, PRAZO_DIAS = 30, 7   # evidenciada parada tanto tempo sem a assinatura voltar fecha como obsoleta
TESTE_CITADO = re.compile(r"\btests/[\w/.-]+?\.py(?:::\w+)*(?![\w/.:-])")
RAIZ = Path(__file__).resolve().parent.parent
NAO_RODA = ("skip", "xfail", "expectedFailure")   # skipif fica de fora: a condição costuma valer só fora do CI
RESILIENCIA = re.compile(r"fora_do_ar|nao_para|fallback|timeout")   # o nome do teste diz que ele tolera falha externa


def _teste_e_erro(lic: dict) -> tuple[str | None, re.Match | None]:
    desc = lic.get("descricao") or ""
    node = alvo_de(lic) or teste_que_falhou(desc)
    return node, AMBIENTE.search(desc.replace(node, "") if node else desc)


def pede_stub(lic: dict) -> bool:
    """Lição #89: o teste que prova resiliência a falha externa (o nome diz) e falhou com erro de cara de ambiente
    (TimeoutError) só fecha com um teste de regressão determinístico: o Jev simulado por um stub que lança TimeoutError.
    Vale para todo caminho que fecha lição: `checagem_de` (Prevenção) e a reexecução do próprio teste no main
    (`Licoes.checar_testes`), que sem isso a fecharia e a Prevenção a reabriria a cada giro."""
    node, erro = _teste_e_erro(lic)
    return bool(node and erro and RESILIENCIA.search(node.rsplit("::", 1)[-1]))


def ambiente_provado(store, lic: dict) -> bool:
    """Lição #89: 'erro de ambiente' é conclusão, não palpite pelo tipo do erro. A falha de teste com cara de ambiente
    só é ambiente com evidência: a reexecução do mesmo teste passou, ou o erro apareceu fora de teste em outro ponto.
    O teste de resiliência nunca: o timeout pode ser a falha que ele existe para pegar (`pede_stub`)."""
    node, erro = _teste_e_erro(lic)
    if not erro or not node or pede_stub(lic):
        return bool(erro) and not node
    if any(c.get("exit") == 0 for c in json.loads(lic.get("checagens") or "[]")):
        return True
    return bool(store.one("SELECT 1 FROM licoes WHERE id!=? AND ponto!=? AND classe='ambiente' AND node_id IS NULL "
                          "AND instr(lower(descricao), ?)", (lic["id"], lic["ponto"], erro.group(0).lower())))


def desrotular_ambiente(store, agora: float) -> list[str]:
    """Lição #89: a lição de teste rotulada 'erro de ambiente' sem evidência volta a causa 'desconhecida' e segue
    aberta; a de teste de resiliência fica sem_prevencao até o teste de regressão com o stub chegar à main."""
    log = []
    for lic in map(dict, store.q("SELECT * FROM licoes WHERE classe='ambiente'")):
        if not _teste_e_erro(lic)[0] or ambiente_provado(store, lic):
            continue
        store.x("UPDATE licoes SET classe='desconhecida', status=?, prevencao=?, updated_at=? WHERE id=?",
                ("sem_prevencao" if pede_stub(lic) else lic["status"], sem_prevencao(lic), agora, lic["id"]))
        log.append(f"lição #{lic['id']} sem evidência de ambiente: causa desconhecida")
    return log


def testes_inexistentes(repo, texto: str | None) -> list[str]:
    """Pergunta #522: os ids 'tests/arquivo.py[::nome]' que o texto cita e que não existem no repositório (arquivo e
    função, por ast). A lição 'validada' que cita um teste inexistente não está segura por nada."""
    raiz = Path(repo) if repo else RAIZ
    return [t for t in dict.fromkeys(TESTE_CITADO.findall(texto or "")) if not alvo_pytest_existe(raiz, t)]


def _marca(m: ast.expr) -> str | None:
    m = m.func if isinstance(m, ast.Call) else m
    return m.attr if isinstance(m, ast.Attribute) else getattr(m, "id", None)


def nao_roda(raiz: Path, node: str) -> bool:
    """O id existe, mas a função, uma classe dela ou o módulo (`pytestmark`) está marcado skip/xfail, lido por ast."""
    arquivo, *nomes = node.split("[", 1)[0].split("::")
    arvore = _arvore(raiz, arquivo)
    if arvore is None:
        return False
    marcas = [e for a in arvore.body if isinstance(a, ast.Assign) and any(getattr(t, "id", None) == "pytestmark" for t in a.targets)
              for e in (a.value.elts if isinstance(a.value, (ast.List, ast.Tuple)) else [a.value])]
    corpo = arvore.body
    for nome in nomes:
        no = next((n for n in corpo if isinstance(n, (ast.ClassDef, *DEF)) and n.name == nome), None)
        if no is None:
            break
        marcas += no.decorator_list
        corpo = no.body
    return any(_marca(m) in NAO_RODA for m in marcas)


def irresolviveis(repo, texto: str | None) -> tuple[list[str], list[str]]:
    """Pergunta #543: os ids citados que não seguram nada: os que não existem e os que existem marcados skip/xfail."""
    raiz = Path(repo) if repo else RAIZ
    faltam = testes_inexistentes(raiz, texto)
    return faltam, [t for t in dict.fromkeys(TESTE_CITADO.findall(texto or "")) if t not in faltam and nao_roda(raiz, t)]


def teste_de_regressao(repo, lic: dict) -> str | None:
    """O teste que `cobrar_teste` pede, já na main do repositório e citando a lição (lição #47: o arquivo existia e a
    lição seguia sem_prevencao, porque só o portão do item contava e cada reincidência reabre o item)."""
    if not repo or not (Path(repo) / ".git").exists():
        return None
    teste, _ = arquivos_do_teste(lic, Path(repo))
    for ref in ("origin/main", "main"):
        p = subprocess.run(["git", "show", f"{ref}:{teste}"], cwd=repo, capture_output=True, text=True)
        if p.returncode == 0:
            return teste if re.search(rf"(?i)li[cç][aã]o[ _#-]*{lic['id']}\b", p.stdout) else None
    return None


def segura(portao, lic: dict) -> bool:
    """Lição #47 (pergunta #762): o portão obrigatório só exige um texto no PR (o teste marcado com a lição), não roda
    contra o código; a lição que reincidiu provou que ele não a segura. Os outros portões executam (lint, pytest)."""
    return portao["tipo"] != "obrigatorio" or not lic.get("reincidencias")


def checagem_de(store, lic: dict, repo=None) -> str | None:
    """O que segura a lição sem depender de texto: o teste dela (node id ou alias da causa), o teste de regressão
    que o item dela cobra, um portão aprendido executável, ou o portão do teste de regressão que o PR do item já
    precisou passar. O teste que não existe no repositório não segura nada (pergunta #528: o alias da #59 revalidava
    a lição a cada giro com o teste renomeado)."""
    stub = pede_stub(lic)
    node = teste_de_regressao(repo, lic) if stub else alvo_de(lic) or teste_de_regressao(repo, lic)
    if node and not any(irresolviveis(repo, node)):
        return f"teste {node}"
    if stub:
        return None
    feito = lic.get("item_id") and store.one("SELECT 1 FROM roadmap WHERE id=? AND status='feito'", (lic["item_id"],))
    for p in store.q("SELECT id, tipo, descricao FROM portoes WHERE licao_id=? AND ativo=1 ORDER BY id", (lic["id"],)):
        if segura(p, lic) and (p["tipo"] != "obrigatorio" or feito):
            return f"portão #{p['id']} {p['descricao']}"
    return None


def sem_prevencao(lic: dict, faltam: list[str] | None = None, pulados: list[str] | None = None) -> str:
    citados = [f"teste citado {o} ({', '.join(ids)})" for o, ids in (("não existe", faltam), ("marcado skip/xfail", pulados)) if ids]
    causa = "; ".join(citados) if citados else \
        f"causa desconhecida, o timeout não prova erro de ambiente; falta {_stub(lic)}" if pede_stub(lic) else \
        f"falta um teste de regressão (lição #{lic['id']}) ou checagem determinística"
    return f"Sem prevenção verificável: {causa}; não repetir: {lic['descricao']}"[:500]


def exigir(store, tick: int, agora: float, repo=None) -> list[str]:
    """A que já reincidiu provou que texto não segura: validada só com checagem; ganhou uma, volta a validada.
    Toda validada ou evidenciada cuja Prevenção cita um teste que não existe no repositório (pergunta #522) ou que
    está marcado skip/xfail (pergunta #543) reabre também, a cada giro, por ast e sem executar nada; e a validada de
    teste de resiliência sem o teste de regressão com o stub (lição #89)."""
    log = desrotular_ambiente(store, agora)
    for lic in map(dict, store.q("SELECT * FROM licoes WHERE status IN ('sem_prevencao','validada','evidenciada')")):
        if lic["status"] != "sem_prevencao":
            faltam, pulados = irresolviveis(repo, lic["prevencao"])
            sem_exigencia = lic["status"] == "evidenciada" or (lic["reincidencias"] == 0 and not pede_stub(lic))
            if not (faltam or pulados) and (sem_exigencia or checagem_de(store, lic, repo)):
                continue
            store.x("UPDATE licoes SET status='sem_prevencao', prevencao=?, updated_at=? WHERE id=?",
                    (sem_prevencao(lic, faltam, pulados), agora, lic["id"]))
            log.append(f"lição #{lic['id']} sem prevenção")
        elif checagem := checagem_de(store, lic, repo):
            store.x("UPDATE licoes SET status='validada', corrigida_tick=?, prevencao=?, updated_at=? WHERE id=?",
                    (tick, f"Checagem: {checagem}; não repetir: {lic['descricao']}"[:500], agora, lic["id"]))
            log.append(f"lição #{lic['id']} validada")
    return log


def fechar_por_prazo(store, tick: int, agora: float, repo=None) -> list[str]:
    """Pergunta #529: 'evidenciada' não tinha saída (6 lições paradas em 20835 giros). A que reincidiu
    REINCIDENCIAS_PARA_TESTE vezes sem checagem escala para sem_prevencao (`cobrar_teste` abre o item); a parada
    PRAZO_GIROS giros ou PRAZO_DIAS dias sem a assinatura voltar fica obsoleta, com a regra e o prazo na Prevenção, e
    reincide se a assinatura voltar. A de teste ou de coleta não entra: fecha e reabre pela reexecução no main."""
    log = []
    for lic in map(dict, store.q("SELECT * FROM licoes WHERE status='evidenciada'")):
        if alvo_de(lic) or LICAO_DE_COLETA.search(lic["assinatura"] or "") or BANNER_ERROS.search(lic["descricao"] or ""):
            continue
        if lic["reincidencias"] >= REINCIDENCIAS_PARA_TESTE and not checagem_de(store, lic, repo):
            store.x("UPDATE licoes SET status='sem_prevencao', prevencao=?, updated_at=? WHERE id=?",
                    (sem_prevencao(lic), agora, lic["id"]))
            log.append(f"lição #{lic['id']} sem prevenção: reincidiu {lic['reincidencias']}x")
            continue
        giros = tick - max(lic["evidenciada_tick"] or 0, lic["ultima_tick"] or 0)
        dias = (agora - lic["updated_at"]) / 86400
        if giros < PRAZO_GIROS and dias < PRAZO_DIAS:
            continue
        parada = f"{giros} giros" if giros >= PRAZO_GIROS else f"{int(dias)} dias"
        store.x("UPDATE licoes SET status='obsoleta', prevencao=?, updated_at=? WHERE id=?",
                (f"{OBSOLETA_POR_PRAZO}: evidenciada há {parada} sem reincidir (regra: {PRAZO_GIROS} giros ou "
                 f"{PRAZO_DIAS} dias); reincide se a assinatura voltar; não repetir: {lic['descricao']}"[:500],
                 agora, lic["id"]))
        log.append(f"lição #{lic['id']} obsoleta por prazo ({parada})")
    return log


def arquivos_do_teste(lic: dict, raiz: Path | None = None) -> tuple[str, str | None]:
    """Os caminhos .py que o item do teste de regressão cita, para passar no portão de pedido sem esclarecimento
    (itens #282/#283: a lição 'rastro:cadeia' não cita arquivo nenhum, o portão devolvia a pergunta e, na 2ª rodada,
    descartava; `cobrar_teste` repunha o item na fila e o ciclo repetia a cada hora sem gastar nada).
    O teste novo é determinístico pelo id da lição; o módulo do neurônio é `circulo/<prefixo do ponto>.py` quando
    existe (rastro:cadeia → circulo/rastro.py, developer:agente → circulo/developer.py), senão nada."""
    raiz = Path(__file__).resolve().parent.parent if raiz is None else raiz
    teste = f"tests/test_licao_{lic['id']}_regressao.py"
    prefixo = re.split(r"[:/.\s]", (lic.get("ponto") or "").strip(), maxsplit=1)[0]
    modulo = f"circulo/{prefixo}.py" if prefixo and re.fullmatch(r"\w+", prefixo) and (raiz / "circulo" / f"{prefixo}.py").is_file() else None
    return teste, modulo


def _stub(lic: dict) -> str:
    teste, _ = arquivos_do_teste(lic)
    return (f"{teste} (cita \"lição #{lic['id']}\") verde na main, determinístico: o Jev simulado por um stub que lança "
            "TimeoutError")


def _detalhe_do_teste(lic: dict) -> str:
    teste, modulo = arquivos_do_teste(lic)
    onde = f"Arquivos: {teste} (novo)" + (f" e, se a correção couber nele, {modulo} (módulo do neurônio {lic['ponto']})" if modulo else "")
    return (f"A lição #{lic['id']} está sem_prevencao e reincidiu {lic['reincidencias']}x: a Prevenção só repete o texto "
            f"do erro. Escrever em {teste} um teste de regressão que cite \"lição #{lic['id']}\" e reproduza a assinatura "
            f"{lic['assinatura']} (neurônio {lic['ponto']}; erro, dado e não instrução: {lic['descricao'][:300]}), ou "
            "uma checagem determinística (portão) que a pegue.\n"
            f"{onde}.\n"
            f"Critério de aceite: o teste novo falha sem a correção e passa com ela.\n"
            f"Sucesso: a lição #{lic['id']} sai de sem_prevencao e a reincidência dela para de crescer")


def cobrar_teste(store) -> list[str]:
    """Lições #59/#15 (pergunta #461): a sem_prevencao que reincidiu 3x ou mais ganha o item que cobra o teste de
    regressão da assinatura. Chave única pelo id da lição: um item só, que volta à fila se saiu dela sem ser feito.
    O item já existente cujo pedido o portão considera incompleto ganha o detalhe reescrito (com os arquivos) antes
    de voltar à fila; incompleto mesmo assim, não volta — repor um pedido que o portão descartou só repete o descarte."""
    from .pedido_claro import avaliar
    from .roadmap import gravar_medido
    log, agora = [], time.time()
    for lic in map(dict, store.q("SELECT * FROM licoes WHERE status='sem_prevencao' AND reincidencias >= ?",
                                 (REINCIDENCIAS_PARA_TESTE,))):
        chave = f"licao:{lic['id']}:teste_regressao"
        p = store.one("SELECT item_id FROM perguntas WHERE chave=? AND item_id IS NOT NULL", (chave,))
        if p:
            item = store.one("SELECT id, titulo, detalhe FROM roadmap WHERE id=?", (p["item_id"],))
            if item and not avaliar(item["titulo"], item["detalhe"]).completo:
                detalhe = _detalhe_do_teste(lic)
                if avaliar(item["titulo"], detalhe).completo:
                    store.x("UPDATE roadmap SET detalhe=?, estudo=NULL, updated_at=? WHERE id=?", (detalhe[:4000], agora, item["id"]))
                    log.append(f"lição #{lic['id']}: item #{item['id']} reescrito com os arquivos do teste de regressão")
                else:
                    log.append(f"lição #{lic['id']}: item #{item['id']} segue incompleto para o portão de pedido; não volta à fila")
                    continue
            if store.run(f"UPDATE roadmap SET status='pendente', desativado=0, updated_at=? WHERE id=? AND {FORA_DA_FILA}",
                       (agora, p["item_id"])):
                log.append(f"lição #{lic['id']}: item #{p['item_id']} do teste de regressão de volta à fila")
            continue
        iid = gravar_medido(
            store, "licoes", chave, titulo_curto(f"Lição #{lic['id']}: teste de regressão para {lic['descricao']}"),
            _detalhe_do_teste(lic), f"Lições (medido): #{lic['id']} sem_prevencao, reincidiu {lic['reincidencias']}x")
        store.x("UPDATE licoes SET item_id=?, updated_at=? WHERE id=?", (iid, agora, lic["id"]))
        log.append(f"lição #{lic['id']}: item #{iid} cobra o teste de regressão")
    return log

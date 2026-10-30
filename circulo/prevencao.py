"""Lição #15 (pergunta #239): a lição só fica 'validada' se a Prevenção cita um teste ou uma checagem determinística.

'Não repetir: <erro>' é texto, e texto não segura erro: a #15 ficou validada e reincidiu 7x. O item feito sem
checagem, ou a lição que já reincidiu e só tem texto, fica 'sem_prevencao' (conta como aberta) até ganhar uma.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from .licoes import FORA_DA_FILA, alvo_de, titulo_curto

REINCIDENCIAS_PARA_TESTE = 3


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


def checagem_de(store, lic: dict, repo=None) -> str | None:
    """O que segura a lição sem depender de texto: o teste dela (node id ou alias da causa), o teste de regressão
    que o item dela cobra, um portão aprendido executável, ou o portão do teste de regressão que o PR do item já
    precisou passar."""
    node = alvo_de(lic) or teste_de_regressao(repo, lic)
    if node:
        return f"teste {node}"
    feito = lic.get("item_id") and store.one("SELECT 1 FROM roadmap WHERE id=? AND status='feito'", (lic["item_id"],))
    for p in store.q("SELECT id, tipo, descricao FROM portoes WHERE licao_id=? AND ativo=1 ORDER BY id", (lic["id"],)):
        if p["tipo"] != "obrigatorio" or feito:
            return f"portão #{p['id']} {p['descricao']}"
    return None


def sem_prevencao(lic: dict) -> str:
    return (f"Sem prevenção verificável: falta um teste de regressão (lição #{lic['id']}) ou checagem determinística; "
            f"não repetir: {lic['descricao']}")[:500]


def exigir(store, tick: int, agora: float, repo=None) -> list[str]:
    """A que já reincidiu provou que texto não segura: validada só com checagem; ganhou uma, volta a validada."""
    log = []
    for lic in map(dict, store.q("SELECT * FROM licoes WHERE status='sem_prevencao' "
                                 "OR (status='validada' AND reincidencias > 0)")):
        checagem = checagem_de(store, lic, repo)
        if lic["status"] == "validada" and not checagem:
            store.x("UPDATE licoes SET status='sem_prevencao', prevencao=?, updated_at=? WHERE id=?",
                    (sem_prevencao(lic), agora, lic["id"]))
            log.append(f"lição #{lic['id']} sem prevenção")
        elif lic["status"] == "sem_prevencao" and checagem:
            store.x("UPDATE licoes SET status='validada', corrigida_tick=?, prevencao=?, updated_at=? WHERE id=?",
                    (tick, f"Checagem: {checagem}; não repetir: {lic['descricao']}"[:500], agora, lic["id"]))
            log.append(f"lição #{lic['id']} validada")
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

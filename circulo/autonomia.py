"""Autonomia: nas primeiras versões o loop não depende de humano para nada (Cássio, 31/10).

O "Precisa de você" continua existindo como janela — mas nada fica parado esperando. Cada ponto que antes esperava uma
decisão humana tem aqui a decisão padrão do próprio loop, com prazo; a sua ação vira sobrescrita opcional, nunca
pré-requisito. Roda no SRE a cada passagem (regras sobre o banco, sem LLM); cada decisão sai como aviso "Decidi
sozinho: …" para você ler depois, e fica em kv `autonomia` (a última passagem e o total por tipo).

Regras (prazo contado desde que o ponto apareceu):
- item contestado pelo estudo → o loop confia no próprio estudo: fora da fila (PRAZO_CONTESTADO);
- item "depende de você" (chave, instalação) → fora da fila, o diagnóstico fica (PRAZO_DEPENDE);
- orçamento do dia esgotado → modo sem limite (decisão do Cássio em 29/10: sem limite de tokens);
- Norte sem evolução no prazo → o loop reescreve a própria estratégia (`reescrever_norte`): sobe a cota de produto,
  abre mais vagas de produto no Indagador e gira a lista de épicos; o marco recomeça;
- lição esgotada (3 PRs e reincide) → sobe de camada (regra → CI → arquitetura); no topo, é aceita (status `aceita`)
  e sai do caminho: o loop não trava mais por ela;
- Médico escalado "para você" → vira item urgente de origem erro na frente da fila (PRAZO_MEDICO);
- lançamento de finanças esperando revisão → confirmado (PRAZO_REVISAO), o que vier de extrato é dado, não opinião;
- aviso não lido → visto (PRAZO_AVISO).
O que o loop não pode decidir (chave de API, login da assinatura, extrato que só você tem) fica no diagnóstico, sem
travar nada: o loop segue com o que tem.
"""
from __future__ import annotations

import time

H = 3600.0
PRAZO_CONTESTADO = 2 * H
PRAZO_DEPENDE = 2 * H
PRAZO_MEDICO = 2 * H
PRAZO_REVISAO = 24 * H
PRAZO_AVISO = 24 * H
KV = "autonomia"
ESTRATEGIA = "norte_estrategia"      # {"nivel", "cota", "vagas", "rotacao", "em"}: o que o loop mudou em si por conta própria
COTAS = (0.5, 0.7, 0.85)
VAGAS = (2, 3, 4)


def _avisar(store, texto: str, agora: float) -> None:
    store.x("INSERT INTO alerts(kind,message,created_at,delivered) VALUES('controle',?,?,1)", ("Decidi sozinho: " + texto, agora))


def itens_contestados(store, agora: float) -> list[int]:
    ids = [r["id"] for r in store.q("SELECT id FROM roadmap WHERE status='contestado' AND updated_at<?", (agora - PRAZO_CONTESTADO,))]
    for iid in ids:
        store.x("UPDATE roadmap SET status='descartado', desativado=1, evidencia=COALESCE(evidencia,'') || ' · fora da fila pela autonomia: o estudo contradiz o pedido', updated_at=? WHERE id=?", (agora, iid))
        _avisar(store, f"item #{iid} contestado pelo estudo ficou fora da fila (reative no painel se discordar).", agora)
    return ids


def itens_dependentes(store, agora: float) -> list[int]:
    ids = [r["id"] for r in store.q("SELECT id FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 AND evidencia LIKE '%depende de você%' "
                                    "AND updated_at<?", (agora - PRAZO_DEPENDE,))]
    for iid in ids:
        store.x("UPDATE roadmap SET desativado=1, updated_at=? WHERE id=?", (agora, iid))
        _avisar(store, f"item #{iid} dependia de você há mais de {int(PRAZO_DEPENDE / H)} h: fora da fila; o diagnóstico continua em Integrações.", agora)
    return ids


def orcamento(store, agora: float) -> bool:
    if store.get("loop_status") != "pausado_orcamento":
        return False
    from .budget import definir_modo
    definir_modo(store, "ilimitado")
    store.set("loop_status", "rodando")
    _avisar(store, "orçamento do dia esgotado virou modo sem limite (sua decisão de 29/10: sem limite de tokens).", agora)
    return True


def estrategia(store) -> dict:
    e = store.get(ESTRATEGIA) or {}
    return {"nivel": int(e.get("nivel", 0)), "cota": float(e.get("cota", COTAS[0])), "vagas": int(e.get("vagas", VAGAS[0])),
            "rotacao": int(e.get("rotacao", 0)), "em": e.get("em")}


def reescrever_norte(store, agora: float) -> dict | None:
    """O marco cobrado sem evolução: em vez de esperar que alguém reescreva o desenho, o loop muda o que controla."""
    nm = store.get("norte_marco") or {}
    if not nm.get("cobrado") or nm.get("evoluiu"):
        return None
    e = estrategia(store)
    nivel = e["nivel"] + 1
    novo = {"nivel": nivel, "cota": COTAS[min(nivel, len(COTAS) - 1)], "vagas": VAGAS[min(nivel, len(VAGAS) - 1)],
            "rotacao": e["rotacao"] + 3, "em": agora}
    store.set(ESTRATEGIA, novo)
    store.set("perguntas_esgotadas", None)             # as chaves ganham nova chance com a estratégia nova
    store.set("norte_marco", None)
    from .norte import marco
    marco(store, agora)
    _avisar(store, f"Norte sem evolução no prazo: reescrevi a estratégia (nível {nivel}): cota de produto {novo['cota']:.0%}, "
                   f"{novo['vagas']} vagas de produto por passagem do Indagador, épicos girados. O prazo recomeçou.", agora)
    return novo


def licoes_esgotadas(store, agora: float) -> list[int]:
    from .licoes import CAMADAS, NOME_CAMADA, subir
    todas = store.get("licoes_esgotadas") or {}
    feitas = []
    for lid in list(todas):
        lic = store.one("SELECT id, camada, status, descricao FROM licoes WHERE id=?", (int(lid),))
        if not lic:
            todas.pop(lid)
            continue
        nova = subir(lic["camada"])
        if nova != lic["camada"] and nova in CAMADAS and lic["camada"] != CAMADAS[-1]:
            store.x("UPDATE licoes SET camada=?, updated_at=? WHERE id=?", (nova, agora, lic["id"]))
            _avisar(store, f"lição #{lid} esgotada subiu de camada para {NOME_CAMADA.get(nova, nova)}: o próximo item pede prevenção nessa camada.", agora)
        else:
            store.x("UPDATE licoes SET status='aceita', updated_at=? WHERE id=?", (agora, lic["id"]))
            _avisar(store, f"lição #{lid} esgotada no topo das camadas: aceita como está ({str(lic['descricao'])[:80]}). O loop não trava mais por ela.", agora)
        feitas.append(int(lid))
        todas.pop(lid)
    store.set("licoes_esgotadas", todas or None)
    return feitas


def medico_escalados(store, agora: float) -> list[str]:
    esc = dict(store.get("medico_escalados") or {})
    feitas = []
    for chave, e in list(esc.items()):
        if agora - float(e.get("em", agora)) < PRAZO_MEDICO:
            continue
        if not store.one("SELECT 1 FROM roadmap WHERE status='pendente' AND evidencia=?", (f"Médico (escalado): {chave}",)):
            ordem = (store.one("SELECT COALESCE(MIN(ordem),0) m FROM roadmap")["m"] or 0) - 1
            store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (f"Urgente: {str(e.get('titulo', chave))[:160]}", f"Diagnóstico do Médico escalado e assumido pelo loop (dono previsto: {e.get('dono')}).\n"
                     f"Evidência: {str(e.get('evidencia', ''))[:900]}\nCorrija a causa, não o sintoma.", "erro", "pendente",
                     f"Médico (escalado): {chave}", ordem, agora, agora))
        esc.pop(chave)
        feitas.append(chave)
        _avisar(store, f"diagnóstico do Médico «{str(e.get('titulo', chave))[:80]}» esperava você: virou item urgente na frente da fila.", agora)
    store.set("medico_escalados", esc)
    return feitas


def revisoes(store, agora: float) -> int:
    if not store.one("SELECT 1 FROM sqlite_master WHERE name='ledger'"):
        return 0
    n = store.run("UPDATE ledger SET status='confirmed' WHERE status='open' AND auto_accepted=0 AND created_at<?", (agora - PRAZO_REVISAO,))
    if n:
        _avisar(store, f"{n} lançamento(s) esperando revisão há mais de 24 h confirmado(s) como vieram do extrato.", agora)
    return n


def avisos(store, agora: float) -> int:
    from .aprovacoes import AVISOS
    return store.run(f"UPDATE alerts SET delivered=1 WHERE delivered=0 AND created_at<? AND kind IN ({','.join('?' * len(AVISOS))})",
                     (agora - PRAZO_AVISO, *AVISOS))


def rodar(store, agora: float | None = None) -> dict:
    agora = agora or time.time()
    rel = {"em": agora, "contestados": itens_contestados(store, agora), "dependentes": itens_dependentes(store, agora),
           "orcamento": orcamento(store, agora), "norte": reescrever_norte(store, agora), "licoes": licoes_esgotadas(store, agora),
           "medico": medico_escalados(store, agora), "revisoes": revisoes(store, agora), "avisos": avisos(store, agora)}
    ant = store.get(KV) or {}
    tot = dict(ant.get("total") or {})
    for k, v in rel.items():
        n = len(v) if isinstance(v, list) else int(bool(v)) if not isinstance(v, int) else v
        if k != "em" and n:
            tot[k] = tot.get(k, 0) + n
    store.set(KV, {"ultima": rel, "total": tot})
    return rel

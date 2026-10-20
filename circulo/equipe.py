"""A equipe: os agentes do loop vistos como um time de engenharia que entrega qualquer produto.

A tela "Equipe ao vivo" mostra cada agente como um integrante com cargo (PO, arquiteto, dev, revisor, QA/release,
DevOps, SRE…), a conversa entre eles em tempo real (pergunta, resposta, tarefa passada adiante, entrega, devolução,
alerta) e o quadro de entregas (de pergunta válida a produção). Nada aqui é inventado: cada mensagem nasce de um
registro que já existe (perguntas, roteiro, PRs, gate, revisões, vigia, lições, alertas) e cita o dado.

Dois pontos de entrada:
- `mensagens(store, cursor)`: as mensagens novas desde o cursor (o painel manda por SSE junto com os eventos do fluxo);
- `retrato(store)`: quem está fazendo o quê agora, a carga de cada um e o quadro de entregas (a tela consulta a cada
  poucos segundos e anima as diferenças).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from . import nomes
from .state import Store

# ------------------------------------------------------------------ o time
GRUPOS = {"direcao": "Direção", "produto": "Produto", "engenharia": "Engenharia", "qualidade": "Qualidade e operação", "externos": "Parceiros externos"}
EQUIPE: dict[str, dict[str, str]] = {
    "cassio": {"grupo": "produto", "faz": "Pede, aprova e recebe as entregas."},
    "orquestrador": {"grupo": "direcao", "faz": "Abre cada giro, confere orçamento e distribui o trabalho."},
    "jev": {"grupo": "direcao", "faz": "Responde sim/não, escolhe e dá nota antes de qualquer gasto; aprova ou barra."},
    "indagar": {"grupo": "produto", "faz": "Levanta as perguntas certas a partir do que foi medido; cada uma passa pelo Jev."},
    "planejar_roteiro": {"grupo": "produto", "faz": "Transforma a pergunta validada num item pequeno e medível do roteiro."},
    "estudar_pedido": {"grupo": "engenharia", "faz": "Pesquisa fontes confiáveis e decide adotar, adaptar ou contestar o item."},
    "corrigir_codigo": {"grupo": "engenharia", "faz": "Escreve o código e o teste num worktree, passa nos portões e abre o PR."},
    "revisor": {"grupo": "engenharia", "faz": "Confere cada PR contra a main de agora e os outros PRs abertos; devolve o que cruza."},
    "revisar_prs": {"grupo": "engenharia", "faz": "CI verde, teste novo, constituição intacta: mescla ou devolve com o motivo."},
    "atualizar_corpo": {"grupo": "engenharia", "faz": "Sobe o código novo em produção, prova em 5 giros e desfaz se piorar."},
    "vigia": {"grupo": "qualidade", "faz": "Mede as travas da autoevolução a cada minuto e abre item ou alerta."},
    "licoes": {"grupo": "qualidade", "faz": "Transforma cada erro em lição, portão e item de correção; fecha o que provou."},
    "saude": {"grupo": "qualidade", "faz": "Mede a saúde do loop a cada giro e pede rollback se piorar."},
    "jardinagem": {"grupo": "qualidade", "faz": "Mede padrões ruins crescendo no código e abre item para podar."},
    "meta_learner": {"grupo": "qualidade", "faz": "Aprende regras com as correções e testa a política candidata em shadow."},
    "evoluir_projeto": {"grupo": "produto", "faz": "Faz um ciclo nas missões suas: régua, versão nova, torneio e evidência."},
    "rotinas": {"grupo": "qualidade", "faz": "Regressão, padrões, resumo, prompts A/B e demais manutenções em rodízio."},
    "llm": {"grupo": "externos", "faz": "Gera texto e raciocina quando o Jev e a regra não bastam (custa tokens)."},
    "github": {"grupo": "externos", "faz": "Guarda o código, roda o CI e registra os PRs."},
}
for _k, _v in EQUIPE.items():                      # nome e cargo vêm da fonte única de nomes
    _v.update(nome=nomes.nome(_k), cargo=nomes.cargo(_k), antes=nomes.antes(_k))
# agentes que a tela do fluxo conhece e que aqui se agrupam num integrante só
ALIAS = {"shadow": "meta_learner", "pedido": "cassio", "decisao": "orquestrador", "descanso": "orquestrador", "pausado": "cassio",
         "analisar_padroes": "rotinas", "revisar_baixa_confianca": "rotinas", "rodar_regressao": "rotinas", "resumo": "rotinas",
         "propor_feature": "rotinas", "evoluir_harness": "rotinas", "conectar_missoes": "evoluir_projeto", "checar_licoes": "licoes",
         "indagador": "indagar", "developer": "corrigir_codigo", "gate": "revisar_prs", "planejador": "planejar_roteiro",
         "estudo": "estudar_pedido", "corpo": "atualizar_corpo"}
TONS = ("pergunta", "resposta", "tarefa", "entrega", "devolucao", "alerta", "status")


def membro(chave: str | None) -> str:
    """Normaliza qualquer chave de agente para um integrante da equipe (agente novo vira 'rotinas')."""
    if not chave:
        return "orquestrador"
    k = ALIAS.get(chave, chave)
    return k if k in EQUIPE else "rotinas"


def _msg(em: float, de: str, para: str, tom: str, texto: str, **extra) -> dict[str, Any]:
    m = {"tipo": "mensagem", "em": float(em), "de": membro(de), "para": membro(para), "tom": tom, "texto": texto[:240]}
    m.update({k: v for k, v in extra.items() if v is not None})
    return m


_PR = re.compile(r"PR #(\d+)")


def _pr_de(texto: str | None) -> int | None:
    m = _PR.search(texto or "")
    return int(m.group(1)) if m else None


# ------------------------------------------------------------------ cursor
def cursor_inicial(store: Store, voltar_s: float = 0) -> dict:
    """Começa no fim de cada tabela, ou `voltar_s` segundos atrás (a tela abre já com a conversa recente)."""
    agora = time.time()
    desde = agora - voltar_s if voltar_s else agora

    def m(sql, args=()):
        return store.one(sql, args)["m"] or 0
    if not voltar_s:
        return {"perg": m("SELECT MAX(id) m FROM perguntas"), "road": agora, "merges": m("SELECT MAX(id) m FROM merges"),
                "rev": m("SELECT MAX(id) m FROM revisoes"), "vig": m("SELECT MAX(id) m FROM vigia"), "vig_res": agora,
                "al": m("SELECT MAX(id) m FROM alerts"), "mem": agora}
    return {"perg": m("SELECT MAX(id) m FROM perguntas WHERE created_at < ?", (desde,)), "road": desde,
            "merges": m("SELECT MAX(id) m FROM merges WHERE created_at < ?", (desde,)), "rev": m("SELECT MAX(id) m FROM revisoes WHERE created_at < ?", (desde,)),
            "vig": m("SELECT MAX(id) m FROM vigia WHERE primeira_em < ?", (desde,)), "vig_res": desde,
            "al": m("SELECT MAX(id) m FROM alerts WHERE created_at < ?", (desde,)), "mem": desde}


# ------------------------------------------------------------------ mensagens
def _de_perguntas(store, c, out, limite):
    for p in store.q("SELECT id, persona, texto, status, eixo, pertinencia, item_id, cerebro, created_at FROM perguntas WHERE id > ? ORDER BY id LIMIT ?",
                     (c.get("perg", 0), limite)):
        c["perg"] = p["id"]
        if p["persona"] == "cassio":
            out.append(_msg(p["created_at"], "cassio", "planejar_roteiro", "tarefa", f"Pedido: {p['texto']}", item=p["item_id"], coluna="planejado" if p["item_id"] else None))
            continue
        if p["status"] in ("feita",) and p["eixo"] is None:
            continue                                       # pergunta do conselho antigo, sem passar pelo Indagador
        out.append(_msg(p["created_at"], "indagar", "jev", "pergunta", f"Essa pergunta vale para a evolução? «{p['texto']}»", pergunta=p["id"]))
        if p["status"] == "inconclusa":
            resp = "Fiquei em dúvida; a regra decidiu. Volta depois com mais dados."
        elif p["status"] == "descartada":
            resp = f"Não vale agora (pertinência {int(float(p['pertinencia'] or 0) * 100)}%)."
        else:
            resp = f"Vale: pertinência {int(float(p['pertinencia'] or 0) * 100)}%, eixo {p['eixo']}. Pode virar item."
        out.append(_msg(float(p["created_at"]) + 0.5, "jev", "indagar", "resposta", resp, pergunta=p["id"]))


def _de_roadmap(store, c, out, limite):
    rows = store.q("SELECT id, titulo, origem, status, evidencia, estudo, pai, updated_at, created_at FROM roadmap WHERE updated_at > ? "
                   "ORDER BY updated_at LIMIT ?", (float(c.get("road", 0)), limite))
    for r in rows:
        c["road"] = float(r["updated_at"])
        ev, st, t, i = (r["evidencia"] or ""), r["status"], (r["titulo"] or "")[:90], r["id"]
        novo = abs(float(r["updated_at"]) - float(r["created_at"])) < 1.0
        pr = _pr_de(ev)
        if novo and r["origem"] == "erro":
            out.append(_msg(r["updated_at"], "licoes", "corrigir_codigo", "tarefa", f"Erro virou lição: corrigir «{t}» (item #{i}).", item=i, coluna="pronto"))
        elif novo and t.startswith("Vigia:"):
            out.append(_msg(r["updated_at"], "vigia", "planejar_roteiro", "alerta", f"Trava detectada: {t[7:]} (item #{i}).", item=i, coluna="planejado"))
        elif novo and r["origem"] == "loop":
            out.append(_msg(r["updated_at"], "planejar_roteiro", "estudar_pedido", "tarefa", f"Planejei o item #{i}: {t}. Pode estudar.", item=i, coluna="planejado"))
        elif novo and r["origem"] == "pedido_cassio":
            out.append(_msg(r["updated_at"], "cassio", "estudar_pedido", "tarefa", f"Pedido novo no roteiro: {t} (item #{i}).", item=i, coluna="planejado"))
        elif st == "pendente" and ev.startswith("estudado"):
            out.append(_msg(r["updated_at"], "estudar_pedido", "corrigir_codigo", "tarefa", f"Item #{i} estudado ({ev[10:60]}): pronto para desenvolver.", item=i, coluna="pronto"))
        elif st == "em_andamento" and ev.startswith("branch"):
            out.append(_msg(r["updated_at"], "corrigir_codigo", "corrigir_codigo", "status", f"Comecei o item #{i}: {t}.", item=i, coluna="dev"))
        elif st == "em_andamento" and pr and "conserto" not in ev:
            out.append(_msg(r["updated_at"], "corrigir_codigo", "revisar_prs", "entrega", f"Abri o PR #{pr} para o item #{i}: {t}.", item=i, pr=pr, coluna="revisao"))
        elif st == "pendente" and ev.startswith("aguarda PR"):
            out.append(_msg(r["updated_at"], "revisor", "planejar_roteiro", "devolucao", f"Devolvi o item #{i}: {ev}.", item=i, pr=_pr_de(ev), coluna="devolvidos"))
        elif st == "pendente" and ev.startswith("revisor:"):
            out.append(_msg(r["updated_at"], "revisor", "corrigir_codigo", "devolucao", f"Rejeitei o item #{i} antes do PR: {ev[9:]}.", item=i, coluna="devolvidos"))
        elif st == "pendente" and ev.startswith("barrado"):
            out.append(_msg(r["updated_at"], "corrigir_codigo", "corrigir_codigo", "devolucao", f"Item #{i} barrado nos portões antes do PR; nada enviado.", item=i, coluna="pronto"))
        elif st == "pendente" and pr and "fechado" in ev:
            out.append(_msg(r["updated_at"], "revisar_prs", "planejar_roteiro", "devolucao", f"PR #{pr} fechado; o item #{i} volta para a fila: {ev[:120]}.", item=i, pr=pr, coluna="devolvidos"))
        elif st == "pendente" and "depende de você" in ev:
            out.append(_msg(r["updated_at"], "corrigir_codigo", "cassio", "alerta", f"O item #{i} depende de você: {ev[:120]}.", item=i, coluna="devolvidos"))
        elif st == "pendente" and ev.startswith("aguardando o limite"):
            out.append(_msg(r["updated_at"], "corrigir_codigo", "orquestrador", "status", f"Claude Code no limite; o item #{i} espera ({ev[:80]}).", item=i, coluna="devolvidos"))
        elif st == "feito" and pr:
            out.append(_msg(r["updated_at"], "revisar_prs", "atualizar_corpo", "entrega", f"PR #{pr} entrou na main: item #{i} concluído. Pode subir.", item=i, pr=pr, coluna="producao"))
        elif st == "feito":
            out.append(_msg(r["updated_at"], "orquestrador", "cassio", "entrega", f"Item #{i} concluído: {t}.", item=i, coluna="producao"))
        elif st in ("descartado", "contestado"):
            quem = "estudar_pedido" if st == "contestado" else "planejar_roteiro"
            out.append(_msg(r["updated_at"], quem, "cassio", "devolucao", f"Item #{i} {st}: {ev[:120] or t}.", item=i, coluna="fora"))
        elif st == "observacao":
            out.append(_msg(r["updated_at"], "corrigir_codigo", "licoes", "status", f"Item #{i} em observação: o erro precisa parar de acontecer.", item=i, coluna="producao"))


def _de_merges(store, c, out, limite):
    for m in store.q("SELECT id, pr, merged, reason, created_at FROM merges WHERE id > ? ORDER BY id LIMIT ?", (c.get("merges", 0), limite)):
        c["merges"] = m["id"]
        r = m["reason"] or ""
        if m["merged"]:
            continue                                       # a entrega já aparece pelo roteiro (feito)
        if r.startswith("checks em andamento") or r.startswith("checks ausentes"):
            out.append(_msg(m["created_at"], "revisar_prs", "github", "status", f"PR #{m['pr']}: esperando o CI ({r[:80]}).", pr=m["pr"]))
        elif r.startswith("Revisor:"):
            out.append(_msg(m["created_at"], "revisor", "corrigir_codigo", "devolucao", f"PR #{m['pr']} rejeitado: {r[9:]}.", pr=m["pr"]))
        elif "atrás da main" in r:
            out.append(_msg(m["created_at"], "revisar_prs", "github", "status", f"PR #{m['pr']}: trouxe a main para a branch; o CI roda de novo.", pr=m["pr"]))
        elif r.startswith(("checks falhando", "check obrigatório", "PR do Developer sem teste", "conflito")):
            out.append(_msg(m["created_at"], "revisar_prs", "corrigir_codigo", "devolucao", f"PR #{m['pr']} devolvido: {r}. Conserta na mesma branch?", pr=m["pr"]))
        elif r.startswith(("fora do alcance", "PR grande")):
            out.append(_msg(m["created_at"], "revisar_prs", "planejar_roteiro", "devolucao", f"PR #{m['pr']} recusado: {r}.", pr=m["pr"]))
        elif r.startswith("Reviewer Code"):
            out.append(_msg(m["created_at"], "jev", "revisar_prs", "resposta", f"PR #{m['pr']}: {r}.", pr=m["pr"]))


def _de_revisoes(store, c, out, limite):
    for r in store.q("SELECT id, pr, item_id, momento, veredito, motivo, conf, fonte, created_at FROM revisoes WHERE id > ? ORDER BY id LIMIT ?",
                     (c.get("rev", 0), limite)):
        c["rev"] = r["id"]
        alvo = f"PR #{r['pr']}" if r["pr"] else f"item #{r['item_id']}"
        conf = f" (Jev {int(float(r['conf'] or 0) * 100)}%)" if r["conf"] is not None else ""
        out.append(_msg(r["created_at"], "revisor", "jev", "pergunta", f"O {alvo} é seguro junto com os PRs abertos?", pr=r["pr"], item=r["item_id"]))
        if r["veredito"] == "aprovado":
            out.append(_msg(float(r["created_at"]) + 0.3, "revisor", "corrigir_codigo", "resposta", f"Revisão do {alvo}: seguro{conf}. Pode seguir.", pr=r["pr"], item=r["item_id"], coluna="revisao"))
        else:
            out.append(_msg(float(r["created_at"]) + 0.3, "revisor", "corrigir_codigo", "devolucao", f"Revisão do {alvo}: {r['motivo']}{conf}.", pr=r["pr"], item=r["item_id"], coluna="devolvidos"))


def _de_vigia(store, c, out, limite):
    for v in store.q("SELECT id, chave, titulo, veredito, acao, conf, primeira_em FROM vigia WHERE id > ? ORDER BY id LIMIT ?", (c.get("vig", 0), limite)):
        c["vig"] = v["id"]
        out.append(_msg(v["primeira_em"], "vigia", "jev", "pergunta", f"Isto é uma trava? «{v['titulo']}»"))
        if v["veredito"] == "trava":
            out.append(_msg(float(v["primeira_em"]) + 0.3, "jev", "vigia", "resposta", f"É trava ({int(float(v['conf'] or 0) * 100)}%): {v['acao'].replace('_', ' ')}."))
            out.append(_msg(float(v["primeira_em"]) + 0.6, "vigia", "orquestrador", "alerta", f"Trava: {v['titulo']}"))
        else:
            out.append(_msg(float(v["primeira_em"]) + 0.3, "jev", "vigia", "resposta", "Em dúvida: observa e mede de novo."))
    for v in store.q("SELECT id, titulo, resolvida_em FROM vigia WHERE status='resolvida' AND resolvida_em > ? ORDER BY resolvida_em LIMIT ?",
                     (float(c.get("vig_res", 0)), limite)):
        c["vig_res"] = float(v["resolvida_em"])
        out.append(_msg(v["resolvida_em"], "vigia", "orquestrador", "status", f"Trava resolvida: {v['titulo']}"))


def _de_alertas(store, c, out, limite):
    for a in store.q("SELECT id, kind, message, created_at FROM alerts WHERE id > ? ORDER BY id LIMIT ?", (c.get("al", 0), limite)):
        c["al"] = a["id"]
        k, msg = a["kind"], a["message"] or ""
        if k == "licao":
            para = "corrigir_codigo" if "registrada" in msg else "orquestrador"
            out.append(_msg(a["created_at"], "licoes", para, "alerta" if "REINCID" in msg else "status", msg))
        elif k == "fora_alcance":
            out.append(_msg(a["created_at"], "corrigir_codigo", "cassio", "alerta", msg))
        elif k == "merge" and msg.startswith("Corpo"):
            out.append(_msg(a["created_at"], "atualizar_corpo", "orquestrador", "entrega" if "evidenciado" in msg else "status", msg))
        elif k == "saude" and msg.startswith("Estagna"):
            out.append(_msg(a["created_at"], "saude", "orquestrador", "alerta", msg))
        elif k == "duvida":
            out.append(_msg(a["created_at"], "estudar_pedido", "indagar", "entrega" if "agora valida" in msg else "status", msg))
        elif k == "roteiro" and msg.startswith("Estudei"):
            out.append(_msg(a["created_at"], "estudar_pedido", "corrigir_codigo", "status", msg))
        elif k == "roteiro" and "sem item novo" in msg:
            out.append(_msg(a["created_at"], "planejar_roteiro", "indagar", "devolucao", msg))


def _de_memoria(store, c, out, limite):
    """Cada consulta à memória do time vira uma fala: o agente diz o que lembrou antes de começar."""
    if not store.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memoria_uso'"):
        return
    for u in store.q("SELECT agente, assunto, hits, poupou_tokens, created_at FROM memoria_uso WHERE created_at > ? ORDER BY created_at LIMIT ?",
                     (float(c.get("mem", 0)), limite)):
        c["mem"] = float(u["created_at"])
        hits = json.loads(u["hits"] or "[]")
        if u["poupou_tokens"]:
            h = hits[0] if hits else {}
            out.append(_msg(u["created_at"], u["agente"], "orquestrador", "entrega",
                            f"Assunto parecido com o item #{h.get('ref', '?')} já estudado: reaproveitei o estudo e poupei ~{int(u['poupou_tokens']):,} tokens.".replace(",", ".")))
        elif hits:
            resumo = ", ".join(f"{h['tipo']} #{str(h['ref']).split(':')[0]}" for h in hits[:4])
            out.append(_msg(u["created_at"], u["agente"], "licoes", "status", f"Antes de começar “{u['assunto'][:70]}”, lembrei de {len(hits)} coisa(s) parecida(s): {resumo}."))


FONTES = (_de_perguntas, _de_roadmap, _de_merges, _de_revisoes, _de_vigia, _de_alertas, _de_memoria)


def mensagens(store: Store, cursor: dict, limite: int = 200) -> tuple[list[dict], dict]:
    """Mensagens novas desde o cursor, na ordem em que aconteceram, e o cursor seguinte."""
    c = dict(cursor)
    out: list[dict] = []
    for f in FONTES:
        f(store, c, out, limite)
    out.sort(key=lambda m: (m["em"], TONS.index(m["tom"]) if m["tom"] in TONS else 9))
    return out, c


# ------------------------------------------------------------------ retrato: quem faz o quê agora, e o quadro
def _agora(store: Store) -> tuple[str, str, float]:
    et = store.get("etapa") or {}
    nome, tarefa = str(et.get("nome") or ""), None
    r = store.one("SELECT etapa, tarefa, detalhe, em FROM trail ORDER BY seq DESC LIMIT 1")
    if r:
        nome, tarefa = r["etapa"], r["tarefa"]
        if nome == "idle" and tarefa:
            return membro(tarefa), (r["detalhe"] or ""), float(r["em"])
        return membro(nome), (r["detalhe"] or ""), float(r["em"])
    return "orquestrador", "", float(et.get("em") or time.time())


def _carga(store: Store) -> dict[str, dict]:
    def n(sql, args=()):
        return int((store.one(sql, args) or {"n": 0})["n"] or 0)
    abertos = n("SELECT COUNT(*) n FROM prs WHERE status='aberto' AND item_id IS NOT NULL")
    dev = store.get("self_dev_aberto") or {}
    return {
        "indagar": {"n": n("SELECT COUNT(*) n FROM perguntas WHERE status='valida'"), "rotulo": "pergunta(s) válida(s) esperando"},
        "planejar_roteiro": {"n": n("SELECT COUNT(*) n FROM roadmap WHERE status='pendente' AND estudo IS NULL AND COALESCE(desativado,0)=0 AND origem IN ('loop','pedido_cassio')"),
                             "rotulo": "item(ns) esperando estudo"},
        "estudar_pedido": {"n": n("SELECT COUNT(*) n FROM roadmap WHERE status='pendente' AND estudo IS NOT NULL AND COALESCE(desativado,0)=0"), "rotulo": "item(ns) prontos para o Developer"},
        "corrigir_codigo": {"n": n("SELECT COUNT(*) n FROM roadmap WHERE status='em_andamento'"), "rotulo": "item(ns) em andamento",
                            "vagas": f"{abertos}/{int(dev.get('max') or 1)} PRs"},
        "revisar_prs": {"n": n("SELECT COUNT(*) n FROM prs WHERE status='aberto'"), "rotulo": "PR(s) no CI/gate"},
        "revisor": {"n": n("SELECT COUNT(*) n FROM revisoes WHERE created_at>=?", (time.time() - 86400,)), "rotulo": "revisão(ões) em 24 h"},
        "vigia": {"n": n("SELECT COUNT(*) n FROM vigia WHERE status='aberta'"), "rotulo": "trava(s) aberta(s)"},
        "licoes": {"n": n("SELECT COUNT(*) n FROM licoes WHERE status IN ('aberta','reincidente','em_correcao')"), "rotulo": "lição(ões) abertas"},
        "atualizar_corpo": {"n": 1 if (store.get("corpo") or {}).get("estado") == "validando" else 0, "rotulo": "versão em prova"},
        "jev": {"n": n("SELECT COUNT(*) n FROM decisions WHERE created_at>=?", (time.time() - 3600,)), "rotulo": "decisões na última hora"},
        "llm": {"n": n("SELECT COUNT(*) n FROM llm_calls WHERE created_at>=?", (time.time() - 3600,)), "rotulo": "chamadas na última hora"},
        "cassio": {"n": n("SELECT COUNT(*) n FROM roadmap WHERE status='pendente' AND evidencia LIKE '%depende de você%'"), "rotulo": "item(ns) esperando você"},
    }


def quadro(store: Store) -> list[dict]:
    """Colunas do quadro de entregas, da ideia à produção, com o dono de cada cartão."""
    dia = time.time() - 86400

    def cards(sql, args, dono, status_card):
        return [{"id": r["id"], "titulo": (r["titulo"] or "")[:110], "dono": dono, "desde": float(r["updated_at"] or 0), "origem": r["origem"],
                 "pr": _pr_de(r["evidencia"]), "estado": status_card, "evidencia": (r["evidencia"] or "")[:140]}
                for r in store.q(sql, args)]
    perguntas = [{"id": f"p{p['id']}", "titulo": p["texto"][:110], "dono": "indagar", "desde": float(p["created_at"]), "origem": "pergunta",
                  "pr": None, "estado": "valida", "evidencia": f"eixo {p['eixo']} · pertinência {int(float(p['pertinencia'] or 0) * 100)}%"}
                 for p in store.q("SELECT id, texto, eixo, pertinencia, created_at FROM perguntas WHERE status='valida' ORDER BY score DESC LIMIT 8")]
    base = "SELECT id, titulo, origem, status, evidencia, updated_at FROM roadmap WHERE COALESCE(desativado,0)=0 AND "
    return [
        {"chave": "ideias", "nome": "Perguntas válidas", "quem": "indagar", "cards": perguntas},
        {"chave": "planejado", "nome": "Planejado", "quem": "planejar_roteiro",
         "cards": cards(base + "status='pendente' AND estudo IS NULL AND origem IN ('loop','pedido_cassio','erro') AND evidencia NOT LIKE 'aguarda PR%' "
                        "AND evidencia NOT LIKE 'revisor:%' AND evidencia NOT LIKE '%depende de você%' AND evidencia NOT LIKE 'PR #% fechado%' ORDER BY ordem LIMIT 8",
                        (), "estudar_pedido", "pendente")},
        {"chave": "pronto", "nome": "Estudado, pronto", "quem": "estudar_pedido",
         "cards": cards(base + "status='pendente' AND estudo IS NOT NULL AND evidencia NOT LIKE 'aguarda PR%' AND evidencia NOT LIKE 'revisor:%' "
                        "AND evidencia NOT LIKE '%depende de você%' ORDER BY ordem LIMIT 8", (), "corrigir_codigo", "pronto")},
        {"chave": "dev", "nome": "Em desenvolvimento", "quem": "corrigir_codigo",
         "cards": cards(base + "status='em_andamento' AND evidencia NOT LIKE 'PR #%' ORDER BY updated_at DESC LIMIT 8", (), "corrigir_codigo", "dev")},
        {"chave": "revisao", "nome": "Em revisão / CI", "quem": "revisar_prs",
         "cards": cards(base + "status='em_andamento' AND evidencia LIKE 'PR #%' ORDER BY updated_at DESC LIMIT 8", (), "revisar_prs", "ci")},
        {"chave": "producao", "nome": "Em produção (24 h)", "quem": "atualizar_corpo",
         "cards": cards(base + "status='feito' AND updated_at>=? ORDER BY updated_at DESC LIMIT 10", (dia,), "atualizar_corpo", "feito")},
        {"chave": "devolvidos", "nome": "Devolvidos / esperando", "quem": "planejar_roteiro",
         "cards": cards(base + "status='pendente' AND (evidencia LIKE 'aguarda PR%' OR evidencia LIKE 'revisor:%' OR evidencia LIKE '%depende de você%' "
                        "OR evidencia LIKE 'PR #% fechado%' OR evidencia LIKE 'aguardando o limite%') ORDER BY updated_at DESC LIMIT 8", (), "planejar_roteiro", "devolvido")},
    ]


def retrato(store: Store) -> dict[str, Any]:
    ativo, detalhe, desde = _agora(store)
    carga = _carga(store)
    ritmo = store.get("ritmo") or {}
    bat = store.get("batimento") or {}
    rodando = (bool(bat.get("em")) and time.time() - float(bat.get("em") or 0) < 900) or time.time() - desde < 900
    membros = []
    for k, d in EQUIPE.items():
        estado = "trabalhando" if k == ativo and rodando else "parado" if not rodando and k not in ("cassio", "llm", "github") else "disponivel"
        if k in ("jev", "llm", "github") and k != ativo:
            estado = "disponivel"
        c = carga.get(k) or {}
        membros.append({"id": k, **d, "estado": estado, "agora": detalhe if k == ativo else "", "desde": desde if k == ativo else None,
                        "carga": c.get("n", 0), "carga_rotulo": c.get("rotulo", ""), "vagas": c.get("vagas")})
    return {"em": time.time(), "rodando": rodando, "ritmo": ritmo.get("modo"), "ativo": ativo, "grupos": GRUPOS, "membros": membros,
            "quadro": quadro(store), "tick": store.tick}


def resumo_json(store: Store) -> str:
    return json.dumps(retrato(store), ensure_ascii=False, default=str)

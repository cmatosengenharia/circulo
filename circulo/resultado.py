"""Resultado do lado do cliente (1.76): o loop vende RESULTADO, não ferramenta (ADR 0015).

Cássio (1/11, "Vender resultado, não ferramenta"): por fora uma agência que entrega o trabalho pronto, por dentro
software autônomo. O Norte media só o lado do loop (PRs, lead time); PR mergeado não conta como produto se nenhum
resultado de cliente mudou. Aqui ficam:

- os três resultados do lado do cliente que entram no Norte (`medir`): taxa de promessa cumprida (pedidos de
  cliente entregues no prazo e sem intervenção ÷ pedidos abertos, meta 90 %), pedidos de cliente entregues por semana,
  e publicações por semana nos canais-piloto (reportadas pela esteira/dogfooding por arquivo na caixa, `tipo: resultado`);
- a classificação Jev de cada item (`classificar`): entrega de resultado / confiabilidade da entrega / ferramenta
  (meta-trabalho). Ferramenta só entra se um dos dois primeiros depender dela: `item_de_produto` ordena por isso;
- a PROMESSA.md de cada produto (`promessa`): trabalho que substitui, resultado em uma frase, cadência, preço
  ancorado no profissional substituído, o que o cliente nunca faz. Sem promessa válida o Fabricante registra
  `fabrica:promessa_md` em falha (evidência, não bloqueio: a esteira ainda nasce);
- a checagem de discurso de plataforma (`discurso_de_plataforma`): landing/demo que fala "IA", "plataforma" ou
  "ferramenta" num título antes do resultado é reprovada pelo Validador.
Falha de entrega para cliente (pedido que esgotou as tentativas) é lição estrutural com item de prevenção, acima de
qualquer lição interna (`fabricante._vermelho`).
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .decision import Decision, Question

SEMANA = 7 * 86400.0
PRAZO_PROMESSA_H = 48.0                 # prazo prometido por pedido (kv `promessa_prazo_h` sobrescreve)
META_PROMESSA = 0.9
KV_RESULTADOS = "resultados_cliente"    # [{"projeto", "metrica", "valor", "em"}] reportados de fora (caixa `tipo: resultado`)
KV_CLASSES = "classificacao_itens"      # {item_id: {"classe", "por", "em"}}
CLASSES = ("resultado", "confiabilidade", "ferramenta")
ORDEM = {"resultado": 0, "confiabilidade": 1, "ferramenta": 2}
PERGUNTA = "classe_do_item"
CAMPOS_PROMESSA = ("trabalho que substitui", "resultado prometido", "cadência", "preço", "o cliente nunca precisa")
_RESULTADO = re.compile(r"(?i)cliente|public|entreg|pedido|cortes?|v[ií]deo|relat[oó]rio|agenda|lead|canal|instagram|youtube|tiktok|facebook|promessa|prazo")
_CONFIAB = re.compile(r"(?i)teste|valida|\bci\b|incidente|falha|retry|idempot|rollback|regress|portão|portao|gate|revis")
_PLATAFORMA = re.compile(r"(?i)\b(IA|AI|intelig[êe]ncia artificial|plataforma|ferramenta|pipeline|software)\b")
_TITULO = re.compile(r"(?im)^\s*(?:#{1,2}\s+(.+)|<h[12][^>]*>(.*?)</h[12]>|<title>(.*?)</title>)")

RESULTADOS = (
    ("promessa_cumprida", "Taxa de promessa cumprida: pedidos de cliente entregues no prazo e sem intervenção ÷ abertos (7 dias)", META_PROMESSA, "maior"),
    ("pedidos_cliente_semana", "Pedidos de repositório cliente entregues por semana", 3.0, "maior"),
    ("publicacoes_semana", "Publicações por semana nos canais-piloto com conteúdo da esteira (reportadas pela esteira)", 3.0, "maior"),
)


# ------------------------------------------------------------------ medição

def prazo_h(store) -> float:
    return float(store.get("promessa_prazo_h") or PRAZO_PROMESSA_H)


def _pedidos(store, desde: float) -> list[dict]:
    if not store.one("SELECT 1 FROM sqlite_master WHERE name='pedidos_repo'"):
        return []
    return [dict(r) for r in store.q("SELECT id, status, created_at, updated_at FROM pedidos_repo WHERE created_at>=?", (desde,))]


def promessa_cumprida(store, agora: float | None = None) -> dict:
    """{taxa, abertos, cumpridos, atrasados}: cumprido = entregue até `prazo_h` horas depois de aberto. Sem pedido: taxa None."""
    agora = agora or time.time()
    ps, prazo = _pedidos(store, agora - SEMANA), prazo_h(store) * 3600
    cumpridos = [p for p in ps if p["status"] == "entregue" and float(p["updated_at"]) - float(p["created_at"]) <= prazo]
    atrasados = [p for p in ps if p not in cumpridos and (p["status"] != "aberto" or agora - float(p["created_at"]) > prazo)]
    return {"taxa": round(len(cumpridos) / len(ps), 2) if ps else None, "abertos": len(ps), "cumpridos": len(cumpridos), "atrasados": len(atrasados)}


def registrar_resultado(store, projeto: str, metrica: str, valor: float, agora: float | None = None) -> None:
    """Resultado reportado de fora (a esteira, o dogfooding): fica no kv, janela de 90 dias."""
    agora = agora or time.time()
    lista = [r for r in (store.get(KV_RESULTADOS) or []) if agora - float(r.get("em", 0)) < 90 * 86400]
    lista.append({"projeto": str(projeto)[:60], "metrica": str(metrica)[:40], "valor": float(valor), "em": agora})
    store.set(KV_RESULTADOS, lista[-2000:])


def ler_resultados_da_caixa(store, texto: str, agora: float | None = None) -> int:
    """Arquivo `tipo: resultado` na caixa: uma linha por medição, `projeto; metrica; valor`. Devolve quantas entraram."""
    n = 0
    for linha in (texto or "").splitlines():
        partes = [x.strip() for x in re.split(r"[;,|\t]", linha) if x.strip()]
        if len(partes) < 3:
            continue
        try:
            registrar_resultado(store, partes[0], partes[1], float(partes[2].replace(",", ".")), agora)
            n += 1
        except ValueError:
            continue
    return n


def publicacoes_semana(store, agora: float | None = None) -> float | None:
    agora = agora or time.time()
    rs = [r for r in (store.get(KV_RESULTADOS) or []) if r.get("metrica") in ("publicacoes", "publicações", "videos_publicados") and agora - float(r["em"]) < SEMANA]
    return float(sum(float(r["valor"]) for r in rs)) if rs else None


def medir(store, agora: float | None = None) -> dict:
    """Os resultados do lado do cliente no formato do Norte ({valor, meta, sentido, distancia, descricao})."""
    agora = agora or time.time()
    pc = promessa_cumprida(store, agora)
    entregues = sum(1 for p in _pedidos(store, agora - SEMANA) if p["status"] == "entregue")
    valores = {"promessa_cumprida": pc["taxa"], "pedidos_cliente_semana": entregues, "publicacoes_semana": publicacoes_semana(store, agora)}
    out = {}
    for chave, descricao, meta, sentido in RESULTADOS:
        v = valores[chave]
        dist = 1.0 if v is None else (0.0 if v >= meta else min(1.0, (meta - v) / max(meta, 1e-9)))
        out[chave] = {"descricao": descricao, "valor": v, "meta": meta, "sentido": sentido, "distancia": round(dist, 2), "lado": "cliente"}
    out["promessa_cumprida"].update({k: pc[k] for k in ("abertos", "cumpridos", "atrasados")})
    return out


# ------------------------------------------------------------------ classificação Jev: resultado / confiabilidade / ferramenta

def regra(jev, qid: str, q: Question, state) -> Decision:
    """Regra local: palavras do item. Marca forte de confiabilidade (teste, retry, incidente…) decide; senão palavra de
    resultado (cliente, publicar, entrega…); senão ferramenta."""
    texto = str(state.get("item", ""))
    if _CONFIAB.search(texto):
        return Decision(qid, "choice", "confiabilidade", 0.6, jev.source)
    if _RESULTADO.search(texto):
        return Decision(qid, "choice", "resultado", 0.6, jev.source)
    return Decision(qid, "choice", "ferramenta", 0.6, jev.source)


def classificar(dl, store, item: dict) -> str:
    """A classe do item (cacheada em kv): o Jev escolhe; sem Jev, a regra local."""
    classes = store.get(KV_CLASSES) or {}
    if str(item.get("id")) in classes:
        return classes[str(item["id"])]["classe"]
    texto = f"{item.get('titulo', '')}\n{str(item.get('detalhe', ''))[:500]}"
    if dl is None:
        d = regra(type("J", (), {"source": "local"})(), PERGUNTA, None, {"item": texto})
    else:
        d = dl.ask(PERGUNTA, Question("choice", "What does this backlog `item` deliver? `resultado`: moves a result the paying client sees "
                                                "(published video, delivered request, report, answered lead). `confiabilidade`: makes that "
                                                "delivery arrive on time and without a human (tests, gates, retries, incidents). `ferramenta`: "
                                                "internal tooling or meta-work neither of the two depends on.",
                                      {"resultado": "entrega de resultado para o cliente", "confiabilidade": "confiabilidade da entrega",
                                       "ferramenta": "ferramenta ou meta-trabalho"}), {"item": texto})
    classe = str(d.value) if str(d.value) in CLASSES else "ferramenta"
    if item.get("id") is not None:
        classes[str(item["id"])] = {"classe": classe, "por": getattr(d, "source", "local"), "em": time.time()}
        store.set(KV_CLASSES, classes)
    return classe


def classificar_pendentes(dl, store, limite: int = 20) -> int:
    """Classifica os itens pendentes ainda sem classe (1×/dia pelo Vigia); devolve quantos classificou."""
    classes = store.get(KV_CLASSES) or {}
    n = 0
    for r in store.q("SELECT id, titulo, detalhe FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0 ORDER BY ordem LIMIT ?", (limite,)):
        if str(r["id"]) not in classes:
            try:
                classificar(dl, store, dict(r))
            except (OSError, ValueError, TypeError, KeyError):      # o Jev fora do ar não para o Vigia; o item fica para amanhã
                continue
            n += 1
    return n


def classe_de(store, item_id: int | None) -> str | None:
    return ((store.get(KV_CLASSES) or {}).get(str(item_id)) or {}).get("classe") if item_id is not None else None


def ordenar_por_classe(store, itens: list[dict]) -> list[dict]:
    """Resultado antes de confiabilidade antes de ferramenta; sem classe conta como confiabilidade (não penaliza o novo)."""
    return sorted(itens, key=lambda i: ORDEM.get(classe_de(store, i.get("id")) or "confiabilidade", 1))


def evidencia_meta_trabalho_perdeu_prioridade(store) -> dict:
    """Para a régua: quantos itens de cada classe estão pendentes e qual classe o próximo pick teria."""
    classes = store.get(KV_CLASSES) or {}
    pend = {str(r["id"]) for r in store.q("SELECT id FROM roadmap WHERE status='pendente' AND COALESCE(desativado,0)=0")}
    cont = {c: sum(1 for i, v in classes.items() if i in pend and v["classe"] == c) for c in CLASSES}
    return {"pendentes_por_classe": cont, "classificados": sum(cont.values()), "pendentes": len(pend)}


# ------------------------------------------------------------------ promessa e discurso

def promessa(repo_dir: Path | str) -> dict:
    """PROMESSA.md do produto: {existe, campos_faltando, texto}. Válida quando os 5 campos aparecem (cabeçalho ou negrito)."""
    arq = Path(repo_dir) / "PROMESSA.md"
    if not arq.exists():
        return {"existe": False, "campos_faltando": list(CAMPOS_PROMESSA), "valida": False}
    texto = arq.read_text(encoding="utf-8", errors="replace")
    baixo = texto.lower()
    faltam = [c for c in CAMPOS_PROMESSA if c not in baixo]
    return {"existe": True, "campos_faltando": faltam, "valida": not faltam, "texto": texto[:4000]}


def discurso_de_plataforma(texto: str) -> list[str]:
    """Títulos (h1/h2/#/##/<title>) que falam de IA/plataforma/ferramenta antes de qualquer título com resultado."""
    problemas, viu_resultado = [], False
    for m in _TITULO.finditer(texto or ""):
        t = next((g for g in m.groups() if g), "").strip()
        if _RESULTADO.search(t) and not _PLATAFORMA.search(t):
            viu_resultado = True
        elif _PLATAFORMA.search(t) and not viu_resultado:
            problemas.append(f"discurso de plataforma antes do resultado: {t[:80]!r} — venda o resultado (\"seus vídeos publicados toda semana\"), não a tecnologia")
    return problemas


def arquivos_de_oferta(adicionadas: dict[str, list[str]]) -> list[str]:
    """Os arquivos de landing/demo/README de oferta cujas linhas novas o Validador confere."""
    return [a for a in (adicionadas or {}) if re.search(r"(?i)landing|oferta|promessa|index\.html$|^README\.md$|demo", a)]


__all__ = ["RESULTADOS", "CLASSES", "medir", "promessa_cumprida", "registrar_resultado", "ler_resultados_da_caixa", "classificar",
           "classificar_pendentes", "classe_de", "ordenar_por_classe", "promessa", "discurso_de_plataforma", "arquivos_de_oferta", "regra"]

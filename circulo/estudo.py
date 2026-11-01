"""Neurônio de estudo: o pedido é uma hipótese, não uma ordem gravada em pedra.

Antes de o Developer pegar um item do roteiro (seu pedido ou um item planejado pelo loop), o loop estuda:
  Jev decide se vale o gasto → pesquisa em fontes confiáveis (busca na web, com citações) → veredito:
  - adotar: a evidência sustenta o pedido como está;
  - adaptar: a evidência mostra um jeito melhor. O item é reescrito e o loop explica a mudança;
  - contestar: a evidência contradiz o pedido. O item não é executado, e o loop explica com as fontes.
    Se você reativar o item no roteiro, ele segue mesmo assim (sua decisão fica registrada).
→ portão mecânico: adaptar ou contestar exige pelo menos MIN_FONTES fontes distintas (sem evidência, o loop não
  desobedece) → Jev confere se a evidência sustenta o veredito → sinapse `estudo:pedido` → o estudo fica no item e
  entra na tarefa do Developer.

Erros do próprio loop (origem "erro") não passam por aqui: a evidência deles é o próprio erro.

Custo proporcional à evidência (1.32.1): medido no Mac, cada estudo com 4 buscas custava 28–40 mil tokens e 11 estudos
comeram 392 mil dos 400 mil do dia, parando a evolução às 22 h. Item do loop nascido de medida interna (Vigia,
jardineiro, lição) é DISPENSADO (0 tokens: a evidência já é medida); item do loop nascido de pergunta do conselho tem
estudo LEVE (1 busca); pedido seu tem estudo COMPLETO (4 buscas). O custo que o porteiro vê é a mediana medida dos
últimos estudos daquele modo, não uma constante.
"""
from __future__ import annotations

import json
import time

from . import alavancas
from .agents import Ctx
from .decision import Question, SN
from .saida_json import Saida, ler

MIN_FONTES = 2
EST_TOKENS = 9000
MAX_TOKENS = 8000           # 2500 era engolido pelas buscas (14 de 40 estudos de 20/10 voltaram sem texto)
MODOS = {"completo": {"buscas": 4, "max_tokens": MAX_TOKENS, "est": 30_000}, "leve": {"buscas": 1, "max_tokens": 4000, "est": 9_000},
         "dispensado": {"buscas": 0, "max_tokens": 0, "est": 0}}
DISPENSA = ("Vigia (medido)", "Médico (medido)", "medido pelo jardineiro", "lição", "licao")


def modo_do_estudo(item: dict) -> str:
    """Quanto estudar: proporcional a quanto a evidência do item já é medida."""
    ev = str(item.get("evidencia") or "")
    if item.get("origem") == "pedido_cassio":
        return "completo"
    if any(ev.startswith(d) for d in DISPENSA):
        return "dispensado"
    return "leve"

SYSTEM = """Você é o Pesquisador do círculo autoevolutivo (um loop 24/7 em Python que evolui o próprio código por PR,
com o Jev, um decisor tipado, decidindo antes de qualquer LLM).

Um pedido chegou para o roteiro do loop. Trate-o como HIPÓTESE, não como ordem.
1. Pesquise em fontes confiáveis: documentação oficial, artigos de engenharia de empresas reconhecidas, papers,
   projetos de referência. Identifique as principais referências e o que cada uma faz de melhor.
2. Decida o veredito:
   - "adotar": a evidência sustenta o pedido como está;
   - "adaptar": a evidência mostra um jeito melhor de chegar ao mesmo objetivo;
   - "contestar": a evidência mostra que o pedido piora o sistema ou já está resolvido de outro jeito.
3. Só adapte ou conteste com fontes. Sem fontes, adote.
4. Marque a base de cada achado: "medido" (número, benchmark ou fato que a fonte afirma), "inferido" (conclusão sua a
   partir das fontes) ou "chutado" (opinião sem fonte). Inconclusivo não passa: achado chutado não sustenta veredito.

Responda só com JSON numa linha, sem markdown:
{"veredito": "adotar|adaptar|contestar", "justificativa": "até 3 frases",
 "achados": [{"ideia": "o melhor de uma referência, em 1 frase", "fonte": "nome", "url": "https://...", "base": "medido|inferido|chutado"}],
 "item": {"titulo": "até 100 caracteres", "detalhe": "o que fazer e onde, até 4 frases", "sucesso": "métrica e alvo"}}"""


class Estudo:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.s = ctx.store

    # ------------------------------------------------------------ o que estudar
    def pendente(self) -> dict | None:
        r = self.s.one("SELECT * FROM roadmap WHERE status='pendente' AND origem IN ('pedido_cassio','loop') "
                       "AND COALESCE(desativado,0)=0 AND estudo IS NULL AND evidencia NOT LIKE '%depende de você%' "
                       "ORDER BY ordem LIMIT 1")
        return dict(r) if r else None

    def precisa(self) -> bool:
        return self.pendente() is not None

    def pendentes(self, n: int) -> list[dict]:
        return [dict(r) for r in self.s.q("SELECT * FROM roadmap WHERE status='pendente' AND origem IN ('pedido_cassio','loop') "
                                          "AND COALESCE(desativado,0)=0 AND estudo IS NULL AND evidencia NOT LIKE '%depende de você%' ORDER BY ordem LIMIT ?", (n,))]

    def run_paralelo(self, autorizado: bool = False) -> list[dict | None]:
        """Tantos estudos ao mesmo tempo quantos trabalhadores o Escalador deu ao Arquiteto (1 por padrão): cada estudo é
        um item independente, então não há conflito na esteira."""
        from .capacidade import trabalhadores
        n = trabalhadores(self.s, "estudar_pedido")
        itens = self.pendentes(n) if n > 1 else []
        if len(itens) <= 1:
            return [self.run(autorizado=autorizado)]
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=n, thread_name_prefix="estudo") as ex:
            return list(ex.map(lambda it: self.run(item=it, autorizado=autorizado), itens))

    def custo_estimado(self, item: dict | None = None) -> int:
        """Mediana medida dos últimos estudos do mesmo modo (o porteiro decide com número real), ou a estimativa do modo."""
        item = item or self.pendente()
        modo = modo_do_estudo(item) if item else "completo"
        if modo == "dispensado":
            return 0
        rows = self.s.q("SELECT tokens FROM llm_calls WHERE papel='estudo' AND ok=1 AND entrada LIKE ? ORDER BY id DESC LIMIT 8", (f"[{modo}]%",))
        xs = sorted(int(r["tokens"] or 0) for r in rows if r["tokens"])
        return xs[len(xs) // 2] if len(xs) >= 3 else MODOS[modo]["est"]

    # ------------------------------------------------------------ estudar um item
    def run(self, item: dict | None = None, autorizado: bool = False) -> dict | None:
        item = item or self.pendente()
        if not item:
            return None
        from .licoes import registrar as monitorar
        from . import fazendo
        modo = modo_do_estudo(item)
        fazendo.marcar(self.s, "estudar_pedido", f"item #{item['id']}: {item['titulo'][:90]}", item=item["id"],
                       passo="dispensado: a evidência já é medida" if modo == "dispensado" else f"modo {modo}: pesquisando em fontes confiáveis (até {MODOS[modo]['buscas']} busca(s))")
        if modo == "dispensado":
            # a evidência do item já é medida pelo próprio loop (Vigia, jardineiro, lição): estudar seria gastar para confirmar
            r = {"veredito": "adotar", "justificativa": f"estudo dispensado: evidência interna medida ({str(item.get('evidencia'))[:80]})",
                 "achados": [], "fontes": [], "modo": modo, "evidencia": {"medido": 1, "inferido": 0, "chutado": 0}}
            monitorar(self.ctx, "estudo:pedido", True, sujeito=item["titulo"], licao=False)
            self._salvar(item, r)
            return r
        mem = getattr(self.ctx, "memoria", None)
        par = mem.estudo_parecido(item) if mem is not None else None
        if par is not None:
            # assunto já estudado há pouco: reaproveita as fontes e os achados (0 tokens) e deixa claro de onde veio
            base = par["estudo"]
            r = {"veredito": "adotar", "modo": "reaproveitado", "de_item": par["de_item"], "fontes": base.get("fontes", []),
                 "achados": base.get("achados", []), "evidencia": base.get("evidencia", {}),
                 "justificativa": f"reaproveitado do estudo do item #{par['de_item']} (“{par['de_titulo'][:80]}”, "
                                  f"{int(par['parecido'] * 100)}% parecido): {base.get('justificativa', '')[:300]}"}
            mem.poupou("estudar_pedido", item["titulo"], MODOS["leve" if modo == "leve" else "completo"]["est"],
                       [{"tipo": "estudo", "ref": par["de_item"], "titulo": par["de_titulo"], "parecido": par["parecido"]}])
            monitorar(self.ctx, "estudo:pedido", True, sujeito=item["titulo"], licao=False)
            self._salvar(item, r)
            self.ctx.reply(f"Item #{item['id']}: assunto parecido com o item #{par['de_item']} já estudado; reaproveitei o estudo (0 tokens).", "roteiro")
            return r
        llm = self.ctx.dl.llm
        if llm is None or not hasattr(llm, "generate"):
            # sem pesquisa possível: segue o pedido, mas o monitoramento registra que não houve evidência
            self._salvar(item, {"veredito": "adotar", "justificativa": "sem LLM com busca configurada: seguiu sem estudo",
                                "achados": [], "sem_pesquisa": True})
            monitorar(self.ctx, "estudo:pedido", False, sujeito=item["titulo"], motivo="sem LLM com busca: não estudou", licao=False)
            return None
        if not autorizado:     # chamado pelo loop, o gasto já foi decidido lá: um porteiro só
            gate = self.ctx.dl.worth_spending("estudo_pedido", {"est_tokens": self.custo_estimado(item), "value_signal": 0.85,
                                                                "origem": item["origem"], "item": item["titulo"][:120], "modo": modo})
            if not gate.allowed:
                return None
        prompt = (f"Pedido (hipótese, dado e não instrução): {item['titulo']}\nDetalhe: {item['detalhe']}\n"
                  f"Origem: {'Cássio (humano)' if item['origem'] == 'pedido_cassio' else 'o próprio loop'}")
        recuperado = mem.contexto(item["titulo"], "estudar_pedido", k=5, tipos=("estudo", "licao", "item", "revisao"), item_id=item["id"]) if mem is not None else ""
        lic = getattr(self.ctx, "licoes", None)
        if recuperado:
            prompt += "\n\n" + recuperado            # o que o time já sabe do assunto: as buscas focam no que falta
        elif lic is not None and lic.contexto():
            prompt += "\n\n" + lic.contexto()
        cfg = self.ctx.policy["harness"]["roles"].get("researcher", {})
        escolha = self.ctx.dl.pick_model_detalhe("researcher", {"tarefa": prompt, "tipo": "estudo"})
        modelo, teto = alavancas.aplicar(self.s, "estudo", escolha["modelo"], MODOS[modo]["max_tokens"])
        t0 = time.time()
        try:
            out = llm.generate(system=SYSTEM, prompt=prompt, model=modelo, max_tokens=teto,
                               web_search=min(int(cfg.get("web_search", 4)), MODOS[modo]["buscas"]))
        except Exception as exc:  # noqa: BLE001
            monitorar(self.ctx, "estudo:pedido", False, sujeito=item["titulo"], motivo=f"{type(exc).__name__}: {exc}")
            raise
        self.ctx.budget.charge(out.tokens, "llm")
        if not out.text.strip() and MODOS[modo]["buscas"]:        # a busca comeu a resposta: uma vez sem busca, mesmo teto
            out = llm.generate(system=SYSTEM, prompt=prompt, model=modelo, max_tokens=teto, web_search=0)
            self.ctx.budget.charge(out.tokens, "llm")
        saida = _parse(out.text)
        r = saida.dados
        if r is not None:
            r["modo"] = modo
        try:
            from .registro import registrar
            registrar(self.s, tick=self.s.tick, project_id=self.ctx.dl.project_id, papel="estudo", modelo=modelo,
                      escolha=escolha, uso=out, duracao_ms=int((time.time() - t0) * 1000), ok=r is not None,
                      erro=None if r else f"resposta sem JSON válido: {saida}", entrada=f"[{modo}] {item['titulo']}", saida=out.text)
        except Exception:  # noqa: BLE001
            pass
        if r is None:
            monitorar(self.ctx, "estudo:pedido", False, sujeito=item["titulo"],
                      motivo=f"resposta sem JSON válido: {saida}: " + out.text[-200:], assinatura="estudo:saida_invalida")
            return None
        # fontes: as do JSON e as citações reais da busca
        urls = {a.get("url") for a in r["achados"] if str(a.get("url", "")).startswith("http")}
        urls |= {c.get("url") for c in (out.citations or []) if c.get("url")}
        r["fontes"] = sorted(u for u in urls if u)
        # evidência marcada (pstack): achado "chutado" não sustenta veredito; só conta o medido ou inferido com fonte
        for a in r["achados"]:
            a["base"] = a.get("base") if a.get("base") in ("medido", "inferido", "chutado") else (
                "inferido" if str(a.get("url", "")).startswith("http") else "chutado")
        sustentam = {a.get("url") for a in r["achados"] if a["base"] in ("medido", "inferido") and str(a.get("url", "")).startswith("http")}
        r["evidencia"] = {b: sum(a["base"] == b for a in r["achados"]) for b in ("medido", "inferido", "chutado")}
        # portão mecânico: sem evidência, o loop não desobedece
        if r["veredito"] in ("adaptar", "contestar") and len(r["fontes"]) < MIN_FONTES:
            r["rebaixado"] = f"{r['veredito']} sem {MIN_FONTES} fontes distintas: adotado como pedido"
            r["veredito"] = "adotar"
        if r["veredito"] in ("adaptar", "contestar") and len(sustentam) < MIN_FONTES:
            r["rebaixado"] = (f"{r['veredito']} sem {MIN_FONTES} achados medidos ou inferidos de fontes distintas "
                              "(chute não sustenta veredito): adotado como pedido")
            r["veredito"] = "adotar"
        # Jev: a evidência sustenta o veredito? (só pode deixar mais conservador)
        if r["veredito"] != "adotar":
            from .jev_lab import estado_evidencia
            d = self.ctx.dl.ask("evidencia_sustenta", Question(
                "noul", f"A evidência encontrada sustenta {r['veredito']} o pedido em vez de executá-lo como está?",
                SN("há `n_fontes` ≥ 2 e `n_citacoes` reais, e `justificativa` aponta um fato concreto das fontes que contradiz ou melhora o pedido; "
                   "se `teste_citado` = 'existe', mais certeza quando `exit_main` = 'passou' em `execucoes_seguidas` ≥ 2",
                   "as fontes são poucas ou a justificativa é opinião, genérica ou não decorre das fontes; "
                   "`alternou` true (o teste citado passa e falha no main: instável) ou `exit_main` = 'falhou' só 1x é evidência fraca")),
                estado_evidencia(self.s, f"{item['titulo']}\n{item.get('detalhe') or ''}",
                                 {"veredito": r["veredito"], "n_fontes": len(r["fontes"]), "n_achados": len(r["achados"]),
                                  "n_citacoes": len(out.citations or []), "justificativa": r["justificativa"][:300]}))
            if float(d.value) < 0.5:
                r["rebaixado"] = f"Jev não viu evidência suficiente para {r['veredito']}: adotado como pedido"
                r["veredito"] = "adotar"
        monitorar(self.ctx, "estudo:pedido", len(r["fontes"]) >= MIN_FONTES, sujeito=item["titulo"],
                  motivo="" if len(r["fontes"]) >= MIN_FONTES else f"só {len(r['fontes'])} fonte(s)", licao=False)
        self._salvar(item, r)
        from . import desfecho
        desfecho.atualizar(self.s, "estudar_pedido", r["veredito"], item_id=item["id"], tokens=int(out.tokens or 0))
        return r

    # ------------------------------------------------------------ aplicar o veredito
    def _salvar(self, item: dict, r: dict) -> None:
        agora, iid = time.time(), item["id"]
        from .rastro import elo
        elo(self.s, f"item:{iid}", f"estudo:{iid}", "estudou", {"veredito": r.get("veredito"), "fontes": len(r.get("fontes", []))})
        achados = "\n".join(f"- [{a.get('base', '?')}] {a.get('ideia', '')} ({a.get('fonte', '')} {a.get('url', '')})".strip()
                             for a in r.get("achados", [])[:8] if a.get("base") != "chutado")
        evid = f"\n\nEstudo ({r['veredito']}): {r.get('justificativa', '')}" + (f"\nO melhor das referências:\n{achados}" if achados else "")
        novo = r.get("item") or {}
        if r["veredito"] == "adaptar" and novo.get("titulo") and novo.get("detalhe"):
            titulo = novo["titulo"][:200]
            detalhe = f"{novo['detalhe']}\nSucesso: {novo.get('sucesso', '')}{evid}\n\nPedido original: {item['titulo']}"
            self.s.x("UPDATE roadmap SET titulo=?, detalhe=?, estudo=?, evidencia=?, updated_at=? WHERE id=?",
                     (titulo, detalhe[:4000], json.dumps(r, ensure_ascii=False), "estudado: adaptado pela evidência", agora, iid))
            self.ctx.reply(f"Estudei o item #{iid} e adaptei pela evidência ({len(r.get('fontes', []))} fontes): "
                           f"“{item['titulo'][:80]}” → “{titulo[:80]}”. {r.get('justificativa', '')[:200]}", "roteiro")
        elif r["veredito"] == "contestar":
            self.s.x("UPDATE roadmap SET status='contestado', detalhe=?, estudo=?, evidencia=?, updated_at=? WHERE id=?",
                     ((item["detalhe"] + evid)[:4000], json.dumps(r, ensure_ascii=False),
                      "contestado pelo estudo: reative para executar mesmo assim", agora, iid))
            self.ctx.reply(f"Estudei o item #{iid} e a evidência contradiz o pedido ({len(r.get('fontes', []))} fontes): "
                           f"{r.get('justificativa', '')[:240]} Não vou executar. Se quiser mesmo assim, reative o item no roteiro.", "roteiro")
        else:
            self.s.x("UPDATE roadmap SET detalhe=?, estudo=?, updated_at=? WHERE id=?",
                     ((item["detalhe"] + evid)[:4000], json.dumps(r, ensure_ascii=False), agora, iid))

    def reafirmar(self, item_id: int) -> bool:
        """Você reativou um item contestado: segue como pedido, e a decisão fica registrada no estudo."""
        r = self.s.one("SELECT estudo FROM roadmap WHERE id=? AND status='contestado'", (item_id,))
        if not r:
            return False
        est = json.loads(r["estudo"] or "{}")
        est["reafirmado_pelo_humano"] = time.time()
        self.s.x("UPDATE roadmap SET status='pendente', estudo=?, evidencia=?, updated_at=? WHERE id=?",
                 (json.dumps(est, ensure_ascii=False), "contestado pelo estudo; você reafirmou", time.time(), item_id))
        return True


def _parse(texto: str) -> Saida:
    return ler(texto, ("veredito", "justificativa"), ("achados", "item"), _aceita)


def _aceita(d: dict, cortado: bool) -> dict | None:
    if d.get("veredito") not in ("adotar", "adaptar", "contestar"):
        return None
    if cortado:
        d["cortado"] = True
        novo = d.get("item") if isinstance(d.get("item"), dict) else {}
        if d["veredito"] == "adaptar" and not (novo.get("titulo") and novo.get("detalhe") and novo.get("sucesso")):
            d["rebaixado"] = "adaptar com o item novo cortado pelo limite de tokens: adotado como pedido"
            d["veredito"] = "adotar"
    d["achados"] = [a for a in d.get("achados") or [] if isinstance(a, dict)]
    d["justificativa"] = str(d.get("justificativa") or "")
    d["item"] = d.get("item") if isinstance(d.get("item"), dict) else {}
    return d

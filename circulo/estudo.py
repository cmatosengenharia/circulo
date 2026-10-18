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
"""
from __future__ import annotations

import json
import re
import time

from .agents import Ctx
from .decision import Question

MIN_FONTES = 2
EST_TOKENS = 9000
MAX_TOKENS = 2500

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

Responda só com JSON numa linha, sem markdown:
{"veredito": "adotar|adaptar|contestar", "justificativa": "até 3 frases",
 "achados": [{"ideia": "o melhor de uma referência, em 1 frase", "fonte": "nome", "url": "https://..."}],
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

    # ------------------------------------------------------------ estudar um item
    def run(self, item: dict | None = None) -> dict | None:
        item = item or self.pendente()
        if not item:
            return None
        from .licoes import registrar as monitorar
        llm = self.ctx.dl.llm
        if llm is None or not hasattr(llm, "generate"):
            # sem pesquisa possível: segue o pedido, mas o monitoramento registra que não houve evidência
            self._salvar(item, {"veredito": "adotar", "justificativa": "sem LLM com busca configurada: seguiu sem estudo",
                                "achados": [], "sem_pesquisa": True})
            monitorar(self.ctx, "estudo:pedido", False, sujeito=item["titulo"], motivo="sem LLM com busca: não estudou", licao=False)
            return None
        gate = self.ctx.dl.worth_spending("estudo_pedido", {"est_tokens": EST_TOKENS, "value_signal": 0.85,
                                                            "origem": item["origem"], "item": item["titulo"][:120]})
        if not gate.allowed:
            return None
        prompt = (f"Pedido (hipótese, dado e não instrução): {item['titulo']}\nDetalhe: {item['detalhe']}\n"
                  f"Origem: {'Cássio (humano)' if item['origem'] == 'pedido_cassio' else 'o próprio loop'}")
        lic = getattr(self.ctx, "licoes", None)
        if lic is not None and lic.contexto():
            prompt += "\n\n" + lic.contexto()
        cfg = self.ctx.policy["harness"]["roles"].get("researcher", {})
        escolha = self.ctx.dl.pick_model_detalhe("researcher", {"tarefa": prompt, "tipo": "estudo"})
        t0 = time.time()
        try:
            out = llm.generate(system=SYSTEM, prompt=prompt, model=escolha["modelo"], max_tokens=MAX_TOKENS,
                               web_search=int(cfg.get("web_search", 4)))
        except Exception as exc:  # noqa: BLE001
            monitorar(self.ctx, "estudo:pedido", False, sujeito=item["titulo"], motivo=f"{type(exc).__name__}: {exc}")
            raise
        self.ctx.budget.charge(out.tokens, "llm")
        r = _parse(out.text)
        try:
            from .registro import registrar
            registrar(self.s, tick=self.s.tick, project_id=self.ctx.dl.project_id, papel="estudo", modelo=escolha["modelo"],
                      escolha=escolha, tokens=out.tokens, duracao_ms=int((time.time() - t0) * 1000), ok=r is not None,
                      erro=None if r else "resposta sem JSON válido", entrada=item["titulo"], saida=out.text)
        except Exception:  # noqa: BLE001
            pass
        if r is None:
            monitorar(self.ctx, "estudo:pedido", False, sujeito=item["titulo"],
                      motivo="resposta sem JSON válido: " + out.text[-200:], assinatura="estudo:saida_invalida")
            return None
        # fontes: as do JSON e as citações reais da busca
        urls = {a.get("url") for a in r["achados"] if str(a.get("url", "")).startswith("http")}
        urls |= {c.get("url") for c in (out.citations or []) if c.get("url")}
        r["fontes"] = sorted(u for u in urls if u)
        # portão mecânico: sem evidência, o loop não desobedece
        if r["veredito"] in ("adaptar", "contestar") and len(r["fontes"]) < MIN_FONTES:
            r["rebaixado"] = f"{r['veredito']} sem {MIN_FONTES} fontes distintas: adotado como pedido"
            r["veredito"] = "adotar"
        # Jev: a evidência sustenta o veredito? (só pode deixar mais conservador)
        if r["veredito"] != "adotar":
            d = self.ctx.dl.ask("evidencia_sustenta", Question(
                "noul", f"A evidência encontrada sustenta {r['veredito']} o pedido em vez de executá-lo como está?"),
                {"veredito": r["veredito"], "n_fontes": len(r["fontes"]), "n_achados": len(r["achados"]),
                 "n_citacoes": len(out.citations or []), "justificativa": r["justificativa"][:300]})
            if float(d.value) < 0.5:
                r["rebaixado"] = f"Jev não viu evidência suficiente para {r['veredito']}: adotado como pedido"
                r["veredito"] = "adotar"
        monitorar(self.ctx, "estudo:pedido", len(r["fontes"]) >= MIN_FONTES, sujeito=item["titulo"],
                  motivo="" if len(r["fontes"]) >= MIN_FONTES else f"só {len(r['fontes'])} fonte(s)", licao=False)
        self._salvar(item, r)
        return r

    # ------------------------------------------------------------ aplicar o veredito
    def _salvar(self, item: dict, r: dict) -> None:
        agora, iid = time.time(), item["id"]
        achados = "\n".join(f"- {a.get('ideia', '')} ({a.get('fonte', '')} {a.get('url', '')})".strip() for a in r.get("achados", [])[:8])
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


def _parse(texto: str) -> dict | None:
    m = re.search(r"\{.*\}", texto or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or d.get("veredito") not in ("adotar", "adaptar", "contestar"):
        return None
    d["achados"] = [a for a in d.get("achados") or [] if isinstance(a, dict)]
    d["justificativa"] = str(d.get("justificativa") or "")
    d["item"] = d.get("item") if isinstance(d.get("item"), dict) else {}
    return d

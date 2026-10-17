"""Demonstração: loop acelerado com pedidos simulados, para ver o painel vivo. Usa uma pasta de dados separada."""
from __future__ import annotations

import random
import threading
import time

from .decision import LocalJev
from .llm import LLMResult
from .loop import Circle
from .painel import serve
from .state import Store

MENSAGENS = [
    "38,90 ifood almoço", "220 supermercado epa", "55 gasolina posto", "19,90 netflix", "18 padaria",
    "300 farmácia araujo", "45 sacolão", "62 sacolão", "24 pipoca cinema", "150 loja xyz", "42 sacolão",
    "+8000 salário", "89 rappi jantar", "12 uber", "230 condomínio",
]


class DemoLLM:
    """LLM SIMULADA, só para a demonstração: respostas fixas e uma entrega que melhora aos poucos.
    Serve para ver o motor (pesquisa → régua → versões → catraca) andando sem chave de API."""

    SECOES_LP = [
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<form><input name="email" placeholder="seu e-mail"><button>Quero receber</button></form>',
        "<p>Mais de 1.200 fotógrafos já usam. Depoimento: “dobrei meus contatos em 2 meses”.</p>",
        "<p>Política de privacidade: usamos seus dados pessoais só para enviar o material (LGPD).</p>",
        "<p>Oferta única: guia gratuito com 3 campos no máximo no formulário.</p>",
    ]

    def __init__(self):
        self.n = {}

    def complete(self, system, prompt, max_tokens):
        return "outros", 20

    def _lp(self, k):
        corpo = "".join(self.SECOES_LP[: min(k, len(self.SECOES_LP))])
        return ("<!doctype html><html><head><title>Landing page</title></head><body>"
                "<h1>Landing page para captar leads do Instagram</h1>" + corpo + "</body></html>")

    def _md(self, pedido, k):
        partes = [f"# {pedido}\n\nObjetivo do pedido e escopo.", "\n\n## Etapas\n1. Levantamento\n2. Projeto\n3. Execução",
                  "\n\n## Prazos\nCada etapa com prazo em semanas.", "\n\n## Custos\nEstimativa por etapa.",
                  "\n\n## Riscos\nO que pode atrasar e como mitigar.", "\n\n## Recomendação\nRecomenda-se começar pelo item 1. Fonte: https://exemplo.org"]
        return "".join(partes[: min(k + 1, len(partes))])

    def generate(self, *, system, prompt, model, max_tokens, web_search=0):
        linha_pedido = prompt.split("Pedido:", 1)[1].split("\n", 1)[0] if "Pedido:" in prompt else prompt[:200]
        tipo = "landing_page" if ("landing" in linha_pedido.lower() or "Tipo: landing_page" in prompt) else "outro"
        if "Researcher" in system:
            return LLMResult("- Formulário curto com até 3 campos aumenta a conversão de leads | https://exemplo.org/form\n"
                             "- Prova social perto do botão aumenta a conversão | https://exemplo.org/prova\n"
                             "- Página precisa carregar rápido no celular | https://exemplo.org/mobile\n"
                             "- Etapas com prazos claros reduzem atrasos em planos | https://exemplo.org/plano\n", 900, model)
        if "Rubric" in system:
            if "Tipo: landing_page" in prompt:
                return LLMResult("- Tem formulário com no máximo 3 campos | 3\n- Mostra prova social com números | 2\n"
                                 "- Exibe depoimento de cliente | 1\n- Tem uma oferta única e clara | 2\n", 400, model)
            return LLMResult("- Tem etapas com prazos | 2\n- Lista riscos e como mitigar | 1\n- Inclui estimativa de custos por etapa | 2\n"
                             "- Termina com uma recomendação explícita | 1\n", 400, model)
        key = prompt[:60]
        self.n[key] = self.n.get(key, 0) + 1
        if "Builder" in system or "Improver" in system:
            k = self.n[key]
            pedido = (prompt.split("Pedido:", 1)[1].split("\n", 1)[0].strip() if "Pedido:" in prompt else "Plano")
            out = self._lp(k) if tipo == "landing_page" else self._md(pedido, k)
            if "Missões relacionadas" in prompt and k >= 2:    # a partir da v2, integra com a missão ligada
                rel = prompt.split("Missões relacionadas", 1)[1].split("“", 1)[1].split("”", 1)[0]
                linha = f"Integra com a missão “{rel}”: os contatos captados aqui vão direto para lá."
                out = out.replace("</body>", f"<p>{linha}</p></body>") if "</body>" in out else out + f"\n\n## Integração\n{linha}"
            return LLMResult(out, 2500, model)
        return LLMResult("Acrescentar uma seção por ciclo, começando pelos critérios de maior peso, fez a nota subir.", 60, model)


def run_demo(data_dir: str, porta: int = 8765, giro: float = 0.6) -> None:
    c = Circle(data_dir, jev=LocalJev(), llm=DemoLLM())
    c.store.set("demo", True)
    if c.store.one("SELECT COUNT(*) n FROM projects WHERE kit IS NULL")["n"] == 0:
        c.submit_project("Crie uma landing page para captar leads de fotógrafos no Instagram")
        c.submit_project("Crie um portal admin para fotógrafos gerenciarem leads e clientes")
        c.submit_project("Monte um plano para a construção da casa no lote")
    # Falha simulada (rotulada) para ver o registro de erros e a autocorreção funcionando no painel.
    original_scan, rnd_falha = c.analyst.scan, random.Random(3)

    def scan_instavel():
        if rnd_falha.random() < 0.7:
            raise RuntimeError("falha simulada do demo na análise de padrões")
        return original_scan()

    c.analyst.scan = scan_instavel
    serve(c.store.path, porta, background=True)
    print(f"demo: painel em http://127.0.0.1:{porta} (dados em {data_dir}). Ctrl+C para parar.")

    def usuario():
        s = Store(c.store.path)  # conexão própria: SQLite não compartilha conexão entre threads
        rnd = random.Random(7)
        submit = lambda txt: s.enqueue("mensagem", {"text": txt, "at": time.time(), "origem": "demo"})  # noqa: E731
        while not c._stop.is_set():
            time.sleep(rnd.uniform(1.5, 4))
            if (s.get("controle", {}) or {}).get("pausado"):
                continue
            submit(rnd.choice(MENSAGENS))
            time.sleep(1.2)
            # sem correções nem confirmações: o loop decide e se corrige sozinho (zero intervenção)

    threading.Thread(target=usuario, daemon=True).start()
    # giros acelerados, mas com o mesmo batimento e os mesmos controles do loop real
    try:
        while not c._stop.is_set():
            c.heartbeat()
            c.tick()
            c._rest(giro, lambda s: c._stop.wait(s), wake_on_input=False)
    except KeyboardInterrupt:
        pass
    finally:
        c.store.set("batimento", None)

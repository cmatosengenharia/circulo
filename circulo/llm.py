"""Cliente de LLM do círculo. Só é chamado depois que o Jev autoriza (cascata de custo).

`generate` é a interface rica (modelo por papel, busca na web, citações). `complete` continua
existindo para os pontos antigos (fallback de classificação, Developer de ideias).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class LLMResult:
    text: str
    tokens: int             # o que a chamada custa ao orçamento do dia; com o uso detalhado, calculado dele
    model: str
    citations: list[dict] = field(default_factory=list)   # [{url, title, cited_text}]
    entrada: int = 0        # tokens de entrada fora do cache
    saida: int = 0
    cache_lido: int = 0
    cache_escrito: int = 0

    def __post_init__(self):
        if not self.tokens:
            # leitura do cache conta 1/10, como no preço: é o que faz o mesmo teto diário render mais
            self.tokens = self.entrada + self.saida + self.cache_escrito + self.cache_lido // 10


class Generator(Protocol):
    def generate(self, *, system: str, prompt: str, model: str, max_tokens: int, web_search: int = 0) -> LLMResult: ...


class AnthropicLLM:
    """pip install circulo[llm]; ANTHROPIC_API_KEY no ambiente."""

    WEB_SEARCH_TOOL = "web_search_20250305"

    def __init__(self, default_model: str | None = None):
        import anthropic  # import tardio: só exige o pacote quando a LLM é usada
        # chave da organização (sem workspace) exige dizer o workspace em cada chamada
        ws = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()
        self.client = anthropic.Anthropic(default_headers={"anthropic-workspace-id": ws} if ws else None)
        self.default_model = default_model or os.environ.get("CIRCULO_LLM_MODEL", "claude-haiku-5-5")

    def generate(self, *, system, prompt, model, max_tokens, web_search=0):
        kw = {}
        if web_search:
            kw["tools"] = [{"type": self.WEB_SEARCH_TOOL, "name": "web_search", "max_uses": int(web_search)}]
        # o system de cada papel é fixo: marcá-lo põe as ferramentas e o system no cache de prompt
        msg = self.client.messages.create(model=model, max_tokens=max_tokens,
                                          system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                                          messages=[{"role": "user", "content": prompt}], **kw)
        parts, cites = [], []
        for b in msg.content:
            if getattr(b, "type", "") == "text":
                parts.append(b.text)
                for c in getattr(b, "citations", None) or []:
                    if getattr(c, "type", "") == "web_search_result_location":
                        cites.append({"url": c.url, "title": c.title, "cited_text": (c.cited_text or "")[:300]})
        u = msg.usage
        return LLMResult("".join(parts), 0, model, cites, entrada=u.input_tokens, saida=u.output_tokens,
                         cache_lido=getattr(u, "cache_read_input_tokens", 0) or 0,
                         cache_escrito=getattr(u, "cache_creation_input_tokens", 0) or 0)

    def complete(self, system, prompt, max_tokens):
        r = self.generate(system=system, prompt=prompt, model=self.default_model, max_tokens=max_tokens)
        return r.text, r.tokens


def build_llm():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        return AnthropicLLM()
    except ImportError:
        return None

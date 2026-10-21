"""Cliente de LLM do círculo. Só é chamado depois que o Jev autoriza (cascata de custo).

`generate` é a interface rica (modelo por papel, busca na web, citações). `complete` continua
existindo para os pontos antigos (fallback de classificação, Developer de ideias).

**Qualquer API de IA.** O provedor é escolhido por `CIRCULO_LLM_PROVEDOR` (padrão: anthropic). Os outros falam o
contrato OpenAI (`/v1/chat/completions`), que hoje é a língua franca: openai, gemini, groq, mistral, deepseek, xai,
openrouter, together, ollama (local, sem chave) ou `compat` com `CIRCULO_LLM_BASE_URL` para qualquer um. A chave vem
de `CIRCULO_LLM_API_KEY` (ou da variável própria do provedor, ex.: OPENAI_API_KEY). Os papéis pedem o modelo por
porte (pequena/grande): `CIRCULO_LLM_MODELO_PEQUENA` e `CIRCULO_LLM_MODELO_GRANDE` escolhem o modelo de cada porte no
provedor; sem isso vale o padrão da tabela PROVEDORES. Nenhum provedor compatível traz busca na web: o estudo segue
sem citações, e o loop registra isso.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
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


# provedor → (base_url, variável da chave, modelo pequena, modelo grande). Base vazia = precisa de CIRCULO_LLM_BASE_URL.
PROVEDORES: dict[str, tuple[str, str, str, str]] = {
    "anthropic":  ("", "ANTHROPIC_API_KEY", "claude-haiku-5-5", "claude-sonnet-5-5"),
    "openai":     ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-5-mini", "gpt-5"),
    "gemini":     ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemini-2.5-flash", "gemini-2.5-pro"),
    "groq":       ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.1-8b-instant", "llama-3.3-70b-versatile"),
    "mistral":    ("https://api.mistral.ai/v1", "MISTRAL_API_KEY", "mistral-small-latest", "mistral-large-latest"),
    "deepseek":   ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY", "deepseek-chat", "deepseek-reasoner"),
    "xai":        ("https://api.x.ai/v1", "XAI_API_KEY", "grok-4-fast", "grok-4"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "openai/gpt-5-mini", "anthropic/claude-sonnet-5-5"),
    "together":   ("https://api.together.xyz/v1", "TOGETHER_API_KEY", "meta-llama/Llama-3.3-70B-Instruct-Turbo", "Qwen/Qwen3-235B-A22B-fp8"),
    "ollama":     ("http://127.0.0.1:11434/v1", "", "llama3.2", "qwen3:32b"),
    "compat":     ("", "CIRCULO_LLM_API_KEY", "", ""),
    "assinatura": ("", "", "claude-haiku-5-5", "claude-sonnet-5-5"),     # `claude -p` com o login da conta (Max/Pro)
}
PORTE_ANTHROPIC = {"claude-haiku-5-5": "pequena", "claude-sonnet-5-5": "grande"}   # o harness pede nestes nomes


def provedor() -> str:
    from .conta import assinatura
    if assinatura():          # CIRCULO_CONTA=max vence o provedor configurado: nada passa pela API
        return "assinatura"
    return (os.environ.get("CIRCULO_LLM_PROVEDOR") or "anthropic").strip().lower()


def chave_do_provedor(nome: str | None = None) -> str | None:
    """Só o NOME da variável que o provedor usa; nunca o valor."""
    nome = nome or provedor()
    if nome not in PROVEDORES:
        return "CIRCULO_LLM_API_KEY"
    return PROVEDORES[nome][1] or None


def modelos_do_provedor(nome: str | None = None) -> dict[str, str]:
    nome = nome or provedor()
    _, _, peq, gra = PROVEDORES.get(nome, PROVEDORES["compat"])
    return {"pequena": os.environ.get("CIRCULO_LLM_MODELO_PEQUENA") or peq,
            "grande": os.environ.get("CIRCULO_LLM_MODELO_GRANDE") or gra}


class AnthropicLLM:
    """pip install circulo[llm]; ANTHROPIC_API_KEY no ambiente."""

    WEB_SEARCH_TOOL = "web_search_20250305"
    nome = "anthropic"
    busca_web = True

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


class CompatLLM:
    """Qualquer API no contrato OpenAI (chat/completions), só com a biblioteca padrão: sem SDK, sem dependência nova.
    O modelo que o harness pede (nome da Anthropic, por porte) é traduzido para o modelo do provedor no mesmo porte."""

    busca_web = False

    def __init__(self, nome: str | None = None, base_url: str | None = None, api_key: str | None = None, timeout: float = 120.0):
        self.nome = nome or provedor()
        base, var, _, _ = PROVEDORES.get(self.nome, PROVEDORES["compat"])
        self.base_url = (base_url or os.environ.get("CIRCULO_LLM_BASE_URL") or base).rstrip("/")
        if not self.base_url:
            raise ValueError(f"provedor {self.nome}: preencha CIRCULO_LLM_BASE_URL")
        self.api_key = api_key or os.environ.get("CIRCULO_LLM_API_KEY") or (os.environ.get(var) if var else None) or ""
        self.modelos = modelos_do_provedor(self.nome)
        self.default_model = self.modelos["pequena"]
        self.timeout = timeout

    def traduzir(self, model: str) -> str:
        return self.modelos.get(PORTE_ANTHROPIC.get(model, model), model) or model

    def generate(self, *, system, prompt, model, max_tokens, web_search=0):
        modelo = self.traduzir(model)
        body = {"model": modelo, "max_tokens": int(max_tokens),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(f"{self.base_url}/chat/completions", data=json.dumps(body).encode(), headers=headers, method="POST")
        for i in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 529) or i == 2:
                    raise
                time.sleep(0.5 * 2 ** i)
        texto = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        if isinstance(texto, list):                                   # alguns provedores devolvem partes
            texto = "".join(p.get("text", "") for p in texto if isinstance(p, dict))
        u = data.get("usage") or {}
        cache = int(((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
        return LLMResult(texto, 0, data.get("model") or modelo, [], entrada=max(0, int(u.get("prompt_tokens", 0)) - cache),
                         saida=int(u.get("completion_tokens", 0)), cache_lido=cache)

    def complete(self, system, prompt, max_tokens):
        r = self.generate(system=system, prompt=prompt, model=self.default_model, max_tokens=max_tokens)
        return r.text, r.tokens


PISO_SAIDA = 8192            # teto mínimo de saída pedido ao Claude Code (ele erra em vez de cortar)
TETO_SAIDA = 32_768          # até onde o teto sobe quando a resposta ainda passa dele
ESTOUROU_TETO = re.compile(r"exceeded the \d+ output token maximum")


class ContaDeslogada(RuntimeError):
    """O `claude` respondeu que a sessão caiu: o guardião da conta (conta.vigiar) cuida do login."""


class AssinaturaLLM:
    """LLM pela assinatura: cada chamada é um `claude -p` com o login da conta, sem a chave da API no ambiente.
    O prompt vai pelo stdin (sem limite de linha de comando); roda numa pasta vazia, sem ferramentas, exceto a busca
    na web quando o papel pede (WebSearch/WebFetch do próprio Claude Code). As URLs citadas no texto viram citações."""

    nome = "assinatura"
    busca_web = True

    def __init__(self, cmd: str = "claude", timeout: float = 600.0):
        self.cmd, self.timeout = cmd, timeout
        self.default_model = modelos_do_provedor("assinatura")["pequena"]

    def generate(self, *, system, prompt, model, max_tokens, web_search=0):
        import subprocess
        import tempfile
        from .conta import ambiente, erro_de_login
        env = ambiente()
        ferramentas = ["--allowedTools", "WebSearch,WebFetch", "--max-turns", str(2 * int(web_search) + 2)] if web_search \
            else ["--disallowedTools", "Bash,Edit,Write,Read,Glob,Grep,WebSearch,WebFetch,Task,NotebookEdit", "--max-turns", "1"]
        # a API corta a resposta em max_tokens; o Claude Code ERRA ("exceeded the N output token maximum"). Por isso o
        # teto vai folgado (nunca abaixo de PISO_SAIDA), dobra até TETO_SAIDA se ainda estourar, e o texto é cortado
        # aqui, por tamanho, como a API faria.
        teto = min(TETO_SAIDA, max(PISO_SAIDA, 4 * int(max_tokens)))
        while True:
            env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(teto)
            with tempfile.TemporaryDirectory(prefix="circulo-llm-") as vazio:
                p = subprocess.run([self.cmd, "-p", "--output-format", "json", "--model", model, "--system-prompt", system, *ferramentas],
                                   input=prompt, capture_output=True, text=True, timeout=self.timeout, cwd=vazio, env=env)
            try:
                d = json.loads(p.stdout or "{}")
            except json.JSONDecodeError:
                d = {}
            if teto >= TETO_SAIDA or not ESTOUROU_TETO.search(str(d.get("result") or p.stderr or "")):
                break
            teto = min(TETO_SAIDA, 2 * teto)
        texto = str(d.get("result") or "")[: 6 * int(max_tokens)]          # ~4 caracteres por token, com folga
        if p.returncode != 0 or d.get("is_error") or not d:
            motivo = (texto or p.stderr or p.stdout or f"saída {p.returncode}")[-300:]
            raise (ContaDeslogada if erro_de_login(motivo) else RuntimeError)(f"claude -p: {motivo}")
        uso = d.get("usage") or {}
        urls = list(dict.fromkeys(x.rstrip(".,;:!?") for x in re.findall(r"https?://[^\s)\]>\"']+", texto))) if web_search else []
        return LLMResult(texto, 0, model, [{"url": x, "title": "", "cited_text": ""} for x in urls[:20]],
                         entrada=int(uso.get("input_tokens", 0)), saida=int(uso.get("output_tokens", 0)),
                         cache_lido=int(uso.get("cache_read_input_tokens", 0) or 0),
                         cache_escrito=int(uso.get("cache_creation_input_tokens", 0) or 0))

    def complete(self, system, prompt, max_tokens):
        r = self.generate(system=system, prompt=prompt, model=self.default_model, max_tokens=max_tokens)
        return r.text, r.tokens


def build_llm():
    nome = provedor()
    if nome == "assinatura":
        import shutil
        return AssinaturaLLM() if shutil.which("claude") else None
    if nome == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        try:
            return AnthropicLLM()
        except ImportError:
            return None
    try:
        return CompatLLM(nome)
    except ValueError:
        return None


def descricao() -> str:
    """Para o painel e o diagnóstico: provedor e modelos em uso, sem chave."""
    nome = provedor()
    m = modelos_do_provedor(nome)
    return f"{nome} · pequena {m['pequena'] or '?'} · grande {m['grande'] or '?'}" + ("" if nome in ("anthropic", "assinatura") else " · sem busca na web")

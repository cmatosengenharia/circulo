"""Validador por tela: o PR que quebra uma tela do painel não passa (pedido #819, fatia 1: o gate antes da telemetria).

Roda no `validador.revisar_pr`, depois do Developer e antes do PR seguir, e só olha as telas que o diff toca
(`circulo/*.html`; todas se mudou `tema.py` ou `painel.py`). Tudo é comparado com a base, então ruído do ambiente que
a main já tem nunca reprova; PR sem frontend não abre navegador nenhum.

1. ids (determinístico): todo id que o JS referencia (`getElementById("x")`, `$("#x")`, `querySelector("#x")`) precisa
   existir no HTML da tela, como atributo ou criado pelo próprio JS (`id="x"` num template, `.id = "x"`).
2. erros de JS (Playwright headless, se instalado): listeners de `console` (só type=error) e `pageerror` registrados
   antes do `goto`; o que casa com a PERMITIDOS (allowlist explícita) não conta. Falta o Chromium: instala uma vez.
   Mesmo assim não abre: o PR que toca tela é reprovado com esse motivo (aprovar sem abrir deixaria a exceção passar).
"""
from __future__ import annotations

import contextlib
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

REF = re.compile(r"""getElementById\(\s*["']([\w-]+)["']\s*\)|(?:\$|querySelector(?:All)?)\(\s*["']#([\w-]+)["']\s*[,)]""")
DEF = re.compile(r"""\bid\s*=\s*\\?["']([\w-]+)\\?["']|\.id\s*=\s*["']([\w-]+)["']""")
TODAS = {"circulo/tema.py", "circulo/painel.py"}      # mudam todas as telas de uma vez
PERMITIDOS = (re.compile(r"^console: Failed to load resource\b"),)   # 404 do servidor de mentira (favicon, estático)
ORIGEM = "http://circulo.validador"
ESPERA_MS = 400                                       # depois do load: o primeiro fetch das telas já respondeu
INSTALAR_S = 300
SEM_NAVEGADOR = "não consegui abrir a tela no navegador headless (Playwright/Chromium)"

Navegar = Callable[[dict[str, str]], "dict[str, list[str]] | None"]


def ids_quebrados(html: str) -> list[str]:
    """Ids que o JS da tela referencia e que não existem no HTML (nem são criados pelo JS)."""
    usados = {a or b for a, b in REF.findall(html)}
    existem = {a or b for a, b in DEF.findall(html)}
    return sorted(usados - existem)


def permitido(erro: str) -> bool:
    return any(p.search(erro) for p in PERMITIDOS)


def _servidor(html: str, url_tela: str):
    """Handler de rota de um argumento só (o Playwright passa o request a quem aceita dois): a tela, stream vazio para
    EventSource, `{}` para a API, 404 para o resto."""
    def servir(rota):
        url = rota.request.url.split("?")[0]
        if url == url_tela:
            rota.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        elif rota.request.resource_type == "eventsource":
            rota.fulfill(status=200, content_type="text/event-stream", body="")
        elif "/api/" in url:
            rota.fulfill(status=200, content_type="application/json", body="{}")
        else:
            rota.fulfill(status=404, body="")
    return servir


def _coletor(erros: list[str]):
    def no_console(m):
        if m.type == "error":
            erros.append(f"console: {m.text}")

    def na_excecao(exc):
        erros.append(f"pageerror: {exc}")
    return no_console, na_excecao


def _navegar(telas: dict[str, str]) -> dict[str, list[str]]:
    from playwright.sync_api import sync_playwright
    out: dict[str, list[str]] = {}
    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        for nome, html in telas.items():
            pagina, erros, url = navegador.new_page(), [], f"{ORIGEM}/{nome}"
            no_console, na_excecao = _coletor(erros)
            pagina.on("console", no_console)
            pagina.on("pageerror", na_excecao)
            pagina.route("**/*", _servidor(html, url))
            pagina.goto(url, wait_until="load")
            pagina.wait_for_timeout(ESPERA_MS)
            out[nome] = [e for e in erros if not permitido(e)]
            pagina.close()
        navegador.close()
    return out


def _instalar_chromium() -> bool:
    p = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium-headless-shell"], capture_output=True,
                       timeout=INSTALAR_S)
    return p.returncode == 0


def navegar_playwright(telas: dict[str, str]) -> dict[str, list[str]] | None:
    """{tela: erros de JS fora da allowlist}; instala o Chromium headless se faltar; None se mesmo assim não abre."""
    with contextlib.suppress(Exception):
        return _navegar(telas)
    with contextlib.suppress(Exception):
        if _instalar_chromium():
            return _navegar(telas)
    return None


def _telas_tocadas(wt: Path, base: str) -> list[str]:
    mudou = set(subprocess.run(["git", "diff", "--name-only", base], cwd=wt, capture_output=True, text=True).stdout.split())
    mudou |= set(subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=wt, capture_output=True,
                                text=True).stdout.split())
    todas = sorted(str(p.relative_to(wt)) for p in (wt / "circulo").glob("*.html"))
    return todas if mudou & TODAS else [t for t in todas if t in mudou]


def _na_base(wt: Path, base: str, caminho: str) -> str:
    p = subprocess.run(["git", "show", f"{base}:{caminho}"], cwd=wt, capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else ""


def verificar(wt: Path, base: str, navegar: Navegar = navegar_playwright) -> list[str]:
    """Os problemas que o PR traz às telas que tocou, comparados com a base; [] = aprovado."""
    wt = Path(wt)
    telas = _telas_tocadas(wt, base)
    if not telas:
        return []
    pr = {t: (wt / t).read_text(encoding="utf-8") for t in telas}
    antes = {t: _na_base(wt, base, t) for t in telas}
    problemas = []
    for t in telas:
        novos = [i for i in ids_quebrados(pr[t]) if i not in ids_quebrados(antes[t])]
        if novos:
            problemas.append(f"{Path(t).name}: o JS usa id que não existe no HTML: " + ", ".join(f"#{i}" for i in novos))
    nomes = {Path(t).stem: t for t in telas}
    erros_pr = navegar({n: pr[t] for n, t in nomes.items()})
    if erros_pr is None:
        return problemas + [f"{Path(t).name}: {SEM_NAVEGADOR}" for t in telas]
    erros_base = navegar({n: antes[t] for n, t in nomes.items() if antes[t]}) if erros_pr and any(erros_pr.values()) else None
    for n, t in nomes.items():
        ja = set((erros_base or {}).get(n, []))
        novos = [e for e in erros_pr.get(n, []) if e not in ja and not permitido(e)]
        if novos:
            problemas.append(f"{Path(t).name}: erro de JS que a base não tem: " + "; ".join(novos)[:300])
    return problemas

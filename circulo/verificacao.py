"""Verificação de ponta a ponta do painel, com um mapa de funcionalidades (Lauren Tan: "verification skills").

Testes de unidade não abrem as telas, e foi assim que uma faixa vazia apareceu no painel do loop sem nenhum teste
falhar. Aqui um comando fixo e reproduzível (`circulo verificar`, e o teste tests/test_verificacao.py, que o CI e a
validação do corpo rodam) sobe o painel num banco novo e confere o MAPA:

- cada tela abre (200) e mostra o que precisa mostrar;
- todo elemento que o JavaScript da tela procura por id (`$("#x")`, `getElementById("x")`) existe na página;
- toda tela segue o caminho único para esconder elementos (`[hidden]{display:none!important}`), para nenhum CSS
  reabrir o que o código escondeu;
- cada API responde com as chaves de que as telas dependem; /metrics sai no formato do Prometheus.

Com o Playwright disponível (CIRCULO_E2E_NAVEGADOR=1), também abre cada tela num navegador de verdade e falha com
qualquer erro de JavaScript.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import urllib.request
from importlib import resources
from pathlib import Path

REGRA_HIDDEN = "[hidden]{display:none!important}"

# o mapa de funcionalidades: tela → arquivo e o que ela tem de mostrar
TELAS = (
    {"rota": "/", "arquivo": "home.html", "contem": ["Nova missão", "Equipe ao vivo", "Rastros e SLOs", "Integrações"]},
    {"rota": "/missao/{zero}", "arquivo": "painel.html", "contem": ["Pausar o loop", "Saúde e estado", "Equipe ao vivo", "Segurança e confiança", "Memória do time", "Consumo de tokens", "Aluno do Jev", "Médico do loop"]},
    {"rota": "/equipe", "arquivo": "equipe.html", "contem": ["Equipe ao vivo", "#equipe", "Quadro de entregas"]},
    {"rota": "/fluxo", "arquivo": "fluxo.html", "contem": ["Bastidores do giro", "Raias do giro", "Laboratório"]},
    {"rota": "/rastros", "arquivo": "rastros.html", "contem": ["Seguir o fio", "Objetivos de serviço", "Sinais de ouro"]},
    {"rota": "/integracoes", "arquivo": "integracoes.html", "contem": ["Integrações", "Cadastrar outra integração"]},
    {"rota": "/aprovacoes", "arquivo": "aprovacoes.html", "contem": ["Precisa de você", "Nada esperando você"]},
)
APIS = (
    ("/api/projetos", ["projetos", "loop", "versao"]),
    ("/api/estado", ["loop", "orcamento"]),
    ("/api/confianca", ["veredito", "checks"]),
    ("/api/fluxo", ["agora", "agentes", "jev"]),
    ("/api/equipe", ["membros", "quadro", "grupos"]),
    ("/api/memoria", ["total", "por_tipo", "usos_24h"]),
    ("/api/consumo", ["modo", "por_dia", "por_papel", "sugestao_limite"]),
    ("/api/aluno", ["perguntas", "resumo", "criterios"]),
    ("/api/aprovacoes", ["total", "urgentes", "itens"]),
    ("/api/medico", ["abertos", "acoes_24h", "precisao"]),
    ("/api/observabilidade", ["sinais", "slos", "rastros"]),
    ("/api/loop", None),
)
ID_JS = re.compile(r"""(?:\$\(\s*["']#([\w-]+)["']\s*\)|getElementById\(\s*["']([\w-]+)["']\s*\)|querySelector\(\s*["']#([\w-]+)["']\s*\))""")


def ids_quebrados(html: str) -> list[str]:
    """Ids que o script procura e que não existem em lugar nenhum da página (nem nos templates que ela gera)."""
    pedidos = {a or b or c for a, b, c in ID_JS.findall(html)}
    return sorted(i for i in pedidos if f'id="{i}"' not in html and f"id='{i}'" not in html)


def verificar_html(nome: str, html: str) -> list[str]:
    erros = [f"{nome}: o script procura #{i}, que não existe na página" for i in ids_quebrados(html)]
    if REGRA_HIDDEN not in html.replace(" ", ""):
        erros.append(f"{nome}: falta a regra única {REGRA_HIDDEN} (um CSS pode reabrir o que o código escondeu)")
    return erros


def _get(url: str) -> tuple[int, str, str]:
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, "", ""


def verificar(db_path: str | None = None, navegador: bool | None = None) -> dict:
    """Sobe o painel (num banco novo, se nenhum for dado) e confere o mapa. Devolve {"ok", "erros", "conferidos"}."""
    from .painel import serve
    from .projects import kit_project_id
    from .state import Store
    tmp = None
    if db_path is None:
        tmp = tempfile.mkdtemp(prefix="circulo-verificar-")
        db_path = str(Path(tmp) / "circulo.db")
    srv = serve(db_path, port=0, background=True)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    erros, conferidos = [], 0
    try:
        zero = kit_project_id(Store(db_path), "circulo")
        for t in TELAS:
            rota = t["rota"].replace("{zero}", str(zero))
            fonte = resources.files("circulo").joinpath(t["arquivo"]).read_text(encoding="utf-8")
            erros += verificar_html(t["arquivo"], fonte)
            code, _, corpo = _get(base + rota)
            conferidos += 1
            if code != 200:
                erros.append(f"{rota}: respondeu {code}")
                continue
            erros += [f"{rota}: não mostra “{x}”" for x in t["contem"] if x not in corpo]
        for rota, chaves in APIS:
            code, tipo, corpo = _get(base + rota)
            conferidos += 1
            if code != 200:
                erros.append(f"{rota}: respondeu {code}")
                continue
            try:
                d = json.loads(corpo)
            except ValueError:
                erros.append(f"{rota}: não devolveu JSON")
                continue
            erros += [f"{rota}: falta a chave “{k}”" for k in (chaves or []) if k not in d]
        code, tipo, corpo = _get(base + "/metrics")
        conferidos += 1
        if code != 200 or not tipo.startswith("text/plain") or "circulo_info" not in corpo:
            erros.append("/metrics: fora do formato do Prometheus")
        usar = navegador if navegador is not None else os.environ.get("CIRCULO_E2E_NAVEGADOR") == "1"
        if usar:
            erros += _navegador(base, zero)
    finally:
        srv.shutdown()
    return {"ok": not erros, "erros": erros, "conferidos": conferidos}


def _navegador(base: str, zero: int) -> list[str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []
    erros = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for t in TELAS:
            rota = t["rota"].replace("{zero}", str(zero))
            pg = b.new_page()
            js: list[str] = []
            pg.on("pageerror", lambda e, js=js: js.append(str(e)))
            pg.goto(base + rota)
            pg.wait_for_timeout(1500)
            erros += [f"{rota}: erro de JavaScript: {e[:200]}" for e in js]
            pg.close()
        b.close()
    return erros


def main() -> int:
    r = verificar()
    for e in r["erros"]:
        print("✗", e)
    print(f"{'OK' if r['ok'] else 'FALHOU'}: {r['conferidos']} pontos do mapa conferidos, {len(r['erros'])} problema(s).")
    return 0 if r["ok"] else 1

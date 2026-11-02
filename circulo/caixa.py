"""Caixa de entrada por arquivo: um `.md` em `<dados>/caixa/` vira pedido, lido pelo próprio loop.

Por que existe (26/10): o banco foi corrompido por uma escrita direta no SQLite feita de fora (pela ponte do Mac)
enquanto o loop escrevia. Pedido de fora do painel nunca mais toca o banco: cai como arquivo, e o loop — o único
dono do banco — o transforma em evento no começo do giro. Serve a qualquer ferramenta (um script, o Claude, um
atalho do macOS, uma pasta sincronizada).

Formato do arquivo (texto puro, UTF-8):
    ---            (cabeçalho opcional, uma chave por linha)
    tipo: pedido | missao | referencia | resultado   (padrão: pedido — roteiro do loop; missao cria missão; referencia: URL de repo; resultado: `projeto; metrica; valor` por linha)
    projeto: 2                     (padrão: a missão do loop; um repositório cliente vira branch circulo/<pedido> nele)
    de: Ana                        (quem pediu; padrão: cassio — a Equipe ao vivo e o digest agrupam por ele)
    ---
    o texto do pedido, em uma ou várias linhas

Lido vai para `caixa/lidos/<data>-<nome>` com o id do evento no nome; inválido vai para `caixa/invalidos/`.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

PASTA = "caixa"
MAX_POR_GIRO = 20
MAX_TEXTO = 4000
MIN_TEXTO = 8


def _cabecalho(texto: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", texto, re.S)
    if not m:
        return {}, texto
    cab = {}
    for linha in m.group(1).splitlines():
        if ":" in linha:
            k, v = linha.split(":", 1)
            cab[k.strip().lower()] = v.strip()
    return cab, m.group(2)


def _repo_cliente(store, projeto: str) -> bool:
    return projeto.isdigit() and bool(store.one("SELECT 1 FROM projects WHERE id=? AND kit='repo'", (int(projeto),)))


def ler(store, data_dir: Path, agora: float | None = None) -> list[int]:
    """Transforma cada arquivo novo da caixa em evento. Devolve os ids dos eventos criados."""
    agora = agora or time.time()
    pasta = Path(data_dir) / PASTA
    if not pasta.is_dir():
        return []
    (pasta / "lidos").mkdir(exist_ok=True)
    (pasta / "invalidos").mkdir(exist_ok=True)
    ids = []
    loop_pid = (store.one("SELECT id FROM projects WHERE kit='circulo'") or {"id": None})["id"]
    for arq in sorted(p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() in (".md", ".txt"))[:MAX_POR_GIRO]:
        try:
            cab, corpo = _cabecalho(arq.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            shutil.move(str(arq), str(pasta / "invalidos" / arq.name))
            continue
        texto = corpo.strip()[:MAX_TEXTO]
        if len(texto) < MIN_TEXTO:
            shutil.move(str(arq), str(pasta / "invalidos" / arq.name))
            continue
        tipo = cab.get("tipo", "pedido").lower()
        if tipo == "referencia":                     # URL de repositório de referência: entra no rodízio de estudo diário
            urls = re.findall(r"https?://\S+", texto)
            lista = list(store.get("repos_referencia") or __import__("circulo.mercado", fromlist=["REPOS"]).REPOS)
            store.set("repos_referencia", lista + [u for u in urls if u not in lista])
            shutil.move(str(arq), str(pasta / "lidos" / f"{time.strftime('%Y-%m-%d_%H%M%S', time.localtime(agora))}-ref-{arq.name}"))
            continue
        if tipo == "resultado":                      # 1.76: resultado do lado do cliente reportado pela esteira/dogfooding (`projeto; metrica; valor` por linha)
            from . import resultado
            resultado.ler_resultados_da_caixa(store, texto, agora)
            shutil.move(str(arq), str(pasta / "lidos" / f"{time.strftime('%Y-%m-%d_%H%M%S', time.localtime(agora))}-res-{arq.name}"))
            continue
        if tipo == "missao":
            eid = store.enqueue("novo_projeto", {"pedido": texto, "at": agora, "origem": "caixa", "arquivo": arq.name})
        elif _repo_cliente(store, projeto := cab.get("projeto", "").strip()):
            from . import repo_cliente                 # repositório cliente: clone isolado numa branch circulo/<pedido>
            try:
                pedido = repo_cliente.receber(store, int(projeto), texto, Path(data_dir) / "fabrica")
            except (OSError, ValueError, subprocess.SubprocessError):
                shutil.move(str(arq), str(pasta / "invalidos" / arq.name))
                continue
            shutil.move(str(arq), str(pasta / "lidos" / f"{time.strftime('%Y-%m-%d_%H%M%S', time.localtime(agora))}-repo{pedido['id']}-{arq.name}"))
            continue
        else:
            payload = {"text": texto, "at": agora, "origem": "caixa", "arquivo": arq.name,
                       "projeto": int(projeto) if projeto.isdigit() else loop_pid, "de": cab.get("de", "")[:60] or None}
            eid = store.enqueue("mensagem", payload)
        ids.append(eid)
        shutil.move(str(arq), str(pasta / "lidos" / f"{time.strftime('%Y-%m-%d_%H%M%S', time.localtime(agora))}-ev{eid}-{arq.name}"))
    if ids:
        store.set("caixa_ultima", {"em": agora, "eventos": ids})
    return ids


QUEM_PADRAO = "cassio"


def quem_pediu(store, itens: list[int]) -> dict[int, str]:
    """Quem pediu cada item do roteiro: o `de:` do arquivo da caixa, achado pelo elo pedido:<evento> → item:<id>;
    pedido sem remetente é do dono (cassio). Só itens que vieram de pedido entram."""
    if not itens:
        return {}
    marcas = ",".join("?" * len(itens))
    out = {r["id"]: QUEM_PADRAO for r in store.q(f"SELECT id FROM roadmap WHERE origem='pedido_cassio' AND id IN ({marcas})", itens)}
    for r in store.q("SELECT CAST(substr(l.para, 6) AS INTEGER) item, json_extract(e.payload, '$.de') de FROM elos l "
                     "JOIN events e ON l.de = 'pedido:' || e.id WHERE l.relacao='virou_item' AND l.para IN "
                     f"({marcas})", [f"item:{i}" for i in itens]):
        if r["de"] and r["item"] in out:
            out[r["item"]] = r["de"]
    return out

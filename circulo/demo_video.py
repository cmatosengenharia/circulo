"""Demo de 30 s por produto (pedido #824): roteiro JSON versionado, mp4 fora do histórico do git.

1. `roteiro(landing)`: determinístico, a partir do HTML da landing. Cenas (abertura, até 3 benefícios, chamada) somam
   30 s e as legendas seguem o tipo `Caption` do @remotion/captions (text, startMs, endMs, timestampMs, confidence).
2. `gravar`: escreve docs/demo.json só quando a landing mudou (o JSON é a única entrada do vídeo, via `--props`).
3. `renderizar`: `remotion render` no projeto Remotion (remotion-create + remotion-captions) com `--props docs/demo.json`;
   o mp4 sai em data/ (ignorado pelo git). Sem Remotion o estado é 'depende de ambiente', com a instrução de instalação.
4. `publicar`: sobe o mp4 como asset de release (`gh release upload --clobber`); nunca é commitado.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

DURACAO_MS = 30_000
FPS = 30
COMPOSICAO = "Demo"
ENTRADA = "src/index.ts"
MAX_BENEFICIOS = 3
PALAVRAS_POR_LEGENDA = 7
LEGENDAS_POR_CENA = 3
CHAVES_CAPTION = {"text", "startMs", "endMs", "timestampMs", "confidence"}
INSTALAR = ("npx create-video@latest --blank <dir> && cd <dir> && npm i @remotion/captions; crie a composição "
            f"'{COMPOSICAO}' ({FPS} fps, {DURACAO_MS * FPS // 1000} frames) que lê cenas e captions das props")


class _Landing(HTMLParser):
    """Blocos de texto da landing na ordem: (tag, texto) para title, h1-h3, p, a, button."""
    TAGS = {"title", "h1", "h2", "h3", "p", "a", "button"}

    def __init__(self):
        super().__init__()
        self.blocos: list[tuple[str, str]] = []
        self._aberta: str | None = None
        self._texto: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.TAGS:
            self._fechar()
            self._aberta = tag

    def handle_endtag(self, tag):
        if tag == self._aberta:
            self._fechar()

    def handle_data(self, data):
        if self._aberta:
            self._texto.append(data)

    def _fechar(self):
        texto = re.sub(r"\s+", " ", "".join(self._texto)).strip()
        if self._aberta and texto:
            self.blocos.append((self._aberta, texto))
        self._aberta, self._texto = None, []


def _cenas(landing: str, produto: str) -> list[dict]:
    p = _Landing()
    p.feed(landing)
    p.close()
    titulo = next((t for tag, t in sorted(p.blocos, key=lambda b: b[0] != "h1") if tag in ("h1", "title")), produto)
    abertura = {"tipo": "abertura", "titulo": titulo, "texto": next((t for tag, t in p.blocos if tag == "p"), "")}
    beneficios = []
    for i, (tag, texto) in enumerate(p.blocos):
        if tag in ("h2", "h3") and len(beneficios) < MAX_BENEFICIOS:
            seguinte = p.blocos[i + 1] if i + 1 < len(p.blocos) else ("", "")
            beneficios.append({"tipo": "beneficio", "titulo": texto, "texto": seguinte[1] if seguinte[0] == "p" else ""})
    cta = [t for tag, t in p.blocos if tag in ("a", "button")]
    chamada = {"tipo": "chamada", "titulo": cta[-1] if cta else f"Conheça o {produto}", "texto": ""}
    return [abertura, *beneficios, chamada]


def _legendas(texto: str, inicio: int, fim: int) -> list[dict]:
    palavras = texto.split()[:PALAVRAS_POR_LEGENDA * LEGENDAS_POR_CENA]
    pedacos = [" ".join(palavras[i:i + PALAVRAS_POR_LEGENDA]) for i in range(0, len(palavras), PALAVRAS_POR_LEGENDA)]
    cortes = [inicio + (fim - inicio) * k // len(pedacos) for k in range(len(pedacos) + 1)]
    return [{"text": t, "startMs": a, "endMs": b, "timestampMs": a, "confidence": None}
            for t, a, b in zip(pedacos, cortes, cortes[1:], strict=False)]


def roteiro(landing: str, produto: str) -> dict:
    """Roteiro do vídeo: o mesmo HTML dá sempre o mesmo JSON (é o que o Remotion recebe em --props)."""
    cenas = _cenas(landing, produto)
    cortes = [DURACAO_MS * k // len(cenas) for k in range(len(cenas) + 1)]
    legendas = []
    for cena, a, b in zip(cenas, cortes, cortes[1:], strict=False):
        cena.update(inicioMs=a, duracaoMs=b - a)
        legendas += _legendas(f"{cena['titulo']} {cena['texto']}", a, b)
    return {"versao": 1, "produto": produto, "landingSha": hashlib.sha256(landing.encode()).hexdigest()[:12],
            "fps": FPS, "duracaoMs": DURACAO_MS, "cenas": cenas, "captions": legendas}


def problemas(r: dict) -> list[str]:
    """O que impede o roteiro de virar o vídeo de 30 s com legendas em ordem (lista vazia = válido)."""
    erros = []
    if r.get("duracaoMs") != DURACAO_MS or sum(c.get("duracaoMs", 0) for c in r.get("cenas", [])) != DURACAO_MS:
        erros.append(f"duração diferente de {DURACAO_MS} ms")
    legendas = r.get("captions") or []
    if not legendas:
        erros.append("sem legendas")
    erros += [f"legenda {i} fora do tipo Caption" for i, c in enumerate(legendas) if set(c) != CHAVES_CAPTION]
    erros += [f"legenda {i} com startMs >= endMs" for i, c in enumerate(legendas) if c.get("startMs", 0) >= c.get("endMs", 0)]
    erros += [f"legenda {i + 1} começa antes da anterior terminar" for i, (a, b) in enumerate(zip(legendas, legendas[1:], strict=False))
              if a.get("endMs", 0) > b.get("startMs", 0)]
    if legendas and legendas[-1].get("endMs", 0) > DURACAO_MS:
        erros.append("legenda passa do fim do vídeo")
    return erros


def caminho(raiz: Path) -> Path:
    return Path(raiz) / "docs" / "demo.json"


def gravar(raiz: Path, landing: str, produto: str) -> bool:
    """Escreve docs/demo.json se a landing mudou; devolve se escreveu."""
    destino = caminho(raiz)
    novo = json.dumps(roteiro(landing, produto), ensure_ascii=False, indent=2) + "\n"
    if destino.exists() and destino.read_text(encoding="utf-8") == novo:
        return False
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(novo, encoding="utf-8")
    return True


def renderizar(raiz: Path, projeto: Path, executar=subprocess.run, saida: Path | None = None) -> dict:
    """mp4 em data/ (fora do git) a partir de docs/demo.json; sem o Remotion do projeto, 'depende de ambiente'."""
    remotion = Path(projeto) / "node_modules" / ".bin" / "remotion"
    if not remotion.exists():
        return {"estado": "depende de ambiente", "instrucao": INSTALAR}
    saida = Path(saida or Path(raiz) / "data" / "demo.mp4")
    saida.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(remotion), "render", ENTRADA, COMPOSICAO, str(saida), "--props", str(caminho(raiz))]
    feito = executar(cmd, cwd=Path(projeto), capture_output=True, text=True)
    if feito.returncode != 0 or not saida.exists():
        return {"estado": "falhou", "erro": (feito.stderr or "")[-500:]}
    return {"estado": "renderizado", "mp4": str(saida)}


def publicar(mp4: Path, tag: str, executar=subprocess.run) -> dict:
    """Asset de release (sem limite total de tamanho nem banda); cria a release se ainda não existe."""
    feito = executar(["gh", "release", "upload", tag, str(mp4), "--clobber"], capture_output=True, text=True)
    if feito.returncode != 0:
        feito = executar(["gh", "release", "create", tag, str(mp4), "--title", f"Demo {tag}", "--notes", "Vídeo de demonstração (30 s)."],
                         capture_output=True, text=True)
    return {"estado": "publicado" if feito.returncode == 0 else "falhou", "tag": tag}


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(prog="python -m circulo.demo_video", description=__doc__.splitlines()[0])
    ap.add_argument("landing", type=Path)
    ap.add_argument("produto")
    ap.add_argument("--raiz", type=Path, default=Path.cwd())
    ap.add_argument("--remotion", type=Path, help="projeto Remotion com a composição Demo")
    ap.add_argument("--release", help="tag da release que recebe o mp4")
    a = ap.parse_args(argv)
    res = {"mudou": gravar(a.raiz, a.landing.read_text(encoding="utf-8"), a.produto)}
    if res["mudou"] and a.remotion:
        res.update(renderizar(a.raiz, a.remotion))
        if res.get("estado") == "renderizado" and a.release:
            res["release"] = publicar(Path(res["mp4"]), a.release)
    print(json.dumps(res, ensure_ascii=False))
    return res


if __name__ == "__main__":
    main()

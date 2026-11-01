"""Demo de 30 s por produto: o roteiro JSON (docs/demo.json) é a única entrada do vídeo e é versionado; o mp4 é
renderizado pelo Remotion fora do histórico do git e sai como asset de release. Sem Remotion: 'depende de ambiente'."""
import json
import subprocess
from pathlib import Path

import pytest

from circulo import demo_video

RAIZ = Path(__file__).resolve().parent.parent

LANDING = """<!doctype html><html><head><title>Fotolead: leads para fotógrafos</title></head><body>
<h1>Fotolead</h1><p>Transforme seguidores do Instagram em clientes.</p>
<h2>Agenda cheia</h2><p>Receba pedidos de orçamento direto no WhatsApp.</p>
<h2>Sem planilha</h2><p>Cada contato entra organizado.</p>
<h2>Prova social</h2><p>Mais de 300 fotógrafos já usam.</p>
<a class="cta" href="#">Quero meus leads</a></body></html>"""


def _remotion_simulado(tmp_path: Path) -> Path:
    projeto = tmp_path / "remotion"
    (projeto / "node_modules" / ".bin").mkdir(parents=True)
    (projeto / "node_modules" / ".bin" / "remotion").write_text("#!/bin/sh\n")
    return projeto


@pytest.mark.parametrize("landing", [LANDING, "<h1>Só título</h1>", "", "<p>" + "palavra " * 400 + "</p>"])
def test_roteiro_tem_30_s_e_legendas_caption_ordenadas(landing):
    r = demo_video.roteiro(landing, "fotolead")
    assert demo_video.problemas(r) == []
    assert r["duracaoMs"] == 30_000
    assert sum(c["duracaoMs"] for c in r["cenas"]) == 30_000
    legendas = r["captions"]
    assert legendas and legendas[0]["startMs"] == 0 and legendas[-1]["endMs"] == 30_000
    for c in legendas:
        assert set(c) == {"text", "startMs", "endMs", "timestampMs", "confidence"} and c["startMs"] < c["endMs"]
    assert all(a["endMs"] <= b["startMs"] for a, b in zip(legendas, legendas[1:], strict=False))


def test_roteiro_vem_da_landing_e_e_deterministico():
    r = demo_video.roteiro(LANDING, "fotolead")
    textos = " ".join(c["text"] for c in r["captions"])
    assert "Fotolead" in textos and "Agenda cheia" in textos and "Quero meus leads" in textos
    assert r == demo_video.roteiro(LANDING, "fotolead")


def test_gravar_so_reescreve_quando_a_landing_muda(tmp_path):
    assert demo_video.gravar(tmp_path, LANDING, "fotolead") is True
    destino = tmp_path / "docs" / "demo.json"
    assert demo_video.problemas(json.loads(destino.read_text(encoding="utf-8"))) == []
    assert demo_video.gravar(tmp_path, LANDING, "fotolead") is False
    assert demo_video.gravar(tmp_path, LANDING.replace("Sem planilha", "Sem retrabalho"), "fotolead") is True
    assert "Sem retrabalho" in destino.read_text(encoding="utf-8")


def test_problemas_pega_legenda_fora_de_ordem_e_duracao_errada():
    r = demo_video.roteiro(LANDING, "fotolead")
    r["captions"][0], r["captions"][1] = r["captions"][1], r["captions"][0]
    r["duracaoMs"] = 31_000
    assert len(demo_video.problemas(r)) >= 2


def test_sem_remotion_o_render_depende_de_ambiente_com_a_instrucao(tmp_path):
    chamadas = []
    res = demo_video.renderizar(tmp_path, tmp_path / "nao-existe", executar=lambda *a, **k: chamadas.append(a))
    assert res["estado"] == "depende de ambiente" and "npx create-video" in res["instrucao"]
    assert chamadas == []


def test_remotion_simulado_renderiza_com_props_do_roteiro_fora_do_git(tmp_path):
    projeto = _remotion_simulado(tmp_path)
    demo_video.gravar(tmp_path, LANDING, "fotolead")
    chamadas = []

    def executar(cmd, **kw):
        chamadas.append((cmd, kw))
        Path(cmd[cmd.index("Demo") + 1]).write_bytes(b"mp4")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    res = demo_video.renderizar(tmp_path, projeto, executar=executar)
    assert res["estado"] == "renderizado"
    cmd, kw = chamadas[0]
    assert cmd[cmd.index("--props") + 1] == str(tmp_path / "docs" / "demo.json") and kw["cwd"] == projeto
    mp4 = Path(res["mp4"])
    assert mp4.exists() and "docs" not in mp4.relative_to(tmp_path).parts


def test_publicar_sobe_o_mp4_como_asset_de_release(tmp_path):
    mp4 = tmp_path / "demo.mp4"
    mp4.write_bytes(b"mp4")
    chamadas = []
    demo_video.publicar(mp4, "demo-fotolead", executar=lambda cmd, **k: chamadas.append(cmd)
                        or subprocess.CompletedProcess(cmd, 0, "", ""))
    assert chamadas[0][:3] == ["gh", "release", "upload"] and str(mp4) in chamadas[0] and "--clobber" in chamadas[0]


def test_nenhum_mp4_entra_no_historico_do_git():
    ignorados = (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "*.mp4" in ignorados
    assert not list((RAIZ / "docs").glob("*.mp4"))

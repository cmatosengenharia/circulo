"""Tema único: as cinco telas usam os mesmos tokens, os contrastes cumprem o mínimo e o estado nunca é só cor."""
import re
from pathlib import Path

import pytest

from circulo import tema

PASTA = Path(tema.__file__).parent


def test_contrastes_dos_dois_modos_cumprem_o_minimo():
    assert tema.conferir() == []                                  # texto >= 4,5:1; bordas e marcas >= 3:1


def test_contraste_conhecido():
    assert tema.contraste("#000000", "#FFFFFF") == pytest.approx(21.0)


@pytest.mark.parametrize("nome", tema.PAGINAS)
def test_pagina_ja_esta_no_tema_e_o_tema_e_idempotente(nome):
    html = (PASTA / nome).read_text(encoding="utf-8")
    assert tema.aplicar(html) == html                              # rodar `python -m circulo.tema` não muda nada
    assert tema.TOKENS.split("\n")[0].split("{", 1)[1][:40] in html
    assert html.count(tema.INI) == 1 and f"--border:{tema.CLARO['--border']}" in html
    assert html.count(tema.NAV_INI) == 1 and 'id="navTopo"' in html          # o menu de cima, igual em todas


@pytest.mark.parametrize("nome", tema.PAGINAS)
def test_sem_cor_antiga_fora_dos_tokens(nome):
    html = (PASTA / nome).read_text(encoding="utf-8")
    for antiga in ("#B7791F", "#1C8C6E", "#C0392B", "#9AA6B2", "#C5CDD5", "#6F8FA6"):
        assert antiga not in html, antiga


def test_chips_e_botoes_tem_pista_alem_da_cor():
    painel = (PASTA / "painel.html").read_text(encoding="utf-8")
    assert ":focus-visible{outline:2px solid var(--accent)" in painel   # foco visível (anel do Primer)
    assert ".btn:disabled" in painel and "dashed" in painel       # desativado se distingue sem cor
    assert re.search(r'\.chip\.[\w-]+::before\{content:"[✓✕!◆]"', painel)   # glifo por tom do chip
    fluxo = (PASTA / "fluxo.html").read_text(encoding="utf-8")
    assert "raiasSvg" in fluxo and 'id="svg"' not in fluxo      # o anel animado saiu daqui (1.36.0): a Equipe ao vivo mostra quem está com a bola


def test_tokens_sao_os_primitives_do_primer_e_sem_fonte_externa():
    """1.39.0: o sistema de design é o Círculo sobre o Primer (GitHub): canvas, fg, done, attention, success, danger."""
    assert tema.CLARO["--bg"] == "#f6f8fa" and tema.ESCURO["--bg"] == "#0d1117" and tema.CLARO["--ink"] == "#1f2328"
    assert tema.CLARO["--primary"] == "#1f883d" and tema.CLARO["--accent"] == "#0969da" and tema.CLARO["--jev"] == "#8250df"
    for nome in tema.PAGINAS:
        html = (PASTA / nome).read_text(encoding="utf-8")
        assert "fonts.googleapis" not in html and "--r-sm:6px;--r-lg:12px" in html, nome   # tipografia de sistema, raio do Primer
    assert "Primer" in (PASTA / "DESIGN.md").read_text(encoding="utf-8")
    assert "DESIGN.md" in (PASTA / "self_dev.py").read_text(encoding="utf-8")       # o Desenvolvedor lê as regras ao mexer em tela

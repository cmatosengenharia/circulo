"""Validador por tela (circulo/validador_telas.py): depois do Developer e antes do PR seguir, cada tela que o diff toca é
conferida contra a base. PR que remove um id que o JS usa ou que faz a tela lançar erro de JS é reprovado; PR sem
mudança de frontend nunca é (0 falso positivo: nada é aberto, nada é comparado)."""
import subprocess
from pathlib import Path

import pytest

from circulo import validador, validador_telas

PACOTE = Path(__file__).resolve().parents[1] / "circulo"
TELA = ('<!doctype html><html><body><h1 id="titulo">x</h1><ul id="lista"></ul>\n'
        '<script>const $ = s => document.querySelector(s);\n'
        '$("#lista").innerHTML = \'<li id="novo">a</li>\'; document.getElementById("titulo").textContent = "ok";\n'
        '$("#novo").hidden = false;</script></body></html>\n')


def _git(wt, *a):
    return subprocess.run(["git", *a], cwd=wt, check=True, capture_output=True, text=True).stdout.strip()


def _repo(tmp_path):
    wt = tmp_path / "wt"
    (wt / "circulo").mkdir(parents=True)
    _git(wt, "init", "-q")
    _git(wt, "config", "user.email", "t@t")
    _git(wt, "config", "user.name", "t")
    (wt / "circulo" / "painel.html").write_text(TELA)
    (wt / "circulo" / "app.py").write_text("x = 1\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-qm", "base")
    return wt, _git(wt, "rev-parse", "HEAD")


def test_ids_que_o_js_usa_e_o_html_nao_tem():
    assert validador_telas.ids_quebrados(TELA) == []                         # id criado pelo próprio JS conta
    assert validador_telas.ids_quebrados(TELA.replace(' id="titulo"', "")) == ["titulo"]
    assert validador_telas.ids_quebrados(TELA.replace(' id="lista"', "")) == ["lista"]


def test_nenhuma_tela_de_hoje_tem_id_quebrado():
    quebrados = {p.name: q for p in PACOTE.glob("*.html") if (q := validador_telas.ids_quebrados(p.read_text(encoding="utf-8")))}
    assert not quebrados, quebrados


def test_pr_fixture_que_remove_um_id_e_reprovado(tmp_path, circle):
    wt, base = _repo(tmp_path)
    (wt / "circulo" / "painel.html").write_text(TELA.replace(' id="titulo"', ""))
    problemas = validador_telas.verificar(wt, base, navegar=lambda telas: {n: [] for n in telas})
    assert len(problemas) == 1 and "painel.html" in problemas[0] and "#titulo" in problemas[0]
    v = validador.revisar_pr(circle.ctx, wt, base, {"id": 1, "titulo": "x"},
                             chamar=lambda s, p: '{"aprovado": true, "problemas": [], "risco": "baixo"}')
    assert v["aprovado"] is False and any("#titulo" in p for p in v["problemas"])


def test_pr_fixture_que_lanca_excecao_e_reprovado_e_o_ruido_da_base_nao_conta(tmp_path):
    wt, base = _repo(tmp_path)
    (wt / "circulo" / "painel.html").write_text(TELA.replace("</script>", 'throw new Error("quebrou");</script>'))

    def navegador(telas):                     # o que o Chromium devolve: o 404 do favicon também aparece na base
        return {nome: ["console: Failed to load resource: 404"] + (["pageerror: Error: quebrou"] if "throw" in html else [])
                for nome, html in telas.items()}
    problemas = validador_telas.verificar(wt, base, navegar=navegador)
    assert problemas == ["painel.html: erro de JS que a base não tem: pageerror: Error: quebrou"]


def test_pr_sem_frontend_nao_abre_navegador_nem_reprova(tmp_path):
    wt, base = _repo(tmp_path)
    (wt / "circulo" / "app.py").write_text("x = 2\n")
    abertas = []
    assert validador_telas.verificar(wt, base, navegar=lambda telas: abertas.append(telas)) == []
    assert abertas == []


def test_tela_tocada_sem_navegador_reprova_com_o_motivo_e_allowlist_e_explicita(tmp_path):
    """Sem Playwright/Chromium não há como provar que a tela não lança erro: o PR que toca tela não passa calado."""
    wt, base = _repo(tmp_path)
    (wt / "circulo" / "painel.html").write_text(TELA.replace("</script>", 'throw new Error("quebrou");</script>'))
    problemas = validador_telas.verificar(wt, base, navegar=lambda telas: None)
    assert problemas == ["painel.html: não consegui abrir a tela no navegador headless (Playwright/Chromium)"]
    assert validador_telas.permitido("console: Failed to load resource: the server responded with a status of 404")
    assert not validador_telas.permitido("pageerror: TypeError: Cannot read properties of null")


def test_playwright_de_verdade_reprova_a_excecao_do_pr_fixture(tmp_path):
    """O listener de pageerror do Chromium real pega a exceção do PR fixture; o Chromium é instalado se faltar."""
    pytest.importorskip("playwright.sync_api")                  # dependência de dev: o CI a tem
    wt, base = _repo(tmp_path)
    (wt / "circulo" / "painel.html").write_text(TELA.replace("</script>", 'throw new Error("quebrou");</script>'))
    assert validador_telas.verificar(wt, base) == ["painel.html: erro de JS que a base não tem: pageerror: quebrou"]
    (wt / "circulo" / "painel.html").write_text(TELA.replace("ok", "ok!"))
    assert validador_telas.verificar(wt, base) == []           # mudança de tela sem erro não é falso positivo

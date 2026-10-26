"""Catálogo de links da empresa por assunto: colo o link com um rótulo curto e acho em segundos, por palavra (FTS5,
com prefixo e sem acento) ou por significado (Graft). A busca fica num atalho do console (tecla `/` no menu do topo)."""
import json
import urllib.error
import urllib.request

import pytest

from circulo import graft, tema
from circulo.links import Links, colar
from circulo.painel import serve
from circulo.state import Store


@pytest.fixture
def links():
    return Links(Store(":memory:"))


def test_colo_com_rotulo_e_acho_por_palavra_por_prefixo_e_sem_acento(links):
    links.guardar("https://wiki.empresa/runbook-connect", "runbook deploy Amazon Connect", "migração Blip")
    links.guardar("https://grafana.empresa/d/custos", "custos da nuvem", "tribo")
    assert [h["url"] for h in links.buscar("deploy")] == ["https://wiki.empresa/runbook-connect"]
    assert links.buscar("conn")[0]["rotulo"] == "runbook deploy Amazon Connect"      # digitando: prefixo já acha
    assert links.buscar("migracao")[0]["assunto"] == "migração Blip"                   # sem acento acha com acento
    assert links.buscar("custos nuvem")[0]["url"] == "https://grafana.empresa/d/custos"
    assert links.buscar("") == [] and links.buscar("inexistente") == []


def test_mesmo_link_colado_de_novo_atualiza_o_rotulo_sem_duplicar(links):
    a = links.guardar("https://x.empresa/a", "rótulo velho")
    b = links.guardar("https://x.empresa/a", "rótulo novo", "squad")
    assert a["id"] == b["id"] and links.buscar("velho") == []
    assert links.buscar("novo")[0]["assunto"] == "squad"


def test_so_aceita_http_e_rotulo_curto(links):
    for url in ("javascript:alert(1)", "ftp://x/y", "wiki sem esquema", ""):
        with pytest.raises(ValueError):
            links.guardar(url, "x")
    with pytest.raises(ValueError):
        links.guardar("https://x.empresa", "")
    assert len(links.guardar("https://x.empresa", "r" * 500)["rotulo"]) <= 120


def test_colar_separa_link_rotulo_e_assunto():
    assert colar("https://wiki.empresa/a  runbook do deploy #migração blip") == ("https://wiki.empresa/a", "runbook do deploy", "migração blip")
    assert colar("runbook do deploy https://wiki.empresa/a") == ("https://wiki.empresa/a", "runbook do deploy", "")
    assert colar("só uma busca") is None


def test_por_significado_o_graft_acha_o_que_a_palavra_nao_acha(links, monkeypatch):
    """Sem palavra em comum ("quanto gastamos na AWS" × "custos da nuvem"), o FTS não acha; o Graft acha pelo vetor."""
    nos = {}
    monkeypatch.setattr(links, "graft", True)
    monkeypatch.setattr(graft, "inserir", lambda tipo, ref, titulo, texto, resultado=None, extras=None: nos.setdefault(graft.chave(tipo, ref), "ab12cd34"))
    monkeypatch.setattr(graft, "recuperar", lambda texto, k=12: [
        {"id_hex": "ff00ff00", "title": "lição qualquer", "score": 0.05, "tipo": "licao", "ref": "3"},      # não é link: fica fora
        {"id_hex": "ab12cd34", "title": "custos da nuvem", "score": 0.03, "tipo": "link", "ref": "1"}])
    links.guardar("https://grafana.empresa/d/custos", "custos da nuvem", "tribo")
    assert "circulo:link:1" in nos
    achados = links.buscar("quanto gastamos na AWS", sentido=True)
    assert [(h["url"], h["via"]) for h in achados] == [("https://grafana.empresa/d/custos", "graft")]
    assert links.buscar("quanto gastamos na AWS", sentido=False) == []          # só palavra: rápido, sem o daemon
    assert links.buscar("custos", sentido=True)[0]["via"] == "ambos"


def test_atalho_de_busca_no_console_em_toda_tela():
    assert 'id="linkBusca"' in tema.NAV and "/api/links" in tema.NAV and 'e.key==="/"' in tema.NAV
    for nome in tema.PAGINAS:
        assert tema.NAV in (tema.Path(tema.__file__).parent / nome).read_text(encoding="utf-8")


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"X-Circulo": "1", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_api_cola_e_busca(tmp_path):
    srv = serve(tmp_path / "circulo.db", port=0, background=True)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert _post(base + "/api/links", {"texto": "https://wiki.empresa/a runbook do deploy #migração"})[0] == 200
        assert _post(base + "/api/links", {"texto": "javascript:alert(1) x"})[0] == 400
        with urllib.request.urlopen(base + "/api/links?q=runb", timeout=5) as r:
            achados = json.loads(r.read())["links"]
        assert [(h["url"], h["assunto"]) for h in achados] == [("https://wiki.empresa/a", "migração")]
    finally:
        srv.shutdown()

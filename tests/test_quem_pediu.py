"""Multiusuário leve: o campo `de:` do arquivo da caixa registra quem pediu; a Equipe ao vivo mostra os pedidos por pessoa
e o digest semanal agrupa as entregas por quem pediu. Critério: 2 remetentes."""
import json
import time
import urllib.request

from circulo import caixa, digest_semanal, equipe


def _dois_remetentes(circle, tmp_path):
    s = circle.store
    pasta = tmp_path / "caixa"
    pasta.mkdir()
    (pasta / "a.md").write_text("---\nde: Ana\n---\nExportar o relatório mensal em CSV.\n", encoding="utf-8")
    (pasta / "b.md").write_text("---\nde: Bruno\n---\nFiltro por data na tela de lançamentos.\n", encoding="utf-8")
    (pasta / "c.md").write_text("Pedido sem remetente no cabeçalho do arquivo.\n", encoding="utf-8")
    ids = caixa.ler(s, tmp_path, agora=time.time())
    assert [json.loads(s.one("SELECT payload FROM events WHERE id=?", (i,))["payload"]).get("de") for i in ids] == ["Ana", "Bruno", None]
    for _ in range(3):
        circle.tick()
    itens = {r["titulo"][:6]: r["id"] for r in s.q("SELECT id, titulo FROM roadmap WHERE origem='pedido_cassio'")}
    return itens["Export"], itens["Filtro"], itens["Pedido"]


def test_de_na_caixa_vira_quem_pediu_do_item(circle, tmp_path):
    a, b, c = _dois_remetentes(circle, tmp_path)
    assert caixa.quem_pediu(circle.store, [a, b, c]) == {a: "Ana", b: "Bruno", c: "cassio"}


def test_equipe_ao_vivo_mostra_os_pedidos_por_pessoa(circle, tmp_path):
    a, b, c = _dois_remetentes(circle, tmp_path)
    por = {p["de"]: p for p in equipe.retrato(circle.store)["por_pessoa"]}
    assert set(por) == {"Ana", "Bruno", "cassio"}
    assert por["Ana"]["itens"] == [a] and por["Bruno"]["itens"] == [b] and c in por["cassio"]["itens"]   # o banco novo já traz pedidos semeados do dono
    assert por["Ana"]["abertos"] == 1 and por["Ana"]["feitos"] == 0
    from circulo.painel import serve
    srv = serve(circle.store.path, port=0, background=True)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/equipe", timeout=5) as r:
            api = {p["de"]: p["itens"] for p in json.loads(r.read())["por_pessoa"]}
    finally:
        srv.shutdown()
    assert api["Ana"] == [a] and api["Bruno"] == [b]                          # a Equipe ao vivo recebe pela API


def test_digest_semanal_agrupa_as_entregas_por_quem_pediu(circle, tmp_path):
    s = circle.store
    a, b, _ = _dois_remetentes(circle, tmp_path)
    agora = time.time()
    for n, item in ((901, a), (902, b), (903, a)):
        s.x("INSERT INTO prs(number,titulo,branch,status,item_id,created_at,updated_at) VALUES(?,?,?,'mergeado',?,?,?)",
            (n, f"PR {n}", f"b{n}", item, agora - 60, agora - 60))
    prs = digest_semanal.prs_da_semana(s, agora + 1)
    assert {p["number"]: p["por"] for p in prs} == {901: "Ana", 902: "Bruno", 903: "Ana"}
    linhas = digest_semanal.markdown(prs).splitlines()
    ana, bruno = linhas.index("### Ana (2)"), linhas.index("### Bruno (1)")
    assert ana < bruno
    assert [x[:9] for x in linhas[ana + 1:bruno] if x.startswith("- ")] == ["- **#901 ", "- **#903 "]
    assert any(x.startswith("- **#902 ") for x in linhas[bruno + 1:])

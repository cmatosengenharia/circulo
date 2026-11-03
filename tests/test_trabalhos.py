"""Catálogo de trabalhos candidatos (missão Vender resultado, item E): kv `catalogo_trabalhos` com os 5 trabalhos,
cada um com promessa em uma frase, valor do profissional substituído, capacidade medida pelo que existe em código e
proximidade de um cliente real; o Jev ranqueia (score) e o painel mostra."""
import json
import urllib.request

from circulo import norte, trabalhos
from circulo.painel import serve

CINCO = ("cortes_video", "fotografia_evento", "relatorio_metricas", "triagem_leads", "documentacao_tecnica")


def test_catalogo_tem_os_cinco_trabalhos_com_promessa_valor_capacidade_e_proximidade(circle):
    lista = trabalhos.catalogo(circle.store)
    assert tuple(t["nome"] for t in lista) == CINCO
    for t in lista:
        assert t["promessa"].count(".") == 1 and t["promessa"].endswith(".")          # uma frase
        vmin, vmax = t["valor_mes"]
        assert 0 < vmin < vmax                                                        # faixa R$/mês do profissional substituído
        assert 0.0 <= t["capacidade"] <= 1.0 and 0.0 <= t["proximidade"] <= 1.0
        assert t["pecas"] and t["cliente"]
    por_nome = {t["nome"]: t for t in lista}
    assert por_nome["fotografia_evento"]["capacidade"] == 0.0                          # nada disso existe em código
    assert por_nome["documentacao_tecnica"]["capacidade"] > por_nome["fotografia_evento"]["capacidade"]


def test_capacidade_vem_so_do_que_existe_em_codigo_e_nao_do_numero_escrito_no_kv(circle):
    s = circle.store
    s.set(trabalhos.KV, [{"nome": "x", "promessa": "P.", "valor_mes": [1000, 2000], "proximidade": 1.0, "cliente": "c",
                          "pecas": ["documentador", "modulo_que_nao_existe"], "capacidade": 1.0}])
    (t,) = trabalhos.catalogo(s)
    assert t["capacidade"] == 0.5                                                      # 1 das 2 peças existe; o 1.0 escrito não inflou


def test_jev_ranqueia_pelo_vigia_o_kv_guarda_o_score_e_o_painel_mostra(circle):
    s, dl = circle.store, circle.ctx.dl
    assert trabalhos.ranking(s) == []                                                  # antes do Vigia: nada ranqueado
    norte.cobrar(s, lambda *a: None, dl=dl)
    kv = s.get(trabalhos.KV)
    assert len(kv) == 5 and all(0 <= t["score"] <= 2 and t["por"] for t in kv)
    r = trabalhos.ranking(s)
    assert [t["score"] for t in r] == sorted((t["score"] for t in r), reverse=True)
    assert r[0]["nome"] != "fotografia_evento" and r[-1]["nome"] == "fotografia_evento"   # sem código e sem cliente fica por último
    srv = serve(s.path, port=0, background=True)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/api/norte", timeout=5) as resp:
            assert [t["nome"] for t in json.loads(resp.read())["trabalhos"]] == [t["nome"] for t in r]
    finally:
        srv.shutdown()
        srv.server_close()

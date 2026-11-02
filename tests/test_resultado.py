"""1.76 — Vender resultado, não ferramenta (ADR 0015): resultados do lado do cliente no Norte, classificação Jev
resultado/confiabilidade/ferramenta na cota de produto, PROMESSA.md do produto e a checagem de discurso de plataforma."""
from __future__ import annotations

import time

from circulo import norte, resultado, validador
from circulo.resultado import (classe_de, classificar, discurso_de_plataforma, ler_resultados_da_caixa, medir, ordenar_por_classe,
                               promessa, promessa_cumprida)


def _pedido(store, status: str, aberto_ha_h: float, entregue_apos_h: float = 1.0, agora: float | None = None) -> int:
    from circulo import repo_cliente
    repo_cliente._esquema(store)
    agora = agora or time.time()
    c = agora - aberto_ha_h * 3600
    return store.x("INSERT INTO pedidos_repo(projeto_id,texto,status,created_at,updated_at) VALUES(1,'x',?,?,?)", (status, c, c + entregue_apos_h * 3600))


def test_taxa_de_promessa_cumprida_conta_entregue_no_prazo_e_sem_humano(circle):
    s, agora = circle.store, time.time()
    assert promessa_cumprida(s, agora)["taxa"] is None                              # sem pedido: nada a medir
    _pedido(s, "entregue", 10, 2, agora)                                            # no prazo
    _pedido(s, "entregue", 100, 60, agora)                                          # entregue, mas 60 h > 48 h
    _pedido(s, "vermelho", 5, 1, agora)                                             # falhou
    _pedido(s, "aberto", 1, 0, agora)                                               # ainda dentro do prazo: conta como aberto, não como atraso
    pc = promessa_cumprida(s, agora)
    assert (pc["abertos"], pc["cumpridos"], pc["taxa"], pc["atrasados"]) == (4, 1, 0.25, 2)
    s.set("promessa_prazo_h", 72)
    assert promessa_cumprida(s, agora)["cumpridos"] == 2


def test_norte_ganha_tres_resultados_do_lado_do_cliente_com_meta(circle):
    s, agora = circle.store, time.time()
    _pedido(s, "entregue", 10, 2, agora)
    n = ler_resultados_da_caixa(s, "esteira; publicacoes; 2\nesteira; publicações; 1,0\nlixo\n", agora)
    assert n == 2
    m = medir(s, agora)
    assert m["promessa_cumprida"]["valor"] == 1.0 and m["promessa_cumprida"]["distancia"] == 0 and m["promessa_cumprida"]["lado"] == "cliente"
    assert m["pedidos_cliente_semana"]["valor"] == 1 and m["publicacoes_semana"]["valor"] == 3.0 and m["publicacoes_semana"]["distancia"] == 0
    todo = norte.medir(s, agora)
    assert {"promessa_cumprida", "pedidos_cliente_semana", "publicacoes_semana"} <= set(todo)
    assert len([k for k in todo if not k.startswith("_")]) == 9
    assert sum(1 for r in norte.resumo(s)["resultados"] if r.get("lado") == "cliente") == 3


def test_caixa_le_arquivo_tipo_resultado(circle, tmp_path):
    from circulo import caixa
    (tmp_path / "caixa").mkdir()
    (tmp_path / "caixa" / "semana.md").write_text("---\ntipo: resultado\n---\nesteira; publicacoes; 4\n", encoding="utf-8")
    assert caixa.ler(circle.store, tmp_path) == []
    assert medir(circle.store)["publicacoes_semana"]["valor"] == 4.0
    assert list((tmp_path / "caixa" / "lidos").glob("*-res-semana.md"))


def test_jev_classifica_resultado_confiabilidade_ferramenta_e_a_cota_ordena(circle):
    s, dl = circle.store, circle.ctx.dl
    itens = [{"id": 1, "titulo": "Refatorar o cache interno do planejador", "detalhe": ""},
             {"id": 2, "titulo": "Publicar os cortes do cliente no Instagram na cadência prometida", "detalhe": ""},
             {"id": 3, "titulo": "Retry e idempotência no worker para o pedido entregar no prazo sem humano", "detalhe": ""}]
    assert [classificar(dl, s, i) for i in itens] == ["ferramenta", "resultado", "confiabilidade"]
    assert classe_de(s, 2) == "resultado" and classe_de(s, 99) is None
    assert [i["id"] for i in ordenar_por_classe(s, itens)] == [2, 3, 1]
    assert [i["id"] for i in ordenar_por_classe(s, [{"id": 1}, {"id": 50}])] == [50, 1]      # sem classe = confiabilidade, antes de ferramenta
    assert resultado.evidencia_meta_trabalho_perdeu_prioridade(s)["classificados"] == 0     # nenhum dos 3 está pendente no roteiro


def test_item_de_produto_poe_resultado_antes_de_meta_trabalho(circle):
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    ferramenta = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,0,0)",
                     ("Refatorar o cache interno do planejador", "", "pedido_cassio", "pendente", "", 1, "ok"))
    res = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,0,0)",
              ("Publicar os cortes do cliente no YouTube toda semana", "", "pedido_cassio", "pendente", "", 2, "ok"))
    assert norte.item_de_produto(s)["id"] == ferramenta                                    # sem classe: a ordem do roteiro
    resultado.classificar_pendentes(circle.ctx.dl, s)
    assert norte.item_de_produto(s)["id"] == res                                           # classificado: resultado primeiro


def test_promessa_md_exige_os_cinco_campos(tmp_path):
    assert promessa(tmp_path) == {"existe": False, "campos_faltando": list(resultado.CAMPOS_PROMESSA), "valida": False}
    (tmp_path / "PROMESSA.md").write_text("# Promessa\n## Trabalho que substitui\neditor\n## Resultado prometido\n3 cortes\n", encoding="utf-8")
    p = promessa(tmp_path)
    assert p["existe"] and not p["valida"] and "cadência" in p["campos_faltando"]
    (tmp_path / "PROMESSA.md").write_text("## Trabalho que substitui\n## Resultado prometido\n## Cadência\n## Preço\n## O cliente nunca precisa\n", encoding="utf-8")
    assert promessa(tmp_path)["valida"]


def test_promessa_da_esteira_e_valida():
    from pathlib import Path
    esteira = Path(__file__).resolve().parents[2] / "esteira"
    if not (esteira / "PROMESSA.md").exists():
        import pytest
        pytest.skip("clone da esteira não está ao lado do loop")
    assert promessa(esteira)["valida"]


def test_discurso_de_plataforma_reprova_titulo_de_tecnologia_antes_do_resultado(circle, tmp_path):
    ruim = "# A plataforma de IA que edita seus vídeos\n## Seus vídeos publicados toda semana\n"
    bom = "# Seus vídeos publicados toda semana, sem você tocar em nada\n## Como a IA faz isso por trás da cortina\n"
    assert discurso_de_plataforma(ruim) and not discurso_de_plataforma(bom)
    assert discurso_de_plataforma("<h1>Ferramenta de cortes</h1>") and not discurso_de_plataforma("<title>3 cortes por semana no seu canal</title>")
    # dentro do Validador: linhas novas de uma landing
    import subprocess
    wt = tmp_path / "wt"
    wt.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=wt, check=True)
    (wt / "a.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], cwd=wt, check=True)
    (wt / "landing.html").write_text("<h1>Plataforma de IA para criadores</h1><h2>Cortes publicados toda semana</h2>", encoding="utf-8")
    v = validador.revisar_pr(circle.ctx, wt, "HEAD", {"id": 1, "titulo": "landing", "detalhe": ""}, chamar=lambda s, p: '{"aprovado": true, "problemas": []}')
    assert not v["aprovado"] and any("discurso de plataforma" in p for p in v["problemas"])


def test_pedido_que_esgota_as_tentativas_vira_licao_estrutural(circle, monkeypatch):
    from circulo import fabricante
    fab = fabricante.Fabricante(circle.ctx, agent=None)
    from circulo import repo_cliente
    repo_cliente._esquema(circle.store)
    pid = circle.store.x("INSERT INTO pedidos_repo(projeto_id,texto,status,created_at,updated_at) VALUES(1,'entregar cortes','aberto',0,0)")
    for _ in range(fabricante.MAX_TENTATIVAS):
        res = fab._vermelho({"id": pid}, fabricante._wip(circle.store, pid), "testes do cliente falham")
    assert res["esgotou"]
    lic = circle.store.one("SELECT classe, status FROM licoes WHERE ponto='fabrica:promessa'")
    assert lic and lic["classe"] == "estrutural"
    assert circle.store.one("SELECT 1 FROM roadmap WHERE titulo LIKE '%romessa não cumprida%' OR detalhe LIKE '%promessa não cumprida%'")

"""Prova de melhora por item mergeado (pergunta do conselho #57): antes (no planejamento) e depois (7 dias pós-merge)
da métrica do critério de sucesso, gravados na trilha. Item sem critério só ganha o lead time de PR mediano como
proxy marcado e contado à parte: ele mede a entrega, não o efeito do item."""
from circulo import prova
from circulo.state import Store

H = 3600
D = 86400
T0 = 1_000 * D


def _item(iid, criado, mergeado, sucesso=True):
    detalhe = "Fazer X.\nSucesso: conflitos_pr cai de 2 para 0" if sucesso else "Fazer X."
    return {"id": iid, "detalhe": detalhe, "criado_em": criado, "mergeado_em": mergeado}


def test_criterio_e_lido_da_linha_sucesso_do_item():
    assert prova.criterio("Pergunta #1\nFazer X.\nSucesso: conflitos_pr cai de 2 para 0\nEvidência (medido): 2") == \
        "conflitos_pr cai de 2 para 0"
    assert prova.criterio("Fazer X.") is None
    assert prova.criterio("Fazer X.\nSucesso:   ") is None


def test_lead_time_mediano_em_minutos_so_dos_prs_mergeados_na_janela():
    prs = [(T0 - 2 * D, T0 - 2 * D + 10 * 60), (T0 - D, T0 - D + 30 * 60), (T0 - 3 * D, T0 - 3 * D + 20 * 60),
           (T0 - 9 * D, T0 - 9 * D + 999 * 60),        # fora da janela de 7 dias
           (T0 - 60, T0 + 60)]                          # mergeado depois do fim da janela
    assert prova.lead_time_mediano_min(prs, T0) == 20
    assert prova.lead_time_mediano_min([], T0) is None


def test_relatorio_conta_com_antes_depois_sem_criterio_e_sem_medicao():
    lido = {("conflitos_pr cai de 2 para 0", T0): 2.0, ("conflitos_pr cai de 2 para 0", T0 + D + 7 * D): 0.0}
    itens = [_item(1, T0, T0 + D),                          # antes e depois lidos
             _item(2, T0, T0 + 2 * D),                       # depois ainda não chegou (7 d pós-merge no futuro)
             _item(3, T0, T0 + D, sucesso=False)]            # sem critério: proxy de lead time
    prs = [(T0 - D, T0 - D + 30 * 60), (T0 + D - 10 * 60, T0 + D + 50 * 60)]
    r = prova.medir(itens, prs, agora=T0 + 8 * D + H, ler=lambda m, em: lido.get((m, em)))
    assert (r["com_antes_depois"], r["sem_criterio"], r["sem_medicao"]) == (1, 1, 1)
    por_item = {m["item"]: m for m in r["medicoes"]}
    assert por_item[1] == {"item": 1, "metrica": "conflitos_pr cai de 2 para 0", "proxy": False, "antes": 2.0, "depois": 0.0}
    assert por_item[2]["depois"] is None
    # o lead time não prova o efeito do item: aparece marcado como proxy e não entra em com_antes_depois
    assert por_item[3] == {"item": 3, "metrica": prova.PROXY, "proxy": True, "antes": 30.0, "depois": 60.0}
    assert r["proxy_com_antes_depois"] == 1


def test_registrar_grava_antes_e_depois_na_trilha_de_cada_item_mergeado():
    s = Store()
    s.x("INSERT INTO roadmap(id,titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
        "VALUES(7,'t','Fazer X.\nSucesso: conflitos_pr cai de 2 para 0','circulo','feito','',1,?,?)", (T0, T0))
    s.x("INSERT INTO roadmap(id,titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
        "VALUES(8,'u','Fazer Y.','circulo','feito','',2,?,?)", (T0, T0))
    s.x("INSERT INTO roadmap(id,titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
        "VALUES(9,'v','Fazer Z.\nSucesso: a','circulo','pendente','',3,?,?)", (T0, T0))   # sem PR mergeado: fora
    s.x("INSERT INTO prs(number,titulo,branch,status,created_at,updated_at) VALUES(60,'w','outra',?,?,?)",
        ("mergeado", T0 - D, T0 - D))                     # PR da semana antes do planejamento: linha de base do proxy
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(60,'z',1,'ok','{}',?)", (T0 - D + 30 * 60,))
    for pr, iid, aberto in ((70, 7, T0), (80, 8, T0), (90, 9, T0)):
        s.x("INSERT INTO prs(number,titulo,branch,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (pr, "t", f"circulo/fix-{iid}-123", "aberto", aberto, aberto))
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(70,'a',1,'ok','{}',?)", (T0 + 40 * 60,))
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(80,'b',1,'ok','{}',?)", (T0 + 20 * 60,))
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(90,'c',0,'ci','{}',?)", (T0 + 20 * 60,))
    ler = {T0: 2.0, T0 + 40 * 60 + 7 * D: 0.0}
    r = prova.registrar(s, agora=T0 + 8 * D, ler=lambda m, em: ler.get(em))
    assert (r["com_antes_depois"], r["sem_criterio"], r["sem_medicao"]) == (1, 1, 0)
    trilha = {(e["de"], e["para"]): e["detalhe"] for e in s.q("SELECT de, para, detalhe FROM elos WHERE relacao='mediu'")}
    assert set(trilha) == {("item:7", "medicao:7:antes"), ("item:7", "medicao:7:depois"),
                           ("item:8", "medicao:8:antes"), ("item:8", "medicao:8:depois")}
    assert '"valor": 0.0' in trilha[("item:7", "medicao:7:depois")]
    assert '"proxy": true' in trilha[("item:8", "medicao:8:antes")]
    prova.registrar(s, agora=T0 + 8 * D, ler=lambda m, em: ler.get(em))           # idempotente
    assert s.one("SELECT COUNT(*) n FROM elos WHERE relacao='mediu'")["n"] == 4

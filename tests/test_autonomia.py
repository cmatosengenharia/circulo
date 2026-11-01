"""31/10: nas primeiras versões o loop não depende de humano para nada — cada ponto do "Precisa de você" tem decisão padrão."""
import time

from circulo import aprovacoes, autonomia, indagador, norte, perguntas


def _item(s, titulo, status="pendente", evidencia="", agora=None, origem="loop"):
    agora = agora or time.time()
    return s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
               (titulo, "d", origem, status, evidencia, 10, agora, agora))


def test_itens_parados_em_voce_saem_da_fila_no_prazo(circle):
    s = circle.store
    agora = time.time()
    s.x("UPDATE roadmap SET status='feito'")
    c_velho = _item(s, "contestado velho", status="contestado", agora=agora - 3 * 3600)
    c_novo = _item(s, "contestado novo", status="contestado", agora=agora - 600)
    d_velho = _item(s, "depende velho", evidencia="depende de você: chave", agora=agora - 3 * 3600)
    d_novo = _item(s, "depende novo", evidencia="depende de você: chave", agora=agora - 600)
    rel = autonomia.rodar(s, agora)
    assert rel["contestados"] == [c_velho] and rel["dependentes"] == [d_velho]
    est = {r["id"]: (r["status"], r["desativado"]) for r in s.q("SELECT id, status, desativado FROM roadmap")}
    assert est[c_velho] == ("descartado", 1) and est[c_novo][0] == "contestado" and est[d_velho][1] == 1 and est[d_novo][1] in (0, None)
    assert not any(i["tipo"] in ("item_contestado", "item_depende") and i["ref"] in (c_velho, d_velho) for i in aprovacoes.pendentes(s, agora, diagnostico=False))
    assert any(m["message"].startswith("Decidi sozinho") for m in s.q("SELECT message FROM alerts WHERE kind='controle'"))
    assert s.get(autonomia.KV)["total"] == {"contestados": 1, "dependentes": 1}


def test_orcamento_esgotado_vira_sem_limite(circle):
    s = circle.store
    s.set("loop_status", "pausado_orcamento")
    assert autonomia.rodar(s)["orcamento"] and s.get("loop_status") == "rodando"
    assert not autonomia.rodar(s)["orcamento"]


def test_norte_sem_evolucao_o_loop_reescreve_a_propria_estrategia(circle):
    s = circle.store
    agora = time.time()
    s.x("UPDATE roadmap SET status='feito'")
    norte.marco(s, agora)
    s.set("perguntas_esgotadas", {"pm:fracao_produto": {"em": agora}})
    assert autonomia.rodar(s, agora)["norte"] is None                                    # prazo não venceu: nada
    norte.cobrar(s, lambda t, k: None, agora + norte.PRAZO_H * 3600 + 1)
    assert s.get("norte_marco")["cobrado"] and not s.get("norte_marco")["evoluiu"]
    novo = autonomia.rodar(s, agora + norte.PRAZO_H * 3600 + 2)["norte"]
    assert novo["nivel"] == 1 and novo["cota"] == 0.7 and novo["vagas"] == 3 and novo["rotacao"] == 3
    assert norte.cota(s) == 0.7 and norte.resumo(s)["cota"] == 0.7 and not s.get("perguntas_esgotadas")
    assert not s.get("norte_marco")["cobrado"]                                             # marco novo: o prazo recomeçou
    assert not any(i["tipo"] == "norte_sem_evolucao" for i in aprovacoes.pendentes(s, agora, diagnostico=False))
    e = perguntas._epicos(s, agora)
    assert e[0].id == f"epico:{perguntas.EPICOS[3][0]}"                                      # épicos girados
    cands = indagador.candidatas(circle.ctx, None)
    assert sum(c.get("eixo") == "produto" for c in cands[:3]) == 3                          # 3 vagas de produto
    s.set("norte_marco", {**s.get("norte_marco"), "cobrado": True, "evoluiu": False})
    assert autonomia.rodar(s, agora)["norte"]["nivel"] == 2 and norte.cota(s) == 0.85
    s.set("norte_marco", {**s.get("norte_marco"), "cobrado": True, "evoluiu": False})
    assert autonomia.rodar(s, agora)["norte"]["cota"] == 0.85                               # no teto: fica no teto


def test_licao_esgotada_sobe_de_camada_e_no_topo_e_aceita(circle):
    s = circle.store
    agora = time.time()
    lid = s.x("INSERT INTO licoes(assinatura,ponto,descricao,classe,status,ocorrencias,reincidencias,camada,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
              ("x:y", "x", "erro que volta", "estrutural", "reincidente", 5, 3, "ci", agora, agora))
    s.set("licoes_esgotadas", {str(lid): {"em": agora, "prs": 3, "item": 1}})
    assert autonomia.rodar(s, agora)["licoes"] == [lid]
    assert s.one("SELECT camada, status FROM licoes WHERE id=?", (lid,))["camada"] == "arquitetura" and not s.get("licoes_esgotadas")
    s.set("licoes_esgotadas", {str(lid): {"em": agora, "prs": 4, "item": 1}})
    autonomia.rodar(s, agora)
    assert s.one("SELECT status FROM licoes WHERE id=?", (lid,))["status"] == "aceita"


def test_medico_escalado_vira_item_urgente_e_aviso_velho_e_visto(circle):
    s = circle.store
    agora = time.time()
    s.set("medico_escalados", {"c1": {"titulo": "Developer gira sem PR", "dono": "você", "em": agora - 3 * 3600, "evidencia": {"n": 3}},
                               "c2": {"titulo": "recente", "dono": "você", "em": agora - 60, "evidencia": {}}})
    s.x("INSERT INTO alerts(kind,message,created_at,delivered) VALUES('saude','velho',?,0)", (agora - 2 * 86400,))
    s.x("INSERT INTO alerts(kind,message,created_at,delivered) VALUES('saude','novo',?,0)", (agora - 60,))
    rel = autonomia.rodar(s, agora)
    assert rel["medico"] == ["c1"] and rel["avisos"] == 1
    it = s.one("SELECT titulo, origem, ordem FROM roadmap WHERE evidencia='Médico (escalado): c1'")
    assert it["titulo"].startswith("Urgente:") and it["origem"] == "erro" and it["ordem"] < 1
    assert list(s.get("medico_escalados")) == ["c2"]
    assert s.one("SELECT delivered FROM alerts WHERE message='velho'")["delivered"] == 1 and s.one("SELECT delivered FROM alerts WHERE message='novo'")["delivered"] == 0
    assert autonomia.rodar(s, agora)["medico"] == []                                        # não duplica o item

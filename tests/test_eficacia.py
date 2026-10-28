"""Veredito de eficácia por PR: o valor 7 dias depois do merge só conta como melhora se sair da banda de 2 desvios da
linha de base (os pontos da semana antes do merge), na direção que o critério de sucesso pede. Sem critério, direção,
leitura ou pontos suficientes, o veredito é 'nao_medivel' e vira item de roteiro pedindo a métrica."""
from circulo import eficacia
from circulo.state import Store

D = 86400
T0 = 1_000 * D
CAI = "conflitos_pr cai de 2 para 0"


def test_sentido_vem_do_criterio():
    assert eficacia.sentido("conflitos_pr cai de 2 para 0") == -1
    assert eficacia.sentido("cobertura sobe de 40 para 60") == 1
    assert eficacia.sentido("latência abaixo de 3 s") == -1
    assert eficacia.sentido("o painel fica bonito") is None


def test_melhora_so_conta_fora_da_banda_de_ruido_na_direcao_desejada():
    base = [2.0, 3.0, 2.0, 3.0, 2.0, 3.0]                    # média 2,5; desvio ~0,55; banda [1,4; 3,6]
    assert eficacia.classificar(base, 2.0, -1)["veredito"] == "sem_efeito"   # caiu, mas dentro do ruído
    assert eficacia.classificar(base, 0.0, -1)["veredito"] == "melhorou"
    assert eficacia.classificar(base, 5.0, -1)["veredito"] == "piorou"
    assert eficacia.classificar(base, 5.0, 1)["veredito"] == "melhorou"
    r = eficacia.classificar(base, 0.0, -1)
    assert (r["n"], round(r["media"], 2)) == (6, 2.5)


def test_nao_medivel_sem_direcao_leitura_ou_pontos_suficientes():
    base = [2.0, 3.0, 2.0, 3.0, 2.0]
    assert eficacia.classificar(base, 0.0, None)["veredito"] == "nao_medivel"
    assert eficacia.classificar(base, None, -1)["veredito"] == "nao_medivel"
    assert eficacia.classificar(base[:eficacia.N_MIN - 1], 0.0, -1)["veredito"] == "nao_medivel"


def test_fracao_nao_medivel_por_semana():
    vs = [{"veredito": "nao_medivel", "em": T0}, {"veredito": "melhorou", "em": T0 + D},
          {"veredito": "sem_efeito", "em": T0 + 7 * D}, {"veredito": "sem_efeito", "em": T0 + 8 * D}]
    assert eficacia.fracao_nao_medivel(vs, T0) == [0.5, 0.0]


def _item(s, iid, detalhe, pr, merge):
    s.x("INSERT INTO roadmap(id,titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
        "VALUES(?,?,?,'circulo','feito','',?,?,?)", (iid, f"t{iid}", detalhe, iid, merge - 2 * D, merge - 2 * D))
    s.x("INSERT INTO prs(number,titulo,branch,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        (pr, "t", f"circulo/fix-{iid}-123", "mergeado", merge - D, merge))
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,?,1,'ok','{}',?)", (pr, f"s{pr}", merge))


def test_registrar_grava_um_veredito_por_pr_com_7_dias_e_pede_a_metrica_do_nao_medivel():
    s = Store()
    _item(s, 7, f"Fazer X.\nSucesso: {CAI}", 70, T0)                 # critério com leitura: veredito medido
    _item(s, 8, "Fazer Y.", 80, T0 + D)                              # sem critério: nao_medivel → item no roteiro
    _item(s, 9, f"Fazer Z.\nSucesso: {CAI}", 90, T0 + 5 * D)         # merge com menos de 7 dias: ainda sem veredito

    def ler(metrica, em):
        return 0.0 if em >= T0 + 7 * D else (2.0 if int(em / D) % 2 else 3.0)

    r = eficacia.registrar(s, agora=T0 + 8 * D + 1, ler=ler)
    assert r == {"gravados": 2, "nao_medivel": 1}
    vs = {v["pr"]: dict(v) for v in s.q("SELECT * FROM eficacia")}
    assert set(vs) == {70, 80}
    assert vs[70]["veredito"] == "melhorou" and vs[70]["n_pontos"] >= eficacia.N_MIN
    assert vs[80]["veredito"] == "nao_medivel"
    # confundimento: os outros merges da janela ficam registrados com o veredito
    assert '80' in vs[70]["outros_merges"] and '90' in vs[70]["outros_merges"]
    pedido = s.one("SELECT r.titulo, r.pergunta_id FROM roadmap r WHERE r.origem='loop'")
    assert "#8" in pedido["titulo"] and pedido["pergunta_id"]
    # uma vez por PR: rodar de novo não regrava nem abre outro item
    assert eficacia.registrar(s, agora=T0 + 9 * D, ler=ler) == {"gravados": 0, "nao_medivel": 0}
    assert s.one("SELECT COUNT(*) n FROM eficacia")["n"] == 2
    assert s.one("SELECT COUNT(*) n FROM roadmap WHERE origem='loop'")["n"] == 1

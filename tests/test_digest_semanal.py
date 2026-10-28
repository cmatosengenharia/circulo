"""Digest semanal: os PRs de produto mergeados em 7 dias, cada um com o pedido ou a pergunta de origem e o antes/depois
da métrica; PR de produto sem origem aparece marcado 'sem pedido', nunca omitido."""
import json
import time

from circulo import digest_semanal, indagador
from circulo.cli import main
from conftest import NOON

AGORA = NOON.timestamp()


def test_pr_de_produto_sem_pedido_fica_marcado_e_nao_e_omitido():
    prs = [
        {"number": 10, "titulo": "Painel da equipe ao vivo", "produto": True, "pedido": "pergunta #299 (pm): o que o time usaria?",
         "metrica": "fracao_produto", "antes": 0.1, "depois": 0.2},
        {"number": 11, "titulo": "Exportar CSV", "produto": True, "pedido": None, "metrica": None, "antes": None, "depois": None},
        {"number": 12, "titulo": "Conserto do vigia", "produto": False, "pedido": "lição #15", "metrica": None,
         "antes": None, "depois": None},
    ]
    t = digest_semanal.texto(prs)
    assert "2 de 3 PRs mergeados em 7 dias foram produto" in t
    assert "#10 Painel da equipe ao vivo" in t and "pergunta #299 (pm)" in t and "fracao_produto: 0.1 → 0.2" in t
    linha = next(x for x in t.splitlines() if "#11" in x)
    assert "sem pedido" in linha
    assert "#12" not in t


def _item(s, titulo, origem, pergunta_id=None):
    return s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,pergunta_id) "
               "VALUES(?,?,?,'feito','',1,?,?,?)", (titulo, f"detalhe de {titulo}", origem, AGORA - 3600, AGORA - 3600, pergunta_id))


def _pr(s, n, item_id, quando=AGORA - 600):
    s.x("INSERT INTO prs(number,titulo,branch,status,item_id,created_at,updated_at) VALUES(?,?,?,'mergeado',?,?,?)",
        (n, f"PR {n}", f"b{n}", item_id, quando, quando))


def test_leitura_pelo_comando_monta_da_base_e_registra_o_uso(circle, capsys):
    s = circle.store
    pid = s.x("INSERT INTO perguntas(chave,persona,texto,evidencia,status,eixo,created_at,updated_at) "
              "VALUES('pm:fracao_produto','pm','Qual funcionalidade o time usaria?',?,'entregue','produto',?,?)",
              (json.dumps({"norte": "fracao_produto", "valor": 0.1}), AGORA - 7200, AGORA - 7200))
    com_pergunta = _item(s, "Digest semanal", "circulo", pid)
    s.x("UPDATE perguntas SET item_id=? WHERE id=?", (com_pergunta, pid))
    _pr(s, 501, com_pergunta)
    _pr(s, 502, _item(s, "Exportar CSV", "pedido_cassio"))
    _pr(s, 503, _item(s, "Conserto interno", "erro"))
    _pr(s, 504, com_pergunta, quando=AGORA - 8 * 86400)         # fora da janela de 7 dias

    prs = {p["number"]: p for p in digest_semanal.prs_da_semana(s, AGORA)}
    assert set(prs) == {501, 502, 503}
    assert prs[501]["produto"] and "pergunta #" in prs[501]["pedido"] and prs[501]["antes"] == 0.1
    assert prs[501]["depois"] is not None
    assert prs[502]["produto"] and prs[502]["pedido"].startswith("pedido:")
    assert not prs[503]["produto"]

    main(["--data", str(circle.data_dir), "digest"])
    out = capsys.readouterr().out
    assert "#501" in out and "#502" in out and "#503" not in out
    assert digest_semanal.leituras(s, AGORA + 1) == 1


def _pergunta(s, chave, eixo, score):
    return s.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,score,eixo,created_at,updated_at) "
               "VALUES(?,'pm','q?','valida','loop',?,?,?,?)", (chave, score, eixo, AGORA, AGORA))


def test_semana_vazia_publica_fracao_sem_valor_e_prioriza_produto(circle):
    t = digest_semanal.texto([])
    assert "0 de 0 PRs" in t and "fração —" in t and "meta 0.5" in t and "Nenhum PR de produto na semana." in t
    avisos = []
    assert digest_semanal.publicar(circle.store, lambda m, k="resposta": avisos.append(m), AGORA) == digest_semanal.texto([])
    assert avisos == [t]
    assert digest_semanal.prioriza_produto(circle.store)


def test_semana_sem_pedido_de_origem_marca_os_prs_e_fica_abaixo_da_meta(circle):
    s = circle.store
    _pr(s, 601, None)
    _pr(s, 602, _item(s, "Ajuste interno", "erro"))
    prs = digest_semanal.prs_da_semana(s, AGORA)
    assert all(p["pedido"] is None and not p["produto"] for p in prs)
    t = digest_semanal.publicar(s, lambda m, k="resposta": None, AGORA)
    assert "0 de 2 PRs" in t and "fração 0.00, meta 0.5" in t and "abaixo da meta" in t
    assert digest_semanal.prioriza_produto(s)


def test_idle_publica_o_digest_uma_vez_por_semana(circle):
    s = circle.store
    circle._run_idle_task("resumo")
    circle._run_idle_task("resumo")
    assert s.one("SELECT COUNT(*) n FROM alerts WHERE message LIKE 'Digest semanal:%'")["n"] == 1
    assert digest_semanal.publicar(s, lambda m, k="resposta": None, time.time() + 6 * 86400) is None
    assert digest_semanal.publicar(s, lambda m, k="resposta": None, time.time() + 7 * 86400 + 1) is not None


def test_fracao_abaixo_da_meta_poe_a_pergunta_de_produto_na_frente_do_roteiro(circle):
    s = circle.store
    infra = _pergunta(s, "arq:a", "infra", 0.9)
    produto = _pergunta(s, "pm:b", "produto", 0.4)
    for n in range(4):                                       # semana na meta: 2 de 4 PRs de produto
        _pr(s, 700 + n, _item(s, f"Pedido {n}", "pedido_cassio" if n < 2 else "erro"))
    digest_semanal.publicar(s, lambda m, k="resposta": None, AGORA)
    assert not digest_semanal.prioriza_produto(s)
    assert indagador.espiar(s, "loop")["id"] == infra
    s.set(digest_semanal.PUBLICADO, None)
    _pr(s, 710, _item(s, "Conserto", "erro"))                 # 2 de 5: abaixo da meta
    digest_semanal.publicar(s, lambda m, k="resposta": None, AGORA)
    assert digest_semanal.prioriza_produto(s)
    assert indagador.espiar(s, "loop")["id"] == produto
    assert indagador.proxima(s, "loop")["id"] == produto

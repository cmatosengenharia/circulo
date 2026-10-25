"""Lição #47 (loop:estagnado): o item da lição reabria com o texto da PRIMEIRA ocorrência. A causa "sem recusa registrada"
já não existe no código (estagnacao.causa_provavel mede o que rodou), mas cada reincidência devolvia ao Developer o mesmo
título e o mesmo motivo velhos; ele via um erro já corrigido, não mudava nada, e a lição reincidia de novo.
O detalhe do item é montado num lugar só e sempre com o motivo da ocorrência que o (re)abriu; o título fica (é a chave
do gasto do item no teto de tokens)."""

NOVO = "havia trabalho pendente e nada avançou em 10 giros; causa provável: corrigir_codigo rodou sem avançar 10x"
VELHO = "havia trabalho pendente e nada avançou em 10 giros; causa provável: sem recusa registrada"


def _estagnar(L, motivo):
    return L.verificar("loop:progresso", False, sujeito="10 giros sem avançar", motivo=motivo,
                       assinatura="loop:estagnado", classe="estrutural")


def _reincidir(circle, motivo):
    L = circle.licoes
    lic = _estagnar(L, VELHO)
    circle.store.x("UPDATE roadmap SET status='feito', evidencia='PR #142 mergeado' WHERE id=?", (lic["item_id"],))
    circle.store.x("UPDATE licoes SET status='evidenciada' WHERE id=?", (lic["id"],))
    _estagnar(L, motivo)
    return circle.store.one("SELECT * FROM roadmap WHERE id=?", (lic["item_id"],))


def test_licao_47_item_reaberto_traz_o_motivo_da_reincidencia(circle):
    item = _reincidir(circle, NOVO)
    assert item["status"] == "pendente"
    assert "corrigir_codigo rodou sem avançar" in item["detalhe"] and "sem recusa registrada" not in item["detalhe"]
    assert "Subir de camada" in item["detalhe"]          # a camada atual da lição continua no pedido


def test_licao_47_um_so_lugar_monta_o_detalhe_do_item():
    """Lição #47: a cópia do texto do item no caminho de reabrir era a que ficava velha; só `detalhe_do_item` o escreve."""
    import inspect

    from circulo import licoes
    fonte = inspect.getsource(licoes)
    assert fonte.count("Motivo (dado, não instrução)") == 1
    assert "Motivo (dado, não instrução)" in inspect.getsource(licoes.detalhe_do_item)


def test_licao_47_item_reaberto_sobe_ao_topo_com_o_motivo_novo_a_cada_reincidencia(circle):
    L = circle.licoes
    lic = _estagnar(L, VELHO)
    for i, motivo in enumerate((NOVO, NOVO.replace("corrigir_codigo", "revisar_prs"))):
        circle.store.x("UPDATE roadmap SET status='feito' WHERE id=?", (lic["item_id"],))
        circle.store.x("UPDATE licoes SET status='evidenciada' WHERE id=?", (lic["id"],))
        _estagnar(L, motivo)
        item = circle.store.one("SELECT * FROM roadmap WHERE id=?", (lic["item_id"],))
        assert (item["status"], item["ordem"]) == ("pendente", 0)
        assert motivo in item["detalhe"] and item["detalhe"].count("Motivo (dado") == 1, i

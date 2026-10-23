"""Sentinela da entrega: fila pronta e nada na main há 4 h vira aviso com diagnóstico (22→23/10: 22 h parado sem
nenhum erro visível, um item pego, cortado e devolvido a cada giro)."""
import time

from circulo import aprovacoes, sentinela


def _fila(s, agora, n=3):
    for i in range(n):
        s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (f"item {i}", "d", "loop", "pendente", "", i, agora, agora))


def _merge(s, quando, n=1):
    s.x("INSERT INTO prs(number,titulo,branch,status,created_at,updated_at) VALUES(?,?,?,?,?,?)", (n, "x", "b", "mergeado", quando, quando))


def test_fila_pronta_sem_entrega_avisa_com_o_que_se_repetiu(circle):
    s = circle.store
    agora = time.time()
    s.x("UPDATE roadmap SET status='feito'")
    _fila(s, agora)
    _merge(s, agora - 6 * 3600)
    for _ in range(40):
        s.x("INSERT INTO alerts(kind,message,created_at,delivered) VALUES('saude',?,?,0)",
            ("Developer: “Lição #67: developer:base” → teto: teto de tokens do item: 98207 gastos + ~3777 > 100000", agora - 3600))
    avisos, notas = [], []
    st = sentinela.checar(s, lambda m, k: avisos.append(m), agora, notificar=lambda t, x: notas.append((t, x)))
    assert st["horas"] >= 6 and st["prontos"] == 3 and st["vezes"] == 40 and st["chamadas_developer"] == 0
    assert "repetiu 40×" in st["frase"] and "não chamou o Claude Code" in st["frase"]
    assert avisos and avisos[0].startswith("Sentinela: Entrega parada") and notas and notas[0][0] == "Círculo: entrega parada"
    topo = aprovacoes.pendentes(s, agora, diagnostico=False)[0]
    assert topo["tipo"] == "entrega_parada" and "3 item(ns)" in topo["titulo"]
    # não repete o aviso a cada minuto; repete depois de REAVISAR_H
    sentinela.checar(s, lambda m, k: avisos.append(m), agora + 60, notificar=lambda t, x: notas.append((t, x)))
    assert len(avisos) == 1
    sentinela.checar(s, lambda m, k: avisos.append(m), agora + sentinela.REAVISAR_H * 3600 + 1, notificar=lambda t, x: notas.append((t, x)))
    assert len(avisos) == 2
    # entrega volta: avisa e sai do "Precisa de você"
    _merge(s, agora + sentinela.REAVISAR_H * 3600 + 30, n=2)
    assert sentinela.checar(s, lambda m, k: avisos.append(m), agora + sentinela.REAVISAR_H * 3600 + 60) is None
    assert avisos[-1].startswith("Entrega voltou") and s.get(sentinela.CHAVE) is None
    assert all(i["tipo"] != "entrega_parada" for i in aprovacoes.pendentes(s, agora, diagnostico=False))


def test_sem_fila_pronta_ou_com_entrega_recente_fica_quieta(circle):
    s = circle.store
    agora = time.time()
    s.x("UPDATE roadmap SET status='feito'")
    _merge(s, agora - 10 * 3600)
    assert sentinela.checar(s, lambda m, k: None, agora, notificar=lambda t, x: None) is None      # fila vazia
    _fila(s, agora)
    s.x("UPDATE roadmap SET evidencia='depende de você: x'")
    assert sentinela.checar(s, lambda m, k: None, agora, notificar=lambda t, x: None) is None      # só itens que esperam você
    s.x("UPDATE roadmap SET evidencia=''")
    _merge(s, agora - 600, n=2)
    assert sentinela.checar(s, lambda m, k: None, agora, notificar=lambda t, x: None) is None      # entregou há 10 min


def test_notificacao_do_mac_fica_desligada_fora_do_mac_ou_por_chave(monkeypatch):
    monkeypatch.setenv("CIRCULO_NOTIFICAR", "0")
    assert sentinela.notificar_mac("t", "x") is False

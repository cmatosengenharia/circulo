"""TTL da lição de estrutura (pergunta #52, Vigia licao_bloqueia: 3 lições de estrutura abertas há 14 h).

A lição de estrutura aberta há mais de 6 h vira 'obsoleta' só se o caminho dela foi exercitado nesse intervalo sem a
assinatura voltar e sem o incidente vinculado crescer: silêncio sem exposição não é prova de correção (Alertmanager,
helm-charts #2695). Se a assinatura voltar depois, a lição reincide e trava de novo.
"""
import json
import time

from circulo.licoes import PASSAGENS_PARA_EXPIRAR, TTL_ESTRUTURA, Licoes, expiradas
from circulo.vigia import s_licao_bloqueia

H = 3600


def _lic(id_, sig, ponto, idade_h, now, ultima_tick=0):
    return {"id": id_, "assinatura": sig, "ponto": ponto, "created_at": now - idade_h * H, "ultima_tick": ultima_tick,
            "origens": json.dumps([sig])}


def _v(ponto, ok, sig, ha_h, now):
    return {"ponto": ponto, "ok": int(ok), "assinatura": sig, "created_at": now - ha_h * H}


def test_licao_de_14h_sem_reincidencia_fecha_e_com_reincidencia_recente_continua():
    now = 1_000_000.0
    calma = _lic(1, "developer:agente:x", "developer:agente", 14, now)
    voltou = _lic(2, "developer:abrir_pr:y", "developer:abrir_pr", 14, now)
    vs = [_v("developer:agente", True, None, h, now) for h in (1, 2, 3)] + \
         [_v("developer:abrir_pr", True, None, h, now) for h in (1, 2, 3)] + \
         [_v("developer:abrir_pr", False, "developer:abrir_pr:y", 0.5, now)]
    assert expiradas([calma, voltou], vs, {}, now, tick=100) == [1]


def test_silencio_sem_exposicao_nao_fecha():
    """A lição aberta trava a evolução: sem passagens pelo caminho, a assinatura não tem como reincidir."""
    now = 1_000_000.0
    lic = _lic(1, "developer:agente:x", "developer:agente", 14, now)
    poucas = [_v("developer:agente", True, None, 1, now)] * (PASSAGENS_PARA_EXPIRAR - 1)
    antigas = [_v("developer:agente", True, None, 7, now)] * PASSAGENS_PARA_EXPIRAR    # fora da janela de 6 h
    assert expiradas([lic], poucas + antigas, {}, now, tick=100) == []
    assert expiradas([_lic(1, "developer:agente:x", "developer:agente", 5, now)],
                     [_v("developer:agente", True, None, 1, now)] * 5, {}, now, tick=100) == []   # ainda não tem 6 h


def test_incidente_vinculado_que_cresceu_mantem_a_licao_aberta():
    now = 1_000_000.0
    lic = _lic(1, "incidente:abc", "execucao:meta", 14, now, ultima_tick=10)
    assert expiradas([lic], [], {"abc": now - 2 * H}, now, tick=100) == []          # o count subiu há 2 h
    assert expiradas([lic], [], {"abc": now - 13 * H}, now, tick=100) == [1]        # 90 giros sem o incidente
    assert expiradas([lic], [], {"abc": now - 13 * H}, now, tick=11) == []          # 1 giro: sem exposição


def test_vigia_expira_antes_de_emitir_e_a_reincidencia_trava_de_novo(circle):
    s, L = circle.store, Licoes(circle.store)
    ESTRUTURA = "estrutural"
    calma = L.verificar("developer:agente", False, motivo="agente saiu sem commit", assinatura="developer:agente:sem_commit", classe=ESTRUTURA)
    voltou = L.verificar("developer:abrir_pr", False, motivo="pr recusado", assinatura="developer:abrir_pr:recusado", classe=ESTRUTURA)
    now = time.time()
    s.x("UPDATE licoes SET created_at=?", (now - 14 * H,))
    s.x("UPDATE verificacoes SET created_at=?", (now - 14 * H,))
    for _ in range(PASSAGENS_PARA_EXPIRAR):
        L.verificar("developer:agente", True)
        L.verificar("developer:abrir_pr", True)
    L.verificar("developer:abrir_pr", False, motivo="pr recusado", assinatura="developer:abrir_pr:recusado", classe=ESTRUTURA)

    trava = s_licao_bloqueia(s, now + 1)
    assert trava and trava["evidencia"]["licoes"] == 1
    assert s.one("SELECT status FROM licoes WHERE id=?", (calma["id"],))["status"] == "obsoleta"
    assert s.one("SELECT status FROM licoes WHERE id=?", (voltou["id"],))["status"] == "aberta"

    L.verificar("developer:agente", False, motivo="agente saiu sem commit", assinatura="developer:agente:sem_commit", classe=ESTRUTURA)
    assert s.one("SELECT status FROM licoes WHERE id=?", (calma["id"],))["status"] == "reincidente"
    assert s_licao_bloqueia(s, now + TTL_ESTRUTURA + 2)["evidencia"]["licoes"] == 2


def test_vigia_conta_as_horas_desde_a_reabertura_e_nao_desde_a_criacao(circle):
    """Item #170 (Vigia: 2 lições de estrutura abertas há 76 h): a lição nascida há 76 h que foi corrigida (item feito,
    PR mergeado) e reincidiu agora estava aberta havia minutos, mas a sonda media desde created_at e abria um item de
    trava a cada passagem. A idade é a do período aberto atual."""
    s, L = circle.store, Licoes(circle.store)
    lic = L.verificar("loop:progresso", False, motivo="nada avançou", assinatura="loop:estagnado", classe="estrutural")
    now = time.time()
    s.x("UPDATE licoes SET created_at=?, status='validada' WHERE id=?", (now - 76 * H, lic["id"]))
    L.verificar("loop:progresso", False, motivo="nada avançou", assinatura="loop:estagnado", classe="estrutural")
    assert s.one("SELECT status FROM licoes WHERE id=?", (lic["id"],))["status"] == "reincidente"

    assert s_licao_bloqueia(s, now + 60) is None
    trava = s_licao_bloqueia(s, now + 3 * H)
    assert trava and 2.9 <= trava["evidencia"]["ha_horas"] <= 3.1

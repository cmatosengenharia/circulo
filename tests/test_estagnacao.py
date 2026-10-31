"""Lição #47 (loop:estagnado): a causa registrada era o palpite "sem recusa registrada" em 8 reincidências. Cada disparo
da estagnação tem de nomear o item pendente parado (id, estado) e a etapa que o tocou por último (fila, developer, gate, CI)."""
import json
import time

import pytest

from circulo import vigia
from circulo.estagnacao import ESTAGNADO, causa_provavel, parado


def _item(store, titulo, evidencia, status="pendente", origem="erro", ordem=1):
    now = time.time()
    store.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (titulo, "d", origem, status, evidencia, ordem, now, now))
    return store.one("SELECT MAX(id) i FROM roadmap")["i"]


@pytest.mark.parametrize("evidencia,status,pr,etapa", [
    ("barrado nos portões antes do PR (lint, testes, constituição, tamanho, teste novo, portões aprendidos)", "pendente", False, "gate"),
    ("agente não produziu mudança", "pendente", False, "developer"),
    ("pegando", "em_andamento", False, "developer"),
    ("planejado pelo loop", "pendente", False, "fila"),
    ("PR aberto", "pendente", True, "CI"),
])
def test_licao_47_causa_da_estagnacao_nomeia_item_e_etapa(circle, evidencia, status, pr, etapa):
    s = circle.store
    rid = _item(s, "Corrigir X", evidencia, status=status)
    if pr:
        s.x("INSERT INTO prs(number,titulo,status,created_at,updated_at,item_id) VALUES(77,'t','aberto',0,0,?)", (rid,))
    p = parado(s)
    assert (p["item"], p["estado"], p["etapa"]) == (rid, status, etapa)
    causa = causa_provavel({"sem": ESTAGNADO, "rodou": {"corrigir_codigo rodou sem avançar": 10}}, s)
    assert f"item #{rid}" in causa and status in causa and f"etapa {etapa}" in causa
    assert "sem recusa registrada" not in causa


def test_licao_47_disparo_do_vigia_grava_item_e_etapa(circle):
    s = circle.store
    rid = _item(s, "Corrigir Y", "barrado nos portões antes do PR")
    s.set("progresso", {"sem": ESTAGNADO, "rodou": {}})
    ev = vigia.s_estagnacao(s, time.time())["evidencia"]
    assert json.loads(json.dumps(ev, default=str))["parado"] == {"item": rid, "estado": "pendente", "etapa": "gate",
                                                                "toque": "barrado nos portões antes do PR"}


def test_licao_47_licao_da_estagnacao_cita_o_item_parado(circle):
    s = circle.store
    rid = _item(s, "Corrigir Z", "barrado nos portões antes do PR")
    circle._tem_trabalho = lambda t: t == "corrigir_codigo"
    s.set("progresso", {"sem": ESTAGNADO - 1, "rodou": {}})
    circle._vigiar_progresso(True, circle._progresso(), None)
    motivo = s.one("SELECT * FROM licoes WHERE assinatura='loop:estagnado'")
    assert motivo and f"item #{rid}" in json.dumps(dict(motivo), ensure_ascii=False) and "etapa gate" in json.dumps(dict(motivo), ensure_ascii=False)

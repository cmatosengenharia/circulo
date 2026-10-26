"""Canário de falha: o guardrail que nunca barrou nada precisa provar, com falha injetada, que ainda barra.

Pergunta do conselho (auditor): "Qual guardrail nunca barrou nada, e como provar com um teste que ele ainda funciona?"
Fault injection com controle: o painel velho tem de falhar em `painel:frescor` e o painel fresco tem de passar; se a
checagem for removida ou virar sempre-verde, o canário acusa.
"""
import time
from pathlib import Path
from types import SimpleNamespace

from circulo import canario, confianca
from circulo.perguntas import _auditor
from circulo.state import Store


def _ultimo(s: Store) -> int | None:
    r = s.one("SELECT ok FROM verificacoes WHERE ponto='painel:frescor' ORDER BY id DESC LIMIT 1")
    return None if r is None else r["ok"]


def test_painel_velho_falha_e_painel_fresco_passa_em_estado_temporario(tmp_path):
    def medir(s, atraso):                                        # o SLO só julga com 100 amostras na janela (1.61.0)
        for _ in range(99):
            s.x("INSERT INTO frescor(atraso_ms, em, versao) VALUES(?,?,?)", (atraso, time.time(), confianca.versao_painel()))
        confianca.registrar_frescor(s, atraso, confianca.versao_painel())

    velho = Store(tmp_path / "velho.db")
    dado_em = time.time() - 60                                   # o painel mostra um dado de um minuto atrás
    medir(velho, (time.time() - dado_em) * 1000)
    assert _ultimo(velho) == 0

    fresco = Store(tmp_path / "fresco.db")
    medir(fresco, 200)
    assert _ultimo(fresco) == 1


def test_canario_do_frescor_detecta_painel_velho():
    r = canario.injetar("painel:frescor")
    assert r == {"ponto": "painel:frescor", "velho_falhou": True, "fresco_passou": True, "ok": True}


def test_canario_acusa_checagem_sempre_verde(monkeypatch):
    monkeypatch.setattr(confianca, "FRESCOR_MAX_MS", float("inf"))
    r = canario.injetar("painel:frescor")
    assert not r["velho_falhou"] and not r["ok"]


def test_canario_acusa_checagem_removida(monkeypatch):
    monkeypatch.setattr(confianca, "registrar_frescor", lambda store, atraso_ms, versao: True)
    assert not canario.injetar("painel:frescor")["ok"]


def test_ciclo_de_saude_registra_canario_e_o_auditor_deixa_de_contar_o_ponto(circle):
    s = circle.store
    agora = time.time()
    for _ in range(51):
        s.x("INSERT INTO verificacoes(tick,ponto,sujeito,ok,created_at) VALUES(0,'painel:frescor','p99',1,?)", (agora,))
    antes = _auditor(s, agora)
    assert antes[0].evidencia["pontos_que_nunca_falharam"] == ["painel:frescor"]

    circle.health.check()
    ev = s.q("SELECT ponto, ok FROM canarios")
    assert [(r["ponto"], r["ok"]) for r in ev] == [("painel:frescor", 1)]
    assert all(p.evidencia.get("pontos_que_nunca_falharam") != ["painel:frescor"] for p in _auditor(s, agora))

    circle.health.check()                                         # no máximo um canário por ponto por dia
    assert s.one("SELECT COUNT(*) n FROM canarios")["n"] == 1


def _portoes_velhos(s: Store, agora: float) -> list[int]:
    """Portões aprendidos como os da pergunta #149: nasceram de lições, têm mais de um dia e nunca barraram nada."""
    from circulo.neuronios import neurogenese
    ids = [*neurogenese(s, {"id": 6, "assinatura": "developer:lint:lint:B905", "item_id": None}),
           *neurogenese(s, {"id": 15, "assinatura": "rastro:lacuna", "item_id": 96})]
    s.x("UPDATE portoes SET created_at=?", (agora - 2 * 86400,))
    return ids


def _ruff_simulado(monkeypatch):
    """O ruff do portão de lint acusa o B905 do canário (o CI roda o ruff real; aqui pode não haver ruff)."""
    from circulo import neuronios, self_dev
    monkeypatch.setattr(self_dev, "garantir_ruff", lambda: True)
    monkeypatch.setattr(neuronios.subprocess, "run", lambda argv, **kw: SimpleNamespace(
        returncode=int("zip(a, b)" in (Path(kw["cwd"]) / "circulo/canario.py").read_text()), stdout="", stderr=""))


def test_ciclo_de_saude_prova_cada_portao_aprendido_e_o_auditor_deixa_de_contar(monkeypatch):
    # pergunta do conselho #149: portoes_aprendidos_que_nunca_barraram cai a 0 quando cada portão tem canário verde
    _ruff_simulado(monkeypatch)
    s = Store(":memory:")
    agora = time.time()
    ids = _portoes_velhos(s, agora)
    assert _auditor(s, agora)[0].evidencia["portoes_aprendidos_que_nunca_barraram"] == 2

    assert {(r["ponto"], r["ok"]) for r in canario.rodar(s, now=agora)} == {(f"portao:{i}", True) for i in ids}
    assert {r["ponto"] for r in s.q("SELECT ponto FROM canarios WHERE ok=1")} == {f"portao:{i}" for i in ids}
    assert _auditor(s, agora) == []
    assert dict(s.one("SELECT SUM(avaliacoes) a, SUM(bloqueios) b FROM portoes")) == {"a": 0, "b": 0}


def test_portao_que_deixa_passar_a_propria_assinatura_continua_contado_e_avisa(monkeypatch):
    _ruff_simulado(monkeypatch)
    s = Store(":memory:")
    agora = time.time()
    _portoes_velhos(s, agora)
    [neutro] = s.q("SELECT id FROM portoes WHERE tipo='obrigatorio'")
    s.x("UPDATE portoes SET spec=? WHERE id=?", ('{"em": "teste", "item": 96, "regex": "."}', neutro["id"]))
    avisos = []
    [r] = [r for r in canario.rodar(s, lambda texto, canal: avisos.append(texto), now=agora) if not r["ok"]]
    assert (r["ponto"], r["ok"], r["velho_falhou"]) == (f"portao:{neutro['id']}", False, False)
    assert avisos and "não foi acusada" in avisos[0]
    assert _auditor(s, agora)[0].evidencia["portoes_aprendidos_que_nunca_barraram"] == 1

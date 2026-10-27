"""Pedido ao humano quando a pasta de extratos não dá lançamentos: 1 pedido aberto por causa do diagnóstico, com o
caminho da pasta e o formato aceito; o giro repetido não abre outro e o extrato solto na pasta fecha o pedido."""
import shutil
from pathlib import Path

from circulo.aprovacoes import pendentes
from circulo.ingestao import GIROS, RODADAS, abertos, girar
from circulo.perguntas import _m_lancamentos

FIX = Path(__file__).parent / "fixtures"


def lancamentos(store) -> int:
    return _m_lancamentos(store, None)[1]["lancamentos"]


def test_pasta_vazia_gera_1_pedido_repetir_nao_gera_outro_e_a_fixture_fecha(circle, tmp_path):
    s = circle.store
    pasta = tmp_path / "extratos"
    pasta.mkdir()
    for _ in range(GIROS - 1):
        girar(pasta, s)
    assert abertos(s) == []                                   # ainda não são N giros seguidos
    girar(pasta, s)
    pedido, = abertos(s)
    assert pedido["causa"] == "vazia" and str(pasta) in pedido["mensagem"]
    assert ".ofx" in pedido["mensagem"] and ".csv" in pedido["mensagem"]
    for _ in range(GIROS * 2):
        girar(pasta, s)
    assert [p["id"] for p in abertos(s)] == [pedido["id"]]   # mesma causa: nenhum pedido novo
    assert [i["tipo"] for i in pendentes(s, diagnostico=False)].count("extratos") == 1

    shutil.copy(FIX / "extrato_anonimo.ofx", pasta / "extrato_anonimo.ofx")
    assert girar(pasta, s) > 0                                 # 1 giro depois do pedido atendido
    assert lancamentos(s) > 0 and abertos(s) == []
    assert "extratos" not in [i["tipo"] for i in pendentes(s, diagnostico=False)]


def test_causa_que_muda_fecha_o_pedido_antigo_e_conta_de_novo(circle, tmp_path):
    s = circle.store
    pasta = tmp_path / "extratos"
    for _ in range(GIROS):
        girar(pasta, s)
    assert [p["causa"] for p in abertos(s)] == ["pasta_inexistente"]
    pasta.mkdir()
    girar(pasta, s)
    assert abertos(s) == []                                   # a pasta passou a existir: a causa antiga sumiu
    for _ in range(GIROS - 1):
        girar(pasta, s)
    assert [p["causa"] for p in abertos(s)] == ["vazia"]


def test_cada_giro_grava_a_causa_da_rodada_e_a_dominante_das_ultimas_explica_lancamentos_0(circle, tmp_path):
    s = circle.store
    pasta = tmp_path / "extratos"

    def causas() -> list[str]:
        return s.get("ingestao_causas")["rodadas"]

    girar(pasta, s)
    assert causas() == ["pasta_inexistente"]
    pasta.mkdir()
    girar(pasta, s)
    girar(pasta, s)
    assert causas() == ["pasta_inexistente", "vazia", "vazia"]
    assert s.get("ingestao_causas")["dominante"] == "vazia" and lancamentos(s) == 0
    (pasta / "a_quebrado.csv").write_text("foo;bar\n1;2\n", encoding="utf-8")
    girar(pasta, s)
    assert causas()[-1] == "so_rejeitados" and lancamentos(s) == 0
    shutil.copy(FIX / "extrato_anonimo.ofx", pasta / "extrato_anonimo.ofx")
    assert girar(pasta, s) > 0
    assert causas()[-1] == "importados" and lancamentos(s) > 0
    shutil.copy(FIX / "extrato_anonimo.ofx", pasta / "de_novo.ofx")
    assert girar(pasta, s) == 0
    assert causas()[-1] == "so_duplicata"                    # antes, "ok(n)": igual a uma rodada que importou
    girar(pasta, s)
    assert causas()[-1] == "sem_extrato_novo"
    for _ in range(RODADAS):
        girar(pasta, s)
    assert causas() == ["sem_extrato_novo"] * RODADAS         # 1 causa por giro, só as últimas RODADAS
    assert s.get("ingestao_causas")["dominante"] == "sem_extrato_novo"

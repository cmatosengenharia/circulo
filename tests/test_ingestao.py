"""Pedido ao humano quando a pasta de extratos não dá lançamentos: 1 pedido aberto por causa do diagnóstico, com o
caminho da pasta e o formato aceito; o giro repetido não abre outro e o extrato solto na pasta fecha o pedido."""
import shutil
from pathlib import Path

from circulo.aprovacoes import pendentes
from circulo.ingestao import GIROS, RODADAS, abertos, girar
from circulo.lancamentos_pasta import contadores
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


def test_pedido_so_abre_com_lancamentos_0_e_fecha_quando_o_ledger_ganha_lancamento(circle, tmp_path):
    from circulo.lancamentos_import import importar

    s = circle.store
    pasta = tmp_path / "extratos"
    for _ in range(GIROS):
        girar(pasta, s)
    assert [p["causa"] for p in abertos(s)] == ["pasta_inexistente"]
    importar(s, (FIX / "extrato_anonimo.ofx").read_text(encoding="utf-8"), "ofx")   # entrou por outro caminho
    girar(pasta, s)
    assert lancamentos(s) > 0 and abertos(s) == []           # o dono já mandou dados: o pedido fecha
    for _ in range(GIROS * 2):
        girar(pasta, s)
    assert abertos(s) == []                                   # pasta ausente com ledger cheio não é falta de dado
    assert "extratos" not in [i["tipo"] for i in pendentes(s, diagnostico=False)]


def test_toda_rodada_grava_registro_com_carimbo_e_sem_registro_recente_e_nunca_rodou(circle, tmp_path):
    from circulo.ingestao import RECENTE, estado

    s = circle.store
    pasta = tmp_path / "extratos"
    pasta.mkdir()
    assert estado(s, agora=1000.0) == "nunca_rodou"            # nenhum giro gravou registro

    def ultima() -> dict:
        return s.get("ingestao_causas")["ultima"]

    girar(pasta, s, agora=1000.0)
    assert ultima() == {"timestamp": 1000.0, "causa": "vazia", "arquivos_vistos": 0, "arquivos_rejeitados": [],
                        "lancamentos_novos": 0, "lancamentos_duplicados": 0, "lancamentos": 0,
                        "fontes": contadores()}                              # rodada com zeros também grava
    assert estado(s, agora=1000.0) == "vazia"
    assert estado(s, agora=1000.0 + RECENTE + 1) == "nunca_rodou"   # sem sinal recente não é "vazia"

    (pasta / "quebrado.csv").write_text("foo;bar\n1;2\n", encoding="utf-8")
    girar(pasta, s, agora=2000.0)
    r = ultima()
    assert (r["timestamp"], r["arquivos_vistos"], r["lancamentos_novos"]) == (2000.0, 1, 0)
    rejeitado, = r["arquivos_rejeitados"]
    assert rejeitado["nome"] == "quebrado.csv" and rejeitado["motivo"].startswith("rejeitado")
    assert estado(s, agora=2000.0) == "so_rejeitados" and lancamentos(s) == 0

    shutil.copy(FIX / "extrato_anonimo.ofx", pasta / "extrato_anonimo.ofx")
    novos = girar(pasta, s, agora=3000.0)
    assert novos > 0 and lancamentos(s) == novos
    fontes = contadores()
    fontes["pasta"].update(vistos=1, novos=1)
    assert ultima() == {"timestamp": 3000.0, "causa": "importados", "arquivos_vistos": 1, "arquivos_rejeitados": [],
                        "lancamentos_novos": novos, "lancamentos_duplicados": 0, "lancamentos": novos,
                        "fontes": fontes}
    assert estado(s, agora=3000.0) == "importados"

    shutil.copy(FIX / "extrato_anonimo.ofx", pasta / "extrato_anonimo.ofx")   # reexecução com o mesmo extrato
    assert girar(pasta, s, agora=4000.0) == 0
    assert lancamentos(s) == novos and ultima()["lancamentos_novos"] == 0
    assert ultima()["arquivos_rejeitados"] == []              # a rodada anterior com rejeitado não vaza para esta


def test_contadores_por_fonte_fecham_vistos_igual_rejeitados_mais_duplicados_mais_novos(circle, tmp_path):
    s = circle.store
    pasta = tmp_path / "extratos"
    pasta.mkdir()
    email = (FIX / "email_notificacao_anonimo.txt").read_text(encoding="utf-8")

    def fonte(nome: str) -> tuple:
        f = s.get("ingestao_causas")["ultima"]["fontes"][nome]
        assert f["vistos"] == f["rejeitados_por_parser"] + f["duplicados_por_hash"] + f["novos"]   # fecha sempre
        return f["vistos"], f["rejeitados_por_parser"], f["duplicados_por_hash"], f["novos"], f["ultimo_descarte"]

    girar(pasta, s)
    assert fonte("pasta") == fonte("email") == (0, 0, 0, 0, None)            # rodada com zeros também grava

    shutil.copy(FIX / "extrato_anonimo.ofx", pasta / "a_valido.ofx")
    (pasta / "b_corrompido.ofx").write_text("<OFX><BANKTRANLIST><STMTTRN><DTPOSTED>2026", encoding="utf-8")
    (pasta / "c_corrompido.csv").write_text("foo;bar\n1;2\n", encoding="utf-8")
    (pasta / "d_aviso.eml").write_text(email, encoding="utf-8")
    novos = girar(pasta, s)
    *contas, descarte = fonte("pasta")
    assert contas == [3, 2, 0, 1]                                            # o OFX truncado não conta como duplicado
    assert descarte.startswith("c_corrompido.csv: rejeitado")
    assert fonte("email") == (1, 0, 0, 1, None) and lancamentos(s) == novos > 1

    shutil.copy(FIX / "extrato_anonimo.ofx", pasta / "reenvio.ofx")          # o mesmo extrato de novo
    (pasta / "reenvio.eml").write_text(email, encoding="utf-8")
    assert girar(pasta, s) == 0 and lancamentos(s) == novos
    assert fonte("pasta") == (1, 0, 1, 0, "reenvio.ofx: duplicado por hash")
    assert fonte("email") == (1, 0, 1, 0, "reenvio.eml: duplicado por hash")


def test_giro_ocioso_ingere_pendentes_lancamentos_0_a_n_e_o_segundo_giro_so_duplica(circle):
    """O giro chama `ingerir_pendentes` (pasta + .eml, sem LLM) e o estado do loop conta `lancamentos`: a fixture com
    duas linhas idênticas no mesmo dia dá N no 1º giro, sem fundir as gêmeas, e 0 novos com N duplicados no 2º."""
    from circulo.ingestao import ingerir_pendentes
    from circulo.lancamentos_import import parse_extrato

    s = circle.store
    pasta = circle.data_dir / "extratos"
    pasta.mkdir()
    csv = (FIX / "extrato_anonimo.csv").read_text(encoding="utf-8")
    fixture = parse_extrato(csv, "csv")
    assert len({(lin.data, lin.centavos, lin.descricao) for lin in fixture}) < len(fixture)   # há gêmeas no mesmo dia

    def estado() -> dict:
        return s.get("ingestao_causas")["ultima"]

    shutil.copy(FIX / "extrato_anonimo.csv", pasta / "extrato_anonimo.csv")
    circle.tick()
    assert estado()["lancamentos"] == lancamentos(s) >= len(fixture)
    assert estado()["lancamentos_novos"] == len(fixture) and estado()["lancamentos_duplicados"] == 0
    assert s.one("SELECT COUNT(*) AS n FROM ledger WHERE description='padaria pao bom'")["n"] == 2

    shutil.copy(FIX / "extrato_anonimo.csv", pasta / "extrato_anonimo.csv")   # o mesmo extrato de novo
    circle.tick()
    assert estado()["lancamentos_novos"] == 0 and estado()["lancamentos_duplicados"] == len(fixture)
    assert estado()["lancamentos"] == lancamentos(s) == len(fixture)
    assert ingerir_pendentes(circle.data_dir, s) == 0                          # sem pendente: nada novo
    assert estado()["lancamentos"] == len(fixture) and estado()["lancamentos_duplicados"] == 0

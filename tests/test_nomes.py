"""Os agentes têm um nome só em todas as telas (fonte única em circulo/nomes.py)."""
from circulo import camadas, equipe, fluxo, nomes


def test_todas_as_telas_usam_os_mesmos_nomes():
    for chave, _ in camadas.ETAPAS:
        assert camadas.NOME[chave] == nomes.nome(chave)
    for chave in equipe.EQUIPE:
        assert equipe.EQUIPE[chave]["nome"] == nomes.nome(chave) and equipe.EQUIPE[chave]["cargo"] == nomes.cargo(chave)
    assert fluxo.nome_do_agente("corrigir_codigo") == nomes.curto("corrigir_codigo") == "Dev"
    assert nomes.nome("corrigir_codigo") == "Desenvolvedor" and nomes.antes("revisar_prs") == "Gate"
    assert nomes.nome("agente_novo_da_autoevolucao") == "Agente novo da autoevolucao"   # agente que nasce depois entra com o próprio nome
    assert all(t["nome"] and t["cargo"] and t["curto"] for t in nomes.tabela())

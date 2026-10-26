"""Contexto enxuto para o Cursor: AGENTS.md curto e regras .mdc escopadas por glob, só com o que o agente não
descobre lendo o repositório (comandos, convenções, armadilhas da memória e lições evidenciadas). Muda só por PR."""
import subprocess
import time

import pytest

from circulo import assuntos, contexto_cursor


def _nota(s, assunto: str, tipo: str, texto: str, em: float | None = None) -> None:
    aid = s.one("SELECT id FROM assuntos WHERE nome=?", (assunto,))["id"]
    s.x("INSERT INTO assunto_notas(assunto_id, tipo, texto, origem, created_at) VALUES(?,?,?,?,?)",
        (aid, tipo, texto, texto, em or time.time()))


@pytest.fixture
def sms(circle):
    s = circle.store
    assuntos.criar(s, "Serviço de SMS", "microsserviço de comunicação que envia SMS por fila e worker")
    _nota(s, "Serviço de SMS", "nota", "comando: make test-integracao sobe o localstack antes dos testes")
    _nota(s, "Serviço de SMS", "decisao", "usar fila SQS FIFO para não duplicar envio")
    _nota(s, "Serviço de SMS", "nota", "armadilha: o provedor devolve 200 mesmo quando o número é inválido")
    _nota(s, "Serviço de SMS", "pendencia", "revisar custo do SMS no mês")
    _nota(s, "Serviço de SMS", "link", "runbook https://exemplo.interno/runbook")
    _nota(s, "Serviço de SMS", "nota", "reunião de ontem foi boa")
    _nota(s, "Serviço de SMS", "decisao", "em src/envio/*.py todo envio passa por enviar_com_idempotencia")
    return s


def test_agents_md_so_tem_comandos_convencoes_e_armadilhas(sms):
    arquivos = contexto_cursor.gerar(sms, "Serviço de SMS")
    agents = arquivos["AGENTS.md"]
    assert "make test-integracao" in agents
    assert "fila SQS FIFO" in agents
    assert "devolve 200" in agents
    assert "revisar custo" not in agents and "runbook" not in agents and "reunião" not in agents
    assert "worker" not in agents                    # a descrição (sumário de arquitetura) não entra


def test_regra_com_caminho_vira_mdc_escopado_e_sai_do_agents_md(sms):
    arquivos = contexto_cursor.gerar(sms, "Serviço de SMS")
    assert "enviar_com_idempotencia" not in arquivos["AGENTS.md"]
    [(caminho, regra)] = [(k, v) for k, v in arquivos.items() if k.startswith(".cursor/rules/")]
    assert caminho.endswith(".mdc")
    assert regra.startswith("---\ndescription: ")
    assert "\nglobs: src/envio/*.py\n" in regra and "\nalwaysApply: false\n---\n" in regra
    assert "enviar_com_idempotencia" in regra


def test_agents_md_tem_no_maximo_60_linhas_e_cada_regra_tem_teto(sms):
    for i in range(200):
        _nota(sms, "Serviço de SMS", "decisao", f"decisão número {i} sobre o envio")
        _nota(sms, "Serviço de SMS", "decisao", f"em src/m{i % 3}/*.py a regra {i} vale")
    arquivos = contexto_cursor.gerar(sms, "Serviço de SMS")
    assert len(arquivos["AGENTS.md"].splitlines()) <= contexto_cursor.LIMITE_AGENTS == 60
    assert "decisão número 199" in arquivos["AGENTS.md"]          # a mais recente fica, a mais antiga sai
    regras = [v for k, v in arquivos.items() if k.endswith(".mdc")]
    assert len(regras) == 4                                        # src/m0..m2 e o src/envio da fixture
    assert all(len(r.splitlines()) <= contexto_cursor.LIMITE_REGRA for r in regras)


def test_o_que_o_readme_ja_diz_nao_entra(sms):
    readme = "# SMS\n\nPara testar: `make test-integracao sobe o localstack antes dos testes`.\n"
    agents = contexto_cursor.gerar(sms, "Serviço de SMS", readme=readme)["AGENTS.md"]
    assert "make test-integracao" not in agents
    assert "fila SQS FIFO" in agents


def test_repositorio_usa_so_licoes_evidenciadas(circle):
    s = circle.store
    agora = time.time()
    for sig, status, desc in (("ci:lint:B905", "evidenciada", "zip() sem strict= quebra o lint B905"),
                              ("loop:estagnado", "aberta", "nada avançou em 10 giros")):
        s.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,status,ocorrencias,reincidencias,created_at,updated_at) "
            "VALUES(?,?,?,?,?,1,0,?,?)", (sig, sig.split(":")[0], "estrutural", desc, status, agora, agora))
    agents = contexto_cursor.gerar(s, readme="", nome="circulo")["AGENTS.md"]
    assert "B905" in agents and "lição #" in agents
    assert "nada avançou" not in agents


def test_assunto_desconhecido_e_recusado(circle):
    with pytest.raises(ValueError):
        contexto_cursor.gerar(circle.store, "não existe")


def _git(repo, *a):
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)


def test_escrever_na_branch_principal_e_recusado(sms, tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    with pytest.raises(ValueError, match="PR"):
        contexto_cursor.escrever(tmp_path, contexto_cursor.gerar(sms, "Serviço de SMS"))
    assert not (tmp_path / "AGENTS.md").exists()


def test_escrever_numa_branch_de_trabalho_grava_para_virar_pr(sms, tmp_path):
    _git(tmp_path, "init", "-q", "-b", "contexto-cursor")
    arquivos = contexto_cursor.gerar(sms, "Serviço de SMS")
    escritos = contexto_cursor.escrever(tmp_path, arquivos)
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == arquivos["AGENTS.md"]
    assert len(escritos) == len(arquivos)


def test_escrever_recusa_arquivo_acima_do_teto(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "contexto")
    with pytest.raises(ValueError, match="linhas"):
        contexto_cursor.escrever(tmp_path, {"AGENTS.md": "x\n" * 61})

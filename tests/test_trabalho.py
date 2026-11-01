"""Meu trabalho (26/10): a tela que junta assuntos, daily, links, orçamento de IA, contexto para o Cursor e GAIA,
com a semente de dados de exemplo que deixa o esqueleto inteiro funcionando antes do dado real."""
import json
import urllib.request
from datetime import datetime

import pytest

from circulo import assuntos, gasto_cursor, tema, trabalho
from circulo.budget import TZ
from circulo.links import Links
from circulo.painel import serve


def test_semente_preenche_todas_as_partes_e_e_idempotente(circle):
    s, dados = circle.store, circle.data_dir
    r = trabalho.semear(s, dados)
    assert len(r["assuntos"]) == len(trabalho.ASSUNTOS) and len(r["notas"]) == len(trabalho.NOTAS) and len(r["links"]) == len(trabalho.LINKS)
    assert trabalho.semear(s, dados)["ja_semeado"]                                   # segunda vez: nada duplica
    assert s.one("SELECT COUNT(*) n FROM assunto_notas")["n"] == len(trabalho.NOTAS)
    v = trabalho.visao(s, dados)
    assert v["exemplo"] and len(v["assuntos"]) == len(trabalho.ASSUNTOS)
    sms = next(a for a in v["assuntos"] if a["nome"] == "svc-sms")
    assert (sms["decisoes"], sms["pendencias"], sms["notas"], sms["links"]) == (1, 1, 2, 2) and sms["ultima"]
    assert any("svc-sms" in linha and "hoje:" in linha for linha in v["daily"]) and "bloqueia:" in " ".join(v["daily"])
    assert v["orcamento"]["gasto_mes"] > 0 and v["orcamento"]["esgota_em"] and v["orcamento"]["por_assunto"][0]["centavos"] > 0
    assert v["links"]["total"] == len(trabalho.LINKS) and v["contexto"]["assunto"] == "svc-sms"
    assert "make test" in v["contexto"]["arquivos"]["AGENTS.md"] and any(k.startswith(".cursor/rules/") for k in v["contexto"]["arquivos"])
    assert v["gaia"]["exemplo"] and [e["etapa"] for e in v["gaia"]["etapas"]] == ["pedido", "estudo", "desenvolvimento", "pr", "merge"]
    assert len(v["pendencias"]) == 5 and v["decisoes"][0]["assunto"] == "svc-whatsapp"   # a decisão mais recente primeiro


def test_apagar_tira_so_o_exemplo_e_deixa_o_que_e_seu(circle):
    s, dados = circle.store, circle.data_dir
    trabalho.semear(s, dados)
    minha = trabalho.anotar(s, "decidimos monitorar a latência do svc-sms por provedor")   # nota real num assunto do exemplo
    assert minha["assunto"] == "svc-sms" and minha["tipo"] == "decisao"
    Links(s).guardar("https://wiki.exemplo/minha", "Meu link", "svc-sms")
    gasto_cursor.lancar(s, "1,00", "svc-sms", "bugfix")
    n = trabalho.apagar(s, dados)
    assert n["notas"] == len(trabalho.NOTAS) and n["links"] == len(trabalho.LINKS) and n["gastos"] > 0 and n["arquivos"] == len(trabalho.DAILY_NOTAS)
    assert n["assuntos"] == len(trabalho.ASSUNTOS) - 1                                   # svc-sms tem nota sua: fica
    v = trabalho.visao(s, dados)
    assert not v["exemplo"] and [a["nome"] for a in v["assuntos"]] == ["svc-sms"]
    assert v["links"]["total"] == 1 and v["orcamento"]["gasto_mes"] == 100 and v["daily"][1:] == ["nada nas notas de ontem nem pendência aberta"]
    assert not v["gaia"]["etapas"] and not s.get(trabalho.KV)
    assert trabalho.semear(s, dados)["assuntos"] and len(v["pendencias"]) == 0           # pode semear de novo


def test_anotar_e_perguntar_sem_jev_pela_regra_local(circle):
    s = circle.store
    trabalho.semear(s, circle.data_dir)
    n = trabalho.anotar(s, "pendência: revisar os templates do svc-whatsapp antes do Natal")
    assert (n["assunto"], n["tipo"]) == ("svc-whatsapp", "pendencia")
    with pytest.raises(ValueError, match="não sei em que assunto"):
        trabalho.anotar(s, "nota: lembrar de beber água")                                # sem palavra em comum: não chuta
    with pytest.raises(ValueError, match="credencial"):
        trabalho.anotar(s, "nota: token: abc123 do svc-sms")
    r = trabalho.api_get(s, circle.data_dir, "/api/trabalho/perguntar", {"q": ["o que decidimos sobre SMS?"]})
    assert r["notas"] and r["notas"][0]["assunto"] == "svc-sms" and "SQS" in r["texto"]
    assert trabalho.api_get(s, circle.data_dir, "/api/trabalho/contexto", {"assunto": ["GAIA"]})["arquivos"]["AGENTS.md"].count("ia-assistida") == 1
    assert "erro" in trabalho.api_get(s, circle.data_dir, "/api/trabalho/contexto", {"assunto": ["não existe"]})
    assert trabalho.api_get(s, circle.data_dir, "/api/outra", {}) is None
    assert trabalho.api_post(s, circle.data_dir, "/api/trabalho/assunto", {"nome": "x"})[1] == 400
    assert trabalho.api_post(s, circle.data_dir, "/api/trabalho/exemplo", {"acao": "?"})[1] == 400
    assert trabalho.api_post(s, circle.data_dir, "/api/trabalho/anotar", {"texto": "decidimos usar um provedor só no svc-sms"})[0]["nota"]["assunto"] == "svc-sms"


def test_tela_meu_trabalho_no_painel_e_no_menu(circle):
    assert ("/trabalho", "Meu trabalho") in [(h, n) for h, n, _ in tema.MENU] and "trabalho.html" in tema.PAGINAS
    srv = serve(circle.store.path, port=0, background=True)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/trabalho", timeout=5) as r:
            html = r.read().decode()
        assert "Meu trabalho" in html and 'href="/trabalho"' in html and "/api/trabalho" in html
        req = urllib.request.Request(base + "/api/trabalho/exemplo", data=json.dumps({"acao": "semear"}).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Circulo": "1"})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert json.loads(r.read())["semeado"]["assuntos"]
        with urllib.request.urlopen(base + "/api/trabalho", timeout=5) as r:
            v = json.loads(r.read())
        assert v["exemplo"] and len(v["assuntos"]) == len(trabalho.ASSUNTOS) and v["orcamento"]["texto"].startswith("Mês:")
        with urllib.request.urlopen(base + "/api/trabalho/perguntar?q=pend%C3%AAncias%20da%20migra%C3%A7%C3%A3o", timeout=5) as r:
            assert "Blip" in json.loads(r.read())["texto"]
    finally:
        srv.shutdown()
    assert assuntos.ver(circle.store, "GAIA")["decisoes"][0]["texto"].startswith("toda PR")


def test_botao_importar_csv_do_cursor_entra_pela_tela_sem_duplicar(circle):
    """O botão 'Importar CSV do Cursor' envia o arquivo a POST /api/trabalho/gasto, que chama gasto_cursor.importar_csv;
    a resposta diz quantas linhas novas entraram e traz o orçamento já atualizado; reimportar não duplica."""
    hoje = datetime.now(TZ).date().isoformat()                                  # o card mostra o mês corrente
    csv_cursor = ("Date,Model,Total Tokens,Cost\n"
                  f"{hoje},claude-sonnet,120000,$1.25\n"
                  f"{hoje},gpt-5,80000,$0.80\n"
                  f"{hoje},claude-sonnet,5000,Included\n")
    srv = serve(circle.store.path, port=0, background=True)
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def enviar(corpo):
        req = urllib.request.Request(base + "/api/trabalho/gasto", data=json.dumps(corpo).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Circulo": "1"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    try:
        with urllib.request.urlopen(base + "/trabalho", timeout=5) as r:
            html = r.read().decode()
        assert "Importar CSV do Cursor" in html and "/api/trabalho/gasto" in html and 'type="file"' in html
        primeira = enviar({"texto": csv_cursor, "assunto": "svc-sms", "tipo": "bugfix"})
        assert primeira["ok"] and primeira["novas"] == 2 and primeira["orcamento"]["gasto_mes"] == 205
        assert enviar({"texto": csv_cursor})["novas"] == 0                                    # reimportar não duplica
    finally:
        srv.shutdown()
    assert circle.store.one("SELECT COUNT(*) n FROM gasto_cursor WHERE origem='csv'")["n"] == 2
    assert trabalho.api_post(circle.store, circle.data_dir, "/api/trabalho/gasto", {"texto": ""})[1] == 400


def test_configuracao_pede_o_exemplo_e_o_sre_semeia_uma_vez(circle, monkeypatch):
    s, dados, avisos = circle.store, circle.data_dir, []
    monkeypatch.delenv("CIRCULO_EXEMPLO", raising=False)
    assert not trabalho.semear_se_pedido(s, dados, lambda m, k: avisos.append(m))
    monkeypatch.setenv("CIRCULO_EXEMPLO", "1")
    assert trabalho.semear_se_pedido(s, dados, lambda m, k: avisos.append(m)) and "semeados" in avisos[0]
    assert not trabalho.semear_se_pedido(s, dados, lambda m, k: avisos.append(m)) and len(avisos) == 1
    trabalho.apagar(s, dados)
    assuntos.criar(s, "Meu assunto", "real")
    assert not trabalho.semear_se_pedido(s, dados)                                   # já tem assunto seu: não mexe

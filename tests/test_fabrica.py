"""Círculo perfeito (fabrica/): um cartão passa por PO → Arquiteto → Dev → QA → Revisor → Release e volta como achado."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fabrica import coordenador, modelo
from fabrica.estado import Estado
from fabrica.oficina import GitHubFalso, Projeto, Simulado


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def oficina(tmp_path):
    """Projeto de exemplo com remoto local: app.py com um bug (soma subtrai) e fabrica.json."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    r = tmp_path / "projeto"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "app.py").write_text("def soma(a, b):\n    return a - b\n")
    (r / "tests").mkdir()
    (r / "tests" / "test_existente.py").write_text("def test_sempre_passa():\n    assert True\n")
    (r / "fabrica.json").write_text(json.dumps({"nome": "exemplo", "testes": f"{sys.executable} -m pytest -q -x -p no:cacheprovider", "lint": "",
                                                "protegidos": ["fabrica.json", "constituicao/"], "max_linhas_pr": 200}))
    git(r, "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "inicial")
    git(r, "remote", "add", "origin", str(origin))
    git(r, "push", "-q", "origin", "main")
    return r


def corrige_soma(instrucao: str, cwd: Path) -> dict:
    """Roteiro do executor simulado: o dev escreve o teste e corrige; PO e arquiteto respondem JSON."""
    if "gerente de produto" in instrucao:
        return {"ok": True, "texto": json.dumps({"titulo": "Corrigir soma", "criterios": ["soma(2, 2) == 4"], "verificacao": "python3 -c 'import app; assert app.soma(2,2)==4'"}), "log": ""}
    if "Você é o arquiteto" in instrucao:
        return {"ok": True, "texto": json.dumps({"onde": ["app.py", "tests/test_soma.py"], "plano": "trocar o operador e cobrir com teste", "riscos": []}), "log": ""}
    if "Você é o desenvolvedor" in instrucao:
        (cwd / "app.py").write_text("def soma(a, b):\n    return a + b\n")
        (cwd / "tests" / "test_soma.py").write_text("from app import soma\n\ndef test_soma():\n    assert soma(2, 2) == 4\n")
        return {"ok": True, "texto": "", "log": "ok"}
    return {"ok": True, "texto": "", "log": ""}


def fabrica_de(oficina, roteiro=corrige_soma, ci="verde"):
    est = Estado(oficina.parent / "fabrica.db")
    return coordenador.Fabrica(Projeto.abrir(oficina), est, Simulado(roteiro), GitHubFalso(oficina.parent / "origin.git", ci), relogio=time.time)


def test_o_circulo_completo_entrega_um_pedido(oficina):
    fab = fabrica_de(oficina)
    cid = fab.pedir("A função soma está devolvendo a diferença; soma(2, 2) tem de dar 4.")
    trilha = []
    for _ in range(12):
        r = fab.passo()
        if r is None:
            break
        trilha.append((r["papel"], r["de"], r["para"]))
        if r["para"] in modelo.FINAIS:
            break
    assert [t[0] for t in trilha] == ["po", "arquiteto", "dev", "qa", "revisor", "release", "release"], trilha
    c = fab.estado.cartao(cid)
    assert c["estado"] == "concluido" and c["dados"]["pr"] == 101 and c["devolucoes"] == 0
    assert fab.github.mesclados == [101]
    assert "return a + b" in git(oficina.parent / "origin.git", "show", "main:app.py")          # entrou na main do remoto
    passos = fab.estado.passos(cid)
    assert all(any(e["base"] == "medido" for e in p["evidencias"]) for p in passos)                 # toda estação mediu algo
    qa = next(p for p in passos if p["papel"] == "qa")
    bases = {e["texto"]: e["dado"]["ok"] for e in qa["evidencias"] if "na base" in e["texto"] or "na branch" in e["texto"]}
    assert bases["testes novos na base (precisam falhar)"] is False and bases["testes novos na branch (precisam passar)"] is True
    tipos = [e["tipo"] for e in fab.estado.eventos_desde(0)]
    assert tipos.count("vez") == 7 and "entrega" in tipos and tipos.count("mensagem") >= 7
    assert fab.passo() is None                                                                     # fila vazia e sem achado: descansa


def test_sem_teste_novo_o_qa_devolve_e_na_terceira_o_cartao_bloqueia(oficina):
    def sem_teste(instrucao, cwd):
        if "Você é o desenvolvedor" in instrucao:
            (cwd / "app.py").write_text("def soma(a, b):\n    return a + b\n")
            return {"ok": True, "texto": "", "log": ""}
        return corrige_soma(instrucao, cwd)
    fab = fabrica_de(oficina, sem_teste)
    cid = fab.pedir("corrigir soma")
    vistos = []
    for _ in range(14):
        r = fab.passo()
        vistos.append((r["papel"], r["para"], r["devolucao"]))
        if r["para"] in modelo.FINAIS:
            break
    devolucoes = [v for v in vistos if v[2]]
    # o QA devolve (sem teste); o dev, de volta, não produz nada novo (devolução 2); na terceira o cartão bloqueia
    assert [v[0] for v in devolucoes] == ["qa", "dev"] and len(devolucoes) == modelo.MAX_DEVOLUCOES
    assert vistos[-1][1] == "bloqueado" and vistos[-1][0] == "dev"
    c = fab.estado.cartao(cid)
    assert c["estado"] == "bloqueado"
    assert any(a["assunto"] == "devolucoes:dev" for a in fab.estado.achados_abertos())
    assert fab.github.mesclados == []                                                               # nada foi mesclado


def test_arquiteto_bloqueia_o_que_exige_mexer_no_protegido(oficina):
    def protegido(instrucao, cwd):
        if "Você é o arquiteto" in instrucao:
            return {"ok": True, "texto": json.dumps({"onde": ["constituicao/regras.py"], "plano": "mudar a regra", "riscos": []}), "log": ""}
        return corrige_soma(instrucao, cwd)
    fab = fabrica_de(oficina, protegido)
    cid = fab.pedir("mudar a constituição")
    fab.passo()
    r = fab.passo()
    assert r["papel"] == "arquiteto" and r["para"] == "bloqueado"
    assert fab.estado.cartao(cid)["estado"] == "bloqueado"
    assert any(a["assunto"].startswith("protegido:") for a in fab.estado.achados_abertos())
    assert fab.passo() is None                                                                     # achado de protegido não vira cartão sozinho


def test_ci_vermelho_devolve_ao_dev_e_achado_vira_cartao_quando_a_fila_esvazia(oficina):
    fab = fabrica_de(oficina, ci="vermelho")
    fab.pedir("corrigir soma")
    r = None
    for _ in range(8):
        r = fab.passo()
        if r["papel"] == "release" and r["para"] == "em_desenvolvimento":
            break
    assert r and r["para"] == "em_desenvolvimento" and "CI vermelho" in r["mensagem"] and r["devolucao"]
    fab.estado.achado("qa", "flaky:test_x", "O teste test_x oscilou 3 vezes em 24 h.", "medido")
    fab.estado.x("UPDATE cartoes SET estado='cancelado'")
    r = fab.passo()                                                                                # fila vazia: o achado vira cartão e o PO o pega
    assert r["papel"] == "po" and fab.estado.um("SELECT origem FROM cartoes WHERE estado!='cancelado'")["origem"] == "fabrica"


def test_painel_mostra_o_chao_de_fabrica_e_aceita_pedido(oficina):
    import urllib.request
    from fabrica.painel import retrato, servir
    fab = fabrica_de(oficina)
    fab.pedir("corrigir soma")
    fab.passo()
    srv = servir(fab.estado.caminho, 0, fundo=True)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        html = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert 'id="chao"' in html and "Quadro de achados" in html and "Diário da fábrica" in html
        d = json.loads(urllib.request.urlopen(base + "/api/estado", timeout=5).read())
        assert [m["id"] for m in d["equipe"]] == list(modelo.ORDEM) and d["em_voo"]["estado"] == "planejado" and d["ativo"] == "arquiteto"
        req = urllib.request.Request(base + "/api/pedido", data=json.dumps({"texto": "segundo pedido"}).encode(), headers={"Content-Type": "application/json"}, method="POST")
        assert json.loads(urllib.request.urlopen(req, timeout=5).read())["id"] == 2
        req = urllib.request.Request(base + "/api/pausa", data=json.dumps({"pausar": True}).encode(), headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=5).read()
        assert fab.pausada and fab.passo() is None and retrato(fab.estado)["pausada"]
    finally:
        srv.shutdown()


def test_cli_demo_tem_projeto_de_exemplo_que_fecha_o_circulo(tmp_path):
    from fabrica.cli import projeto_exemplo, roteiro_demo
    raiz = projeto_exemplo(tmp_path)
    cfg = json.loads((raiz / "fabrica.json").read_text())
    cfg["testes"] = f"{sys.executable} -m pytest -q -x -p no:cacheprovider"
    (raiz / "fabrica.json").write_text(json.dumps(cfg))
    git(raiz, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "testes locais")
    git(raiz, "push", "-q", "origin", "main")
    fab = coordenador.Fabrica(Projeto.abrir(raiz), Estado(tmp_path / "f.db"), Simulado(lambda i, c: roteiro_demo(i, c)), GitHubFalso(tmp_path / "origin.git"))
    fab.pedir("O total do carrinho ignora a quantidade: total([(10, 2)]) tem de dar 20.")
    fab.pedir("Quero um cupom DEZ que dá 10% de desconto no total.")
    finais = []
    for _ in range(30):
        r = fab.passo()
        if r is None:
            break
        if r["para"] in modelo.FINAIS:
            finais.append((r["cartao"], r["para"]))
        if len(finais) == 2:
            break
    assert finais == [(1, "concluido"), (2, "concluido")]                                        # o segundo precisou de uma devolução do QA
    assert fab.estado.cartao(2)["devolucoes"] == 0 and any(p["papel"] == "qa" and p["para_estado"] == "em_desenvolvimento" for p in fab.estado.passos(2))

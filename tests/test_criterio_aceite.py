"""Critério de aceite verificável por pedido: o Arquiteto grava 'Sucesso: ...' no estudo; o critério congela ao entrar
no item (pick), o portão do PR confere (check executável = teste roda; frase = Validador contra o diff) e o corpo do
PR ganha a linha 'Critério: ✓/✗'. PR com critério ✗ não é aberto."""
import subprocess

from test_reparo import ZipAgent, dev_de
from test_self_dev import erro_recorrente, repo  # noqa: F401 — fixture do repositório

from circulo import criterio_aceite as ca
from circulo import validador
from circulo.developer import GitHubComConvencoes
from circulo.neuronios import ABRIR_PR, avaliar_aprendidos


def _item(circle, sucesso: str) -> dict:
    item = erro_recorrente(circle)
    circle.store.x("UPDATE roadmap SET detalhe=detalhe || ? WHERE id=?", (f"\nSucesso: {sucesso}", item["id"]))
    return dict(circle.store.one("SELECT * FROM roadmap WHERE id=?", (item["id"],)))


def _corpos(dev):
    corpos = []
    interno = dev.gh._gh

    def create_pr(head, base, title, body):
        corpos.append(body)
        interno.prs.append((head, base, title))
        return 42
    interno.create_pr = create_pr
    return corpos


def test_extrai_check_executavel_ou_frase():
    c = ca.extrair("faz x\nSucesso: `python -m pytest tests/test_x.py::test_y` passa e tests/test_z.py também")
    assert c.texto.startswith("`python -m pytest") and c.testes == ("tests/test_x.py::test_y", "tests/test_z.py")
    assert ca.extrair("Sucesso: o painel mostra a linha nova").testes == ()
    assert ca.extrair("sem linha de sucesso") is None and ca.extrair("Sucesso:   ") is None


def test_criterio_congela_ao_entrar_e_o_arquiteto_nao_reescreve(circle):
    s = circle.store
    item = _item(circle, "o painel mostra a linha nova")
    ca.congelar(s, item)
    s.x("UPDATE roadmap SET detalhe=? WHERE id=?", ("reescrito\nSucesso: qualquer coisa mais fácil", item["id"]))
    ca.congelar(s, dict(s.one("SELECT * FROM roadmap WHERE id=?", (item["id"],))))
    assert ca.congelado(s, item["id"])["texto"] == "o painel mostra a linha nova"


def test_validador_simulado_reprova_criterio_nao_atendido_e_o_portao_barra(circle, tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=wt, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "b"], cwd=wt, check=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, capture_output=True, text=True).stdout.strip()
    (wt / "app.py").write_text("x = 1\n")
    s = circle.store
    item = _item(circle, "o corpo do PR ganha a linha Critério")
    ca.congelar(s, item)
    vistos = []

    def chamar(system, prompt):
        vistos.append(prompt)
        return '{"aprovado": true, "problemas": [], "criterio_ok": false, "criterio_evidencia": "o diff não toca o corpo do PR"}'
    v = validador.revisar_pr(circle.ctx, wt, base, item, chamar=chamar)
    assert "o corpo do PR ganha a linha Critério" in vistos[0]            # o Validador vê o critério congelado
    assert not v["aprovado"] and any("Critério ✗" in p for p in v["problemas"])
    adicionadas = {"app.py": ["x = 1"]}
    barrado = [r for r in avaliar_aprendidos(s, ABRIR_PR, wt, adicionadas, {}, item["id"]) if r.portao == ca.PORTAO]
    assert barrado and not barrado[0].ok and "o diff não toca o corpo do PR" in barrado[0].motivo
    assert ca.linha_pr(s, item["id"]).startswith("Critério: ✗")
    corrigido = [r for r in avaliar_aprendidos(s, ABRIR_PR, wt, {"app.py": ["x = 2"]}, {}, item["id"]) if r.portao == ca.PORTAO]
    assert corrigido[0].ok and ca.linha_pr(s, item["id"]).startswith("Critério: ?")   # diff mudou: não reconferido, nunca ✓


def test_pr_nao_abre_com_criterio_executavel_nao_atendido(circle, repo, tmp_path):  # noqa: F811
    _item(circle, "`test_app.py::test_criterio_que_ninguem_escreveu` passa")
    dev, gh = dev_de(circle, repo, tmp_path, ZipAgent(conserta_na=1))
    corpos = _corpos(dev)
    r = dev.run_once()
    assert r.status != "proposto" and not gh.prs and not corpos, r.detalhe
    assert ca.PORTAO in r.detalhe


def test_pr_de_pedido_leva_a_linha_criterio_com_a_evidencia(circle, repo, tmp_path):  # noqa: F811
    item = _item(circle, "`test_app.py::test_soma` passa")
    dev, gh = dev_de(circle, repo, tmp_path, ZipAgent(conserta_na=1))
    assert isinstance(dev.gh, GitHubComConvencoes)
    corpos = _corpos(dev)
    r = dev.run_once()
    assert r.status == "proposto" and gh.prs, r.detalhe
    linha = next(x for x in corpos[0].splitlines() if x.startswith("Critério:"))
    assert linha.startswith("Critério: ✓") and "test_app.py::test_soma" in linha and "passou" in linha
    assert ca.congelado(circle.store, item["id"])["ok"] == 1


def test_pr_com_criterio_de_frase_reprovado_pelo_validador_nao_abre(circle, repo, tmp_path, monkeypatch):  # noqa: F811
    _item(circle, "a soma aparece no log do giro")
    resposta = '{"aprovado": true, "problemas": [], "criterio_ok": false, "criterio_evidencia": "nada no diff escreve no log"}'
    monkeypatch.setattr(validador, "_chamar_llm", lambda ctx, it: lambda system, prompt: resposta)
    dev, gh = dev_de(circle, repo, tmp_path, ZipAgent(conserta_na=1))
    corpos = _corpos(dev)
    r = dev.run_once()
    assert not gh.prs and not corpos and ca.PORTAO in r.detalhe, r.detalhe

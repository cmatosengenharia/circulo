"""Cadastro de chaves: cofre do sistema, nunca devolve valor, cada mudança registrada e reinicia o loop."""
import json
import urllib.request

import pytest

from circulo.cofre import Arquivo, Cadastro, Keychain, mascarar

from test_painel import painel, post  # noqa: F401 — fixture do servidor do painel


class KeychainFalso(Keychain):
    """Simula o comando `security`; guarda o que receberia e prova que o valor veio pelo stdin, não no argv."""

    def __init__(self):
        super().__init__()
        self.itens, self.argvs = {}, []

    def _rodar(self, args, entrada=None):
        import shlex
        import subprocess
        self.argvs.append(args)
        if args == ["-i"]:
            partes = shlex.split(entrada)
            conta, valor = partes[partes.index("-a") + 1], partes[partes.index("-w") + 1]
            self.itens[conta] = valor
            return subprocess.CompletedProcess(args, 0, "", "")
        conta = args[args.index("-a") + 1]
        if args[0] == "find-generic-password":
            v = self.itens.get(conta)
            return subprocess.CompletedProcess(args, 0 if v else 44, (v or "") + "\n", "")
        self.itens.pop(conta, None)
        return subprocess.CompletedProcess(args, 0, "", "")


@pytest.fixture
def env(tmp_path):
    p = tmp_path / "env"
    p.write_text("# comentário\nANTHROPIC_API_KEY=sk-ant-arquivo-1234567890\nCIRCULO_REPO=dono/circulo\n")
    p.chmod(0o600)
    return p


def test_valor_vai_pelo_stdin_e_nunca_volta_na_listagem(circle, env):
    kc = KeychainFalso()
    cad = Cadastro(circle.store, env, cofre=kc)
    r = cad.gravar("ANTHROPIC_API_KEY", "sk-ant-segredo-abcd")
    assert r["acao"] == "trocou" and r["final"] == "…abcd"
    assert all("sk-ant-segredo-abcd" not in " ".join(a) for a in kc.argvs)          # nunca no argv (ps)
    assert "sk-ant" not in env.read_text()                                          # saiu do arquivo
    lista = json.dumps(cad.listar(), ensure_ascii=False)
    assert "sk-ant-segredo-abcd" not in lista and "…abcd" in lista
    item = next(c for c in cad.listar() if c.get("nome") == "ANTHROPIC_API_KEY")
    assert item["onde"] == "keychain" and item["valor"] is None
    assert circle.store.get("config_alterada_em")                                   # o loop reinicia para valer
    assert circle.store.one("SELECT message FROM alerts ORDER BY id DESC LIMIT 1")["message"].startswith("Você trocou a chave ANTHROPIC_API_KEY (final …abcd)")


def test_migrar_so_apaga_do_arquivo_depois_de_ler_igual_no_cofre(circle, env):
    kc = KeychainFalso()
    r = Cadastro(circle.store, env, cofre=kc).migrar()
    assert r["movidas"] == ["ANTHROPIC_API_KEY", "CIRCULO_REPO"]
    assert kc.itens["ANTHROPIC_API_KEY"] == "sk-ant-arquivo-1234567890"
    assert "sk-ant" not in env.read_text() and "# comentário" in env.read_text()


def test_carrega_do_cofre_sem_sobrescrever_o_ambiente(circle, env, monkeypatch):
    kc = KeychainFalso()
    kc.itens["GITHUB_TOKEN"] = "ghp_x"
    kc.itens["ANTHROPIC_API_KEY"] = "do-cofre"
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "de-fora")
    lidas = Cadastro(circle.store, env, cofre=kc).carregar_no_ambiente()
    import os
    assert lidas == ["GITHUB_TOKEN"] and os.environ["ANTHROPIC_API_KEY"] == "de-fora"


def test_sem_cofre_do_sistema_usa_arquivo_600(circle, tmp_path):
    p = tmp_path / "env"
    cad = Cadastro(circle.store, p, cofre=Arquivo(p))
    cad.gravar("OPENAI_API_KEY", "sk-novo-xyzw", ajuda="outra LLM")
    assert oct(p.stat().st_mode)[-3:] == "600"
    assert any(c.get("nome") == "OPENAI_API_KEY" and c["cadastrada"] for c in cad.listar())


def test_nome_invalido_e_rejeitado(circle, env):
    with pytest.raises(ValueError):
        Cadastro(circle.store, env, cofre=KeychainFalso()).gravar("x; rm -rf /", "v")
    assert mascarar("curta") == "…"


def test_api_de_chaves_protegida_e_sem_valores(circle, painel, monkeypatch, tmp_path):  # noqa: F811
    import circulo.configuracao as cfg
    monkeypatch.setattr(cfg, "ENV_FILE", tmp_path / "env")
    monkeypatch.setenv("CIRCULO_COFRE", "arquivo")
    code, r = post(painel + "/api/chaves", {"nome": "GITHUB_TOKEN", "valor": "ghp_segredo_9876"}, {"X-Circulo": "1"})
    assert code == 200 and r["final"] == "…9876" and "ghp_segredo" not in json.dumps(r)
    with urllib.request.urlopen(painel + "/api/chaves", timeout=5) as resp:
        assert "ghp_segredo" not in resp.read().decode()
    assert post(painel + "/api/chaves", {"nome": "GITHUB_TOKEN", "valor": "x"})[0] == 403        # sem cabeçalho
    req = urllib.request.Request(painel + "/api/chaves", headers={"Host": "evil.example:80"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 403                                                              # DNS rebinding
    with urllib.request.urlopen(painel + "/integracoes", timeout=5) as resp:
        assert "Integrações" in resp.read().decode()

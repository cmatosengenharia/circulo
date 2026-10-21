"""`circulo init` (circulo/kit.py): o motor cuidando de qualquer repositório — constituição, testes, checks e pedido
vêm do repositório; CI e CODEOWNERS escritos nele; variáveis gravadas no arquivo de configuração sem tocar nas chaves."""
import subprocess
from pathlib import Path

from circulo import kit
from circulo.merge_gate import CONSTITUICAO, protegidos, required_checks, touches_constitution


def _repo(tmp_path, pyproject=True):
    r = tmp_path / "meu-app"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    subprocess.run(["git", "remote", "add", "origin", "git@github.com:fulano/meu-app.git"], cwd=r, check=True)
    (r / "tests").mkdir()
    if pyproject:
        (r / "pyproject.toml").write_text('[project]\nname = "meu-app"\nversion = "0.1"\n\n[tool.circulo]\nprotegidos = ["app/core/", ".github/"]\ntestes = "pytest -q tests"\nlint = "ruff check app"\nchecks = ["Testes", "Lint"]\n')
    return r


def test_init_le_o_kit_do_repositorio_e_prepara_ci_codeowners_e_config(tmp_path):
    r = _repo(tmp_path)
    env = tmp_path / "env"
    env.write_text("TYPESAFE_API_KEY=segredo-jev\nANTHROPIC_API_KEY=segredo-llm\n")
    out = kit.init(str(r), pedido="entregar o app", env_file=env)
    k = out["kit"]
    assert k["nome"] == "meu-app" and k["repo"] == "fulano/meu-app" and list(k["protegidos"]) == ["app/core/", ".github/"]
    assert k["testes"] == "pytest -q tests" and k["lint"] == "ruff check app" and list(k["checks"]) == ["Testes", "Lint"] and k["pedido"] == "entregar o app"
    assert (r / ".github" / "workflows" / "circulo.yml").exists() and "name: Testes" in (r / ".github" / "workflows" / "circulo.yml").read_text()
    co = (r / ".github" / "CODEOWNERS").read_text()
    assert "/app/core/ @fulano" in co
    txt = env.read_text()
    assert "TYPESAFE_API_KEY=segredo-jev" in txt and "ANTHROPIC_API_KEY=segredo-llm" in txt          # chaves intactas
    assert "CIRCULO_PROTEGIDOS=app/core/,.github/" in txt and "CIRCULO_TEST_CMD=pytest -q tests" in txt and "CIRCULO_ENTRADA=equipe" in txt
    assert f"CIRCULO_REPO_DIR={r.resolve()}" in txt and "CIRCULO_REPO=fulano/meu-app" in txt
    assert oct(env.stat().st_mode)[-3:] == "600"
    out2 = kit.init(str(r), env_file=env)                                            # de novo: não duplica nem reescreve CI
    assert out2["arquivos"] == [] and env.read_text().count("CIRCULO_REPO_DIR=") == 1


def test_sem_pyproject_usa_padroes_e_avisa(tmp_path):
    r = _repo(tmp_path, pyproject=False)
    k = kit.carregar(str(r))
    assert k.testes == kit.PADRAO_TESTES and tuple(k.protegidos) == kit.PADRAO_PROTEGIDOS and any("pyproject" in a for a in k.avisos)
    assert k.repo == "fulano/meu-app"


def test_motor_le_a_constituicao_e_os_checks_do_repositorio_alvo(monkeypatch):
    assert protegidos() == CONSTITUICAO and len(required_checks()) == 5
    monkeypatch.setenv("CIRCULO_PROTEGIDOS", "app/core/, .github/")
    monkeypatch.setenv("CIRCULO_REQUIRED_CHECKS", "Testes,Lint")
    assert protegidos() == ("app/core/", ".github/") and required_checks() == ("Testes", "Lint")
    assert touches_constitution(["app/core/x.py"]) and not touches_constitution(["circulo/policy.py"])   # a constituição é a do repo cuidado


def test_container_e_entrypoint_existem_e_nao_levam_chave():
    raiz = Path(__file__).resolve().parent.parent
    d = (raiz / "Dockerfile").read_text()
    assert "claude-code" in d and 'CMD ["run", "--painel"' in d and "ENTRYPOINT" in d
    assert not any(k in d for k in ("ANTHROPIC_API_KEY=", "TYPESAFE_API_KEY=", "GITHUB_TOKEN="))
    assert (raiz / "ops" / "entrypoint.sh").read_text().startswith("#!/bin/sh") and "circulo.env" in (raiz / ".gitignore").read_text()
    assert "env_file" in (raiz / "docker-compose.yml").read_text()


def test_entrada_pela_equipe_quando_o_kit_pede(circle, painel, monkeypatch):  # noqa: F811
    import urllib.request
    monkeypatch.setenv("CIRCULO_ENTRADA", "equipe")
    assert "Equipe ao vivo" in urllib.request.urlopen(painel + "/", timeout=5).read().decode().split("<h1")[1][:200]
    monkeypatch.delenv("CIRCULO_ENTRADA")
    assert 'id="cards"' in urllib.request.urlopen(painel + "/", timeout=5).read().decode() or "Missões" in urllib.request.urlopen(painel + "/", timeout=5).read().decode()


from test_painel import painel  # noqa: E402,F401 — fixture do servidor do painel

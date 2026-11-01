"""Fábrica: AGENTS.md/.cursor/rules no repositório do cliente só com lições evidenciadas e só por PR, e só quando o
conteúdo muda (arquivo de contexto redundante custa >20% sem ganho, estudo da ETH Zurich)."""
import subprocess
import time

import pytest

from circulo import contexto_cliente


def _git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def clone(tmp_path):
    remoto, pasta = tmp_path / "remoto.git", tmp_path / "cliente"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remoto))
    _git(tmp_path, "clone", "-q", str(remoto), str(pasta))
    _git(pasta, "checkout", "-q", "-b", "main")
    (pasta / "README.md").write_text("# cliente\n\nRode `pytest` para testar.\n", encoding="utf-8")
    _git(pasta, "add", "-A")
    _git(pasta, "commit", "-q", "-m", "inicial")
    _git(pasta, "push", "-q", "origin", "main")
    return pasta


class PRs:
    def __init__(self):
        self.abertos = []

    def __call__(self, clone, branch, base, titulo, corpo):
        self.abertos.append({"branch": branch, "base": base, "titulo": titulo, "corpo": corpo})
        return f"https://exemplo/pr/{len(self.abertos)}"


def _licao(store, sig, desc, status="evidenciada"):
    agora = time.time()
    store.x("INSERT INTO licoes(assinatura,ponto,classe,descricao,status,ocorrencias,reincidencias,created_at,updated_at) "
            "VALUES(?,?,?,?,?,1,0,?,?)", (sig, sig.split(":")[0], "estrutural", desc, status, agora, agora))


def test_sem_licao_evidenciada_nao_abre_pr_nem_escreve(circle, clone):
    _licao(circle.store, "loop:estagnado", "nada avançou em 10 giros", status="aberta")
    prs = PRs()
    assert contexto_cliente.sincronizar(circle.store, clone, "main", prs) is None
    assert prs.abertos == [] and not (clone / "AGENTS.md").exists()


def test_licao_nova_abre_um_pr_e_conteudo_igual_abre_zero(circle, clone):
    s, prs = circle.store, PRs()
    _licao(s, "ci:lint:B905", "zip() sem strict= quebra o lint B905")
    r = contexto_cliente.sincronizar(s, clone, "main", prs)
    assert len(prs.abertos) == 1 and r["pr"] == "https://exemplo/pr/1"
    [pr] = prs.abertos
    assert pr["base"] == "main" and pr["branch"].startswith("circulo/contexto-")
    agents = _git(clone, "show", f"origin/{pr['branch']}:AGENTS.md")
    assert "B905" in agents and len(agents.splitlines()) <= contexto_cliente.TETO_AGENTS == 40
    assert _git(clone, "branch", "--show-current") == "main"
    assert not (clone / "AGENTS.md").exists()                 # a base do clone não muda: só a branch do PR

    assert contexto_cliente.sincronizar(s, clone, "main", prs) is None   # mesmo conteúdo, PR já aberto
    _git(clone, "merge", "-q", f"origin/{pr['branch']}")
    _git(clone, "push", "-q", "origin", "main")
    assert contexto_cliente.sincronizar(s, clone, "main", prs) is None   # já está na base: diff vazio
    assert len(prs.abertos) == 1

    _licao(s, "ci:lint:F811", "redefinição de função quebra o lint F811")
    contexto_cliente.sincronizar(s, clone, "main", prs)
    assert len(prs.abertos) == 2 and "F811" in _git(clone, "show", f"origin/{prs.abertos[1]['branch']}:AGENTS.md")


def test_agents_md_fica_abaixo_do_teto_com_muitas_licoes(circle, clone):
    for i in range(120):
        _licao(circle.store, f"x:{i}", f"armadilha não padronizada número {i}")
    prs = PRs()
    contexto_cliente.sincronizar(circle.store, clone, "main", prs)
    agents = _git(clone, "show", f"origin/{prs.abertos[0]['branch']}:AGENTS.md")
    assert len(agents.splitlines()) <= 40


def test_edicoes_locais_do_clone_do_cliente_sobrevivem(circle, clone):
    _licao(circle.store, "ci:lint:B905", "zip() sem strict= quebra o lint B905")
    (clone / "README.md").write_text("# cliente\n\nedição local não commitada\n", encoding="utf-8")
    (clone / "rascunho.py").write_text("x = 1\n", encoding="utf-8")
    prs = PRs()
    contexto_cliente.sincronizar(circle.store, clone, "main", prs)
    assert len(prs.abertos) == 1
    assert "edição local não commitada" in (clone / "README.md").read_text(encoding="utf-8")
    assert (clone / "rascunho.py").read_text(encoding="utf-8") == "x = 1\n"
    assert "edição local" not in _git(clone, "show", f"origin/{prs.abertos[0]['branch']}:README.md")
    assert _git(clone, "branch", "--show-current") == "main" and not (clone / "AGENTS.md").exists()

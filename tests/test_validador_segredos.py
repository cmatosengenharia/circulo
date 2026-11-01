"""Pedido #827 (fatia 1): gate determinístico de segredos no diff do PR, no Validador e nos portões antes do PR.

Os segredos de mentira são montados por concatenação: assim este arquivo não tem nenhum segredo em claro e o
próprio gate não o reprova."""
import subprocess

import pytest

from circulo import segredos, validador
from circulo.neuronios import portoes_natos_pr

AWS = "AKIA" + "Q7W3E9R2T5Y8U1I4"
GITHUB = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
ANTHROPIC = "sk-ant-" + "api03-" + "Zx9Yw8Vu7Ts6Rq5Po4Nm3Lk2"
CHAVE = "-----BEGIN " + "RSA PRIVATE KEY-----"
SENHA = "Pr0d" + "Senha9x7Kq2Lm4Zt"
CASOS = {
    "aws": (f'AWS_KEY = "{AWS}"\n', AWS),
    "github": (f'cabecalho = {{"Authorization": "token {GITHUB}"}}\n', GITHUB),
    "anthropic": (f'cliente = Anthropic(api_key="{ANTHROPIC}")\n', ANTHROPIC),
    "chave_privada": (f'PEM = """{CHAVE}\nMIIEpAIBAAKCAQEA\n"""\n', None),
    "senha": (f'db_password = "{SENHA}"\n', SENHA),
}


def _repo(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=wt, check=True)
    (wt / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base"], cwd=wt, check=True)
    return wt, subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, capture_output=True, text=True).stdout.strip()


def _aprova(system, prompt):
    return '{"aprovado": true, "problemas": [], "risco": "baixo"}'


@pytest.mark.parametrize("caso", sorted(CASOS))
def test_validador_simulado_reprova_segredo_em_claro_em_todas_as_execucoes_com_o_valor_mascarado(circle, tmp_path, caso):
    wt, base = _repo(tmp_path)
    codigo, valor = CASOS[caso]
    (wt / "config.py").write_text(codigo)
    for _ in range(20):                                       # 100% das execuções, mesmo com o revisor LLM aprovando
        v = validador.revisar_pr(circle.ctx, wt, base, {"id": 7, "titulo": "x"}, chamar=_aprova)
        assert not v["aprovado"]
        achado = [p for p in v["problemas"] if p.startswith("segredo em claro")]
        assert achado and "config.py" in achado[0]
        assert valor is None or (valor not in achado[0] and valor[:4] in achado[0])   # o trecho, com o valor mascarado
    r = circle.store.one("SELECT ok, motivo FROM verificacoes WHERE ponto=? ORDER BY id DESC", (segredos.PONTO,))
    assert r["ok"] == 0 and "config.py" in r["motivo"] and (valor is None or valor not in r["motivo"])


def test_diff_limpo_passa_sem_falso_positivo(circle, tmp_path):
    wt, base = _repo(tmp_path)
    (wt / "config.py").write_text('token_env = "CIRCULO_GITHUB_TOKEN"\nsenha = os.environ["SENHA"]\n'
                                  'api_key = "<sua chave aqui>"\npassword = "example-password-123456"\nsha = "9f2c4e1a7b3d"\n')
    for _ in range(20):
        v = validador.revisar_pr(circle.ctx, wt, base, {"id": 7, "titulo": "x"}, chamar=_aprova)
        assert v["aprovado"] and v["problemas"] == []


def test_nenhum_falso_positivo_no_proprio_repositorio():
    arquivos = subprocess.run(["git", "ls-files", "circulo", "tests"], capture_output=True, text=True).stdout.split()
    adicionadas = {}
    for f in arquivos:
        try:
            adicionadas[f] = open(f, encoding="utf-8").read().splitlines()
        except (OSError, UnicodeDecodeError):
            continue
    assert segredos.internas(adicionadas) == []


def test_portao_antes_do_pr_reprova_segredo_mesmo_depois_da_correcao_local():
    arquivos = [{"filename": "tests/test_a.py", "additions": 1, "deletions": 0}]
    r = {x.portao: x for x in portoes_natos_pr(arquivos, {"tests/test_a.py": [f'K = "{AWS}"']})}
    assert not r["sem segredo em claro"].ok and AWS not in r["sem segredo em claro"].motivo
    assert {x.portao: x.ok for x in portoes_natos_pr(arquivos, {"tests/test_a.py": ["x = 1"]})}["sem segredo em claro"]


def test_scanner_externo_ausente_registra_aviso_e_segue(circle, monkeypatch):
    monkeypatch.setattr(segredos.shutil, "which", lambda nome: None)
    assert segredos.verificar(circle.ctx, {"app.py": ["x = 1"]}) == []
    r = circle.store.one("SELECT ok, motivo FROM verificacoes WHERE ponto=? ORDER BY id DESC", (segredos.PONTO_SCANNER,))
    assert r["ok"] == 0 and "gitleaks" in r["motivo"]
    assert circle.store.one("SELECT COUNT(*) n FROM roadmap WHERE origem='erro'")["n"] == 0     # aviso, não lição


def test_achado_do_gitleaks_reprova_com_o_trecho_mascarado(circle):
    segredo = "zq81" + "Hh2Kk3Ll4"

    def gitleaks(adicionadas):
        return [{"arquivo": "app.py", "regra": "gitleaks:generic-api-key", "linha": 2, "segredo": segredo}]
    problemas = segredos.verificar(circle.ctx, {"app.py": ["x = 1", f"chave({segredo!r})"]}, externo=gitleaks)
    assert len(problemas) == 1 and "gitleaks:generic-api-key" in problemas[0] and "app.py" in problemas[0]
    assert segredo not in problemas[0] and "zq81" in problemas[0]

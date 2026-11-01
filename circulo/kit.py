"""`circulo init`: o motor do loop cuidando de QUALQUER repositório, não só deste.

O que é motor (Jev First, SRE, Médico, memória do time, Escalador, painel, Developer, gate) fica igual; o que é do
repositório — nome, constituição (arquivos que o Developer nunca toca), comando de testes e de lint, checks que o
gate exige, o pedido inicial — vem do próprio repositório, em `[tool.circulo]` no `pyproject.toml` dele (ou dos
padrões), e `circulo init <pasta>` grava tudo no arquivo de configuração do loop e deixa o repositório pronto:

    circulo init ~/Projects/meu-repo --pedido "entregar o que eu pedir com evidência, pelo menor custo"
    circulo configurar      # chaves (Jev, LLM, GitHub) — só você digita
    circulo diagnostico
    circulo instalar        # 24/7

Para o loop, o repositório é um "kit": `kit.carregar(pasta)` lê o que ele declara. Chaves nunca passam por aqui.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

PADRAO_PROTEGIDOS = (".github/",)
PADRAO_TESTES = "python -m pytest -q -x"
PADRAO_CHECKS = ("Testes",)
PADRAO_PEDIDO = "entregar qualquer pedido do humano com evidência, pelo menor custo, sem babá: registrar todo erro, aprender com ele e se autocorrigir"
# As etapas da esteira onde um framework de governança (ex.: GAIA) entra como portão: `[tool.circulo.etapas]` declara
# os comandos de cada uma; sem declaração a etapa fica vazia e passa — nenhuma regra é inventada.
ETAPAS = ("pedido", "estudo", "desenvolvimento", "pr", "merge")

WORKFLOW = """name: CI

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  testes:
    name: Testes
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e . || pip install -r requirements.txt || true
      - run: {testes}
"""


@dataclass
class Kit:
    nome: str
    pasta: str
    repo: str | None = None                      # owner/repo no GitHub
    protegidos: tuple[str, ...] = PADRAO_PROTEGIDOS
    testes: str = PADRAO_TESTES
    lint: str | None = None
    checks: tuple[str, ...] = PADRAO_CHECKS
    pedido: str = PADRAO_PEDIDO
    etapas: dict[str, tuple[str, ...]] = field(default_factory=lambda: {e: () for e in ETAPAS})
    avisos: list[str] = field(default_factory=list)

    def env(self) -> dict[str, str]:
        """As variáveis que o loop lê (o `configurar` grava no arquivo; nunca chaves)."""
        d = {"CIRCULO_REPO_DIR": self.pasta, "CIRCULO_PROTEGIDOS": ",".join(self.protegidos), "CIRCULO_TEST_CMD": self.testes,
             "CIRCULO_REQUIRED_CHECKS": ",".join(self.checks), "CIRCULO_NOME": self.nome, "CIRCULO_PEDIDO": self.pedido,
             "CIRCULO_ENTRADA": "equipe"}
        if self.repo:
            d["CIRCULO_REPO"] = self.repo
        if self.lint:
            d["CIRCULO_LINT_CMD"] = self.lint
        return d


def _remoto(pasta: Path) -> str | None:
    try:
        url = subprocess.run(["git", "-C", str(pasta), "remote", "get-url", "origin"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def carregar(pasta: str | Path, pedido: str | None = None, nome: str | None = None) -> Kit:
    pasta = Path(pasta).expanduser().resolve()
    cfg: dict = {}
    pp = pasta / "pyproject.toml"
    avisos = []
    if pp.exists():
        try:
            cfg = tomllib.loads(pp.read_text(encoding="utf-8")).get("tool", {}).get("circulo", {}) or {}
        except (tomllib.TOMLDecodeError, OSError) as exc:
            avisos.append(f"pyproject.toml não pôde ser lido ({exc}); usando padrões")
    else:
        avisos.append("sem pyproject.toml: o Developer vai rodar os testes com o comando padrão; declare [tool.circulo] para ajustar")
    if not (pasta / ".git").exists():
        avisos.append("a pasta não é um repositório git: o Developer precisa de um clone com remoto no GitHub")
    if not (pasta / "tests").exists() and not list(pasta.glob("test*")):
        avisos.append("sem pasta tests/: o gate exige teste novo em cada PR do Developer")
    k = Kit(nome=nome or cfg.get("nome") or pasta.name, pasta=str(pasta), repo=cfg.get("repo") or _remoto(pasta),
            protegidos=tuple(cfg.get("protegidos", PADRAO_PROTEGIDOS)) or PADRAO_PROTEGIDOS, testes=cfg.get("testes", PADRAO_TESTES),
            lint=cfg.get("lint"), checks=tuple(cfg.get("checks", PADRAO_CHECKS)) or PADRAO_CHECKS,
            pedido=pedido or cfg.get("pedido") or PADRAO_PEDIDO, avisos=avisos)
    for etapa, comandos in (cfg.get("etapas") or {}).items():
        if etapa in k.etapas:
            k.etapas[etapa] = tuple(comandos)
        else:
            k.avisos.append(f"etapa {etapa!r} em [tool.circulo.etapas] não é da esteira ({', '.join(ETAPAS)}): ignorada")
    if not k.repo:
        k.avisos.append("remoto do GitHub não encontrado: defina `repo = \"owner/nome\"` em [tool.circulo] ou CIRCULO_REPO")
    return k


def argv(cmd: str) -> list[str]:
    """O comando declarado como argv; `python` vira o intérprete do loop (`python` pode nem existir no PATH)."""
    a = shlex.split(cmd)
    if a and a[0] in ("python", "python3"):
        a[0] = sys.executable
    return a


def rodar(k: Kit, etapa: str, cwd: str | Path | None = None, timeout: int = 600) -> list[dict]:
    """Roda em `cwd` (padrão: a pasta do repositório) cada comando declarado da etapa: {comando, ok, codigo, saida}."""
    if etapa not in k.etapas:
        raise ValueError(f"etapa {etapa!r} não é da esteira: {', '.join(ETAPAS)}")
    out = []
    for cmd in k.etapas[etapa]:
        try:
            p = subprocess.run(argv(cmd), cwd=str(cwd or k.pasta), capture_output=True, text=True, timeout=timeout)
            codigo, saida = p.returncode, (p.stdout + p.stderr).strip()
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            codigo, saida = None, str(exc)
        out.append({"comando": cmd, "ok": codigo == 0, "codigo": codigo, "saida": saida[-500:]})
    return out


def checar(k: Kit, etapa: str, cwd: str | Path | None = None, timeout: int = 600) -> list[str]:
    """O portão da etapa: os comandos declarados que falharam (vazio = passa)."""
    return [r["comando"] for r in rodar(k, etapa, cwd, timeout) if not r["ok"]]


def preparar_repositorio(k: Kit, escrever_ci: bool = True) -> list[str]:
    """Deixa o repositório pronto para o loop: workflow de CI com o job que o gate exige (se não houver nenhum),
    CODEOWNERS com a constituição dele. Não mexe em código."""
    feitos = []
    pasta = Path(k.pasta)
    wf = pasta / ".github" / "workflows"
    if escrever_ci and not (wf.exists() and any(wf.glob("*.yml"))):
        wf.mkdir(parents=True, exist_ok=True)
        (wf / "circulo.yml").write_text(WORKFLOW.format(testes=k.testes), encoding="utf-8")
        feitos.append(".github/workflows/circulo.yml")
    co = pasta / ".github" / "CODEOWNERS"
    if not co.exists():
        dono = f"@{k.repo.split('/')[0]}" if k.repo else "@dono"
        co.parent.mkdir(parents=True, exist_ok=True)
        co.write_text("# Constituição do loop neste repositório: só uma pessoa aprova mudanças aqui.\n" +
                      "".join(f"/{p} {dono}\n" for p in k.protegidos), encoding="utf-8")
        feitos.append(".github/CODEOWNERS")
    return feitos


def gravar_env(k: Kit, env_file: Path) -> list[str]:
    """Grava as variáveis do kit no arquivo de configuração do loop, preservando o que já existe (as chaves, acima de tudo)."""
    from .configuracao import configurar
    path = configurar(env_file)
    linhas = path.read_text(encoding="utf-8").splitlines()
    novos = k.env()
    vistos = set()
    out = []
    for linha in linhas:
        chave = linha.split("=", 1)[0].strip() if "=" in linha and not linha.startswith("#") else None
        if chave in novos:
            out.append(f"{chave}={novos[chave]}")
            vistos.add(chave)
        else:
            out.append(linha)
    for chave, v in novos.items():
        if chave not in vistos:
            out.append(f"{chave}={v}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return sorted(novos)


def init(pasta: str, pedido: str | None = None, nome: str | None = None, env_file: Path | None = None, escrever_ci: bool = True) -> dict:
    from .configuracao import ENV_FILE
    k = carregar(pasta, pedido, nome)
    feitos = preparar_repositorio(k, escrever_ci)
    gravadas = gravar_env(k, env_file or ENV_FILE)
    return {"kit": asdict(k), "arquivos": feitos, "variaveis": gravadas,
            "proximos": ["circulo configurar  (chaves: Jev, LLM, GitHub — só você digita)", "circulo diagnostico", "circulo instalar  (24/7)"]}


def resumo_json(r: dict) -> str:
    return json.dumps(r, ensure_ascii=False, indent=1)


__all__ = ["ETAPAS", "Kit", "carregar", "argv", "rodar", "checar", "preparar_repositorio", "gravar_env", "init"]

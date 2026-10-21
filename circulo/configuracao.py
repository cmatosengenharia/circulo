"""Configuração única: o único momento em que o loop precisa de você.

- `circulo configurar`  cria o arquivo de configuração (~/.config/circulo/env) com as chaves em branco, permissão 600.
- `circulo diagnostico` diz, peça por peça, o que está ligado, o que está parado e por quê (sem gastar nada por padrão).
- `circulo instalar`    registra o loop para rodar 24/7 (launchd no macOS, systemd no Linux) e já sobe o painel.

O loop carrega o arquivo de configuração sozinho ao iniciar, então launchd/systemd não precisam de `export`.
O estado da configuração vai para o banco, e o painel mostra o que falta — sem você abrir terminal.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ENV_FILE = Path(os.environ.get("CIRCULO_ENV", Path.home() / ".config" / "circulo" / "env"))
CHAVES = (
    ("TYPESAFE_API_KEY", "Jev real (TypeSafe). Sem ela: decisor local com o mesmo contrato."),
    ("CIRCULO_CONTA", "Opcional: 'max' roda tudo na assinatura do Claude (Max/Pro) pelo Claude Code, sem a API; o loop cuida do login."),
    ("CLAUDE_CODE_OAUTH_TOKEN", "Assinatura sem queda de sessão: rode `claude setup-token` no Mac (vale 1 ano) e cole aqui."),
    ("ANTHROPIC_API_KEY", "LLM: motor das missões, pesquisa na web, evolução do harness."),
    ("ANTHROPIC_WORKSPACE_ID", "Só se a chave da Anthropic não for de um workspace: o ID do workspace (wrkspc_...). Chave criada dentro de um workspace não precisa."),
    ("CIRCULO_LLM_PROVEDOR", "Opcional: qual API de IA a LLM usa — anthropic (padrão), openai, gemini, groq, mistral, deepseek, xai, openrouter, together, ollama ou compat."),
    ("CIRCULO_LLM_API_KEY", "Opcional: chave do provedor escolhido (ou a variável própria dele, ex.: OPENAI_API_KEY). Ollama local não precisa."),
    ("CIRCULO_LLM_BASE_URL", "Opcional: endereço da API no contrato OpenAI (obrigatório com provedor compat; ex.: http://127.0.0.1:1234/v1)."),
    ("CIRCULO_LLM_MODELO_PEQUENA", "Opcional: modelo do porte pequeno no provedor escolhido (padrão por provedor)."),
    ("CIRCULO_LLM_MODELO_GRANDE", "Opcional: modelo do porte grande no provedor escolhido (padrão por provedor)."),
    ("GITHUB_TOKEN", "Token fine-grained só do repo circulo (Contents, Pull requests, Checks: leitura e escrita)."),
    ("CIRCULO_REPO", "Repositório, ex.: cmatosengenharia/circulo"),
    ("CIRCULO_REPO_DIR", "Clone local do repo para o Developer corrigir o próprio código."),
    ("CIRCULO_DECISOR", "Opcional: 'aluno' faz o decisor local (aluno destilado onde provou + regra) responder mesmo com a chave do Jev."),
    ("CIRCULO_MEMORIA_EXTERNA", "Opcional: caminhos (vírgula) de circulo.db de outros loops; lições, itens e estudos deles entram na memória do time (só leitura)."),
    ("OTEL_EXPORTER_OTLP_ENDPOINT", "Opcional: coletor OpenTelemetry (ex.: Grafana Cloud, Tempo, Jaeger) que recebe os traços dos giros por OTLP/HTTP."),
    ("OTEL_EXPORTER_OTLP_HEADERS", "Opcional: cabeçalhos do coletor no formato do OpenTelemetry (ex.: Authorization=Basic%20...)."),
)
LABEL = "com.circulo.loop"


# ------------------------------------------------------------------ arquivo de configuração
def carregar_env(path: Path = ENV_FILE) -> list[str]:
    """Carrega KEY=valor sem sobrescrever o ambiente. Devolve as chaves carregadas (nunca os valores)."""
    path = Path(path)
    if not path.exists():
        return []
    lidas = []
    for linha in path.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        k, v = linha.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v
            lidas.append(k)
    return lidas


def configurar(path: Path = ENV_FILE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existentes = {}
    if path.exists():
        for linha in path.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                k, v = linha.split("=", 1)
                existentes[k.strip()] = v.strip()
    linhas = ["# Configuração única do Círculo. Preencha e salve; o loop lê este arquivo sozinho ao iniciar.",
              "# Nada aqui é enviado para lugar nenhum além das próprias APIs.", ""]
    for k, ajuda in CHAVES:
        linhas += [f"# {ajuda}", f"{k}={existentes.get(k, '')}", ""]
    path.write_text("\n".join(linhas), encoding="utf-8")
    path.chmod(0o600)
    return path


# ------------------------------------------------------------------ diagnóstico
@dataclass
class Peca:
    nome: str
    estado: str          # ligado | parado | aviso
    detalhe: str
    como_ligar: str = ""


def _erro(exc: Exception) -> str:
    """Mensagem de erro inteira o bastante para saber o que fazer (inclui o corpo da resposta HTTP)."""
    msg = f"{type(exc).__name__}: {exc}"
    corpo = getattr(exc, "body", None)
    if corpo is None and hasattr(exc, "read"):
        try:
            corpo = exc.read().decode("utf-8", "replace")
        except Exception:
            corpo = None
    if corpo and str(corpo)[:60] not in msg:
        msg += f" · {corpo}"
    return msg[:600]


def _jev_ok() -> tuple[bool, str]:
    from .decision import SN, JevHttpClient, Question
    try:
        out, _ = JevHttpClient(os.environ["TYPESAFE_API_KEY"], timeout=8).ask_many(
            {"teste": "diagnóstico do círculo"}, {"ok": Question("noul", "Este é um teste de conexão?",
                                                                  SN("`teste` diz que é um diagnóstico ou teste", "é um pedido real de trabalho"))})
        return True, f"respondeu (noul {float(out['ok'].value):.2f})"
    except Exception as exc:
        return False, f"falhou: {type(exc).__name__}: {str(exc)[:120]}"


def _llm_ok() -> tuple[bool, str]:
    try:
        from .llm import build_llm
        from .policy import DEFAULT_POLICY
        modelo = DEFAULT_POLICY["harness"]["models"]["pequena"]
        llm = build_llm()
        if llm is None:
            return False, "provedor sem chave ou sem endereço"
        r = llm.generate(system="Responda só: ok", prompt="ok", model=modelo, max_tokens=5)
        return True, f"respondeu ({r.model}, {r.tokens} tokens)"
    except Exception as exc:
        dica =(" → crie a chave dentro de um workspace no Console, ou preencha ANTHROPIC_WORKSPACE_ID"
                if "anthropic-workspace-id" in str(exc) else "")
        return False, f"falhou: {_erro(exc)}{dica}"


def _github_ok() -> tuple[bool, str]:
    """Só leitura: lista PRs e lê os checks da main. Não cria nada."""
    etapa = "conectar"
    try:
        from .merge_gate import GitHubREST
        gh = GitHubREST(os.environ["CIRCULO_REPO"], os.environ["GITHUB_TOKEN"])
        etapa = "listar PRs (permissão Pull requests)"
        prs = gh.open_prs()
        etapa = "ler os checks da main (permissão Checks ou Actions, leitura)"
        checks = gh.check_runs("main")
        return True, f"acesso ao repo ok ({len(prs)} PR abertos, {len(checks)} checks na main)"
    except Exception as exc:
        return False, f"falhou ao {etapa}: {_erro(exc)}"


def diagnostico(testar_conexoes: bool = False) -> list[Peca]:
    """Sem `testar_conexoes`, não gasta nada: só confere o que está configurado."""
    p: list[Peca] = []
    v = sys.version_info
    p.append(Peca("Python", "ligado" if v >= (3, 11) else "parado", f"{v.major}.{v.minor}.{v.micro}",
                  "Instale Python 3.11 ou mais novo." if v < (3, 11) else ""))
    p.append(Peca("Arquivo de configuração", "ligado" if ENV_FILE.exists() else "aviso",
                  str(ENV_FILE) if ENV_FILE.exists() else "ainda não existe",
                  "" if ENV_FILE.exists() else "Rode `circulo configurar` e preencha as chaves."))
    if os.environ.get("TYPESAFE_API_KEY"):
        ok, det = _jev_ok() if testar_conexoes else (True, "chave presente (use --testar para chamar a API)")
        p.append(Peca("Jev (decisões)", "ligado" if ok else "parado", det, "" if ok else "Confira TYPESAFE_API_KEY."))
    else:
        p.append(Peca("Jev (decisões)", "aviso", "sem chave: usando o decisor local (mesmo contrato, menos preciso)",
                      "Preencha TYPESAFE_API_KEY."))
    tem_sdk = True
    try:
        import anthropic  # noqa: F401
    except ImportError:
        tem_sdk = False
    from .llm import chave_do_provedor, descricao, provedor
    prov, var = provedor(), chave_do_provedor()
    if prov == "assinatura":
        from . import conta
        st = conta.status() if testar_conexoes else {"logado": True, "metodo": "não testado (use --testar)"}
        p.append(Peca("Motor das missões (LLM)", "ligado" if st["logado"] else "parado", f"assinatura do Claude · login {st['metodo']}",
                      "" if st["logado"] else "Rode `claude auth login` no Mac, ou `claude setup-token` e cole o token no painel."))
    elif prov != "anthropic":
        ok, det = _llm_ok() if testar_conexoes else (bool(not var or os.environ.get(var) or os.environ.get("CIRCULO_LLM_API_KEY")), descricao())
        p.append(Peca("Motor das missões (LLM)", "ligado" if ok else "parado", det, "" if ok else f"Preencha {var or 'CIRCULO_LLM_BASE_URL'}."))
    elif not os.environ.get("ANTHROPIC_API_KEY"):
        p.append(Peca("Motor das missões (LLM)", "parado", "sem ANTHROPIC_API_KEY: missões ficam registradas, sem construir",
                      "Preencha ANTHROPIC_API_KEY."))
    elif not tem_sdk:
        p.append(Peca("Motor das missões (LLM)", "parado", "SDK da Anthropic não instalado", 'Rode `pip install -e ".[llm]"`.'))
    else:
        ok, det = _llm_ok() if testar_conexoes else (True, "chave e SDK presentes (use --testar para chamar a API)")
        p.append(Peca("Motor das missões (LLM)", "ligado" if ok else "parado", det, "" if ok else "Confira ANTHROPIC_API_KEY."))
    gh = bool(os.environ.get("GITHUB_TOKEN") and os.environ.get("CIRCULO_REPO"))
    if not gh:
        p.append(Peca("QA e release (merge)", "parado", "sem GITHUB_TOKEN/CIRCULO_REPO", "Preencha GITHUB_TOKEN e CIRCULO_REPO."))
    else:
        ok, det = _github_ok() if testar_conexoes else (True, "PRs de agente avaliados e mergeados sozinhos (use --testar para chamar a API)")
        p.append(Peca("QA e release (merge)", "ligado" if ok else "parado", det,
                      "" if ok else "Confira o GITHUB_TOKEN: só o repo circulo, Contents e Pull requests em escrita; Checks (ou Actions) em leitura."))
    repo = os.environ.get("CIRCULO_REPO_DIR")
    claude = shutil.which(os.environ.get("CIRCULO_CODE_AGENT", "claude"))
    dev_ok = bool(repo and (Path(repo) / ".git").exists() and claude)
    falta = [x for x, ok in (("CIRCULO_REPO_DIR (clone do repo)", repo and (Path(repo) / ".git").exists()),
                              ("Claude Code (comando `claude`)", claude)) if not ok]
    p.append(Peca("Desenvolvedor (corrige o próprio código)", "ligado" if dev_ok else "parado",
                  "pega erros e pedidos do roteiro e abre PR" if dev_ok else "falta: " + ", ".join(falta),
                  "" if dev_ok else "Clone o repo, aponte CIRCULO_REPO_DIR e instale o Claude Code."))
    sistema = platform.system()
    p.append(Peca("Rodando 24/7", "ligado" if servico_instalado() else "aviso",
                  f"serviço registrado no {'launchd' if sistema == 'Darwin' else 'systemd'}" if servico_instalado()
                  else "ainda não instalado como serviço", "" if servico_instalado() else "Rode `circulo instalar`."))
    return p


def registrar(store, pecas: list[Peca]) -> None:
    """Grava o estado real no banco (o painel mostra) e fecha sozinho os itens de configuração do roteiro."""
    store.set("configuracao", {"em": time.time(), "pecas": [asdict(x) for x in pecas]})
    estado = {x.nome: x.estado for x in pecas}
    chaves_ok = estado.get("Motor das missões (LLM)") == "ligado" and estado.get("Jev (decisões)") == "ligado"
    if chaves_ok and estado.get("Desenvolvedor (corrige o próprio código)") == "ligado" and estado.get("QA e release (merge)") == "ligado":
        store.x("UPDATE roadmap SET status='feito', evidencia='diagnóstico: tudo ligado' WHERE titulo LIKE 'Ligar as chaves%'")
    elif chaves_ok:
        store.x("UPDATE roadmap SET status='parcial', evidencia='diagnóstico: Jev e LLM ligados; falta Developer/Gate · depende de você' "
                "WHERE titulo LIKE 'Ligar as chaves%'")
    if estado.get("Rodando 24/7") == "ligado":
        store.x("UPDATE roadmap SET status='feito', evidencia='diagnóstico: serviço instalado' WHERE titulo='Rodar 24/7'")


# ------------------------------------------------------------------ 24/7
def _plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / "circulo.service"


def _comando() -> list[str]:
    """O executável `circulo` do próprio ambiente. Não usa `python -m`: ele põe a pasta atual no sys.path,
    e uma pasta `circulo/` ao lado (o clone do repo) esconderia o pacote instalado."""
    exe = Path(sys.executable).parent / "circulo"
    return [str(exe)] if exe.exists() else [sys.executable, "-m", "circulo"]


def servico_instalado() -> bool:
    return _plist_path().exists() if platform.system() == "Darwin" else _unit_path().exists()


def plist(data_dir: Path, porta: int) -> str:
    data_dir = Path(data_dir).resolve()
    args = [*_comando(), "--data", str(data_dir), "run", "--painel", "--porta", str(porta)]
    arr = "\n".join(f"    <string>{a}</string>" for a in args)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>WorkingDirectory</key><string>{data_dir}</string>
  <key>ProgramArguments</key>
  <array>
{arr}
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>CIRCULO_ENV</key><string>{ENV_FILE}</string><key>PATH</key><string>{os.environ.get("PATH", "/usr/bin:/bin")}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>{data_dir}/loop.log</string>
  <key>StandardErrorPath</key><string>{data_dir}/loop.err</string>
</dict>
</plist>
"""


def unit(data_dir: Path, porta: int) -> str:
    data_dir = Path(data_dir).resolve()
    return f"""[Unit]
Description=Circulo autoevolutivo Jev First
After=network-online.target

[Service]
Environment=CIRCULO_ENV={ENV_FILE}
Environment=PATH={os.environ.get("PATH", "/usr/bin:/bin")}
ExecStart={" ".join(_comando())} --data {data_dir} run --painel --porta {porta}
WorkingDirectory={data_dir}
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
"""


def instalar(data_dir: Path, porta: int = 8765, aplicar: bool = True) -> tuple[Path, list[str]]:
    """Escreve o serviço e (se `aplicar`) liga. Devolve o arquivo e os comandos executados."""
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    if platform.system() == "Darwin":
        dest, conteudo = _plist_path(), plist(data_dir, porta)
        cmds = [["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"],
                ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(dest)]]
    else:
        dest, conteudo = _unit_path(), unit(data_dir, porta)
        cmds = [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", "circulo.service"]]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(conteudo, encoding="utf-8")
    feitos = []
    if aplicar:
        for c in cmds:
            subprocess.run(c, capture_output=True, text=True)   # bootout falha se não estava rodando: tudo bem
            feitos.append(" ".join(c))
    return dest, feitos


def desinstalar(aplicar: bool = True) -> Path | None:
    if platform.system() == "Darwin":
        dest = _plist_path()
        if aplicar:
            subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    else:
        dest = _unit_path()
        if aplicar:
            subprocess.run(["systemctl", "--user", "disable", "--now", "circulo.service"], capture_output=True)
    if dest.exists():
        arquivo = dest.with_suffix(dest.suffix + ".desativado")
        dest.rename(arquivo)   # não apaga: fica guardado ao lado
        return arquivo
    return None


def imprimir(pecas: list[Peca]) -> str:
    simb = {"ligado": "●", "parado": "○", "aviso": "◐"}
    out = []
    for x in pecas:
        out.append(f"{simb[x.estado]} {x.nome}: {x.detalhe}")
        if x.como_ligar:
            out.append(f"    → {x.como_ligar}")
    return "\n".join(out)


def resumo_json(pecas: list[Peca]) -> str:
    return json.dumps([asdict(x) for x in pecas], ensure_ascii=False, indent=2)

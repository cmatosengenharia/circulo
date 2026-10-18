"""Cofre de chaves: o cadastro das integrações sai do arquivo de texto e vai para o cofre do sistema.

Onde a chave fica (escolhido sozinho, ou por CIRCULO_COFRE=keychain|secret-service|arquivo):
- macOS: **Keychain** (cofre criptografado do sistema, item "circulo" por chave). O valor vai para o comando
  `security` pelo stdin (modo interativo `-i`), nunca na linha de comando: não aparece no `ps`.
- Linux com `secret-tool` (GNOME Keyring/KWallet): Secret Service, também via stdin.
- Nos outros casos: o arquivo de configuração com permissão 600 (o comportamento anterior).

Garantias do cadastro (painel):
- a API NUNCA devolve o valor de uma chave: só se está cadastrada, onde, os 4 últimos caracteres e o teste;
- cadastrar, trocar ou remover exige o cabeçalho do painel, origem e Host locais (contra outro site e DNS rebinding);
- cada mudança vira alerta ("Você trocou a chave X, final abcd") e reinicia o loop limpo para valer;
- mover as chaves do arquivo para o Keychain é um botão seu: o loop confere a leitura no cofre antes de apagar
  o valor do arquivo.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path

SERVICO = "circulo"
NOME_VALIDO = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
SEGREDO = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|SENHA")


def e_segredo(nome: str) -> bool:
    return bool(SEGREDO.search(nome))


def mascarar(valor: str | None) -> str | None:
    if not valor:
        return None
    return "…" + valor[-4:] if len(valor) > 8 else "…"


# ------------------------------------------------------------------ backends

class Arquivo:
    """Arquivo KEY=valor com permissão 600 (o env de sempre)."""
    nome = "arquivo"

    def __init__(self, path: Path):
        self.path = Path(path)

    def _ler(self) -> list[str]:
        return self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []

    def ler(self, chave: str) -> str | None:
        for linha in self._ler():
            if "=" in linha and not linha.lstrip().startswith("#"):
                k, v = linha.split("=", 1)
                if k.strip() == chave:
                    v = v.strip().strip('"').strip("'")
                    return v or None
        return None

    def gravar(self, chave: str, valor: str | None) -> None:
        linhas, achou = self._ler(), False
        for i, linha in enumerate(linhas):
            if "=" in linha and not linha.lstrip().startswith("#") and linha.split("=", 1)[0].strip() == chave:
                linhas[i] = f"{chave}={valor or ''}"
                achou = True
        if not achou:
            linhas.append(f"{chave}={valor or ''}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        self.path.chmod(0o600)

    def remover(self, chave: str) -> None:
        self.gravar(chave, None)


def _aspas(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


class Keychain:
    """Keychain do macOS pelo comando `security`; o valor vai pelo stdin (não aparece no ps)."""
    nome = "keychain"

    def __init__(self, conta_prefixo: str = ""):
        self.prefixo = conta_prefixo

    @staticmethod
    def disponivel() -> bool:
        return platform.system() == "Darwin" and shutil.which("security") is not None

    def _rodar(self, args: list[str], entrada: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["security", *args], input=entrada, capture_output=True, text=True, timeout=20)

    def ler(self, chave: str) -> str | None:
        p = self._rodar(["find-generic-password", "-s", SERVICO, "-a", self.prefixo + chave, "-w"])
        return p.stdout.rstrip("\n") or None if p.returncode == 0 else None

    def gravar(self, chave: str, valor: str | None) -> None:
        if not valor:
            return self.remover(chave)
        cmd = f"add-generic-password -U -s {SERVICO} -a {_aspas(self.prefixo + chave)} -l {_aspas('Círculo · ' + chave)} -w {_aspas(valor)}\n"
        p = self._rodar(["-i"], cmd)
        if p.returncode != 0 or self.ler(chave) != valor:
            raise RuntimeError("o Keychain recusou a gravação")

    def remover(self, chave: str) -> None:
        self._rodar(["delete-generic-password", "-s", SERVICO, "-a", self.prefixo + chave])


class SecretService:
    """GNOME Keyring/KWallet pelo `secret-tool`; o valor vai pelo stdin."""
    nome = "secret-service"

    @staticmethod
    def disponivel() -> bool:
        return platform.system() == "Linux" and shutil.which("secret-tool") is not None and bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))

    def ler(self, chave: str) -> str | None:
        p = subprocess.run(["secret-tool", "lookup", "servico", SERVICO, "chave", chave], capture_output=True, text=True, timeout=20)
        return p.stdout.rstrip("\n") or None if p.returncode == 0 else None

    def gravar(self, chave: str, valor: str | None) -> None:
        if not valor:
            return self.remover(chave)
        p = subprocess.run(["secret-tool", "store", "--label", f"Círculo · {chave}", "servico", SERVICO, "chave", chave],
                           input=valor, capture_output=True, text=True, timeout=20)
        if p.returncode != 0:
            raise RuntimeError("o Secret Service recusou a gravação")

    def remover(self, chave: str) -> None:
        subprocess.run(["secret-tool", "clear", "servico", SERVICO, "chave", chave], capture_output=True, timeout=20)


def cofre_padrao(env_file: Path):
    escolha = os.environ.get("CIRCULO_COFRE", "auto")
    if escolha == "keychain" or (escolha == "auto" and Keychain.disponivel()):
        return Keychain()
    if escolha == "secret-service" or (escolha == "auto" and SecretService.disponivel()):
        return SecretService()
    return Arquivo(env_file)


# ------------------------------------------------------------------ cadastro

class Cadastro:
    """O que o painel usa: lista, grava, remove e migra. Nunca devolve um valor de chave."""

    def __init__(self, store, env_file: Path, cofre=None):
        self.s = store
        self.env_file = Path(env_file)
        self.cofre = cofre or cofre_padrao(self.env_file)
        self.arquivo = Arquivo(self.env_file)

    def nomes(self) -> list[tuple[str, str]]:
        from .configuracao import CHAVES
        extras = [(n, a) for n, a in (self.s.get("integracoes_extra") or {}).items()]
        return list(CHAVES) + [x for x in extras if x[0] not in dict(CHAVES)]

    def _valor(self, nome: str) -> tuple[str | None, str | None]:
        """(valor, onde): o cofre tem prioridade sobre o arquivo."""
        if not isinstance(self.cofre, Arquivo):
            try:
                v = self.cofre.ler(nome)
            except Exception:  # noqa: BLE001
                v = None
            if v:
                return v, self.cofre.nome
        v = self.arquivo.ler(nome)
        return (v, "arquivo") if v else (None, None)

    def listar(self) -> list[dict]:
        cfg = self.s.get("configuracao") or {}
        testes = {p["nome"]: p for p in cfg.get("pecas", [])}
        out = []
        for nome, ajuda in self.nomes():
            v, onde = self._valor(nome)
            seg = e_segredo(nome)
            out.append({"nome": nome, "ajuda": ajuda, "segredo": seg, "cadastrada": bool(v), "onde": onde,
                        "final": mascarar(v) if seg else None, "valor": (v if (v and not seg) else None),
                        "cofre": self.cofre.nome})
        return out + [{"_testes": {k: {"estado": x["estado"], "detalhe": x["detalhe"]} for k, x in testes.items()},
                       "_testado_em": cfg.get("em")}]

    def gravar(self, nome: str, valor: str | None, ajuda: str = "") -> dict:
        if not NOME_VALIDO.match(nome or ""):
            raise ValueError("nome de chave inválido: use LETRAS_MAIUSCULAS, números e _ (3 a 64)")
        valor = (valor or "").strip()
        if valor and (len(valor) > 4096 or "\n" in valor):
            raise ValueError("valor inválido")
        if nome not in dict(self.nomes()):
            extras = self.s.get("integracoes_extra") or {}
            extras[nome] = (ajuda or "Integração cadastrada por você.")[:200]
            self.s.set("integracoes_extra", extras)
        antes, _ = self._valor(nome)
        self.cofre.gravar(nome, valor or None)
        if not isinstance(self.cofre, Arquivo) and self.arquivo.ler(nome):
            self.arquivo.gravar(nome, None)          # com cofre do sistema, nada fica em texto
        acao = "removeu" if not valor else ("trocou" if antes else "cadastrou")
        detalhe = f" (final {mascarar(valor)})" if valor and e_segredo(nome) else ""
        self._avisar(f"Você {acao} a chave {nome}{detalhe} no {self.cofre.nome}. O loop reinicia para valer.")
        self.s.set("config_alterada_em", time.time())
        return {"nome": nome, "acao": acao, "onde": self.cofre.nome if valor else None, "final": mascarar(valor) if e_segredo(nome) else None}

    def migrar(self) -> dict:
        """Botão seu: move do arquivo para o cofre; só apaga do arquivo depois de ler de volta igual no cofre."""
        if isinstance(self.cofre, Arquivo):
            return {"movidas": [], "motivo": "sem cofre do sistema disponível nesta máquina"}
        movidas = []
        for nome, _ in self.nomes():
            v = self.arquivo.ler(nome)
            if not v:
                continue
            self.cofre.gravar(nome, v)
            if self.cofre.ler(nome) == v:
                self.arquivo.gravar(nome, None)
                movidas.append(nome)
        if movidas:
            self._avisar(f"Chaves movidas do arquivo para o {self.cofre.nome}: {', '.join(movidas)}. O arquivo ficou sem valores.")
            self.s.set("config_alterada_em", time.time())
        return {"movidas": movidas}

    def carregar_no_ambiente(self) -> list[str]:
        """Ao iniciar: o que estiver no cofre entra no ambiente do loop (sem sobrescrever o que já veio de fora)."""
        lidas = []
        if isinstance(self.cofre, Arquivo):
            return lidas
        for nome, _ in self.nomes():
            if os.environ.get(nome):
                continue
            try:
                v = self.cofre.ler(nome)
            except Exception:  # noqa: BLE001
                v = None
            if v:
                os.environ[nome] = v
                lidas.append(nome)
        return lidas

    def _avisar(self, msg: str) -> None:
        try:
            from .projects import kit_project_id
            pid = kit_project_id(self.s, "circulo")
        except Exception:  # noqa: BLE001
            pid = None
        self.s.x("INSERT INTO alerts(kind,message,created_at,project_id) VALUES('controle',?,?,?)", (msg, time.time(), pid))

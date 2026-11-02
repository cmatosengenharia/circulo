# Instalação em 5 minutos

Versão: **1.76.0**. Precisa de Python 3.11+, git e, para o loop corrigir código, o Claude Code.

## 1. Instalar

```bash
git clone https://github.com/cmatosengenharia/circulo && cd circulo
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[llm]"
circulo --version
```

## 2. Conferir a máquina

```bash
circulo doctor
```

O `doctor` não gasta nada: confere cada peça e, para o que falta, diz o comando que corrige. Sai com código 1 enquanto faltar algo.

| Verificação | Se faltar |
|---|---|
| Python | Instale Python 3.11 ou mais novo (https://www.python.org/downloads/ ou `brew install python@3.12`) e recrie o venv. |
| git | Instale o git (`brew install git` no macOS, `sudo apt install git` no Linux). |
| Claude Code | Instale o Claude Code (`npm install -g @anthropic-ai/claude-code`) e entre com `claude auth login`. |
| Jev | Rode `circulo configurar` e preencha TYPESAFE_API_KEY (sem ela o loop usa o decisor local, menos preciso). |
| GitHub | Rode `circulo configurar` e preencha GITHUB_TOKEN e CIRCULO_REPO (token fine-grained: Contents e Pull requests em escrita, Checks em leitura). |

## 3. Chaves

```bash
circulo configurar     # cria ~/.config/circulo/env (permissão 600): preencha e salve
circulo doctor         # de novo, até tudo ✓
```

## 4. Repositório (opcional)

```bash
circulo init ~/Projects/meu-repo --pedido "o que o loop deve fazer primeiro"
```

Prepara qualquer clone com remoto no GitHub para o loop cuidar dele (constituição, testes, CI).

## 5. Painel e primeiro pedido

```bash
circulo painel         # http://127.0.0.1:8765 (o loop roda com `circulo run`)
circulo pedir "mostrar o gasto do mês por categoria"
circulo caminho        # o caminho do pedido até o merge
```

Para rodar 24/7: `circulo instalar`. Para ver sem chave nenhuma: `circulo demo`.

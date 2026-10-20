# Círculo perfeito — a fábrica

Uma fábrica de software autônoma, pequena o bastante para caber na cabeça: **um cartão por vez** passa por seis
estações e volta ao começo com o que aprendeu.

```
 pedido ──► Gerente de produto ──► Arquiteto ──► Desenvolvedor ──► QA ──► Revisor ──► Release ──► produção
              ▲                                                                                     │
              └──────────────────── achados (o que a fábrica aprendeu) ◄────────────────────────────┘
```

| Estação | Faz | Evidência medida que libera a próxima |
|---|---|---|
| Gerente de produto | lê o pedido e escreve o cartão (critérios, como verificar) | o pedido registrado |
| Arquiteto | planeja a menor mudança; onde; o que não tocar | caminhos do plano conferidos contra os protegidos |
| Desenvolvedor | reproduz primeiro (teste que falha), corrige, lint e testes | diff não vazio, lint e testes verdes no worktree |
| QA | prova na superfície real | testes novos **falham na base e passam na branch**; suíte verde; verificação do projeto |
| Revisor | lê o diff | tamanho dentro do limite, nada protegido, teste presente, sem padrão proibido |
| Release | PR, CI, merge, implantação | PR aberto, CI verde, merge feito, verificação em produção |

Rotulagem: toda evidência é `medido`, `inferido` ou `chutado`. Só `medido` avança o cartão. Devolução conta; na terceira
seguida o cartão **bloqueia** e fica para o humano, com o histórico. Caminho protegido e implantação sem permissão
também param na sua mão.

## Princípios (Lauren Tan, @poteto) e como viraram código

- **Confiança antes de paralelismo** → `estado.em_andamento()` devolve um cartão só; a fábrica não abre o segundo antes
  de fechar o primeiro.
- **Corrigir na camada mais forte** → caminhos protegidos (arquitetura), lint e testes iguais ao CI (análise estática),
  padrões proibidos no diff (`pytest.skip`, `xfail`, `TODO`), e só então a leitura do revisor.
- **Verificar rodando, não lendo** → o QA copia os testes novos para a base e exige que falhem lá; roda o comando de
  `verificacao` do projeto (a superfície real), não só a suíte.
- **Separar julgamento de trabalho mecânico** → julgamento (cartão, plano, código, leitura do diff) é do executor
  (Claude Code); worktree, diff, testes, PR, merge são comandos.
- **Operação resolvida vira ferramenta** → `fabrica.json` guarda os comandos do projeto; ninguém reinventa o script.
- **Parar antes do irreversível** → implantar só com `auto_implantar: true`; mexer em protegido nunca.
- **Achados, não volume** → o quadro de achados agrupa o que se repete; sem pedido na fila, o Gerente de produto
  pega o achado mais frequente. PRs não são a meta.

## Usar

```bash
python -m fabrica iniciar              # escreve fabrica.json no projeto atual
python -m fabrica pedir "o total do carrinho ignora a quantidade"
python -m fabrica rodar --painel       # gira a fábrica e abre http://127.0.0.1:8766
python -m fabrica demo                 # projeto de exemplo + executor simulado: veja o círculo fechar
python -m fabrica achados              # o documento de achados
```

`fabrica.json`:

```json
{"nome": "loja", "base": "main", "testes": "python3 -m pytest -q -x", "lint": "python3 -m ruff check .",
 "verificacao": "python3 scripts/fumaca.py", "protegidos": [".github/", "fabrica.json", "pagamentos/"],
 "max_linhas_pr": 400, "implantar": "git pull --ff-only && systemctl --user restart loja", "auto_implantar": false,
 "repo_github": "dono/repo"}
```

Executor: `claude` (Claude Code) se estiver instalado; senão o simulado (só para demonstração). GitHub: `FABRICA_REPO`
ou `repo_github` + `GITHUB_TOKEN`. Sem remoto, a fábrica mescla localmente.

## O painel

`fabrica/painel.html` é o chão de fábrica desenhado à mão (SVG próprio, sem biblioteca; funciona offline): as seis
estações num círculo, a nota amarela é o cartão viajando de estação em estação, o balão é a mensagem real que a estação
deixou no registro, verde quando entrega e vermelho tracejado quando devolve. Ao lado: fila de cartões, quadro de
achados (post-its) e o diário. Clique numa estação para ver a evidência do último passo.

## A fábrica trabalhando na própria fábrica

Aponte `fabrica.json` para este repositório, com `protegidos` cobrindo `fabrica/modelo.py`, `fabrica/coordenador.py` e
`.github/`, e `implantar` para o comando que reinicia o serviço. O Release implanta só com `auto_implantar: true`, e a
verificação em produção é o que decide se ficou.

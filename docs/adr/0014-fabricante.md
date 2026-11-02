# ADR 0014 — Fabricante: o loop evolui repositórios cliente (primeiro produto: Esteira de Vídeo)

- **Status**: aceito · **Data**: 2026-11-01 · **Versão**: 1.75.0

## Contexto
Cássio (1/11): "integre o repo cmatosengenharia/esteira (.NET 10) como primeiro produto evoluído pelo loop; o loop deve
planejar, implementar, testar e validar a evolução da esteira usando as skills absorvidas; cada entrega precisa de plano,
teste antes do código e evidência de validação guardada no loop".

O que já existia: `circulo init <pasta> --cliente` registra o repositório (kit 'repo'); um pedido na caixa com
`projeto: <id>` vira clone isolado + branch `circulo/<n>` (`repo_cliente.receber`); `repo_cliente.entregar` comita,
roda etapas e testes do kit e empurra a branch. O que faltava: **ninguém implementava nem chamava `entregar`** — o
pedido ficava `aberto` para sempre. O Developer só trabalha no repositório do loop (TASK_TEMPLATE é Python/pytest).

## Decisão
1. **`circulo/fabricante.py`**: trabalhador do idle (`fabricar`, trabalho real, custo 0 no orçamento da API — Claude Code
   na assinatura, como o Developer). Fases, cada uma com evidência em `etapas_repo` (ficha do pedido na missão) e
   `verificacoes` (`fabrica:<fase>`): plano (só leitura, formato verificável — writing-plans), implementar (mesma sessão,
   `--resume`), teste_vermelho (os testes novos copiados para um worktree da base FALHAM: TDD provado, agnóstico de
   linguagem — compilar quebrado conta), teste_verde (comando de testes do kit), tecnicas (`tecnicas.medir`),
   validador (revisão cruzada, revisor externo se houver), entrega (`repo_cliente.entregar`) e PR na API do GitHub com a
   evidência no corpo. Barrou: UMA correção na mesma sessão; vermelho volta à fila até 3 tentativas com o motivo no
   prompt; depois fica vermelho e avisa (nunca espera humano, nunca gira em vão).
2. **Kit sem Python**: `circulo.toml` na raiz do cliente com as mesmas chaves de `[tool.circulo]` (testes, lint,
   etapas, protegidos). As ferramentas do agente somam os executáveis do kit (`Bash(dotnet:*)`).
3. **A Esteira** (`~/Projects/esteira`) entra por `circulo init --cliente` com `circulo.toml`: testes `dotnet test`,
   etapa `pr` = `scripts/portoes.sh` (licença: nada de Remotion core; tenant: `IgnoreQueryFilters` só com justificativa;
   THIRD_PARTY_NOTICES quando há algoritmo portado) — os portões do CLAUDE.md dela viram comando, não texto.
4. **Backlog**: pedidos pequenos na caixa (`projeto: <id>`), fatiados do `docs/FASE_1.md` da esteira, na ordem que
   destrava o produto (copy por rede → render 16:9/1:1 → cortes → molde → planner LLM → descoberta → conectores).

## Fora de escopo (próximos itens, já na caixa do loop)
- Merge automático do PR do cliente quando CI verde + validador aprovou (hoje a branch e o PR são a entrega).
- Fabricante em paralelo com o Developer (hoje um pedido por giro, síncrono).
- Painel: coluna "Fábrica" na Equipe ao vivo com as fases (a ficha da missão já mostra).

## Consequências
Todo pedido de cliente agora anda sozinho e deixa rastro: plano, prova de que o teste falhava antes, testes do cliente,
técnicas, veredito do validador, commit, PR. Custo: 2–4 sessões de Claude Code por pedido (plano, implementação,
correção) + 1 chamada do Validador.

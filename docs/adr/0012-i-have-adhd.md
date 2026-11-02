# ADR 0012 — i-have-adhd absorvido

- **Status**: aceito · **Data**: 2026-11-01 · **Versão**: 1.75.0
- **Fonte**: https://github.com/ayghri/i-have-adhd (MIT): 10 regras de forma da resposta (ação primeiro, passos numerados,
  um próximo passo, sem tangente, estado a cada turno, estimativa concreta, vitória visível, erro seco, listas ≤ 5, sem preâmbulo).

## O que entrou
- Medida `tecnica:resposta_direta` sobre a mensagem final do Claude Code (`result` do stream-json, novo campo `resposta`
  em `ClaudeCodeAgent.run`): ≤ 12 linhas e sem preâmbulo ("Great", "Vou começar", "Let me", "Claro,"…). Não barra: a
  resposta já foi dada; a taxa mostra se o agente obedece.
- Regra "RESPOSTA DIRETA" em `tecnicas.PROMPT`: o que mudou, como verificou, UM próximo passo; erro como causa + correção
  (regras 1, 3, 8, 10 da skill).
- Skill vendorizada em `.claude/skills/i-have-adhd/` (o agente pode invocá-la; `disable-model-invocation: true` é dela).

## O que ficou de fora e por quê
- Modo "sempre ligado" (hook `SessionStart` + arquivo-flag em `~/.claude`): mexe na máquina do humano; o loop só injeta
  no próprio prompt.
- Regras 5–7 e 9 (restate state, estimativa em minutos, vitória visível, listas ≤ 5): são para um leitor humano em
  conversa; o leitor do Developer é o loop (o `desfecho`, a Equipe ao vivo e o painel já mostram estado e vitória).
  Não há conversa de vários turnos com o agente headless.
- Aplicar ao próprio loop (`ctx.reply`): os avisos do painel já são de uma linha; fica para quando houver medida de
  leitura do humano.

## Consequências
Uma medida nova por entrega; `resposta` no retorno do agente (até 4 000 caracteres) fica disponível para o `desfecho` e
para o Fabricante registrar como evidência.

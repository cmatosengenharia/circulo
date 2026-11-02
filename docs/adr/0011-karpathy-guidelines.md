# ADR 0011 — andrej-karpathy-skills absorvido

- **Status**: aceito · **Data**: 2026-11-01 · **Versão**: 1.75.0
- **Fonte**: https://github.com/forrestchang/andrej-karpathy-skills (MIT), uma skill `karpathy-guidelines` com 4 regras:
  pensar antes de codar, simplicidade, mudança cirúrgica, execução guiada por critério verificável.

## O que entrou
| regra | o que virou no loop | barra? | prova |
| --- | --- | --- | --- |
| §3 Surgical changes ("every changed line traces to the request") | portão `tecnica:cirurgica`: arquivos de CÓDIGO mudados que o item não cita (nem teste/docs/config) ≤ 2 (≤ 4 quando o item não cita arquivo algum) | **sim** — correção local no mesmo worktree | `test_cirurgica_*` |
| §2 Simplicity first (nada especulativo, sem abstração de uso único) | portão `tecnica:simplicidade`: dependência nova (pyproject, csproj, package.json) que o item não pede; `def`/`class` público novo que nada no repositório usa | **sim** | `test_simplicidade_*` |
| §1 Think before coding (suposições explícitas, não escolher em silêncio) | texto em `tecnicas.PROMPT`: "afirme as suposições; duas leituras → a mais simples, dita" ; medido junto com `plano_antes` (ADR 0010) | não | `test_prompt_do_developer_carrega_as_tecnicas` |
| §4 Goal-driven execution ("Add validation" → teste que falha e passa) | já era o portão "reprodução primeiro"; reforçado em `plano_antes` (cada passo com "verificar:") | — | já coberto |

## O que ficou de fora e por quê
- "If uncertain, ask" / "If something is unclear, stop. Ask.": o loop não espera humano (regra permanente; ADR de
  autonomia 1.72). Em vez de perguntar, o agente escolhe a leitura mais simples e declara qual; o Validador e o critério
  de aceite congelado pegam a leitura errada.
- O `CLAUDE.md`/`CURSOR.md` do repositório (mesmo texto em formato de regra): o loop injeta `tecnicas.PROMPT`, mais curto
  e amarrado a cada portão medido; dois textos para a mesma coisa é redundância (contexto redundante custa >20%, ETH/ICLR 2026, já citado em `contexto_cliente.py`).

## Consequências
Dois portões natos a mais no neurônio "abrir PR". Risco: falso positivo em refatoração legítima que toca muitos arquivos —
mitigado pelo teto por item com escopo e pelo item poder citar os arquivos (o Planejador já escreve caminhos no detalhe).

# ADR 0010 — obra/superpowers absorvido

- **Status**: aceito · **Data**: 2026-11-01 · **Versão**: 1.75.0
- **Fonte**: https://github.com/obra/superpowers (MIT, commit em `.claude/skills/ORIGEM.md`), 15 skills.

## Contexto
Cássio pediu para instalar e estudar a skill, extrair as técnicas e incorporá-las "onde fizer sentido", sem copiar
cegamente, com validação automática de que cada técnica está ativa.

## O que entrou
| técnica da skill | onde já existia no loop | o que mudou em 1.75 | prova de que está ativa |
| --- | --- | --- | --- |
| test-driven-development ("no production code without a failing test") | portão "reprodução primeiro" (`reproducao.reproduz`): o teste novo precisa falhar na base | medida `tecnica:teste_antes`: a PRIMEIRA edição do agente é em `tests/` (ordem dos passos do Claude Code) | `tests/test_tecnicas.py::test_teste_antes_*`; `circulo tecnicas` |
| writing-plans (plano em passos verificáveis antes do código) | o Planejador planeja o roteiro, mas o Developer não planejava a tarefa | `tecnicas.PROMPT` no prompt do Developer e do Fabricante; medida `tecnica:plano_antes` (TodoWrite/plano antes da 1ª edição); no Fabricante o plano é uma fase separada, só leitura, gravada como evidência `plano` | `test_plano_antes_*`, `test_fabricante_*plano*` |
| verification-before-completion ("evidence before claims") | `verificar()` roda lint+testes iguais ao CI antes do PR; `desfecho` grava | nada novo: já era a regra; o ADR registra a equivalência | `tests/test_self_dev*.py` (já existiam) |
| requesting-code-review / receiving-code-review (revisor com contexto próprio) | Validador (1.70) lê só o diff e o item | revisão cruzada medida: o Validador nunca usa o mesmo modelo do Developer (`validador.modelo_cruzado`); `tecnica:revisao_cruzada` | `test_revisao_cruzada_*` |
| systematic-debugging (causa raiz, não sintoma) | TASK_TEMPLATE já exige "corrija a causa, na camada mais forte" | skill vendorizada para o agente consultar | — (texto; sem medida própria) |
| as 7 skills acima vendorizadas em `.claude/skills/` | `skills.py` já pedia a instalação por PR | instaladas de uma vez, com licença conferida (MIT) | `skills.instaladas(repo)` lista 7 |

## O que ficou de fora e por quê
- **brainstorming** (sessão interativa com o humano, servidor visual): o loop não depende de humano (regra permanente); o
  Indagador e o Planejador cumprem o papel sem conversa.
- **subagent-driven-development, dispatching-parallel-agents, executing-plans**: o loop já tem trabalhadores paralelos
  (Escalador, `run_paralelo`) e o Claude Code já despacha subagentes; copiar a orquestração duplicaria o motor.
- **using-git-worktrees, finishing-a-development-branch**: o Developer já trabalha em worktree isolado e o gate fecha a
  branch; a skill ensinaria o que o código já impõe.
- **writing-skills, diagnosing-superpowers, using-superpowers**: meta-skills do próprio plugin; sem uso aqui.
- O hook `SessionStart` do plugin (injeta o texto no começo da sessão) não foi copiado: o prompt do Developer já carrega
  `tecnicas.PROMPT`, e portão medido vale mais que texto (arquitetura.md: "instrução em texto é o último recurso").

## Consequências
Duas medidas novas por entrega (plano_antes, teste_antes) e a revisão cruzada; nenhuma barra sozinha (a ordem dos passos
já aconteceu), mas a taxa fica visível ao Médico e às lições. O portão "reprodução primeiro" continua sendo o que barra.

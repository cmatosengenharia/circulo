# Os agentes do loop

O loop é um time de engenharia em que cada agente tem um papel. Os nomes abaixo são os que aparecem em todas as
telas (`circulo/nomes.py`); o nome técnico antigo fica entre parênteses.

## Direção

| Papel | Nome técnico | O que faz |
|---|---|---|
| **Tech lead** | `orquestrador` (Orquestrador) | Abre cada giro, confere orçamento e distribui o trabalho. |
| **Jev** | `jev` (Jev) | Responde sim/não, escolhe e dá nota antes de qualquer gasto; aprova ou barra. |

## Produto

| Papel | Nome técnico | O que faz |
|---|---|---|
| **Cássio** | `cassio` (pedido) | Pede, aprova e recebe as entregas. |
| **Product owner** | `indagar` (Indagador) | Levanta as perguntas certas a partir do que foi medido; cada uma passa pelo Jev. |
| **Gerente de produto** | `planejar_roteiro` (Planejador) | Transforma a pergunta validada num item pequeno e medível do roteiro. |
| **Gerente de missões** | `evoluir_projeto` (Missões) | Faz um ciclo nas missões suas: régua, versão nova, torneio e evidência. |

## Engenharia

| Papel | Nome técnico | O que faz |
|---|---|---|
| **Arquiteto** | `estudar_pedido` (Estudo / Pesquisa) | Pesquisa fontes confiáveis e decide adotar, adaptar ou contestar o item. |
| **Desenvolvedor** | `corrigir_codigo` (Developer) | Escreve o código e o teste num worktree, passa nos portões e abre o PR. |
| **Revisor de código** | `revisor` (Revisor) | Confere cada PR contra a main de agora e os outros PRs abertos; devolve o que cruza. |
| **QA e release** | `revisar_prs` (Gate) | CI verde, teste novo, constituição intacta: mescla ou devolve com o motivo. |
| **DevOps** | `atualizar_corpo` (Corpo) | Sobe o código novo em produção, prova em 5 giros e desfaz se piorar. |

## Qualidade e operação

| Papel | Nome técnico | O que faz |
|---|---|---|
| **SRE** | `vigia` (Vigia) | Mede as travas da autoevolução a cada minuto e abre item ou alerta. |
| **Curador de lições** | `licoes` (Lições) | Transforma cada erro em lição, portão e item de correção; fecha o que provou. |
| **Monitor de saúde** | `saude` (Saúde) | Mede a saúde do loop a cada giro e pede rollback se piorar. |
| **Jardineiro** | `jardinagem` (Jardinagem) | Mede padrões ruins crescendo no código e abre item para podar. |
| **Cientista de dados** | `meta_learner` (Aprendiz / Meta-Learner) | Aprende regras com as correções e testa a política candidata em shadow. |
| **Médico do loop** | `medico` (Médico) | Lê incidentes, erros e tentativas; um padrão medido vira diagnóstico, o Jev diz de quem é, e a resposta sobe a escada: observar, conter, corrigir, escalar. |
| **Redator técnico** | `documentar` (Documentador) | Gera a documentação em docs/ a partir do código, do banco e do CHANGELOG, com o Jev classificando cada entrega, e abre o PR. |
| **Operações** | `rotinas` (Rotinas) | Regressão, padrões, resumo, prompts A/B e demais manutenções em rodízio. |

## Parceiros externos

| Papel | Nome técnico | O que faz |
|---|---|---|
| **Consultor (LLM)** | `llm` (LLM) | Gera texto e raciocina quando o Jev e a regra não bastam (custa tokens). |
| **GitHub** | `github` (GitHub) | Guarda o código, roda o CI e registra os PRs. |

## O giro

Cada giro escolhe uma tarefa (as de trabalho primeiro, depois as de manutenção) e a executa até o fim; o SRE roda em paralelo.

| Tarefa | O que faz |
|---|---|
| `atualizar_corpo` (DevOps) | Validando e passando a rodar o código que o loop evoluiu |
| `evoluir_projeto` (Gerente de missões) | Evoluindo missões |
| `estudar_pedido` (Arquiteto) | Estudando o pedido em fontes confiáveis antes de executar |
| `corrigir_codigo` (Desenvolvedor) | Corrigindo o próprio código |
| `revisar_prs` (QA e release) | Revisando PRs abertos no gate |
| `planejar_roteiro` (Gerente de produto) | Planejando o próximo item do roteiro a partir da evidência |
| `indagar` (Product owner) | Indagador: levantando as perguntas da missão e passando cada uma pelo Jev |

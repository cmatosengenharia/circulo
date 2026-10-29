# Evolução

Tudo o que entrou na main: as versões (CHANGELOG) e as entregas que **o próprio loop** fez por PR, com a linhagem
pergunta → item → PR quando ela existe. O tipo de cada entrega foi classificado pelo Jev.

## Versões

| Versão | Data | Destaque | Itens |
|---|---|---|---|
| 1.69.2 | 2026-10-28 | Cobrança do prazo de 48 h do Norte: a cadeia girava em falso — o conselho para de insistir. | 4 |
| 1.69.1 | 2026-10-26 | - `CIRCULO_EXEMPLO=1` no arquivo de configuração: o SRE semeia o exemplo da tela Meu trabalho uma vez, na primeira | 2 |
| 1.69.0 | 2026-10-26 | Meu trabalho: a tela que junta o dia a dia do engenheiro, com dados de exemplo para o esqueleto nascer pronto. | 5 |
| 1.68.2 | 2026-10-26 | Caixa de entrada por arquivo — e a lição do banco corrompido. | 2 |
| 1.68.1 | 2026-10-25 | Prazo de 2 dias do Norte | 1 |
| 1.68.0 | 2026-10-25 | O Norte: o loop passa a evoluir em direção ao produto, medido, e não só a si mesmo. | 6 |
| 1.67.0 | 2026-10-24 | Giro preso 6 h e meia sem sinal de vida: prazo em tudo e um cão de guarda. | 5 |
| 1.66.0 | 2026-10-23 | Sentinela da entrega: o loop avisa quando para de entregar, mesmo sem erro nenhum. | 3 |
| 1.65.1 | 2026-10-23 | Fila parada 17 h atrás de um item que não podia mais andar. | 3 |
| 1.65.0 | 2026-10-22 | 15 h sem evolução: os testes usavam o Graft real no Mac. | 3 |
| 1.64.1 | 2026-10-22 | Graft instalado e invisível | 2 |
| 1.64.0 | 2026-10-21 | Evidência do Graft em tela (aba Autoevolução → "Graft · memória semântica"). | 4 |
| 1.63.0 | 2026-10-21 | Developer preso pedindo aprovação: 272 chamadas em 4 h (15:33–19:20) sem mudar nada. | 2 |
| 1.62.2 | 2026-10-21 | A main estava vermelha no CI desde a 1.61: a coleta do pytest quebrava. | 3 |
| 1.62.1 | 2026-10-21 | LLM pela assinatura | 2 |
| 1.62.0 | 2026-10-21 | Noite de 20→21/10: 31 PRs em círculo com o CI recusado. Dois freios. | 3 |
| 1.61.0 | 2026-10-21 | Auditoria de todo o código: 20 defeitos reais corrigidos (três revisões independentes, cada achado confirmado no código). | 15 |
| 1.60.0 | 2026-10-21 | Graft: memória semântica local do time ao lado do índice de texto. | 8 |
| 1.59.0 | 2026-10-21 | O loop roda na assinatura do Claude (Max), sem a API, e cuida sozinho da sessão. | 5 |
| 1.58.0 | 2026-10-21 | Falhas que não são do código deixam de reprovar código: CI bloqueado por cobrança e worktree órfão. | 4 |
| 1.57.0 | 2026-10-21 | Escala do aprendizado: decisor local destilado, itens por módulo e memória entre repositórios. | 4 |
| 1.56.0 | 2026-10-21 | Produtização: o motor cuidando de qualquer repositório, container, e a Equipe como porta de entrada. | 6 |
| 1.55.0 | 2026-10-21 | Plano de controle em processo próprio. | 0 |
| 1.54.0 | 2026-10-21 | Rollback de dados junto com o de código, e a constituição protegida fora do sistema. | 2 |
| 1.53.0 | 2026-10-21 | Higiene: as telas e a memória sem ruído. | 4 |
| 1.52.0 | 2026-10-21 | Desenvolvedor com sessão contínua e contexto do código. | 3 |
| 1.51.0 | 2026-10-21 | Desfecho por decisão: o Jev passa a ver o que cada "sim" rendeu. | 4 |
| 1.50.0 | 2026-10-20 | O Escalador: quem está sobrecarregado, e mais trabalhadores em paralelo para quem pode. | 5 |
| 1.49.0 | 2026-10-20 | Saúde e estado | 6 |
| 1.48.0 | 2026-10-20 | Equipe ao vivo mostra o que cada agente está fazendo, não só quem está trabalhando. | 4 |
| 1.47.0 | 2026-10-20 | Passe do Jev lab nas quatro perguntas em que o Jev mais duvidava. | 7 |
| 1.46.0 | 2026-10-20 | O Desenvolvedor parou 45 min com um PR esperando conserto — deadlock entre o fatiador e o conserto. | 3 |
| 1.45.0 | 2026-10-20 | Os gargalos medidos no Mac (24 h: 1,5 M tokens do Desenvolvedor para 7 itens entregues). | 5 |
| 1.44.0 | 2026-10-20 | A memória do time (RAG) compartilhada com toda a equipe — a começar pelo Product owner. | 5 |
| 1.43.0 | 2026-10-20 | Todo consumo do loop pela API, e qualquer API de IA. | 3 |
| 1.42.0 | 2026-10-20 | Conexões ao vivo na Gestão do loop. | 3 |
| 1.41.1 | 2026-10-20 | - Painel: aba fechada pelo navegador no meio de um `/api/...` gerava `BrokenPipeError` com traceback no `loop.err`; agora é ignorado (outros erros do servidor continuam no log). | 1 |
| 1.41.0 | 2026-10-20 | `circulo/medico.py` | 9 |
| 1.40.2 | 2026-10-20 | Dois defeitos que o loop real expôs em 3 h de 1.40.x, corrigidos com teste: | 2 |
| 1.40.1 | 2026-10-20 | Diagnóstico do "travado na 1.32.1" (medido no Mac às 14:17): | 2 |

## Entregas do loop (192 PRs mergeados)

Por tipo: **funcionalidade** 134 · **observabilidade** 20 · **correcao** 16 · **documentacao** 10 · **seguranca** 10 · **velocidade** 2.

| PR | Data | Tipo | Visível | Entrega | Veio de |
|---|---|---|---|---|---|
| #233 | 28/10/2026 | correcao (77%) | sim | Lição #15: teste de regressão para rastro:cadeia: item planejado pelo loop sem a pergunta do… | pergunta do licoes: “Lição #15: teste de regressão para rastro:cadeia: item planejado pelo loop sem a” |
| #232 | 28/10/2026 | correcao (70%) | — | PR #232 | — |
| #231 | 28/10/2026 | documentacao (0%) | — | Lição sem_prevencao com reincidência ≥3 vira item de roteiro 'escrever teste de regressão' (uma vez… | pergunta do cetico: “As lições #70 e #71 estão 'validada', mas os mesmos erros voltaram nas lições #7” |
| #230 | 28/10/2026 | funcionalidade (84%) | sim | Entrada manual de uma linha ('mercado 45,90 ontem') → lançamento, com dedupe por hash e pergunta se… | pergunta do financeiro: “Hoje há zero lançamentos reais. Dá para criar uma entrada manual de uma linha (p” |
| #229 | 28/10/2026 | observabilidade (100%) | sim | Medir rodadas de comentário de revisão por PR até o merge e expor a mediana na evidência | pergunta do mercado: “Como revisor do time, posso comentar num PR do loop e ver o agente iterar naquel” |
| #228 | 28/10/2026 | observabilidade (100%) | sim | Registrar o canal de origem de cada pedido e contar os pedidos da semana por canal | pergunta do mercado: “Como engenheiro do time, posso abrir um pedido direto de um issue, de um comentá” |
| #227 | 28/10/2026 | observabilidade (99%) | sim | Painel: fração de pedidos com plano registrado e aprovado antes do primeiro commit | pergunta do mercado: “Como membro da equipe, consigo ver e aprovar (ou corrigir) um plano curto do loo” |
| #226 | 28/10/2026 | observabilidade (98%) | sim | Registrar cada disparo da ação de recuperação por estagnação e expor a contagem dos últimos 30 dias | pergunta do auditor: “A métrica 'estagnacao' já chegou a disparar algum alerta ou ação (escalar, pausa” |
| #225 | 28/10/2026 | observabilidade (90%) | sim | Painel: mostrar motivo e fontes de cada pedido contestado, com alerta se faltar fonte | pergunta do usuario: “Como usuário, o loop me explica bem por que contestou meus pedidos, com as fonte” |
| #224 | 28/10/2026 | observabilidade (89%) | sim | Veredito de eficácia por PR com banda de ruído da linha de base (circulo/eficacia.py) | pergunta do cientista: “Das mudanças entregues, quais têm prova medida de que melhoraram algo, e como me” |
| #223 | 28/10/2026 | observabilidade (86%) | sim | Lição #15: bloquear no ponto único de gravação do roteiro itens sem pergunta_origem, com teste… | pergunta do arquiteto: “A lição #15 (rastro:cadeia, item planejado sem a pergunta do conselho que o orig” |
| #222 | 28/10/2026 | seguranca (74%) | sim | Pausar o Planejador quando o roteiro já tem muitos itens pendentes (limite determinístico) | pergunta do economista: “O sub-item #60 do fatiador estourou o teto de tokens (94705 gastos). Dá para est” |
| #221 | 28/10/2026 | seguranca (28%) | sim | Podar o contexto do planejador: roteiro só com itens recentes/ativos e lições obsoletas fora | pergunta do economista: “Qual é o jeito mais barato de obter o mesmo resultado na etapa que mais gasta (p” |
| #220 | 28/10/2026 | velocidade (41%) | sim | Detectar pedidos repetidos do humano por tokens normalizados e arquivo alvo em 7 dias | pergunta do entrevistador_jtbd: “Na última semana, quantos pedidos do humano são reformulações ou repetições de u” |
| #219 | 27/10/2026 | funcionalidade (27%) | sim | Garantir causa registrada em todo ciclo com lancamentos=0 e pedido 'sem_fonte' único | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #218 | 27/10/2026 | correcao (33%) | sim | Reusar o digest semanal existente e ligar fracao_produto ao planejamento do idle | pergunta do pm: “Como PM, qual funcionalidade uma equipe de engenharia usaria já na próxima seman” |
| #217 | 27/10/2026 | seguranca (41%) | sim | Disjuntor puro de LLM: crédito baixo abre pausa com backoff+jitter e um aviso por abertura | pergunta do operador: “A lição #54 (credit_balance_is_too_low) foi 'corrigida' no PR #91, mas esse erro” |
| #216 | 27/10/2026 | seguranca (75%) | sim | Ligar ingerir_pendentes() ao giro ocioso e provar lancamentos 0→N com fixture | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #215 | 27/10/2026 | funcionalidade (87%) | sim | Relatório semanal de entrega: PRs mergeados por categoria, com o pedido de origem de cada um | pergunta do pm: “Como PM, qual funcionalidade uma equipe de engenharia usaria já na próxima seman” |
| #214 | 27/10/2026 | observabilidade (83%) | sim | Developer: registrar passos por tarefa e acionar o fatiador quando o risco previsto passar do limiar calibrado | pergunta do curador_licoes: “A lição #59 (developer:agente: maximo de passos) está em 'sem_prevencao': não há” |
| #213 | 27/10/2026 | funcionalidade (39%) | sim | Contadores por fonte na ingestão: arquivos vistos, rejeitados, duplicados e novos, gravados no… | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #212 | 27/10/2026 | observabilidade (98%) | — | Ingestão: registro por rodada (vistos, rejeitados com motivo, novos) com heartbeat | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #211 | 27/10/2026 | observabilidade (95%) | sim | Pedir ao dono o primeiro extrato quando a ingestão diagnostica pasta vazia e lancamentos=0 | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #210 | 27/10/2026 | funcionalidade (65%) | sim | Entrega de produto sem uso após 7 dias vira item de roteiro 'revisar ou remover', sem duplicar | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #209 | 27/10/2026 | funcionalidade (0%) | — | Rejeitar lição cujo texto é JSON de estatística sem sinal de erro (failed>0, exceção, exit≠0) | pergunta do cetico: “A lição #83 guarda só um dump de subagent_stats com todos os contadores em 0 (co” |
| #208 | 27/10/2026 | funcionalidade (0%) | — | Painel: listar entregas de produto sem evento de uso 7+ dias após o merge | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #207 | 27/10/2026 | funcionalidade (0%) | — | Registrar a causa normalizada de cada barra em missao:verificacao_saida e expô-la na evidência de… | pergunta do operador: “Por que o neurônio missao:verificacao_saida é barrado tanto, e o que evitaria a ” |
| #206 | 27/10/2026 | funcionalidade (0%) | — | Entregas de produto sem uso após 7 dias viram item de revisão no roteiro (uma vez por entrega) | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #205 | 27/10/2026 | funcionalidade (0%) | — | Abrir 1 pedido de revisão por entrega de produto sem uso (chave única pelo PR) | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #204 | 27/10/2026 | funcionalidade (0%) | — | Atribuir os tokens de 24 h sem PR (1,29M de 1,61M) a papel e desfecho do item | pergunta do entrevistador_jtbd: “Entre os PRs das últimas 24 h com mais tokens, quantos partiram de um pedido sem” |
| #203 | 27/10/2026 | funcionalidade (0%) | — | Registrar evento de uso real quando comando ou endpoint de produto é executado, casando com o… | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #202 | 27/10/2026 | funcionalidade (0%) | — | Auditar se a causa de ingestão do #225 chega ao estado do loop e cobre os 4 cenários | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #201 | 27/10/2026 | funcionalidade (0%) | — | Pedido ao humano quando lancamentos=0: instrução com a causa do diagnóstico e o caminho da pasta | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #200 | 27/10/2026 | funcionalidade (0%) | — | Entrega de produto sem uso após 7 dias vira item de decisão (divulgar ou remover) no roteiro | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #199 | 27/10/2026 | funcionalidade (0%) | — | Painel: seção 'Entregas sem uso após 7 dias' lendo a tabela de eventos esperados | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #198 | 26/10/2026 | funcionalidade (0%) | — | Portão de pedido: devolver 1 pergunta de esclarecimento ao gerador e não chamar o Developer | pergunta do entrevistador_jtbd: “Entre os PRs das últimas 24 h com mais tokens, quantos partiram de um pedido sem” |
| #197 | 26/10/2026 | funcionalidade (0%) | — | Gravar o evento de uso esperado de cada entrega de produto mergeada, em tabela própria | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #196 | 26/10/2026 | funcionalidade (0%) | — | Registrar o veredito do portão de pedido em todo PR, inclusive nos itens vindos do planejador | pergunta do entrevistador_jtbd: “Entre os PRs das últimas 24 h com mais tokens, quantos partiram de um pedido sem” |
| #195 | 26/10/2026 | funcionalidade (0%) | — | Painel: agrupar as falhas das últimas 24h por causa e mostrar a dominante no topo | pergunta do usuario: “Como usuário, qual componente do painel devo melhorar para facilitar a visualiza” |
| #194 | 26/10/2026 | funcionalidade (0%) | — | Função pura: listar entregas de produto mergeadas há 7+ dias sem evento de uso esperado | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #193 | 26/10/2026 | funcionalidade (0%) | — | Medir tokens por PR segundo o veredito do portão de pedido (claro vs. incompleto) | pergunta do entrevistador_jtbd: “Entre os PRs das últimas 24 h com mais tokens, quantos partiram de um pedido sem” |
| #192 | 26/10/2026 | funcionalidade (0%) | — | Painel: mostrar em cada causa do card de falhas a variação contra as 24h anteriores | pergunta do usuario: “Como usuário, qual componente do painel devo melhorar para facilitar a visualiza” |
| #191 | 26/10/2026 | funcionalidade (0%) | — | Portão de pedido: checar critério de aceite, arquivo alvo e resultado esperado antes da LLM | pergunta do entrevistador_jtbd: “Entre os PRs das últimas 24 h com mais tokens, quantos partiram de um pedido sem” |
| #190 | 26/10/2026 | funcionalidade (0%) | — | Resumo semanal: listar pedidos de usuário abertos sem PR de produto, ordenados por idade | pergunta do pm: “Como PM, qual funcionalidade uma equipe de engenharia usaria já na próxima seman” |
| #189 | 26/10/2026 | funcionalidade (0%) | — | Medir o uso do resumo semanal: registrar cada leitura e mostrar PRs de produto sem uso | pergunta do pm: “Como PM, qual funcionalidade uma equipe de engenharia usaria já na próxima seman” |
| #188 | 26/10/2026 | funcionalidade (0%) | — | Painel: delta de falhas 24h vs 24h anteriores nos cards, com cor invertida e caso sem base | pergunta do usuario: “Como usuário, qual componente do painel devo melhorar para facilitar a visualiza” |
| #187 | 26/10/2026 | funcionalidade (0%) | — | Resumo semanal para a equipe: PRs de produto mergeados, quem pediu e uso medido | pergunta do pm: “Como PM, qual funcionalidade uma equipe de engenharia usaria já na próxima seman” |
| #186 | 26/10/2026 | funcionalidade (0%) | — | Limitar reentradas de developer:abrir_pr:adiar e escalar a tarefa após N adiamentos seguidos | pergunta do operador: “O PR 'Integrar a pré-checagem em developer:abrir_pr antes do push' foi aberto e ” |
| #185 | 26/10/2026 | funcionalidade (0%) | — | Painel: card de falhas por componente nas últimas 24h, ordenado pelo mais afetado | pergunta do usuario: “Como usuário, qual componente do painel devo melhorar para facilitar a visualiza” |
| #184 | 26/10/2026 | funcionalidade (0%) | — | Changelog semanal: PRs mergeados agrupados em produto/infra, com o pedido de origem | pergunta do pm: “Como PM, qual funcionalidade uma equipe de engenharia usaria já na próxima seman” |
| #183 | 26/10/2026 | funcionalidade (0%) | — | Diagnóstico de ingestão: registrar por que lancamentos=0 (pasta ausente, vazia ou arquivos… | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #182 | 26/10/2026 | funcionalidade (0%) | — | Painel: agrupar as falhas das últimas 24h por causa em um card único no topo | pergunta do usuario: “Como usuário, qual componente do painel devo melhorar para facilitar a visualiza” |
| #181 | 26/10/2026 | funcionalidade (0%) | — | Disjuntor por causa em developer:abrir_pr:adiar: após 3 falhas seguidas iguais, pôr o item em… | pergunta do operador: “O PR 'Integrar a pré-checagem em developer:abrir_pr antes do push' foi aberto e ” |
| #180 | 26/10/2026 | funcionalidade (0%) | — | Digest semanal do que o time ganhou: PRs de produto ligados ao pedido de origem | pergunta do pm: “Como PM, qual funcionalidade uma equipe de engenharia usaria já na próxima seman” |
| #179 | 26/10/2026 | funcionalidade (0%) | — | Parser determinístico de e-mail de notificação bancária → lançamentos, com dedupe por hash | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #178 | 26/10/2026 | funcionalidade (0%) | — | Registrar causa e limitar retentativas de developer:abrir_pr:adiar, que falhou 13 de 13 | pergunta do operador: “O PR 'Integrar a pré-checagem em developer:abrir_pr antes do push' foi aberto e ” |
| #177 | 26/10/2026 | funcionalidade (0%) | — | Vigia: 1 lição(ões) de estrutura aberta(s) há 4 h bloqueando a evolução | item #219 (loop) |
| #176 | 26/10/2026 | funcionalidade (0%) | — | Lição #60: painel:frescor: painel atrasado: p99 5472 ms em 24 h (meta 3000 ms) | item #138 (erro) |
| #175 | 26/10/2026 | funcionalidade (0%) | — | Lição #60: painel:frescor: painel atrasado: p99 5472 ms em 24 h (meta 3000 ms) | item #138 (erro) |
| #174 | 26/10/2026 | funcionalidade (0%) | — | Vigia: 1 lição(ões) de estrutura aberta(s) há 2 h bloqueando a evolução | item #213 (loop) |
| #173 | 26/10/2026 | funcionalidade (0%) | — | Lição #60: painel:frescor: painel atrasado: p99 5472 ms em 24 h (meta 3000 ms) | item #138 (erro) |
| #172 | 26/10/2026 | funcionalidade (0%) | — | Lição #60: painel:frescor: painel atrasado: p99 5472 ms em 24 h (meta 3000 ms) | item #138 (erro) |
| #171 | 26/10/2026 | funcionalidade (0%) | — | Isolar o teste de paralelismo do Arquiteto: trocar timing por threading.Barrier com timeout | item #214 (sub_item) |
| #170 | 26/10/2026 | funcionalidade (0%) | — | Alinhar o kit do loop ao framework GAIA da Localiza, que padroniza o uso de IA em toda a esteira de… | pergunta do cassio: “Alinhar o kit do loop ao framework GAIA da Localiza, que padroniza o uso de IA e” |
| #169 | 26/10/2026 | funcionalidade (0%) | — | Uma estrutura de pastas padrão no meu Mac por assunto (docs, decisões, links, notas, prompts)… | pergunta do cassio: “Uma estrutura de pastas padrão no meu Mac por assunto (docs, decisões, links, no” |
| #168 | 26/10/2026 | funcionalidade (0%) | — | Exportar contexto enxuto para o Cursor (AGENTS.md e .cursor/rules) a partir da memória do assunto | pergunta do cassio: “Para cada assunto ou repositório, o loop gera e mantém os arquivos de contexto q” |
| #167 | 26/10/2026 | funcionalidade (0%) | — | Gasto diário do Cursor por assunto/tarefa, com projeção de esgotamento dos US$ 250 | pergunta do cassio: “Tenho US$ 250 por mês de IA no Cursor e sempre acabo antes do fim do mês. Quero ” |
| #166 | 26/10/2026 | funcionalidade (0%) | — | Quero um espaço de trabalho por ASSUNTO (minha tribo, minha squad, cada microsserviço de… | pergunta do cassio: “Quero um espaço de trabalho por ASSUNTO (minha tribo, minha squad, cada microsse” |
| #165 | 26/10/2026 | funcionalidade (0%) | — | Catálogo de links da empresa por assunto: eu colo o link com um rótulo curto e depois acho em segundos, por pa | pergunta do cassio: “Catálogo de links da empresa por assunto: eu colo o link com um rótulo curto e d” |
| #164 | 26/10/2026 | funcionalidade (0%) | — | Toda manhã às 8h quero a pauta da minha daily por assunto: o que fiz ontem (das notas), o que farei hoje (pend | pergunta do cassio: “Toda manhã às 8h quero a pauta da minha daily por assunto: o que fiz ontem (das ” |
| #163 | 26/10/2026 | funcionalidade (0%) | — | Quero pedir uma feature em uma frase pelo console e acompanhar o caminho dela até o merge: pedido →… | pergunta do cassio: “Quero pedir uma feature em uma frase pelo console e acompanhar o caminho dela at” |
| #162 | 26/10/2026 | funcionalidade (0%) | — | Motivo tipado de recusa/parada (gate, check, próxima ação) ao lado do item na Equipe ao vivo | pergunta do cassio: “Na Equipe ao vivo quero entender em 10 segundos por que um PR foi recusado ou um” |
| #161 | 26/10/2026 | funcionalidade (0%) | — | Corpo do PR do Developer: template fixo de impacto e risco, com módulos e testes vindos do diff e do gate | pergunta do cassio: “Todo PR do Developer deve vir com um resumo de impacto e risco no corpo: o que m” |
| #160 | 25/10/2026 | funcionalidade (0%) | — | Parser puro de e-mail de notificação com dedup por hash+ocorrência, cruzando com o extrato | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #159 | 25/10/2026 | funcionalidade (0%) | — | Teste de ponta a ponta: pasta monitorada → lançamentos > 0 medido no estado do loop | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #158 | 25/10/2026 | funcionalidade (0%) | — | Impressão digital de PR (título + checks falhos) que bloqueia a 3ª abertura idêntica | pergunta do operador: “O PR 'Integrar a pré-checagem em developer:abrir_pr antes do push' foi aberto e ” |
| #157 | 25/10/2026 | funcionalidade (0%) | — | Ingestão de pasta monitorada: importar extratos OFX/CSV novos para os lançamentos, de forma… | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #156 | 25/10/2026 | funcionalidade (0%) | — | Parser OFX/CSV determinístico com dedupe idempotente (FITID ou hash+ocorrência) | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #155 | 25/10/2026 | funcionalidade (0%) | — | Validar por ast o id pytest (arquivo, classe, função) antes do reparo, sem rodar pytest | pergunta do operador: “As lições #31 e #35 registram 'ERROR: file or directory not found' ao rodar test” |
| #154 | 25/10/2026 | funcionalidade (0%) | — | Reabrir lição 'validada' quando nova lição chega com a mesma assinatura (neurônio+arquivo+código) | pergunta do cetico: “As lições #70 e #71 estão 'validada', mas os mesmos erros voltaram nas lições #7” |
| #153 | 25/10/2026 | funcionalidade (0%) | — | Lição só vira 'validada' se a Prevenção citar um teste/checagem; senão fica 'sem_prevencao' | pergunta do cetico: “As lições #70 e #71 estão 'validada', mas os mesmos erros voltaram nas lições #7” |
| #152 | 25/10/2026 | funcionalidade (0%) | — | Lição #78: developer:abrir_pr: --> tests/test_vigia_drena.py:93:89 | item #191 (erro) |
| #151 | 25/10/2026 | funcionalidade (0%) | — | Vigia: 2 pergunta(s) validada(s) pelo Jev esperando há 31 min sem virar item (último progresso há 235 min) | item #178 (loop) |
| #150 | 24/10/2026 | funcionalidade (0%) | — | Lição #47: loop:progresso: havia trabalho pendente e nada avançou em 10 giros; causa provável: sem… | item #115 (erro) |
| #149 | 24/10/2026 | funcionalidade (0%) | — | Expor por que a antecipação gerou 0 propostas com 32 pedidos: maior grupo de job e o limiar 3+ | item #176 (loop) |
| #148 | 24/10/2026 | funcionalidade (0%) | — | Evidência do conselho: contar falhas locais por execução distinta, não por linha repetida | pergunta do arquiteto: “Qual parte do código mais faz o Developer errar e refazer, e como simplificá-la?” |
| #147 | 24/10/2026 | funcionalidade (0%) | — | Gerar proposta antecipada quando um job de pedido do humano se repete 3+ vezes em 7 dias | pergunta do entrevistador_jtbd: “Nos pedidos do humano da última semana, qual era o trabalho (job) por trás de ca” |
| #146 | 24/10/2026 | funcionalidade (0%) | — | Auditar e corrigir o corte de developer:teto: chave por item raiz, estado persistente, bloqueio | pergunta do operador: “O PR 'Integrar a pré-checagem em developer:abrir_pr antes do push' foi aberto e ” |
| #145 | 24/10/2026 | funcionalidade (0%) | — | Medir se a proposta antecipada de job recorrente foi aceita ou o humano pediu o mesmo job depois | pergunta do entrevistador_jtbd: “Nos pedidos do humano da última semana, qual era o trabalho (job) por trás de ca” |
| #144 | 24/10/2026 | funcionalidade (0%) | — | Vigia: 1 lição(ões) de estrutura aberta(s) há 79 h bloqueando a evolução | item #171 (loop) |
| #143 | 24/10/2026 | funcionalidade (0%) | — | Vigia: 2 lição(ões) de estrutura aberta(s) há 76 h bloqueando a evolução | item #170 (loop) |
| #142 | 24/10/2026 | funcionalidade (0%) | — | Lição #47: loop:progresso: havia trabalho pendente e nada avançou em 10 giros; causa provável: sem… | item #115 (erro) |
| #141 | 23/10/2026 | funcionalidade (0%) | — | Lição #19: developer:testes: __… | item #168 (erro) |
| #140 | 23/10/2026 | funcionalidade (0%) | — | Lição #47: loop:progresso: havia trabalho pendente e nada avançou em 10 giros; causa provável: sem… | item #115 (erro) |
| #139 | 23/10/2026 | funcionalidade (0%) | — | Teste do Developer em paralelo: Barrier(2) com timeout e causa raiz de test_capacidade.py:112 | pergunta do arquiteto: “Qual parte do código mais faz o Developer errar e refazer, e como simplificá-la?” |
| #138 | 23/10/2026 | funcionalidade (0%) | — | Canário parametrizado: cada portão aprendido recusa a assinatura da lição que o criou | pergunta do auditor: “Qual guardrail nunca barrou nada, e como provar com um teste que ele ainda funci” |
| #137 | 23/10/2026 | funcionalidade (0%) | — | Base vermelha: upsert da falha local por (item, assinatura, sha da main) com contador | pergunta do arquiteto: “Qual parte do código mais faz o Developer errar e refazer, e como simplificá-la?” |
| #136 | 23/10/2026 | funcionalidade (0%) | — | Canário para portões aprendidos: reexecutar a assinatura de cada lição e exigir que o portão barre | pergunta do auditor: “Qual guardrail nunca barrou nada, e como provar com um teste que ele ainda funci” |
| #135 | 23/10/2026 | funcionalidade (0%) | — | Quarentena de item por teto de falhas locais com a mesma assinatura (limite 5, à la DLQ) | pergunta do arquiteto: “Qual parte do código mais faz o Developer errar e refazer, e como simplificá-la?” |
| #134 | 23/10/2026 | funcionalidade (0%) | — | Ligar o agrupador de jobs (#146) ao loop: registrar o job recorrente como proposta antecipada | pergunta do entrevistador_jtbd: “Nos pedidos do humano da última semana, qual era o trabalho (job) por trás de ca” |
| #133 | 23/10/2026 | funcionalidade (0%) | — | Canário de falha para gate:merge: provar com teste que o portão recusa merge com check vermelho | pergunta do auditor: “Qual guardrail nunca barrou nada, e como provar com um teste que ele ainda funci” |
| #132 | 23/10/2026 | funcionalidade (0%) | — | Antecipar o job recorrente: abrir item proposto com origem na pergunta quando ele passa de 3… | pergunta do entrevistador_jtbd: “Nos pedidos do humano da última semana, qual era o trabalho (job) por trás de ca” |
| #131 | 23/10/2026 | funcionalidade (0%) | — | Medir tokens do developer por desfecho do item (PR entregue vs sem PR) para achar o desperdício | pergunta do economista: “Qual é o jeito mais barato de obter o mesmo resultado na etapa que mais gasta (d” |
| #130 | 23/10/2026 | funcionalidade (0%) | — | Canário de falha para developer:abrir_pr:sem_marcador_de_conflito e teste_novo | pergunta do auditor: “Qual guardrail nunca barrou nada, e como provar com um teste que ele ainda funci” |
| #129 | 23/10/2026 | funcionalidade (0%) | — | Developer: base vermelha com a mesma assinatura de teste para o item em vez de repetir a execução | pergunta do arquiteto: “Qual parte do código mais faz o Developer errar e refazer, e como simplificá-la?” |
| #128 | 23/10/2026 | funcionalidade (0%) | — | Medir cobertura de antecipação: fração dos pedidos humanos cujo job já tinha item proativo aberto… | pergunta do entrevistador_jtbd: “Nos pedidos do humano da última semana, qual era o trabalho (job) por trás de ca” |
| #127 | 23/10/2026 | funcionalidade (0%) | — | Vigia: 1 lição(ões) de estrutura aberta(s) há 127 h bloqueando a evolução | item #153 (loop) |
| #126 | 23/10/2026 | funcionalidade (0%) | — | Vigia: 1 lição(ões) de estrutura aberta(s) há 125 h bloqueando a evolução | item #148 (loop) |
| #125 | 23/10/2026 | funcionalidade (0%) | — | Disjuntor por assinatura no seletor do roadmap, com reteste e fechamento por reexecução verde | pergunta do arquiteto: “Qual parte do código mais faz o Developer errar e refazer, e como simplificá-la?” |
| #124 | 23/10/2026 | funcionalidade (0%) | — | Isolar test_arquiteto_estuda_varios_itens: tornar o teste determinístico (barreira em vez de tempo) | pergunta do arquiteto: “Qual parte do código mais faz o Developer errar e refazer, e como simplificá-la?” |
| #123 | 23/10/2026 | funcionalidade (0%) | — | Função pura que agrupa os pedidos de 7d por job e aponta o job recorrente a antecipar | pergunta do entrevistador_jtbd: “Nos pedidos do humano da última semana, qual era o trabalho (job) por trás de ca” |
| #122 | 23/10/2026 | funcionalidade (0%) | — | Vigia: 1 lição(ões) de estrutura aberta(s) há 85 h bloqueando a evolução | item #139 (loop) |
| #121 | 23/10/2026 | funcionalidade (0%) | — | Vigia: 1 lição(ões) de estrutura aberta(s) há 17 h bloqueando a evolução | item #137 (loop) |
| #120 | 23/10/2026 | funcionalidade (0%) | — | Fatiador: pré-divisão determinística por módulos/símbolos citados, limite calibrado e teto como… | pergunta do economista: “O sub-item #60 do fatiador estourou o teto de tokens (94705 gastos). Dá para est” |
| #119 | 23/10/2026 | funcionalidade (0%) | — | Lição #63: developer:testes: tests/test_capacidade.py:112: AssertionError | item #145 (erro) |
| #118 | 21/10/2026 | funcionalidade (0%) | — | Classificar falha de CI por conclusion/anotação (infra vs código) e reexecutar local antes de… | pergunta do arquiteto: “O PR #82 (“Teste de arquitetura: detectar padrão sdk_opt_in_required em saídas d” |
| #117 | 22/10/2026 | funcionalidade (0%) | — | Portão pré-PR: descartar item com 2 PRs fechados sem merge (fundir com #128) | pergunta do arquiteto: “O PR #83 (“Teste de arquitetura: detectar padrão sdk_opt_in_required em saídas d” |
| #116 | 21/10/2026 | funcionalidade (0%) | — | Portão de reincidência: não abrir PR de item que já fechou 2x sem merge com os mesmos checks… | pergunta do arquiteto: “O PR #84 (“Teste de arquitetura: detectar padrão sdk_opt_in_required em saídas d” |
| #115 | 21/10/2026 | funcionalidade (0%) | — | Lição #60: painel:frescor: painel atrasado: p99 5472 ms em 24 h (meta 3000 ms) | item #138 (erro) |
| #114 | 21/10/2026 | funcionalidade (0%) | — | Medir falha uniforme de checks por PR fechado e o gasto do developer nele | pergunta do arquiteto: “O PR #48 (“Integrar a pré-checagem em developer:abrir_pr antes do push”) fechou ” |
| #113 | 21/10/2026 | funcionalidade (0%) | — | Portão pré-PR: não abrir PR se a main está vermelha ou se todos os checks falham de modo uniforme | pergunta do arquiteto: “O PR #49 (“Integrar a pré-checagem em developer:abrir_pr antes do push”) fechou ” |
| #112 | 21/10/2026 | funcionalidade (0%) | — | Portão pré-PR: não abrir PR enquanto o CI da main estiver vermelho ou sem iniciar | pergunta do arquiteto: “O PR #50 (“Integrar a pré-checagem em developer:abrir_pr antes do push”) fechou ” |
| #111 | 21/10/2026 | funcionalidade (0%) | — | Painel local: faixa de saúde no topo (semáforo + 5 números) em HTML estático, sem Grafana | pergunta do usuario: “Dado que /metrics e o Grafana opcional já existem, qual visão do painel do loop ” |
| #110 | 21/10/2026 | funcionalidade (0%) | — | Registrar medição antes/depois por item mergeado e listar os sem linha de base | pergunta do cientista: “Dos 15 PRs mergeados em 7 dias, quantos dos 11 itens com critério de sucesso têm” |
| #109 | 21/10/2026 | funcionalidade (0%) | — | Classificar a falha do developer:agente pela causa real (subtype/is_error), não pelo trecho cru do… | pergunta do operador: “O neurônio developer:agente foi barrado 17 de 181 vezes em 24 h: qual é a causa ” |
| #108 | 21/10/2026 | funcionalidade (0%) | — | Disjuntor por assinatura de causa no abrir_pr: após 2 barras iguais no mesmo item, não gasta até a… | pergunta do operador: “O neurônio developer:abrir_pr:aprendido foi barrado 495 de 1910 vezes em 24 h: q” |
| #107 | 21/10/2026 | funcionalidade (0%) | — | Gravar os arquivos realmente em conflito (git merge-tree) de cada PR devolvido e contar por arquivo… | pergunta do operador: “Nos PRs devolvidos por conflito com a main nos últimos 7 dias (hoje 2), quais ar” |
| #106 | 21/10/2026 | funcionalidade (0%) | — | Estado de dado_na_evidencia com features numéricas: o número do campo 'dado' aparece literal na… | pergunta do economista: “O Jev decide “dado_na_evidencia” com dúvida (a regra decidiu 27% de 26 vezes em ” |
| #105 | 21/10/2026 | funcionalidade (0%) | — | TTL de lição de estrutura: marcar obsoleta se a assinatura não reincide em 6 h | pergunta do operador: “O Vigia mede a trava “3 lição(ões) de estrutura aberta(s) há 14 h bloqueando a e” |
| #104 | 21/10/2026 | funcionalidade (0%) | — | Estado do revisor_seguro com linhas alteradas, nº de arquivos, categoria dominante e se há teste no… | pergunta do economista: “O Jev decide “revisor_seguro” com dúvida (a regra decidiu 41% de 22 vezes em 24 ” |
| #103 | 21/10/2026 | funcionalidade (0%) | — | Assinar lição de erro de coleta do pytest pelo módulo e exceção, e fechá-la com --collect-only… | pergunta do curador_licoes: “A lição #9 (developer:testes: ==================================== ERRORS ======” |
| #102 | 21/10/2026 | funcionalidade (0%) | — | Pytest com alvo inexistente (exit 4) vira lição obsoleta e não conta como nova ocorrência | pergunta do curador_licoes: “A lição #27 (developer:abrir_pr: ERROR: file or directory not found: tests/test_” |
| #101 | 21/10/2026 | funcionalidade (0%) | — | Planejador lê a hora de reset do limite de uso e retoma sozinho, sem sondar a LLM | pergunta do operador: “O Planejador não planeja porque “Claude Code no limite de uso”: essa trava é leg” |
| #100 | 21/10/2026 | funcionalidade (0%) | — | Vigia: 3 lição(ões) de estrutura aberta(s) há 14 h bloqueando a evolução | item #102 (loop) |
| #99 | 21/10/2026 | funcionalidade (0%) | — | Migração: coluna origem_status e marcar itens antigos sem pergunta como 'legado' | item #133 (sub_item) |
| #98 | 21/10/2026 | funcionalidade (0%) | — | Contrato único de saída JSON: extrator tolerante a truncamento para estudo, meta e planejador | pergunta do curador_licoes: “A lição #22 (estudo:pedido: resposta sem JSON válido: tps://github.com/cgwalters” |
| #97 | 21/10/2026 | funcionalidade (0%) | — | Extrair erro do agente de JSON estruturado, não de fatia de texto bruto, antes de gravar a lição | pergunta do curador_licoes: “A lição #18 (developer:agente: s","fast_mode_state":"off","fast_mode_disabled_re” |
| #96 | 21/10/2026 | funcionalidade (0%) | — | Recusar item de roteiro sem pergunta de origem antes de gastar, com causa tipada | pergunta do operador: “O neurônio rastro:cadeia foi barrado 3 de 13 vezes em 24 h: qual é a causa que s” |
| #95 | 21/10/2026 | funcionalidade (0%) | — | Tipo Origem(pergunta_id) validado, sem DB, em circulo/roadmap.py | item #132 (sub_item) |
| #94 | 21/10/2026 | funcionalidade (0%) | — | Dar ao estado de evidencia_sustenta o resultado medido do teste citado e as execuções seguidas | pergunta do economista: “O Jev decide “evidencia_sustenta” com dúvida (a regra decidiu 35% de 20 vezes em” |
| #93 | 21/10/2026 | funcionalidade (0%) | — | revisar_prs: classificar a causa da falha e adiar sem gastar (rede, checks pendentes, atrás da main) | pergunta do operador: “O neurônio execucao:idle:revisar_prs foi barrado 3 de 3 vezes em 24 h: qual é a ” |
| #92 | 21/10/2026 | funcionalidade (0%) | — | Lição #56: Corrigir erro: RuntimeError em idle:propor_feature | item #127 (erro) |
| #91 | 21/10/2026 | funcionalidade (0%) | — | Lição #54: developer:agente: credit balance is too low — Credit balance is too low | pergunta do operador: “A lição #54 (credit_balance_is_too_low) foi 'corrigida' no PR #91, mas esse erro” |
| #90 | 21/10/2026 | funcionalidade (0%) | — | Lição #53: gate:ci: checks falhando: Evidência reforçada, Container, Testes (Python 3.13), Testes… | item #118 (erro) |
| #89 | 21/10/2026 | funcionalidade (0%) | — | Lição #50: gate:main: CI da main falhou no 93fe8ef: algo entrou quebrado | item #117 (erro) |
| #88 | 21/10/2026 | funcionalidade (0%) | — | Lição #47: loop:progresso: havia trabalho pendente e nada avançou em 10 giros; causa provável: sem… | item #115 (erro) |
| #87 | 21/10/2026 | funcionalidade (0%) | — | Lição #45: planejador:saida: resposta sem JSON válido (cortada pelo limite de tokens ou fora do… | item #106 (erro) |
| #86 | 21/10/2026 | funcionalidade (0%) | — | Lição #44: corpo:evidencia: erros nos primeiros giros do código novo: … | item #98 (erro) |
| #47 | 20/10/2026 | funcionalidade (0%) | — | Obter o numstat real via merge-base com a base | item #93 (sub_item) |
| #46 | 20/10/2026 | funcionalidade (0%) | — | Lição #2: corpo:atualizar: > with pytest.raises(RuntimeError): # o erro do incidente, sem o caminho… | item #30 (erro) |
| #45 | 20/10/2026 | funcionalidade (0%) | — | Comparar o total com o limite de tamanho e devolver veredito | item #92 (sub_item) |
| #43 | 20/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #42 | 20/10/2026 | correcao (42%) | sim | Lição #43: Corrigir erro: JSONDecodeError em meta | item #97 (erro) |
| #41 | 20/10/2026 | correcao (46%) | — | Lição #22: estudo:pedido: resposta sem JSON válido: tps://github.com/cgwalters-forge/agentic-job/issues/556"," | item #55 (erro) |
| #39 | 20/10/2026 | seguranca (41%) | — | Parser puro de numstat com soma total e categoria dominante | item #91 (sub_item) |
| #38 | 20/10/2026 | documentacao (99%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #37 | 20/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #36 | 20/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #35 | 20/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #34 | 20/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #33 | 20/10/2026 | correcao (87%) | — | Lição #22: estudo:pedido: resposta sem JSON válido: tps://github.com/cgwalters-forge/agentic-job/issues/556"," | item #55 (erro) |
| #32 | 20/10/2026 | correcao (47%) | sim | Developer: classificar a causa de cada falha de testes e rodar pré-voo dos testes afetados na main antes de ga | pergunta do operador: “O neurônio developer:testes foi barrado 6 de 22 vezes em 24 h: qual é a causa qu” |
| #31 | 20/10/2026 | velocidade (38%) | sim | Vigia: drenar sozinho a pergunta validada mais antiga quando a fila passa do prazo, 1 por ciclo | pergunta do operador: “O Vigia mede a trava “6 pergunta(s) validada(s) pelo Jev esperando há 31 min sem” |
| #30 | 20/10/2026 | funcionalidade (65%) | sim | Vigia: 13 pergunta(s) validada(s) pelo Jev esperando há 395 min sem virar item (último progresso há 198 min) | item #54 (loop) |
| #29 | 20/10/2026 | correcao (81%) | sim | Jardineiro: podar linhas com `noqa` (lint silenciado) | item #52 (loop) |
| #28 | 20/10/2026 | correcao (81%) | sim | Planejador: vetar antes da LLM item cujo alvo toca a constituição e registrar a causa de cada falha de abrir_p | pergunta do operador: “O neurônio developer:abrir_pr foi barrado 5 de 19 vezes em 24 h: qual é a causa ” |
| #27 | 20/10/2026 | seguranca (98%) | sim | Orçamento diário de tokens configurável (1M/dia), com alerta e corte, medido por job do Jev | pergunta do cassio: “aumente o limite de token da llm para 1milha por dia” |
| #26 | 20/10/2026 | seguranca (99%) | sim | Lição #22: estudo:pedido: resposta sem JSON válido: tps://github.com/cgwalters-forge/agentic-job/issues/556"," | item #55 (erro) |
| #25 | 19/10/2026 | correcao (74%) | — | Vigia: 6 pergunta(s) validada(s) pelo Jev esperando há 31 min sem virar item (último progresso há 111 min) | item #50 (loop) |
| #24 | 19/10/2026 | correcao (46%) | sim | Planejador no mesmo giro da pergunta validada, 1 retry com jitter e espera por sub-etapa gravada | pergunta do operador: “A etapa “da pergunta validada ao item do roteiro (Planejador + porteiro)” levou ” |
| #23 | 19/10/2026 | correcao (42%) | sim | Canário de falha para painel:frescor: provar com teste que o ponto detecta painel velho | pergunta do auditor: “Qual guardrail nunca barrou nada, e como provar com um teste que ele ainda funci” |
| #22 | 19/10/2026 | observabilidade (65%) | — | Vigia: recusa do porteiro não é trava; limitar espera da pergunta com prazo máximo e envelhecimento | — |
| #21 | 19/10/2026 | documentacao (0%) | sim | Registrar o job de cada pedido humano (regra do Jev, limiar calibrado) e antecipar jobs recorrentes | — |
| #20 | 19/10/2026 | observabilidade (38%) | — | Gravar o id do item na falha local ao registrá-la; nunca agregar por caminho .circulo-wt-* | — |
| #19 | 19/10/2026 | observabilidade (51%) | — | Vigia: registrar o resultado real de cada tentativa do planejador e diagnosticar a trava por ele | — |
| #18 | 19/10/2026 | observabilidade (76%) | sim | Curador: fechar #10/#11 por alias causa→node id da #12 e proteger o mapa como constituição | — |
| #17 | 19/10/2026 | seguranca (50%) | — | Developer: teto de tokens checado antes da chamada + corte na 2ª falha igual, rumo ao fatiamento | — |
| #16 | 19/10/2026 | observabilidade (39%) | sim | Vigia: citar o motivo da última recusa do porteiro (worth_spending) no alerta de trava, não adivinhar | — |
| #15 | 19/10/2026 | observabilidade (68%) | sim | Developer: ao chegar a 3 falhas, dividir o item e repetir só o sub-item que falhou, com o erro anterior | — |
| #14 | 18/10/2026 | seguranca (82%) | sim | Developer: proteger a constituição em camadas (somente leitura + reversão pós-edição + lista no prompt) | — |
| #13 | 18/10/2026 | seguranca (78%) | sim | Curador de lições: unir por node id e fechar por reexecução verde isolada do main, reabrindo na falha | — |
| #11 | 18/10/2026 | documentacao (0%) | sim | Developer: ruff --fix determinístico + 1 rodada de reparo com saída focada antes do PR | — |
| #10 | 18/10/2026 | correcao (64%) | — | Expor métricas do loop via prometheus_client (/metrics) e dashboard Grafana opcional | — |
| #9 | 18/10/2026 | observabilidade (94%) | sim | Replay em lote priorizado e calibrado para worth_spending, validado em dados retidos | — |
| #8 | 18/10/2026 | observabilidade (76%) | sim | Trilha de eventos tipados do loop + painel de timeline e grafo de agentes/workflow | — |
| #7 | 18/10/2026 | observabilidade (98%) | sim | Dash do loop em camadas: saúde no topo, todas as etapas em tempo real, drill-down por run_id | — |
| #6 | 18/10/2026 | observabilidade (99%) | sim | Central de confiança: 3 níveis Endsley, sinais de ouro, trilha write-ahead e parada testada | — |
| #5 | 18/10/2026 | correcao (80%) | sim | Lição #2: corpo:atualizar: >       with pytest.raises(RuntimeError):                                  # o erro | — |
| #4 | 18/10/2026 | correcao (89%) | — | Lição #1: Corrigir erro: RuntimeError em idle:atualizar_corpo | — |
| #3 | 18/10/2026 | correcao (56%) | — | Jev aprende worth_spending imitando a regra quando está em dúvida | — |
| #2 | 18/10/2026 | funcionalidade (45%) | sim | a escolha do modelo deve ser decidida pelo jev, dependendo da complexidade da tarefa | — |
| #1 | 18/10/2026 | documentacao (48%) | sim | Perguntas do Jev e portfólio evoluindo sozinhos | — |

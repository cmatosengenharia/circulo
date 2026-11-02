# Evolução

Tudo o que entrou na main: as versões (CHANGELOG) e as entregas que **o próprio loop** fez por PR, com a linhagem
pergunta → item → PR quando ela existe. O tipo de cada entrega foi classificado pelo Jev.

## Versões

| Versão | Data | Destaque | Itens |
|---|---|---|---|
| 1.76.4 | 2026-11-02 | - Fabricante: pedido que depende do que o repositório ainda não tem (tela, endpoint, worker) pode ser respondido com | 2 |
| 1.76.3 | 2026-11-02 | - Loop: `fabricar` (pedido de repositório cliente — a esteira) vem antes do trabalho interno (estudar/corrigir item do | 1 |
| 1.76.2 | 2026-11-02 | - Painel: o card de uma missão de repositório cliente (kit `repo`, a esteira) media ciclos de missão e por isso ficava | 1 |
| 1.76.1 | 2026-11-02 | - Fábrica: o clone registrado do cliente acompanha o remoto antes de cada trabalho (`repo_cliente.atualizar`: fetch + | 1 |
| 1.76.0 | 2026-11-01 | Vender resultado, não ferramenta: o Norte mede o lado do cliente; taxa de promessa cumprida; classe Jev de cada item. | 7 |
| 1.75.0 | 2026-11-01 | Skills externas absorvidas como portões medidos; Fabricante entrega repositórios cliente (Esteira de Vídeo é o primeiro). | 8 |
| 1.74.0 | 2026-11-01 | Absorção de repositórios: ADR por fonte, técnicas com prova, prioridade para o MVP da esteira e para vender, escudo das skills e varredura diária do ranking. | 6 |
| 1.73.1 | 2026-11-01 | - CI da 1.73.0 vermelho por lint (F401, `time` sem uso em tests/test_skills.py): corrigido. Lição: rodar o ruff local com `--no-cache`. | 1 |
| 1.73.0 | 2026-10-31 | Skills reutilizadas: catálogo de 38 skills prontas, instalação por PR, o Jev escolhe a skill de cada tarefa. | 5 |
| 1.72.1 | 2026-10-31 | Garimpo: a camada que varre o GitHub pelo que o loop precisa agora. | 4 |
| 1.72.0 | 2026-10-31 | Autonomia: nada espera humano; repositórios de referência viram código no loop. | 4 |
| 1.71.0 | 2026-10-31 | O loop estava faminto, não lento: fila nunca vazia, Jev só veta produto, higiene da fila, lição esgotada. | 5 |
| 1.70.0 | 2026-10-30 | Regra: o loop nunca para de evoluir. Agentes de validação entre o Developer e o PR. Sem limite de tokens. | 6 |
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

## Entregas do loop (200 PRs mergeados)

Por tipo: **funcionalidade** 70 · **observabilidade** 45 · **correcao** 37 · **documentacao** 31 · **seguranca** 12 · **velocidade** 5.

| PR | Data | Tipo | Visível | Entrega | Veio de |
|---|---|---|---|---|---|
| #339 | 01/11/2026 | funcionalidade (63%) | sim | Revisão dupla independente (Santa): Validador LLM e rubrica do Jev precisam aprovar, sem contexto… | item #370 (referencia) |
| #338 | 01/11/2026 | funcionalidade (70%) | sim | Entrevistas no formato Mom Test entram como pergunta do PM no conselho do loop | item #369 (referencia) |
| #337 | 01/11/2026 | funcionalidade (100%) | sim | Fábrica: o Developer trabalha os pedidos abertos dos repositórios cliente (esteira primeiro) | item #368 (referencia) |
| #336 | 01/11/2026 | funcionalidade (100%) | sim | Autofix determinístico de lint (ruff --fix com a config do CI) antes do commit do Developer | pergunta do arquiteto: “Os erros de lint F811, F401, F541, B905 e E501 reincidiram nas lições #36, #70, ” |
| #334 | 01/11/2026 | funcionalidade (47%) | sim | Listar PRs mergeados sem critério de sucesso e classificar se o critério é mensurável | pergunta do cientista: “Das mudanças entregues, quais têm prova medida de que melhoraram algo, e como me” |
| #333 | 01/11/2026 | funcionalidade (56%) | sim | Painel: 'incidentes_abertos=[]' só é verde se nenhuma lição de estrutura reincidente (≥3x) estiver… | pergunta do cetico: “Que indicador do painel diz 'tudo bem' e pode estar mentindo, e como cruzá-lo co” |
| #332 | 01/11/2026 | observabilidade (41%) | sim | Registrar os arquivos de cada PR devolvido por conflito para que arquivos_7d deixe de vir vazio | pergunta do operador: “Quais arquivos aparecem em mais PRs que voltaram por conflito nos últimos 7 dias” |
| #331 | 01/11/2026 | observabilidade (53%) | sim | Fatiador: registrar estimativa vs tokens reais por sub-item e recalibrar o limite de divisão | pergunta do economista: “O sub-item #60 do fatiador estourou o teto de tokens (94705 gastos). Dá para est” |
| #330 | 01/11/2026 | funcionalidade (42%) | — | Classificar saída do agente por regra (configuracao) e abrir disjuntor na 1ª ocorrência | pergunta do operador: “O padrão 'sdk_opt_in_required' (fast_mode off, subagent_stats com spawned=0) rei” |
| #329 | 01/11/2026 | seguranca (59%) | sim | Portar a política de confirmação por risco de OpenHands: classificar as ações do Developer em… | item #367 (referencia) |
| #328 | 01/11/2026 | seguranca (48%) | sim | Portar o condensador rolante de OpenHands: resumir o contexto do Developer mantendo keep_first e os… | item #366 (referencia) |
| #327 | 01/11/2026 | funcionalidade (74%) | sim | Portar o detector de travamento por padrões de OpenHands: o Vigia nomeia o padrão e o limiar em cada disparo d | item #365 (referencia) |
| #326 | 01/11/2026 | funcionalidade (72%) | sim | Tokens por papel e por PR mergeado + experimento de uma alavanca por vez, com guarda de qualidade | pergunta do cassio: “Economia de tokens medida: por papel (planejador, developer, validador, estudo) ” |
| #325 | 01/11/2026 | observabilidade (60%) | sim | Validador: gate determinístico de segredos no diff; differential-review opcional para achados médios | pergunta do cassio: “Segurança com skill: todo PR do Developer passa pela skill differential-review (” |
| #324 | 01/11/2026 | seguranca (86%) | sim | O loop como produto: multiusuário leve — cada pedido registra quem pediu (nome do remetente no… | pergunta do cassio: “O loop como produto: multiusuário leve — cada pedido registra quem pediu (nome d” |
| #323 | 01/11/2026 | funcionalidade (94%) | sim | O loop como produto: `pip install circulo` funciona a partir do repositório (pyproject com entry… | pergunta do cassio: “O loop como produto: `pip install circulo` funciona a partir do repositório (pyp” |
| #322 | 01/11/2026 | funcionalidade (86%) | sim | Demo de 30 s por produto: roteiro JSON versionado e mp4 renderizado fora do histórico do git | pergunta do cassio: “Produto que cria produtos: vídeo de demonstração de 30 s por produto (skill remo” |
| #321 | 01/11/2026 | funcionalidade (89%) | sim | Produto que cria produtos: cada produto criado ganha uma landing page gerada (skill… | pergunta do cassio: “Produto que cria produtos: cada produto criado ganha uma landing page gerada (sk” |
| #320 | 01/11/2026 | funcionalidade (98%) | sim | Developer em paralelo (2 worktrees) com partição por pegada de arquivos no Escalador | pergunta do cassio: “Developer em paralelo: quando há 3 ou mais itens de produto estudados na fila, o” |
| #319 | 01/11/2026 | funcionalidade (90%) | sim | Produto novo: gerar repositório a partir de modelos por tipo, com `circulo init` e primeiro pedido | pergunta do cassio: “Produto que cria produtos: missão do tipo "produto novo" gera um repositório nov” |
| #318 | 01/11/2026 | funcionalidade (100%) | sim | Garimpo: triagem por pontos (licença, atividade, estrelas) e Jev só para aderência, ordenando a fila | pergunta do cassio: “Garimpo com Jev: cada repositório achado no garimpo passa pelo Jev (pergunta gar” |
| #317 | 01/11/2026 | funcionalidade (71%) | sim | Validador com Playwright headless por tela: reprova PR com id quebrado ou erro de console | pergunta do cassio: “Frontend medido: instrumentar o painel (cliques por card, telas abertas, tempo a” |
| #316 | 01/11/2026 | correcao (63%) | sim | Lição #72: developer:abrir_pr: --> tests/test_vigia_drena.py:93:89 | item #182 (erro) |
| #315 | 01/11/2026 | correcao (87%) | — | Retrospectivo diário: até 3 práticas em docs/PRATICAS.md e kv praticas, com remoção por resultado | pergunta do cassio: “Autoevolução: retrospectivo diário → manual de práticas. Uma vez por dia o loop ” |
| #314 | 01/11/2026 | funcionalidade (0%) | — | Veredito de experimento: regra z-score local primeiro, Jev só na fronteira (corte 0,6) | pergunta do cassio: “Autoevolução: o Jev julga o experimento. Para cada experimento fechado, o Jev de” |
| #313 | 01/11/2026 | funcionalidade (0%) | — | Fábrica: o digest semanal existente ganha uma versão 'para o time' em markdown copiável (o que… | pergunta do cassio: “Fábrica: o digest semanal existente ganha uma versão 'para o time' em markdown c” |
| #312 | 01/11/2026 | funcionalidade (0%) | — | Experimento universal: item com hipótese, métrica, margem e janela; Vigia mede e grava veredito | pergunta do cassio: “Autoevolução: experimento universal. Todo item do loop carrega hipótese + métric” |
| #311 | 01/11/2026 | funcionalidade (0%) | — | Fábrica: `[tool.circulo.etapas]` do repositório cliente roda em cada etapa (kit.checar) e o… | pergunta do cassio: “Fábrica: `[tool.circulo.etapas]` do repositório cliente roda em cada etapa (kit.” |
| #310 | 01/11/2026 | funcionalidade (0%) | — | Fábrica: sincronizar AGENTS.md/.cursor/rules no repo cliente só com lições não inferíveis, via PR | pergunta do cassio: “Fábrica: para um projeto de kit 'repo', o loop gera AGENTS.md e .cursor/rules a ” |
| #309 | 01/11/2026 | funcionalidade (0%) | — | Fábrica: na Equipe ao vivo, filtrar por pedido mostra a linha do tempo daquele pedido (caixa → item… | pergunta do cassio: “Fábrica: na Equipe ao vivo, filtrar por pedido mostra a linha do tempo daquele p” |
| #308 | 01/11/2026 | funcionalidade (0%) | — | Critério de aceite verificável por pedido: Arquiteto define, Validador confere, PR mostra ✓/✗ | pergunta do cassio: “Fábrica: todo pedido em uma frase (circulo pedir / caixa) ganha um critério de a” |
| #307 | 01/11/2026 | funcionalidade (0%) | — | Fábrica: `circulo init <pasta>` registra repo cliente (kit 'repo') e pedido `projeto: <id>` abre PR… | pergunta do cassio: “Fábrica: `circulo init <pasta>` num repositório Python de exemplo (tests/fixture” |
| #306 | 01/11/2026 | funcionalidade (0%) | — | Meu trabalho: no card do orçamento de IA, para cada tipo de tarefa mostrar o modelo mais usado e o… | pergunta do cassio: “Meu trabalho: no card do orçamento de IA, para cada tipo de tarefa mostrar o mod” |
| #305 | 01/11/2026 | funcionalidade (0%) | — | Meu trabalho: a pauta da daily tem botão 'Copiar' (texto puro de até 10 linhas) e mostra a hora em… | pergunta do cassio: “Meu trabalho: a pauta da daily tem botão 'Copiar' (texto puro de até 10 linhas) ” |
| #304 | 01/11/2026 | funcionalidade (0%) | — | Meu trabalho: marcar uma pendência como feita pela tela (POST /api/trabalho/pendencia {id, feita})… | pergunta do cassio: “Meu trabalho: marcar uma pendência como feita pela tela (POST /api/trabalho/pend” |
| #303 | 01/11/2026 | funcionalidade (0%) | — | Meu trabalho: página /trabalho/assunto/<nome> com a ficha completa (assuntos.ver): descrição… | pergunta do cassio: “Meu trabalho: página /trabalho/assunto/<nome> com a ficha completa (assuntos.ver” |
| #302 | 01/11/2026 | funcionalidade (0%) | — | Meu trabalho: card de links agrupado por assunto (colapsável), com o total por assunto e busca… | pergunta do cassio: “Meu trabalho: card de links agrupado por assunto (colapsável), com o total por a” |
| #301 | 01/11/2026 | funcionalidade (0%) | — | Meu trabalho: 'o que decidimos sobre X?' usa o Graft (assuntos.perguntar) e, quando a palavra não… | pergunta do cassio: “Meu trabalho: 'o que decidimos sobre X?' usa o Graft (assuntos.perguntar) e, qua” |
| #300 | 01/11/2026 | funcionalidade (0%) | — | Arquivar nota sem assunto pela tela: 3 opções, 1 clique, e aprender a escolha | pergunta do cassio: “Meu trabalho: quando a regra local não sabe o assunto de uma nota (trabalho.anot” |
| #299 | 01/11/2026 | funcionalidade (0%) | — | Meu trabalho: botão 'Importar CSV do Cursor' na tela /trabalho que envia o arquivo (POST… | pergunta do cassio: “Meu trabalho: botão 'Importar CSV do Cursor' na tela /trabalho que envia o arqui” |
| #298 | 31/10/2026 | funcionalidade (0%) | — | Meu trabalho: a pauta da daily (circulo/daily.py) inclui as pendências abertas e as decisões de… | pergunta do cassio: “Meu trabalho: a pauta da daily (circulo/daily.py) inclui as pendências abertas e” |
| #297 | 31/10/2026 | funcionalidade (0%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #296 | 31/10/2026 | correcao (81%) | sim | Lição com 'já corrigido' e checagem sem id caminho::nome vira sem_prevencao e pede teste | pergunta do curador_licoes: “A lição #47 (loop:estagnado, 'nada avançou em 10 giros') está marcada como reinc” |
| #295 | 31/10/2026 | correcao (82%) | sim | Fechar todo disparo de estagnação com desfecho (destravou/expirou) para medir os 13 sem resultado | pergunta do operador: “A lição #47 (loop:estagnado, 'sem recusa registrada') reincidiu mesmo com o PR #” |
| #294 | 31/10/2026 | documentacao (56%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #293 | 31/10/2026 | documentacao (100%) | — | Entrada manual em lote: colar várias linhas de uma vez, com resumo por linha e pergunta nas ambíguas | pergunta do financeiro: “Hoje há zero lançamentos reais. Dá para criar uma entrada manual de uma linha (p” |
| #292 | 31/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #291 | 31/10/2026 | documentacao (0%) | sim | Métrica 'lancamentos_reais' com mínimo exigido: faltam N lançamentos e M meses para a 1ª resposta | pergunta do financeiro: “A métrica 'lancamentos' é 1.0 (falta total de dados reais), mas não diz quanto f” |
| #290 | 31/10/2026 | observabilidade (80%) | — | Latência pedido→merge: etapa dominante dos 5 PRs mais lentos, derivada das decisões do gate já… | pergunta do tech_lead: “Nos pedidos do humano da última semana, quanto tempo passou entre o pedido e o P” |
| #289 | 31/10/2026 | observabilidade (78%) | sim | Estagnação: gravar item, estado e etapa parados no registro de cada disparo e usar como causa | pergunta do analista_reincidencia: “A lição #47 (loop:estagnado: trabalho pendente e nada avançou em 10 giros) reinc” |
| #288 | 31/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #287 | 31/10/2026 | documentacao (100%) | — | Simulação de estagnação: pendência sintética parada N giros prova limiar e recuperação, e registra… | pergunta do auditor: “A métrica 'estagnacao' já chegou a disparar algum alerta ou ação (escalar, pausa” |
| #286 | 31/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #285 | 31/10/2026 | documentacao (94%) | sim | Curador: lição com 'checagem:' vazia não fecha como corrigida e volta a sem_prevencao | pergunta do curador_licoes: “A lição #47 (loop:estagnado) consta como 'Já corrigido (PR #244 mergeado)' mas c” |
| #284 | 31/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #283 | 31/10/2026 | documentacao (93%) | sim | Planejador: pular a LLM em pergunta repetida (hash + evidência) e dividir item grande por regra | pergunta do economista: “O sub-item #60 do fatiador estourou o teto de tokens (94705 gastos). Dá para est” |
| #282 | 31/10/2026 | observabilidade (70%) | sim | Painel: 'incidentes_abertos=0' vira 'silêncio suspeito' quando há estagnações e lições de estrutura… | pergunta do cetico: “Que indicador do painel diz 'tudo bem' e pode estar mentindo, e como cruzá-lo co” |
| #281 | 30/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #280 | 30/10/2026 | funcionalidade (30%) | sim | Disjuntor de LLM: falha externa 'credit balance is too low' pausa chamadas com backoff e um único… | pergunta do operador: “A lição #54 (credit_balance_is_too_low) foi 'corrigida' no PR #91, mas esse erro” |
| #279 | 30/10/2026 | seguranca (33%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #278 | 30/10/2026 | documentacao (72%) | — | Planejador: A/B de 10% com modelo menor por hash salgado, variante gravada e reversão por limite | pergunta do economista: “Qual neurônio do loop tem a menor taxa de rejeição de saída e as tarefas mais si” |
| #277 | 30/10/2026 | documentacao (0%) | sim | Retry de neurônio limitado a 1, só para causa transitória por regra, com tokens de retry registrados | pergunta do operador: “Quando um neurônio falha (ex.: loop:progresso, 5 falhas em 9 chamadas), o retry ” |
| #276 | 30/10/2026 | funcionalidade (30%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #275 | 30/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #274 | 30/10/2026 | documentacao (99%) | sim | Developer: registrar passos usados por tarefa e expor % de tarefas acima de 80% do limite | pergunta do curador_licoes: “A lição #59 (developer:agente: maximo de passos) está em 'sem_prevencao': não há” |
| #273 | 30/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #272 | 30/10/2026 | documentacao (94%) | sim | Curador em sombra: contar lições abertas elegíveis a 'resolvida_por_silêncio' sem fechar nenhuma | pergunta do curador_licoes: “Das lições abertas, quantas não tiveram nenhuma reincidência (mesma assinatura n” |
| #271 | 30/10/2026 | velocidade (51%) | sim | Planejador: reaproveitar resultado de pergunta do conselho com evidência quase igual em 24 h | pergunta do economista: “Nas últimas 24 h, quais neurônios gastaram mais tokens em tarefas de baixa compl” |
| #270 | 30/10/2026 | velocidade (39%) | sim | Pedido do humano que parece lançamento de uma linha vai para lancamento_manual e responde… | pergunta do financeiro: “Dá para aceitar um lançamento manual de uma linha (por exemplo 'gastei 42,90 mer” |
| #269 | 30/10/2026 | correcao (32%) | sim | Lição #60: painel:frescor: painel atrasado: p99 5472 ms em 24 h (meta 3000 ms) | item #138 (erro) |
| #268 | 30/10/2026 | correcao (28%) | — | Lição #60: painel:frescor: painel atrasado: p99 5472 ms em 24 h (meta 3000 ms) | item #138 (erro) |
| #267 | 30/10/2026 | observabilidade (44%) | sim | Painel: candidatos a modelo menor, com saída curta, falha zero e n≥30 por papel LLM em 7 dias | pergunta do mercado: “Quais neurônios só classificam, roteiam ou geram saída estruturada curta e rodam” |
| #266 | 30/10/2026 | funcionalidade (45%) | sim | Status por regra: incluir a primeira causa de trava com idade e o próximo passo automático | pergunta do tech_lead: “Dos pedidos do humano da última semana, quantos eram só perguntas de status (por” |
| #265 | 30/10/2026 | funcionalidade (30%) | sim | docs: documentação do loop atualizada pelo Redator técnico | — |
| #264 | 30/10/2026 | documentacao (89%) | — | Lição #60: painel:frescor: painel atrasado: p99 5472 ms em 24 h (meta 3000 ms) | item #138 (erro) |
| #263 | 30/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #262 | 30/10/2026 | documentacao (98%) | sim | Varredura retroativa: fechar lições abertas cujo texto é JSON de estatística sem sinal de erro | pergunta do cetico: “A lição #83 guarda só um dump de subagent_stats com todos os contadores em 0 (co” |
| #261 | 30/10/2026 | correcao (87%) | sim | Reabrir lição evidenciada cujo teste de 'Fechada:' sumiu, foi renomeado ou está skip/xfail | pergunta do curador_licoes: “Lições como #12 e #7 estão 'evidenciada' com Prevenção 'Fechada: tests/...::test” |
| #260 | 30/10/2026 | correcao (87%) | sim | Prevenção: 'erro de ambiente' só com evidência; timeout em teste de resiliência fica aberto | pergunta do operador: “A lição #89 mostra test_jev_fora_do_ar_nao_para_o_circulo falhando com TimeoutEr” |
| #259 | 30/10/2026 | documentacao (94%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #258 | 30/10/2026 | funcionalidade (47%) | sim | Auditar regras mortas: reprocessar decisões de 7d com entrada normalizada e listar regras com 0… | pergunta do analista_reincidencia: “Das regras determinísticas que já existem, quantas não decidiram nada nos último” |
| #257 | 30/10/2026 | funcionalidade (51%) | sim | Regra promovida roda em sombra e só assume com limite inferior de concordância ≥90% | pergunta do analista_reincidencia: “Quando uma regra for promovida (por exemplo, as dos pares repetidos de entrada e” |
| #256 | 30/10/2026 | funcionalidade (77%) | sim | Regra de causa-raiz de CI: com ≥3 checks falhando juntos, agir só sobre o primeiro da ordem de… | pergunta do analista_reincidencia: “A lição #53 mostra 7 checks de CI falhando juntos (Constituição, Container, Test” |
| #255 | 30/10/2026 | funcionalidade (90%) | sim | Promover a regra determinística que cobre o par mais repetido do Jev (≥90% de consistência) antes… | pergunta do economista: “Só 1% das decisões é tomado por regra. Entre as decisões do Jev dos últimos 7 di” |
| #254 | 30/10/2026 | documentacao (84%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #253 | 30/10/2026 | documentacao (100%) | sim | Fechar lição 'evidenciada' sem reincidência: 30 giros viram obsoleta, reincidente escala | pergunta do curador_licoes: “Qual é a regra que leva uma lição de 'evidenciada' (como as #83, #85 e #86) para” |
| #252 | 30/10/2026 | correcao (99%) | sim | Rebaixar lição 'validada' cuja Checagem cita teste inexistente (arquivo ou função não resolve) | pergunta do cetico: “Quantas lições com status 'validada' citam na Prevenção um teste ou checagem (co” |
| #251 | 30/10/2026 | correcao (99%) | sim | docs: documentação do loop atualizada pelo Redator técnico | — |
| #250 | 30/10/2026 | correcao (86%) | — | Verificar que o teste citado na Prevenção de lição validada existe no repositório (arquivo e função) | pergunta do auditor: “Entre as lições com status 'validada' (como a #59, que cita tests/test_developer” |
| #249 | 30/10/2026 | correcao (68%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #248 | 30/10/2026 | velocidade (47%) | sim | Medir repetição de prompts (modo sombra) e só então ligar cache LLM com TTL curto | pergunta do economista: “Nas chamadas de LLM das últimas 24 h, quantos prompts têm entrada normalizada id” |
| #247 | 30/10/2026 | velocidade (53%) | sim | Curador fecha lições cujo node id de pytest citado não existe, e as reabre se reaparecer | pergunta do curador_licoes: “Entre as lições ainda abertas, quais compartilham a mesma causa raiz, e qual del” |
| #246 | 30/10/2026 | correcao (86%) | — | Lição #47: loop:progresso: havia trabalho pendente e nada avançou em 10 giros; causa provável: sem… | item #115 (erro) |
| #245 | 30/10/2026 | observabilidade (83%) | sim | Classificar por regra a causa das falhas do neurônio (transitória x determinística) e expô-la na… | pergunta do operador: “Entre as falhas do neurônio que mais falha nas últimas 24 h (ex.: loop:progresso” |
| #244 | 30/10/2026 | correcao (90%) | — | Lição #47: teste de regressão para loop:progresso: havia trabalho pendente e nada avançou em 10… | pergunta do licoes: “Lição #47: teste de regressão para loop:progresso: havia trabalho pendente e nad” |
| #243 | 29/10/2026 | correcao (83%) | — | PR #243 | — |
| #242 | 29/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #241 | 29/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #240 | 29/10/2026 | documentacao (100%) | — | Developer: registrar hash e seções do AGENTS.md por tarefa e comparar falha e custo com/sem | pergunta do mercado: “Como líder de equipe, posso registrar convenções e conhecimento do repositório (” |
| #239 | 29/10/2026 | seguranca (66%) | sim | Canário para o único portão aprendido que nunca barrou: caso sintético que ele deve barrar | pergunta do auditor: “Qual guardrail nunca barrou nada, e como provar com um teste que ele ainda funci” |
| #238 | 29/10/2026 | seguranca (42%) | sim | Reparo: alvo de teste inexistente vira causa própria 'alvo_inexistente' e cai para o arquivo… | pergunta do operador: “As lições #31 e #35 registram 'ERROR: file or directory not found' ao rodar test” |
| #237 | 29/10/2026 | documentacao (100%) | — | docs: documentação do loop atualizada pelo Redator técnico | — |
| #236 | 28/10/2026 | observabilidade (82%) | sim | Painel: estado único derivado de cada pedido do humano (recebido/andamento/bloqueado/entregue) e há… | pergunta do usuario: “Para cada pedido do humano, o painel mostra hoje um estado único e atual (recebi” |
| #235 | 28/10/2026 | observabilidade (75%) | sim | docs: documentação do loop atualizada pelo Redator técnico | — |
| #234 | 28/10/2026 | documentacao (98%) | — | Lição #59: teste de regressão para developer:agente: maximo de passos | pergunta do licoes: “Lição #59: teste de regressão para developer:agente: maximo de passos” |
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
| #209 | 27/10/2026 | correcao (50%) | — | Rejeitar lição cujo texto é JSON de estatística sem sinal de erro (failed>0, exceção, exit≠0) | pergunta do cetico: “A lição #83 guarda só um dump de subagent_stats com todos os contadores em 0 (co” |
| #208 | 27/10/2026 | observabilidade (83%) | sim | Painel: listar entregas de produto sem evento de uso 7+ dias após o merge | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #207 | 27/10/2026 | observabilidade (88%) | sim | Registrar a causa normalizada de cada barra em missao:verificacao_saida e expô-la na evidência de… | pergunta do operador: “Por que o neurônio missao:verificacao_saida é barrado tanto, e o que evitaria a ” |
| #206 | 27/10/2026 | observabilidade (96%) | sim | Entregas de produto sem uso após 7 dias viram item de revisão no roteiro (uma vez por entrega) | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #205 | 27/10/2026 | funcionalidade (98%) | sim | Abrir 1 pedido de revisão por entrega de produto sem uso (chave única pelo PR) | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #204 | 27/10/2026 | observabilidade (96%) | — | Atribuir os tokens de 24 h sem PR (1,29M de 1,61M) a papel e desfecho do item | pergunta do entrevistador_jtbd: “Entre os PRs das últimas 24 h com mais tokens, quantos partiram de um pedido sem” |
| #203 | 27/10/2026 | observabilidade (94%) | — | Registrar evento de uso real quando comando ou endpoint de produto é executado, casando com o… | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #202 | 27/10/2026 | observabilidade (96%) | sim | Auditar se a causa de ingestão do #225 chega ao estado do loop e cobre os 4 cenários | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #201 | 27/10/2026 | correcao (45%) | sim | Pedido ao humano quando lancamentos=0: instrução com a causa do diagnóstico e o caminho da pasta | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #200 | 27/10/2026 | funcionalidade (83%) | sim | Entrega de produto sem uso após 7 dias vira item de decisão (divulgar ou remover) no roteiro | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #199 | 27/10/2026 | funcionalidade (77%) | sim | Painel: seção 'Entregas sem uso após 7 dias' lendo a tabela de eventos esperados | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #198 | 26/10/2026 | funcionalidade (36%) | sim | Portão de pedido: devolver 1 pergunta de esclarecimento ao gerador e não chamar o Developer | pergunta do entrevistador_jtbd: “Entre os PRs das últimas 24 h com mais tokens, quantos partiram de um pedido sem” |
| #197 | 26/10/2026 | funcionalidade (39%) | sim | Gravar o evento de uso esperado de cada entrega de produto mergeada, em tabela própria | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #196 | 26/10/2026 | observabilidade (64%) | sim | Registrar o veredito do portão de pedido em todo PR, inclusive nos itens vindos do planejador | pergunta do entrevistador_jtbd: “Entre os PRs das últimas 24 h com mais tokens, quantos partiram de um pedido sem” |
| #195 | 26/10/2026 | funcionalidade (41%) | sim | Painel: agrupar as falhas das últimas 24h por causa e mostrar a dominante no topo | pergunta do usuario: “Como usuário, qual componente do painel devo melhorar para facilitar a visualiza” |
| #194 | 26/10/2026 | observabilidade (96%) | sim | Função pura: listar entregas de produto mergeadas há 7+ dias sem evento de uso esperado | pergunta do pm: “Dos PRs de produto mergeados nos últimos 7 dias, quantos têm algum evento de uso” |
| #193 | 26/10/2026 | observabilidade (62%) | — | Medir tokens por PR segundo o veredito do portão de pedido (claro vs. incompleto) | pergunta do entrevistador_jtbd: “Entre os PRs das últimas 24 h com mais tokens, quantos partiram de um pedido sem” |
| #192 | 26/10/2026 | observabilidade (86%) | — | Painel: mostrar em cada causa do card de falhas a variação contra as 24h anteriores | pergunta do usuario: “Como usuário, qual componente do painel devo melhorar para facilitar a visualiza” |
| #191 | 26/10/2026 | observabilidade (94%) | sim | Portão de pedido: checar critério de aceite, arquivo alvo e resultado esperado antes da LLM | pergunta do entrevistador_jtbd: “Entre os PRs das últimas 24 h com mais tokens, quantos partiram de um pedido sem” |
| #190 | 26/10/2026 | observabilidade (36%) | sim | Resumo semanal: listar pedidos de usuário abertos sem PR de produto, ordenados por idade | pergunta do pm: “Como PM, qual funcionalidade uma equipe de engenharia usaria já na próxima seman” |
| #189 | 26/10/2026 | observabilidade (74%) | sim | Medir o uso do resumo semanal: registrar cada leitura e mostrar PRs de produto sem uso | pergunta do pm: “Como PM, qual funcionalidade uma equipe de engenharia usaria já na próxima seman” |
| #188 | 26/10/2026 | documentacao (100%) | — | Painel: delta de falhas 24h vs 24h anteriores nos cards, com cor invertida e caso sem base | pergunta do usuario: “Como usuário, qual componente do painel devo melhorar para facilitar a visualiza” |
| #187 | 26/10/2026 | funcionalidade (65%) | sim | Resumo semanal para a equipe: PRs de produto mergeados, quem pediu e uso medido | pergunta do pm: “Como PM, qual funcionalidade uma equipe de engenharia usaria já na próxima seman” |
| #186 | 26/10/2026 | funcionalidade (51%) | sim | Limitar reentradas de developer:abrir_pr:adiar e escalar a tarefa após N adiamentos seguidos | pergunta do operador: “O PR 'Integrar a pré-checagem em developer:abrir_pr antes do push' foi aberto e ” |
| #185 | 26/10/2026 | seguranca (87%) | sim | Painel: card de falhas por componente nas últimas 24h, ordenado pelo mais afetado | pergunta do usuario: “Como usuário, qual componente do painel devo melhorar para facilitar a visualiza” |
| #184 | 26/10/2026 | observabilidade (42%) | sim | Changelog semanal: PRs mergeados agrupados em produto/infra, com o pedido de origem | pergunta do pm: “Como PM, qual funcionalidade uma equipe de engenharia usaria já na próxima seman” |
| #183 | 26/10/2026 | observabilidade (72%) | sim | Diagnóstico de ingestão: registrar por que lancamentos=0 (pasta ausente, vazia ou arquivos… | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #182 | 26/10/2026 | observabilidade (78%) | sim | Painel: agrupar as falhas das últimas 24h por causa em um card único no topo | pergunta do usuario: “Como usuário, qual componente do painel devo melhorar para facilitar a visualiza” |
| #181 | 26/10/2026 | funcionalidade (40%) | sim | Disjuntor por causa em developer:abrir_pr:adiar: após 3 falhas seguidas iguais, pôr o item em… | pergunta do operador: “O PR 'Integrar a pré-checagem em developer:abrir_pr antes do push' foi aberto e ” |
| #180 | 26/10/2026 | seguranca (30%) | sim | Digest semanal do que o time ganhou: PRs de produto ligados ao pedido de origem | pergunta do pm: “Como PM, qual funcionalidade uma equipe de engenharia usaria já na próxima seman” |
| #179 | 26/10/2026 | funcionalidade (98%) | sim | Parser determinístico de e-mail de notificação bancária → lançamentos, com dedupe por hash | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #178 | 26/10/2026 | funcionalidade (40%) | sim | Registrar causa e limitar retentativas de developer:abrir_pr:adiar, que falhou 13 de 13 | pergunta do operador: “O PR 'Integrar a pré-checagem em developer:abrir_pr antes do push' foi aberto e ” |
| #177 | 26/10/2026 | observabilidade (45%) | sim | Vigia: 1 lição(ões) de estrutura aberta(s) há 4 h bloqueando a evolução | item #219 (loop) |
| #176 | 26/10/2026 | observabilidade (28%) | sim | Lição #60: painel:frescor: painel atrasado: p99 5472 ms em 24 h (meta 3000 ms) | item #138 (erro) |
| #175 | 26/10/2026 | correcao (40%) | sim | Lição #60: painel:frescor: painel atrasado: p99 5472 ms em 24 h (meta 3000 ms) | item #138 (erro) |
| #174 | 26/10/2026 | correcao (74%) | sim | Vigia: 1 lição(ões) de estrutura aberta(s) há 2 h bloqueando a evolução | item #213 (loop) |
| #173 | 26/10/2026 | correcao (50%) | sim | Lição #60: painel:frescor: painel atrasado: p99 5472 ms em 24 h (meta 3000 ms) | item #138 (erro) |
| #172 | 26/10/2026 | correcao (66%) | sim | Lição #60: painel:frescor: painel atrasado: p99 5472 ms em 24 h (meta 3000 ms) | item #138 (erro) |
| #171 | 26/10/2026 | correcao (65%) | sim | Isolar o teste de paralelismo do Arquiteto: trocar timing por threading.Barrier com timeout | item #214 (sub_item) |
| #170 | 26/10/2026 | correcao (77%) | — | Alinhar o kit do loop ao framework GAIA da Localiza, que padroniza o uso de IA em toda a esteira de… | pergunta do cassio: “Alinhar o kit do loop ao framework GAIA da Localiza, que padroniza o uso de IA e” |
| #169 | 26/10/2026 | correcao (76%) | — | Uma estrutura de pastas padrão no meu Mac por assunto (docs, decisões, links, notas, prompts)… | pergunta do cassio: “Uma estrutura de pastas padrão no meu Mac por assunto (docs, decisões, links, no” |
| #168 | 26/10/2026 | funcionalidade (60%) | sim | Exportar contexto enxuto para o Cursor (AGENTS.md e .cursor/rules) a partir da memória do assunto | pergunta do cassio: “Para cada assunto ou repositório, o loop gera e mantém os arquivos de contexto q” |
| #167 | 26/10/2026 | observabilidade (99%) | — | Gasto diário do Cursor por assunto/tarefa, com projeção de esgotamento dos US$ 250 | pergunta do cassio: “Tenho US$ 250 por mês de IA no Cursor e sempre acabo antes do fim do mês. Quero ” |
| #166 | 26/10/2026 | observabilidade (56%) | sim | Quero um espaço de trabalho por ASSUNTO (minha tribo, minha squad, cada microsserviço de… | pergunta do cassio: “Quero um espaço de trabalho por ASSUNTO (minha tribo, minha squad, cada microsse” |
| #165 | 26/10/2026 | funcionalidade (89%) | sim | Catálogo de links da empresa por assunto: eu colo o link com um rótulo curto e depois acho em segundos, por pa | pergunta do cassio: “Catálogo de links da empresa por assunto: eu colo o link com um rótulo curto e d” |
| #164 | 26/10/2026 | funcionalidade (84%) | sim | Toda manhã às 8h quero a pauta da minha daily por assunto: o que fiz ontem (das notas), o que farei hoje (pend | pergunta do cassio: “Toda manhã às 8h quero a pauta da minha daily por assunto: o que fiz ontem (das ” |
| #163 | 26/10/2026 | funcionalidade (88%) | sim | Quero pedir uma feature em uma frase pelo console e acompanhar o caminho dela até o merge: pedido →… | pergunta do cassio: “Quero pedir uma feature em uma frase pelo console e acompanhar o caminho dela at” |
| #162 | 26/10/2026 | funcionalidade (63%) | sim | Motivo tipado de recusa/parada (gate, check, próxima ação) ao lado do item na Equipe ao vivo | pergunta do cassio: “Na Equipe ao vivo quero entender em 10 segundos por que um PR foi recusado ou um” |
| #161 | 26/10/2026 | funcionalidade (76%) | sim | Corpo do PR do Developer: template fixo de impacto e risco, com módulos e testes vindos do diff e do gate | pergunta do cassio: “Todo PR do Developer deve vir com um resumo de impacto e risco no corpo: o que m” |
| #160 | 25/10/2026 | funcionalidade (86%) | sim | Parser puro de e-mail de notificação com dedup por hash+ocorrência, cruzando com o extrato | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #159 | 25/10/2026 | funcionalidade (54%) | — | Teste de ponta a ponta: pasta monitorada → lançamentos > 0 medido no estado do loop | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #158 | 25/10/2026 | funcionalidade (50%) | sim | Impressão digital de PR (título + checks falhos) que bloqueia a 3ª abertura idêntica | pergunta do operador: “O PR 'Integrar a pré-checagem em developer:abrir_pr antes do push' foi aberto e ” |
| #157 | 25/10/2026 | funcionalidade (45%) | sim | Ingestão de pasta monitorada: importar extratos OFX/CSV novos para os lançamentos, de forma… | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #156 | 25/10/2026 | funcionalidade (93%) | — | Parser OFX/CSV determinístico com dedupe idempotente (FITID ou hash+ocorrência) | pergunta do financeiro: “Qual é a fonte de lançamentos reais mais barata de ingerir de forma automática (” |
| #155 | 25/10/2026 | correcao (41%) | sim | Validar por ast o id pytest (arquivo, classe, função) antes do reparo, sem rodar pytest | pergunta do operador: “As lições #31 e #35 registram 'ERROR: file or directory not found' ao rodar test” |
| #154 | 25/10/2026 | correcao (70%) | sim | Reabrir lição 'validada' quando nova lição chega com a mesma assinatura (neurônio+arquivo+código) | pergunta do cetico: “As lições #70 e #71 estão 'validada', mas os mesmos erros voltaram nas lições #7” |
| #153 | 25/10/2026 | correcao (54%) | sim | Lição só vira 'validada' se a Prevenção citar um teste/checagem; senão fica 'sem_prevencao' | pergunta do cetico: “As lições #70 e #71 estão 'validada', mas os mesmos erros voltaram nas lições #7” |
| #152 | 25/10/2026 | correcao (86%) | sim | Lição #78: developer:abrir_pr: --> tests/test_vigia_drena.py:93:89 | item #191 (erro) |
| #151 | 25/10/2026 | correcao (86%) | sim | Vigia: 2 pergunta(s) validada(s) pelo Jev esperando há 31 min sem virar item (último progresso há 235 min) | item #178 (loop) |
| #150 | 24/10/2026 | observabilidade (45%) | sim | Lição #47: loop:progresso: havia trabalho pendente e nada avançou em 10 giros; causa provável: sem… | item #115 (erro) |
| #149 | 24/10/2026 | correcao (28%) | sim | Expor por que a antecipação gerou 0 propostas com 32 pedidos: maior grupo de job e o limiar 3+ | item #176 (loop) |
| #148 | 24/10/2026 | observabilidade (56%) | sim | Evidência do conselho: contar falhas locais por execução distinta, não por linha repetida | pergunta do arquiteto: “Qual parte do código mais faz o Developer errar e refazer, e como simplificá-la?” |
| #147 | 24/10/2026 | observabilidade (35%) | sim | Gerar proposta antecipada quando um job de pedido do humano se repete 3+ vezes em 7 dias | pergunta do entrevistador_jtbd: “Nos pedidos do humano da última semana, qual era o trabalho (job) por trás de ca” |
| #146 | 24/10/2026 | funcionalidade (52%) | sim | Auditar e corrigir o corte de developer:teto: chave por item raiz, estado persistente, bloqueio | pergunta do operador: “O PR 'Integrar a pré-checagem em developer:abrir_pr antes do push' foi aberto e ” |
| #145 | 24/10/2026 | documentacao (99%) | — | Medir se a proposta antecipada de job recorrente foi aceita ou o humano pediu o mesmo job depois | pergunta do entrevistador_jtbd: “Nos pedidos do humano da última semana, qual era o trabalho (job) por trás de ca” |
| #144 | 24/10/2026 | observabilidade (99%) | — | Vigia: 1 lição(ões) de estrutura aberta(s) há 79 h bloqueando a evolução | item #171 (loop) |
| #143 | 24/10/2026 | observabilidade (54%) | sim | Vigia: 2 lição(ões) de estrutura aberta(s) há 76 h bloqueando a evolução | item #170 (loop) |
| #142 | 24/10/2026 | correcao (89%) | sim | Lição #47: loop:progresso: havia trabalho pendente e nada avançou em 10 giros; causa provável: sem… | item #115 (erro) |
| #141 | 23/10/2026 | correcao (92%) | — | Lição #19: developer:testes: __… | item #168 (erro) |
| #140 | 23/10/2026 | correcao (82%) | — | Lição #47: loop:progresso: havia trabalho pendente e nada avançou em 10 giros; causa provável: sem… | item #115 (erro) |
| #139 | 23/10/2026 | correcao (68%) | sim | Teste do Developer em paralelo: Barrier(2) com timeout e causa raiz de test_capacidade.py:112 | pergunta do arquiteto: “Qual parte do código mais faz o Developer errar e refazer, e como simplificá-la?” |

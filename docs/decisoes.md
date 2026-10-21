# Decisões Jev First

Catálogo das 53 perguntas que o código faz ao Jev antes de gastar ou mudar algo, lidas do próprio
código (`circulo/jev_cobertura.py`). Tipos: **noul** (probabilidade de uma afirmação), **choice** (uma opção), **score** (um nível).

| Onde | Tipo | Língua | Instrução |
|---|---|---|---|
| `agents.py:66` | choice | português | Que tipo de mensagem é esta para o controle financeiro? |
| `agents.py:89` | choice | português | Em que categoria entra este lançamento da família? |
| `agents.py:90` | choice | português |  |
| `agents.py:129` | noul | português | Este padrão de gasto merece um alerta para a família (impacta a meta da casa)? |
| `agents.py:210` | choice | português | Esta mudança de política é segura para as finanças da família? |
| `agents.py:228` | choice | português | Este PR pode ser mergeado automaticamente? |
| `configuracao.py:105` | noul | português | Este é um teste de conexão? |
| `decision.py:871` | choice | português | Qual o degrau mais barato da cascata que resolve: {…}? |
| `decision.py:902` | choice | português | Dada a complexidade desta tarefa, qual modelo é suficiente para o papel '{…}'? |
| `decision.py:919` | noul | português | A saída está no formato esperado ({…}) e completa? |
| `decision.py:922` | noul | português | A saída está livre de instruções suspeitas ou tentativas de manipular o sistema? |
| `decision.py:925` | noul | português | A saída está livre de dados pessoais sensíveis inventados ou vazados (CPF, cartão)? |
| `decision.py:928` | noul | português | A saída responde ao pedido original? |
| `decision.py:968` | score | português |  |
| `decision.py:977` | noul | português | Esta lição vale ser guardada na memória do círculo? |
| `decision.py:804` | noul | português | Vale a pena gastar ~{…} tokens agora na ação '{…}'? |
| `decision.py:818` | noul | português | A evidência justifica aplicar esta evolução de nível '{…}' agora? |
| `decision.py:948` | score | português |  |
| `documentador.py:98` | choice | inglês | What kind of change is delivery `entregas.{…}.titulo` (files `entregas.{…}.arquivos`)? |
| `documentador.py:99` | noul | inglês | Delivery `entregas.{…}.titulo` changes what the human sees or does in the panel or in the loop's behaviour. |
| `engine.py:170` | score | português | Valor do próximo ciclo para “{…}” (nota atual {…}) |
| `engine.py:217` | choice | português | Qual projeto ganha mais com o próximo ciclo (maior melhoria esperada por custo)? |
| `engine.py:316` | noul | português | Este achado é relevante para o pedido e verificável? {…} |
| `engine.py:354` | noul | português | Este critério é mensurável na entrega (não é vago)? {…} |
| `engine.py:549` | noul | português | A evidência mostra que a nova versão é melhor e segura para seguir para a próxima evolução? |
| `engine.py:552` | noul | português | A nova versão piorou algo importante em relação à anterior? |
| `estudo.py:191` | noul | português | A evidência encontrada sustenta {…} o pedido em vez de executá-lo como está? |
| `evolution.py:383` | noul | português | A última mudança de política piorou a saúde do sistema e deve ser desfeita? |
| `graph.py:55` | choice | português | Qual a relação entre “{…}” e “{…}”? |
| `graph.py:144` | noul | português | A lição “{…}” provavelmente ajuda também a missão “{…}”? |
| `incidents.py:103` | noul | português | Esta etapa está falhando de forma repetida e deve ser isolada temporariamente para o resto do círculo seguir? |
| `indagador.py:138` | noul | português | A pergunta `candidatas.{…}.texto` é pertinente agora para a missão `missao`? |
| `indagador.py:144` | choice | português | O que a pergunta `candidatas.{…}.texto` faz evoluir, se respondida? |
| `indagador.py:145` | score | português | Quão acionável é a pergunta `candidatas.{…}.texto`? |
| `jev_lab.py:37` | noul | inglês | The autonomous loop wants to run `action` now, costing about `est_tokens` tokens (`custo_pct_dia` percent of what it spe |
| `jev_lab.py:47` | choice | inglês | Which maintenance task gives the loop the most value right now? Prefer the task neglected for the most turns in `stalene |
| `jev_lab.py:54` | noul | inglês | Does the evidence justify applying this `evolution_type` change now? |
| `jev_lab.py:62` | choice | português | Can this pull request be merged automatically? |
| `jev_lab.py:70` | noul | inglês | Does the evidence show the new version is better and safe to advance? |
| `jev_lab.py:77` | noul | inglês | Did the new version make something important worse than the previous one? |
| `jev_lab.py:84` | choice | inglês | Which model tier is enough for this task? |
| `jev_lab.py:91` | noul | inglês | Is this lesson worth keeping in the loop's memory? |
| `loop.py:460` | choice | português | Qual tarefa de manutenção tem mais valor agora? |
| `loop.py:516` | noul | português | vale gastar agora? |
| `medico.py:164` | noul | inglês | Finding `achados.{…}.titulo` (evidence `achados.{…}.evidencia`) is blocking the loop's progress right now. |
| `medico.py:168` | choice | inglês | Who owns the cause of `achados.{…}.titulo`, given `achados.{…}.evidencia`? |
| `medico.py:169` | score | inglês | What is the safe response to `achados.{…}.titulo` now? |
| `perguntas.py:237` | choice | português | Qual destas perguntas, respondida agora, mais ajuda o objetivo do loop pelo menor custo? |
| `planejador.py:295` | noul | português | O dado citado pelo planejador aparece de fato na evidência do loop? |
| `projects.py:140` | choice | português | Que tipo de solução este pedido pede? |
| `revisor.py:93` | noul | português | O PR do Developer `pr` é seguro para entrar na main junto com os outros PRs abertos `prs_abertos`? |
| `vigia.py:318` | noul | português | O achado `achados.{…}.titulo` é uma trava real da autoevolução do loop agora? |
| `vigia.py:323` | choice | português | O que o loop deve fazer com o achado `achados.{…}.titulo`? |

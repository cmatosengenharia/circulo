# Evolução

Tudo o que entrou na main: as versões (CHANGELOG) e as entregas que **o próprio loop** fez por PR, com a linhagem
pergunta → item → PR quando ela existe. O tipo de cada entrega foi classificado pelo Jev.

## Versões

| Versão | Data | Destaque | Itens |
|---|---|---|---|
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
| 1.40.0 | 2026-10-20 | O Redator técnico: documentação profissional do loop, gerada da autoevolução e publicada por PR. | 8 |
| 1.39.0 | 2026-10-20 | Sistema de design: o Círculo sobre o Primer (GitHub). | 5 |
| 1.38.0 | 2026-10-20 | Precisa de você, dúvidas do Jev estudadas, e o Jev usado até o fim da doc. | 5 |
| 1.37.0 | 2026-10-20 | O aluno do Jev: aprendizado a partir das decisões, em sombra. | 7 |
| 1.36.0 | 2026-10-20 | Varredura do dash: o que aparecia em duas telas agora aparece numa só. | 4 |
| 1.35.0 | 2026-10-20 | Orçamento sem corte, medindo. | 6 |
| 1.34.0 | 2026-10-19 | Memória do time: RAG dentro do loop. | 8 |
| 1.33.0 | 2026-10-19 | Equipe ao vivo como canal (`#equipe`) | 5 |
| 1.32.1 | 2026-10-19 | O loop parou às 22 h porque o orçamento do dia acabou — quase todo em estudos com busca na web. | 4 |
| 1.32.0 | 2026-10-19 | Círculo perfeito: a fábrica (`fabrica/`), reconstruída do básico. | 5 |
| 1.31.1 | 2026-10-19 | O loop parou de evoluir por 4 h: o Jev recusava o estudo com confiança média. | 2 |
| 1.31.0 | 2026-10-19 | Equipe ao vivo: os agentes como um time de engenharia, conversando e entregando em tempo real. | 6 |
| 1.30.0 | 2026-10-19 | O Indagador vira um dos agentes mais atuantes. | 3 |
| 1.29.0 | 2026-10-19 | Vários PRs do Developer em paralelo, com o Revisor validando cada um dentro do ecossistema. | 4 |
| 1.28.0 | 2026-10-19 | O loop não dorme 5 min com trabalho a caminho. | 2 |
| 1.27.0 | 2026-10-19 | O Indagador vira especialista no próprio funil, e um 502 do GitHub não trava mais a evolução. | 3 |
| 1.26.0 | 2026-10-19 | Velocidade e continuidade da autoevolução. | 5 |
| 1.25.0 | 2026-10-18 | Cores, legendas e botões legíveis em todas as telas. | 4 |
| 1.24.0 | 2026-10-18 | Vigia: o validador paralelo das travas da autoevolução. | 6 |
| 1.23.1 | 2026-10-18 | Pergunta validada pelo Jev agora vira trabalho. | 1 |
| 1.23.0 | 2026-10-18 | Fluxo ao vivo no padrão do mercado (grafo + raias + obras) e a fila do Developer com folga. | 5 |
| 1.22.0 | 2026-10-18 | Indagador: o agente da autoevolução. As perguntas são o ponto de partida, e o Jev classifica cada uma. | 7 |
| 1.21.1 | 2026-10-18 | Fluxo ao vivo sem balões: | 1 |
| 1.21.0 | 2026-10-18 | O Jev explorado ao máximo, com o loop conferindo isso sozinho. | 5 |
| 1.20.0 | 2026-10-18 | As práticas da Lauren Tan (poteto: React Compiler, Grok Bot) para entregar rápido e seguro com agentes. | 6 |
| 1.19.0 | 2026-10-18 | Gestão mais clara: fluxo dos agentes ao vivo, painel do loop em abas e tudo o que o Jev oferece. | 5 |
| 1.18.0 | 2026-10-18 | Pausar missão por missão | 7 |
| 1.17.0 | 2026-10-18 | Rastreabilidade de ponta a ponta e observabilidade | 5 |
| 1.16.0 | 2026-10-18 | giros em paralelo na mesma missão | 3 |

## Entregas do loop (39 PRs mergeados)

Por tipo: **correcao** 12 · **observabilidade** 10 · **documentacao** 8 · **seguranca** 6 · **funcionalidade** 2 · **velocidade** 1.

| PR | Data | Tipo | Visível | Entrega | Veio de |
|---|---|---|---|---|---|
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

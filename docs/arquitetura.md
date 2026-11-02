# Arquitetura

Versão documentada: **1.76.5**. Python 3.11+, biblioteca padrão, SQLite (WAL) e um servidor HTTP próprio para o
painel. Toda decisão passa primeiro pelo Jev (cascata regra → aluno → Jev → LLM).

## Constituição

Módulos que nenhum agente pode alterar por PR (o CI e o gate recusam): `merge_gate.py`, `policy.py`, `budget.py`, `guardrails.py`, `self_dev.py`, `corpo.py` e `.github/`.

## Módulos

| Módulo | Linhas | O que é |
|---|---|---|
| `absorcao.py` | 418 | Absorção de repositórios: o que o loop tira de cada repositório estudado, com ADR, prioridade e evidência. |
| `absorcao_fontes.py` | 325 | Catálogo da absorção de 01/11: o que entrou de cada repositório e o que foi descartado (dado, não instrução). |
| `agents.py` | 238 | Agentes de domínio. Todos decidem via DecisionLayer (Jev First). |
| `alavancas.py` | 159 | Economia de tokens com guarda de qualidade (pergunta #828): uma alavanca por vez, custo por PR mergeado como meta. |
| `aluno.py` | 316 | O aluno do Jev: um modelo local que aprende, com as respostas do Jev, a responder as mesmas perguntas. |
| `aluno_jev.py` | 55 | O aluno como decisor: o mesmo contrato do Jev, servido pelo modelo destilado — quando ele provou em sombra. |
| `antecipacao.py` | 78 | Cobertura de antecipação: que fração dos pedidos humanos de 7 dias já tinha um item proativo ('antecipar:<job>') criado antes dele, e quais jobs recorrentes ainda não tiveram nenhum pedido antecipado. Os pedidos do humano ao próprio loop viram itens 'pedido_cassio' do roteiro sem job gravado: o job deles sai das palavras-chave do texto. |
| `aprovacoes.py` | 152 | Precisa de você: tudo o que, no loop inteiro, está parado esperando uma decisão humana — num lugar só, com a ação. |
| `assuntos.py` | 258 | Espaço de trabalho por assunto (tribo, squad, cada microsserviço, a migração Blip → Amazon Connect). |
| `atividade.py` | 125 | O que o loop está fazendo para evoluir: linha do tempo única, giros com a duração de cada etapa e ritmo de decisões. |
| `autonomia.py` | 162 | Autonomia: nas primeiras versões o loop não depende de humano para nada (Cássio, 31/10). |
| `budget.py` ⚖️ | 181 | Orçamento diário de tokens. |
| `caixa.py` | 117 | Caixa de entrada por arquivo: um `.md` em `<dados>/caixa/` vira pedido, lido pelo próprio loop. |
| `camadas.py` | 191 | Dash do loop em camadas: saúde no topo, todas as etapas do ciclo ao vivo, detalhe de uma execução pelo run_id. |
| `caminho.py` | 142 | O caminho de um pedido feito pelo console: pedido → item → estudo → PR → CI → merge, com o tempo de cada etapa e o que está esperando agora. |
| `canario.py` | 179 | Canário de falha: ponto de verificação que nunca falhou pode estar quebrado sem ninguém saber. |
| `cao_de_guarda.py` | 52 | Cão de guarda do giro: um giro preso sem nenhum sinal de vida encerra o processo, e o launchd (KeepAlive) sobe um limpo em 10 s. |
| `capacidade.py` | 230 | Escalador: quem está sobrecarregado na equipe, e quem pode ganhar mais um trabalhador em paralelo. |
| `causas.py` | 25 | Alias causa raiz → node id: lição sem teste próprio herda a checagem determinística de outra lição da mesma causa. |
| `changelog.py` | 25 | Changelog semanal: os PRs mergeados em 7 dias agrupados em produto e infra, cada um com o pedido de origem, e a fração de produto contra a meta do Norte. Usa os PRs de `digest_semanal.prs_da_semana`; PR sem origem sai marcado 'sem pedido', nunca omitido. |
| `ci_causa.py` | 74 | Causa da falha de CI pelos sinais diretos da API de checks, não pela contagem de checks que caíram. |
| `cli.py` | 302 | circulo doctor | run [--painel] | painel | demo | tick [-n N] | add "38,90 ifood almoço" | pedir "<frase>" | caminho [ref] | latencia | status | resumo | respostas |
| `cofre.py` | 247 | Cofre de chaves: o cadastro das integrações sai do arquivo de texto e vai para o cofre do sistema. |
| `condensador.py` | 124 | Condensador rolante do contexto do Developer, portado do LLMSummarizingCondenser do OpenHands (item #366). |
| `conexoes.py` | 129 | Conexões ao vivo: o que o loop depende de fora — Jev, Claude Code, LLM, GitHub — e se cada uma responde agora. |
| `confianca.py` | 427 | Central de confiança: a pergunta que o painel responde primeiro é "posso confiar no loop agora?". |
| `configuracao.py` | 341 | Configuração única: o único momento em que o loop precisa de você. |
| `conflitos.py` | 71 | Arquivos em que cada PR devolvido por conflito conflitou, um registro (pr, sha, arquivo, data) por arquivo (pergunta #183). |
| `conta.py` | 166 | Conta do Claude: o loop roda na assinatura (Max/Pro) em vez da API, e cuida sozinho da sessão. |
| `contexto_cliente.py` | 71 | Fábrica: AGENTS.md/.cursor/rules no repositório do cliente (kit 'repo') só por PR e só quando muda. |
| `contexto_cursor.py` | 161 | Contexto enxuto para o Cursor: AGENTS.md curto e regras .cursor/rules/*.mdc escopadas por glob. |
| `controle.py` | 131 | Plano de controle em processo próprio: painel + SRE (travas) + Médico + Higiene + Escalador. |
| `corpo.py` ⚖️ | 237 | Corpo: o loop passa a rodar o código que ele mesmo evoluiu, com evidência antes e depois. |
| `corpo_caminho.py` | 65 | Caminho livre para o corpo trocar de código (lição #1). |
| `corpo_pr.py` | 63 | Corpo do PR do Developer: template fixo de impacto e risco. |
| `criterio_aceite.py` | 125 | Critério de aceite verificável por pedido: o Arquiteto define, o portão confere, o PR mostra ✓/✗. |
| `curador_licoes.py` | 172 | Curador de lições (pergunta do conselho #190): a lição que cita um node id de pytest que não existe em tests/ não tem o que corrigir. Ela fecha (`obsoleta`) com a causa e reabre se o teste citado aparecer. |
| `custo.py` | 146 | Custo do Developer por desfecho do item: quanto do gasto virou PR e quanto foi para item sem PR. |
| `daily.py` | 140 | Pauta da daily às 8h, por assunto: o que fiz ontem (das notas), o que farei hoje (pendências) e o que me bloqueia. |
| `decision.py` | 1000 | DecisionLayer — Jev First: todo ponto do círculo que vai gastar recurso pergunta primeiro aqui. JevHttpClient (API da TypeSafe, POST /v1/systemone) e LocalJev (regra determinística) têm o MESMO contrato. |
| `demo.py` | 119 | Demonstração: loop acelerado com pedidos simulados, para ver o painel vivo. Usa uma pasta de dados separada. |
| `demo_video.py` | 171 | Demo de 30 s por produto (pedido #824): roteiro JSON versionado, mp4 fora do histórico do git. |
| `desfecho.py` | 157 | Desfecho por decisão: o que cada "sim" do Jev rendeu — fecha o ciclo de aprendizado. |
| `developer.py` | 299 | O id pytest conferido por `ast` antes de rodar (lição #26): o reparo copiava ou inventava um id, e o pytest só avisava depois de iniciar ('ERROR: file or directory not found', saída 4). |
| `diff_size.py` | 97 | Tamanho de um diff a partir do texto de `git diff --numstat`: total de linhas e a causa dominante (categoria e arquivo que mais pesam). Só `numstat_contra_base` chama git; o resto é puro. |
| `digest_semanal.py` | 150 | Digest semanal do que o time ganhou: os PRs de produto mergeados em 7 dias, cada um com o pedido ou a pergunta de origem e o antes/depois da métrica que a motivou. PR de produto sem origem sai marcado 'sem pedido', nunca omitido: o buraco no rastro é o que o time precisa ver. Cada leitura (`circulo digest`) fica em `digest_leituras`. O idle publica o digest uma vez por semana (`publicar`); com a fração de produto abaixo da meta, o próximo roteiro parte de uma pergunta de produto (`prioriza_produto`, lido pelo Indagador). `markdown` é a versão 'para o time' (o que entrou, quem pediu, tempo pedido→merge), servida em /api/digest?formato=md e copiada pelo botão de Meu trabalho. |
| `disjuntor.py` | 126 | Disjuntor de LLM: a conta sem crédito ("credit balance is too low") não volta sozinha, e cada chamada repetida só gasta tentativa e enche o log de falhas do Developer. |
| `doctor.py` | 108 | `circulo doctor`: confere o que o loop precisa na máquina (Python, git, Claude Code, Jev, GitHub) e diz exatamente o que falta, com o comando que corrige. |
| `documentador.py` | 332 | O Redator técnico: documentação profissional do loop, gerada do que o loop é e do que ele fez, publicada por PR. |
| `duvidas.py` | 132 | Dúvidas do Jev viram estudo: a pergunta que o Jev não soube classificar vai para o Arquiteto antes de voltar a ele. |
| `eficacia.py` | 131 | Veredito de eficácia por PR mergeado: o critério de sucesso do item melhorou de verdade ou só oscilou? |
| `engine.py` | 630 | Motor genérico de projetos: o "kit geral" que atende qualquer tipo de pedido. |
| `equipe.py` | 395 | A equipe: os agentes do loop vistos como um time de engenharia que entrega qualquer produto. |
| `escudo.py` | 116 | Escudo das skills: auditoria determinística do `.claude/` de um repositório (técnica ECC-1, absorvida do AgentShield). |
| `estagnacao.py` | 72 | A causa medida da estagnação: o que cada giro parado fez de fato (lição #47). |
| `estudo.py` | 284 | Neurônio de estudo: o pedido é uma hipótese, não uma ordem gravada em pedra. |
| `evolution.py` | 403 | Meta-Learner (evolução nível 1 e 2), Shadow mode e Health Monitor (rollback automático). |
| `experimentos.py` | 137 | Experimento universal: todo item do Planejador carrega hipótese, métrica, baseline, alvo, margem de não inferioridade, janela e n_min de eventos; ao fim da janela o Vigia mede e grava o veredito. |
| `fabrica_developer.py` | 88 | Fábrica: o Developer trabalha os pedidos abertos dos repositórios cliente, na ordem da esteira (o mais antigo primeiro). |
| `fabricante.py` | 392 | Fabricante (1.75): o trabalhador que ENTREGA os pedidos de repositório cliente (kit 'repo'), com as técnicas absorvidas. |
| `falhas.py` | 55 | Classe da falha do agente, por regra, antes de tentar de novo (Retry pattern: só a transitória se repete). |
| `falhas_painel.py` | 71 | Funções puras do card de falhas do painel: agrupar por causa e por componente e o delta contra as 24 h anteriores. |
| `fatiador.py` | 286 | Fatiador: item do roteiro que acumula falhas locais vira sub-itens validados um a um. |
| `fazendo.py` | 76 | O que cada agente está fazendo agora — não só quem está trabalhando, mas em quê, e o passo em curso. |
| `finance.py` | 100 | Cálculos financeiros e invariantes. Só inteiros em centavos. Nenhum agente altera este arquivo sozinho. |
| `financeiro.py` | 20 | Prontidão do cérebro financeiro: quantos lançamentos reais e meses cobertos faltam para a 1ª pergunta útil (gasto por categoria no mês). Sintético é o lançamento que veio de evento com origem 'demo'. |
| `fluxo.py` | 388 | Fluxo dos agentes ao vivo: quem fez o quê em cada giro, na ordem, para a tela animar a passagem entre agentes. |
| `garimpo.py` | 206 | Garimpo: a camada que varre o GitHub atrás de código já escrito que sirva de melhoria para o próprio loop. |
| `gasto_cursor.py` | 204 | Gasto do Cursor em US$ por dia, assunto e tipo de tarefa, com a projeção do dia em que o limite do mês acaba. |
| `gate_causa.py` | 43 | Causa da falha de checks no gate (pergunta do conselho #76): o PR caiu sozinho ou com o CI inteiro? |
| `gemeas.py` | 63 | Lição #70 (pergunta #248): a lição 'validada' reabre quando o mesmo erro volta numa lição nova. |
| `graft.py` | 219 | Graft (github.com/AEndrix03/Graft): memória semântica local do time, ao lado do índice lexical (FTS5). |
| `graph.py` | 182 | Grafo de missões: as missões se conhecem, compartilham memória e contexto, e se integram. |
| `guardrails.py` ⚖️ | 153 | Guardrails da autoevolução (Prompt Mestre §11) que não cabem em outro lugar. |
| `harness_lab.py` | 117 | Evolução do harness: A/B online de prompts de papel (estilo otimização de prompts), sempre com gates. |
| `higiene.py` | 103 | Higiene do roteiro e das lições — o que as telas mostravam em 20/10: itens "dependem de você" que ninguém olha há dias, títulos de 500 caracteres com JSON dentro, a mesma falha do agente em várias lições (uma por ponto de truncamento). |
| `impressao_pr.py` | 30 | Impressão digital de PR: título normalizado + conjunto de checks falhos, num hash. |
| `incidents.py` | 134 | Registro de erros e autocorreção em tempo de execução. |
| `indagador.py` | 562 | Indagador: o agente da autoevolução. Faz as perguntas certas para cada missão, e o Jev classifica cada uma. |
| `ingestao.py` | 116 | Pedido ao humano quando a pasta de extratos não dá lançamentos: o código de ingestão existe, falta o arquivo. |
| `insistencia.py` | 67 | Não insistir: a regra que o Cássio deu em 25/10 ("se não evoluiu, reescreva a solução"), aplicada ao que o loop repete sem resultado. Em 31/10 a lição #47 (estagnação) tinha 9 reincidências e 5 PRs no mesmo dia tentando fechá-la; 9 sub-itens esperavam na fila desde 22/10 sem ninguém pegar (e, por serem 9, mantinham o roteiro "cheio" e o Planejador descartando pergunta nova); 12 itens estavam 'bloqueado' pelo disjuntor de lint desde 25/10 sem sonda que os reabrisse. Tudo aqui é regra de tempo e contagem, sem LLM, e roda na higiene do SRE (uma vez por hora). |
| `intencoes.py` | 104 | Trilha write-ahead das ações do loop: a intenção é gravada ANTES de a ação rodar. |
| `jardineiro.py` | 96 | Jardineiro: vigia padrões ruins se espalhando pelo próprio código (Lauren Tan: "assign a gardener"). |
| `jev_cobertura.py` | 101 | Cobertura do Jev: o loop confere, no próprio código, se cada pergunta ao Jev usa tudo o que a API oferece. |
| `jev_lab.py` | 464 | Laboratório do Jev: o loop testa, com evidência, formas melhores de perguntar ao Jev e adota sozinho a que vence. |
| `jobs.py` | 244 | Job de cada pedido humano e antecipação dos que se repetem. |
| `json_llm.py` | 73 | A única forma de ler o objeto JSON que uma LLM respondeu (lição #22). |
| `jtbd.py` | 50 | O agrupador de jobs ligado ao loop: no idle, cada job com ≥3 pedidos em 7 dias vira a missão 'antecipar:<job>' e exatamente 1 proposta antecipada no roteiro, presa à última pergunta do entrevistador_jtbd (lição #15). Os pedidos vêm dos eventos (job gravado) e dos itens 'pedido_cassio' do roteiro (job pelas palavras-chave do texto). |
| `kit.py` | 217 | `circulo init`: o motor do loop cuidando de QUALQUER repositório, não só deste. |
| `lancamento_manual.py` | 131 | Entrada manual de uma linha ('mercado 45,90 ontem') → lançamento, sem LLM. |
| `lancamentos_email.py` | 41 | E-mail de notificação do banco → lançamentos, sem rede e sem LLM (o texto chega pronto, nunca do Gmail aqui). |
| `lancamentos_import.py` | 138 | Importa extrato bancário (OFX/CSV) para o ledger, sem rede e sem LLM. |
| `lancamentos_pasta.py` | 131 | Pasta monitorada de extratos: cada .ofx/.csv/.eml novo vai para o ledger e sai da pasta. |
| `landing.py` | 147 | Landing de cada produto criado: uma página em `docs/index.html` do próprio produto (o GitHub Pages serve a pasta docs/ com o index.html como home), com nome, proposta de valor, 3 telas e o link do repositório (pedido #823). |
| `latencia.py` | 55 | Latência até o merge (pergunta do conselho #695): só lê as decisões do gate (tabela `merges`). |
| `licoes.py` | 897 | Lições: o loop aprende com os próprios erros como um humano, e o mesmo erro de estrutura só acontece uma vez. |
| `limite_uso.py` | 100 | Limite de uso do Claude Code: até quando não chamar a LLM, lido da própria mensagem de erro. |
| `links.py` | 130 | Catálogo de links da empresa por assunto: colo o link com um rótulo curto e acho em segundos. |
| `lint_fix.py` | 79 | Autofix determinístico do lint do CI nos testes alterados, antes do commit do Developer: só o que sobra vai para a LLM. |
| `llm.py` | 345 | Cliente de LLM do círculo. Só é chamado depois que o Jev autoriza (cascata de custo). |
| `llm_cache.py` | 83 | Cache exato das respostas da LLM, por (neurônio + modelo + prompt normalizado), com TTL curto. |
| `loop.py` | 900 | O círculo: loop infinito, Jev First, retoma de onde parou, pausa só por orçamento. |
| `medico.py` | 319 | O Médico do loop: plano de controle que diagnostica gargalos por PADRÃO medido e responde pela escada mais barata. |
| `memoria.py` | 494 | Memória de trabalho do time: o que o círculo já viu, recuperado por relevância na hora em que um agente precisa. |
| `memory.py` | 112 | Memória do círculo (RAG) e playbooks por tipo de pedido. |
| `mercado.py` | 240 | Pesquisa de mercado semanal: o que as melhores fábricas de software com IA já fazem e o loop ainda não. |
| `merge_gate.py` ⚖️ | 591 | QA e release (merge) do círculo. |
| `metrics.py` | 98 | Métricas do loop no padrão Prometheus, via prometheus_client, num registry próprio (não no global do processo). |
| `missao.py` | 30 | Causa normalizada de cada barra em missao:verificacao_saida (pergunta #363): a falha é classificada, não só contada. |
| `modelo_menor.py` | 28 | Candidatos a modelo menor por papel de LLM (pergunta #553): só mede e ranqueia, não roda sombra nem troca modelo. |
| `money.py` | 45 | Dinheiro sempre em centavos (int). Nunca float. |
| `motivo.py` | 114 | Motivo tipado de recusa/parada (pergunta #269): por que um PR foi recusado ou um item parou, em três campos. |
| `neuronios.py` | 257 | Cérebros e neurônios: cada ponto do fluxo segue o mesmo contrato, e o loop cria portões novos a partir dos próprios erros. |
| `nomes.py` | 71 | Os nomes dos agentes, num lugar só, para todas as telas falarem a mesma língua. |
| `norte.py` | 178 | Norte: para onde o loop evolui, em resultados mensuráveis — não em erros. |
| `observabilidade.py` | 385 | Observabilidade do loop: sinais de ouro, SLOs com orçamento de erro, métricas no padrão Prometheus e exportação OTLP. |
| `orcamento_dia.py` | 62 | Orçamento diário de tokens vindo da configuração, com aviso antes do corte. |
| `painel.py` | 890 | Painel local do círculo: estado, feed ao vivo (SSE) e controles do humano. |
| `parada.py` | 91 | Parada verificável (kill switch): o botão do painel, a confirmação do loop e o teste semanal. |
| `pastas.py` | 53 | Pastas padrão por assunto no Mac, espelhando os assuntos do console (`circulo assunto novo`). |
| `pausa.py` | 131 | Pausar e retomar missão por missão, sem parar o loop inteiro. |
| `pedido_claro.py` | 135 | Portão de pedido (pergunta do conselho #323): antes da LLM, o pedido do Developer (título + detalhe do item) cita critério de aceite, arquivo alvo (.py) e resultado esperado? Se falta algum, sai UMA pergunta de esclarecimento, a do primeiro campo ausente. O veredito de cada item fica em `pedidos_claros`. |
| `pedido_estado.py` | 63 | Estado único de cada pedido do humano no painel (pergunta #472): recebido, andamento (com o PR), bloqueado (com o motivo) ou entregue (com a evidência), e há quanto tempo está nele. |
| `pedidos.py` | 73 | Canal de origem de cada pedido (pergunta do conselho #441): só mede, não integra Slack nem GitHub. |
| `pedidos_repetidos.py` | 52 | Pergunta #399 (entrevistador_jtbd): pedido do humano que reformula um anterior é sinal de que a entrega não resolveu. |
| `perguntas.py` | 677 | Conselho de perguntas: a autoevolução do loop parte de PERGUNTAS, feitas por quem tem o olhar certo. |
| `persona_cliente.py` | 60 | Persona `cliente` do conselho: entrevista no formato Mom Test para cada produto da fábrica. |
| `planejador.py` | 619 | Planejador do roteiro: o loop nunca fica sem o que evoluir. |
| `planejador_cache.py` | 81 | A mesma pergunta do conselho com a métrica quase igual em 7 dias não volta à LLM do Planejador. |
| `planos.py` | 71 | Plano do Developer por item (passos, arquivos, premissas) e a fração de PRs com plano antes do primeiro commit (item #276). |
| `policy.py` ⚖️ | 282 | Política do círculo: versionada, com guard que impede a auto-evolução de remover proteções. |
| `portao_previo.py` | 63 | Portão de reincidência (pergunta do conselho #85): não abrir PR de item que já fechou 2x sem merge com os mesmos checks. |
| `praticas.py` | 124 | Retrospectivo diário → manual de práticas (ExpeL: insights extraídos das tentativas e podados pelo resultado). |
| `pre_pr.py` | 85 | Portão pré-PR (pergunta do conselho #74): não abrir PR enquanto o CI da main está vermelho ou nem iniciou. |
| `prevencao.py` | 261 | Lição #15 (pergunta #239): a lição só fica 'validada' se a Prevenção cita um teste ou uma checagem determinística. |
| `produto_novo.py` | 108 | Produto novo: pedido → repo gerado de `modelos/<tipo>/` (dados com `{{variáveis}}`, CI próprio; tipos em `modelos/tipos.json`) → `circulo init` + `git init` + `origin` (bare local ou GitHub por token) → registro (kit 'repo') → pedido na fila (`circulo/<n>`). O primeiro PR: `repo_cliente.entregar` desse pedido roda o CI e empurra a branch. |
| `projects.py` | 314 | Projetos vivos: cada pedido vira um projeto que o círculo evolui com o propósito dele. |
| `prova.py` | 72 | Prova de melhora por item mergeado (pergunta do conselho #57): a métrica do critério de sucesso do item, lida no planejamento (antes) e 7 dias depois do merge (depois), gravada na trilha (`elos`: item:N → medicao:N:antes|depois). |
| `rastro.py` | 448 | Rastreabilidade de ponta a ponta: de onde veio cada mudança do loop até a prova de que ela funciona rodando. |
| `registro.py` | 105 | Registro estruturado das chamadas de LLM. |
| `regras.py` | 256 | Regras promovidas do Jev (pergunta #533): o par (entrada normalizada → decisão) que o Jev repete vira regra determinística consultada ANTES dele. |
| `reparo.py` | 769 | Reparo do Developer antes do PR: passo determinístico primeiro, depois no máximo UMA rodada do agente. |
| `repo_cliente.py` | 260 | Fábrica: o loop trabalhando no repositório de um cliente — kit 'repo'. |
| `repo_stats.py` | 65 | Números do repositório do loop (commits), lidos do clone local. Cache curto: o painel atualiza a cada poucos segundos. |
| `reproducao.py` | 282 | Reprodução primeiro: o teste novo de uma correção precisa FALHAR no código antigo e passar no novo. |
| `resultado.py` | 211 | Resultado do lado do cliente (1.76): o loop vende RESULTADO, não ferramenta (ADR 0015). |
| `resumo_semanal.py` | 77 | Resumo semanal para a equipe: o changelog (produto/infra, cada PR com o pedido de origem, e a fração de produto contra a meta), os PRs sem pedido listados à parte, o uso medido (leituras do digest em 7 dias) e as consultas 7d de cada PR de produto, com os que ninguém consultou sinalizados, e os pedidos abertos ainda sem PR de produto mergeado, do mais velho ao mais novo, para a equipe ver o que vem a seguir. Cada consulta fica em `uso_resumo` (recurso, created_at): 'resumo' e 'pr:<número>' de cada PR de produto mostrado. Compõe `changelog` e `digest_semanal`; não refaz a coleta nem a classificação. |
| `revisao_dupla.py` | 97 | Revisão dupla independente (ECC-2 do ADR 0001, portado da skill `santa-method` do everything-claude-code, MIT). |
| `revisao_uso.py` | 112 | Pedido de revisão por entrega de produto sem uso: um por PR, para sempre. A chave é `pr_numero UNIQUE` e a abertura é `INSERT ... ON CONFLICT DO NOTHING`, então repetição (seguida ou em paralelo, de qualquer conexão) não duplica e pedido fechado não reabre: a chave não expira nem é podada. O destino (usar, ajustar ou remover) segue a regra da chave de idempotência: o primeiro fica, e uma repetição com destino diferente vira divergência registrada. |
| `revisor.py` | 453 | Revisor: o agente que valida cada PR do Developer DENTRO do ecossistema, para vários PRs andarem em paralelo. |
| `risco.py` | 140 | Confirmação por risco das ações do Developer (porte do SecurityAnalyzer + ConfirmRisky de OpenHands). |
| `roadmap.py` | 254 | Roadmap: todo item nasce de uma pergunta do conselho; `Origem` só existe com um pergunta_id válido. |
| `rodadas_revisao.py` | 76 | Rodadas de comentário de revisão até o merge (pergunta do conselho #446): só mede. |
| `saida_json.py` | 59 | Contrato de saída JSON de um papel (lição #22): as chaves obrigatórias do esquema chegam inteiras, ou um motivo tipado. |
| `segredos.py` | 121 | Gate determinístico de segredos no diff do PR (pedido #827, fatia 1). |
| `self_dev.py` ⚖️ | 899 | Developer do projeto zero: o círculo corrigindo o próprio código. |
| `servidor.py` | 25 | Servidor HTTP do painel e da verificação das telas: threads daemon, aba fechada no meio da resposta não vira traceback, e `encerrando` tira os fluxos SSE do laço no `shutdown()`. |
| `sentinela.py` | 94 | Sentinela da entrega: olha o RESULTADO (o que entrou na main), não os erros. |
| `silencio.py` | 39 | Silêncio suspeito (pergunta #619): zero incidente aberto só é verde se o loop também não estagnou nem tem lição de estrutura aberta nos últimos 7 dias; ausência de alerta não prova saúde. |
| `skills.py` | 170 | Skills reutilizadas: catálogo de skills prontas em repositórios públicos, instalação por PR em `.claude/skills/` e a escolha, pelo Jev, de qual skill cada tarefa do Developer deve usar. |
| `state.py` | 790 | Estado persistente do círculo (SQLite). Tudo que o loop precisa para retomar de onde parou. |
| `status.py` | 106 | Estado do loop para humanos, derivado do batimento + controles + etapa. Usado pelo painel. |
| `tecnicas.py` | 231 | Técnicas absorvidas das skills externas (1.75), como PORTÕES MEDIDOS — nunca só texto no prompt. |
| `telemetria.py` | 422 | Trilha de eventos tipados do loop, no vocabulário OpenTelemetry GenAI, e o painel de timeline + grafo. |
| `telemetria_sem_erro.py` | 51 | Lição #83: um dump de estatística (subagent_stats com completed/failed/killed/spawned) não é erro. |
| `tema.py` | 210 | Tema único das telas do loop: as cores, os botões, os chips e a legenda são os mesmos em todas as páginas. |
| `trabalho.py` | 315 | Meu trabalho: a tela que junta o dia a dia do engenheiro — assuntos, daily, links, orçamento de IA, contexto para o Cursor e o mapa do GAIA — e a semente de dados de exemplo que deixa o esqueleto inteiro funcionando antes do dado real. |
| `uso_entregas.py` | 83 | Entregas de produto sem uso: os PRs de produto mergeados há 7 dias ou mais sem nenhum evento com o nome do `evento_esperado` gravado no merge depois do `merged_at`. Uso anterior ao merge não conta: é de antes da entrega. O evento esperado de cada entrega fica em `entrega_uso_esperado` (um por PR); o uso, em `entrega_uso` (gravado pela rota do painel chamada, com o último instante por nome) e nos `events` do loop (kind). |
| `validador.py` | 250 | Validador: os agentes de validação que ficam entre o Developer e o PR (1.70). |
| `validador_telas.py` | 142 | Validador por tela: o PR que quebra uma tela do painel não passa (pedido #819, fatia 1: o gate antes da telemetria). |
| `veredito_experimento.py` | 57 | Veredito de um experimento fechado: regra z-score local primeiro, o Jev (experimento_veredito) só na fronteira. |
| `verificacao.py` | 150 | Verificação de ponta a ponta do painel, com um mapa de funcionalidades (Lauren Tan: "verification skills"). |
| `vigia.py` | 666 | Vigia: o agente que roda em paralelo ao giro e vigia as travas da autoevolução. |

## Telas

| Rota | Arquivo | O que mostra |
|---|---|---|
| `/` | `home.html` | Nova missão, Equipe ao vivo, Rastros e SLOs, Integrações |
| `/missao/{zero}` | `painel.html` | Pausar o loop, Saúde e estado, Equipe ao vivo, Segurança e confiança, Memória do time, Consumo de tokens, Aluno do Jev, Médico do loop |
| `/equipe` | `equipe.html` | Equipe ao vivo, #equipe, Quadro de entregas |
| `/fluxo` | `fluxo.html` | Bastidores do giro, Raias do giro, Laboratório |
| `/rastros` | `rastros.html` | Seguir o fio, Objetivos de serviço, Sinais de ouro |
| `/integracoes` | `integracoes.html` | Integrações, Cadastrar outra integração |
| `/aprovacoes` | `aprovacoes.html` | Precisa de você, Nada esperando você |

## APIs do painel

| Rota | Chaves da resposta |
|---|---|
| `/api/projetos` | `projetos`, `loop`, `versao` |
| `/api/estado` | `loop`, `orcamento` |
| `/api/confianca` | `veredito`, `checks` |
| `/api/fluxo` | `agora`, `agentes`, `jev` |
| `/api/equipe` | `membros`, `quadro`, `grupos` |
| `/api/memoria` | `total`, `por_tipo`, `usos_24h` |
| `/api/consumo` | `modo`, `por_dia`, `por_papel`, `sugestao_limite` |
| `/api/aluno` | `perguntas`, `resumo`, `criterios` |
| `/api/aprovacoes` | `total`, `urgentes`, `itens` |
| `/api/medico` | `abertos`, `acoes_24h`, `precisao` |
| `/api/observabilidade` | `sinais`, `slos`, `rastros` |
| `/api/loop` | estado inteiro do loop |

# Arquitetura

Versão documentada: **1.48.0**. Python 3.11+, biblioteca padrão, SQLite (WAL) e um servidor HTTP próprio para o
painel. Toda decisão passa primeiro pelo Jev (cascata regra → aluno → Jev → LLM).

## Constituição

Módulos que nenhum agente pode alterar por PR (o CI e o gate recusam): `merge_gate.py`, `policy.py`, `budget.py`, `guardrails.py`, `self_dev.py`, `corpo.py` e `.github/`.

## Módulos

| Módulo | Linhas | O que é |
|---|---|---|
| `agents.py` | 238 | Agentes de domínio. Todos decidem via DecisionLayer (Jev First). |
| `aluno.py` | 293 | O aluno do Jev: um modelo local que aprende, com as respostas do Jev, a responder as mesmas perguntas. |
| `aprovacoes.py` | 121 | Precisa de você: tudo o que, no loop inteiro, está parado esperando uma decisão humana — num lugar só, com a ação. |
| `atividade.py` | 125 | O que o loop está fazendo para evoluir: linha do tempo única, giros com a duração de cada etapa e ritmo de decisões. |
| `budget.py` ⚖️ | 181 | Orçamento diário de tokens. |
| `camadas.py` | 182 | Dash do loop em camadas: saúde no topo, todas as etapas do ciclo ao vivo, detalhe de uma execução pelo run_id. |
| `canario.py` | 64 | Canário de falha: ponto de verificação que nunca falhou pode estar quebrado sem ninguém saber. |
| `causas.py` | 22 | Alias causa raiz → node id: lição sem teste próprio herda a checagem determinística de outra lição da mesma causa. |
| `cli.py` | 145 | circulo run [--painel] | painel | demo | tick [-n N] | add "38,90 ifood almoço" | status | resumo | respostas |
| `cofre.py` | 247 | Cofre de chaves: o cadastro das integrações sai do arquivo de texto e vai para o cofre do sistema. |
| `conexoes.py` | 129 | Conexões ao vivo: o que o loop depende de fora — Jev, Claude Code, LLM, GitHub — e se cada uma responde agora. |
| `confianca.py` | 342 | Central de confiança: a pergunta que o painel responde primeiro é "posso confiar no loop agora?". |
| `configuracao.py` | 324 | Configuração única: o único momento em que o loop precisa de você. |
| `corpo.py` ⚖️ | 174 | Corpo: o loop passa a rodar o código que ele mesmo evoluiu, com evidência antes e depois. |
| `corpo_caminho.py` | 65 | Caminho livre para o corpo trocar de código (lição #1). |
| `decision.py` | 1000 | DecisionLayer — Jev First: todo ponto do círculo que vai gastar recurso pergunta primeiro aqui. JevHttpClient (API da TypeSafe, POST /v1/systemone) e LocalJev (regra determinística) têm o MESMO contrato. |
| `demo.py` | 119 | Demonstração: loop acelerado com pedidos simulados, para ver o painel vivo. Usa uma pasta de dados separada. |
| `diff_size.py` | 66 | Tamanho de um diff a partir do texto de `git diff --numstat`, sem chamar git: total de linhas e a causa dominante (categoria e arquivo que mais pesam). |
| `documentador.py` | 308 | O Redator técnico: documentação profissional do loop, gerada do que o loop é e do que ele fez, publicada por PR. |
| `duvidas.py` | 132 | Dúvidas do Jev viram estudo: a pergunta que o Jev não soube classificar vai para o Arquiteto antes de voltar a ele. |
| `engine.py` | 634 | Motor genérico de projetos: o "kit geral" que atende qualquer tipo de pedido. |
| `equipe.py` | 361 | A equipe: os agentes do loop vistos como um time de engenharia que entrega qualquer produto. |
| `estudo.py` | 261 | Neurônio de estudo: o pedido é uma hipótese, não uma ordem gravada em pedra. |
| `evolution.py` | 397 | Meta-Learner (evolução nível 1 e 2), Shadow mode e Health Monitor (rollback automático). |
| `fatiador.py` | 122 | Fatiador: item do roteiro que acumula falhas locais vira sub-itens validados um a um. |
| `fazendo.py` | 76 | O que cada agente está fazendo agora — não só quem está trabalhando, mas em quê, e o passo em curso. |
| `finance.py` | 100 | Cálculos financeiros e invariantes. Só inteiros em centavos. Nenhum agente altera este arquivo sozinho. |
| `fluxo.py` | 388 | Fluxo dos agentes ao vivo: quem fez o quê em cada giro, na ordem, para a tela animar a passagem entre agentes. |
| `graph.py` | 182 | Grafo de missões: as missões se conhecem, compartilham memória e contexto, e se integram. |
| `guardrails.py` ⚖️ | 119 | Guardrails da autoevolução (Prompt Mestre §11) que não cabem em outro lugar. |
| `harness_lab.py` | 117 | Evolução do harness: A/B online de prompts de papel (estilo otimização de prompts), sempre com gates. |
| `incidents.py` | 134 | Registro de erros e autocorreção em tempo de execução. |
| `indagador.py` | 530 | Indagador: o agente da autoevolução. Faz as perguntas certas para cada missão, e o Jev classifica cada uma. |
| `intencoes.py` | 99 | Trilha write-ahead das ações do loop: a intenção é gravada ANTES de a ação rodar. |
| `jardineiro.py` | 97 | Jardineiro: vigia padrões ruins se espalhando pelo próprio código (Lauren Tan: "assign a gardener"). |
| `jev_cobertura.py` | 101 | Cobertura do Jev: o loop confere, no próprio código, se cada pergunta ao Jev usa tudo o que a API oferece. |
| `jev_lab.py` | 349 | Laboratório do Jev: o loop testa, com evidência, formas melhores de perguntar ao Jev e adota sozinho a que vence. |
| `jobs.py` | 169 | Job de cada pedido humano e antecipação dos que se repetem. |
| `json_llm.py` | 71 | A única forma de ler o objeto JSON que uma LLM respondeu (lição #22). |
| `licoes.py` | 495 | Lições: o loop aprende com os próprios erros como um humano, e o mesmo erro de estrutura só acontece uma vez. |
| `llm.py` | 190 | Cliente de LLM do círculo. Só é chamado depois que o Jev autoriza (cascata de custo). |
| `loop.py` | 900 | O círculo: loop infinito, Jev First, retoma de onde parou, pausa só por orçamento. |
| `medico.py` | 314 | O Médico do loop: plano de controle que diagnostica gargalos por PADRÃO medido e responde pela escada mais barata. |
| `memoria.py` | 335 | Memória de trabalho do time: o que o círculo já viu, recuperado por relevância na hora em que um agente precisa. |
| `memory.py` | 112 | Memória do círculo (RAG) e playbooks por tipo de pedido. |
| `merge_gate.py` ⚖️ | 461 | QA e release (merge) do círculo. |
| `metrics.py` | 98 | Métricas do loop no padrão Prometheus, via prometheus_client, num registry próprio (não no global do processo). |
| `money.py` | 45 | Dinheiro sempre em centavos (int). Nunca float. |
| `neuronios.py` | 225 | Cérebros e neurônios: cada ponto do fluxo segue o mesmo contrato, e o loop cria portões novos a partir dos próprios erros. |
| `nomes.py` | 69 | Os nomes dos agentes, num lugar só, para todas as telas falarem a mesma língua. |
| `observabilidade.py` | 384 | Observabilidade do loop: sinais de ouro, SLOs com orçamento de erro, métricas no padrão Prometheus e exportação OTLP. |
| `orcamento_dia.py` | 62 | Orçamento diário de tokens vindo da configuração, com aviso antes do corte. |
| `painel.py` | 678 | Painel local do círculo: estado, feed ao vivo (SSE) e controles do humano. |
| `parada.py` | 91 | Parada verificável (kill switch): o botão do painel, a confirmação do loop e o teste semanal. |
| `pausa.py` | 131 | Pausar e retomar missão por missão, sem parar o loop inteiro. |
| `perguntas.py` | 508 | Conselho de perguntas: a autoevolução do loop parte de PERGUNTAS, feitas por quem tem o olhar certo. |
| `planejador.py` | 498 | Planejador do roteiro: o loop nunca fica sem o que evoluir. |
| `policy.py` ⚖️ | 282 | Política do círculo: versionada, com guard que impede a auto-evolução de remover proteções. |
| `projects.py` | 297 | Projetos vivos: cada pedido vira um projeto que o círculo evolui com o propósito dele. |
| `rastro.py` | 442 | Rastreabilidade de ponta a ponta: de onde veio cada mudança do loop até a prova de que ela funciona rodando. |
| `registro.py` | 97 | Registro estruturado das chamadas de LLM. |
| `reparo.py` | 419 | Reparo do Developer antes do PR: passo determinístico primeiro, depois no máximo UMA rodada do agente. |
| `repo_stats.py` | 65 | Números do repositório do loop (commits), lidos do clone local. Cache curto: o painel atualiza a cada poucos segundos. |
| `reproducao.py` | 138 | Reprodução primeiro: o teste novo de uma correção precisa FALHAR no código antigo e passar no novo. |
| `revisor.py` | 187 | Revisor: o agente que valida cada PR do Developer DENTRO do ecossistema, para vários PRs andarem em paralelo. |
| `self_dev.py` ⚖️ | 782 | Developer do projeto zero: o círculo corrigindo o próprio código. |
| `state.py` | 662 | Estado persistente do círculo (SQLite). Tudo que o loop precisa para retomar de onde parou. |
| `status.py` | 57 | Estado do loop para humanos, derivado do batimento + controles + etapa. Usado pelo painel. |
| `telemetria.py` | 422 | Trilha de eventos tipados do loop, no vocabulário OpenTelemetry GenAI, e o painel de timeline + grafo. |
| `tema.py` | 187 | Tema único das telas do loop: as cores, os botões, os chips e a legenda são os mesmos em todas as páginas. |
| `verificacao.py` | 150 | Verificação de ponta a ponta do painel, com um mapa de funcionalidades (Lauren Tan: "verification skills"). |
| `vigia.py` | 528 | Vigia: o agente que roda em paralelo ao giro e vigia as travas da autoevolução. |

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

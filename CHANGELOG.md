# Changelog

## 1.4.0 — 2026-10-18

Incidente: o loop girou mais de 1.400 vezes sem evoluir. O PR #1 do Developer (item #26) falhou no CI por lint
(`zip()` sem `strict=`). Como só existe um PR do Developer por vez, ele ficou "ocupado" para sempre, e o gate repetia
"checks falhando" sem devolver o trabalho para ninguém.

- PR do Developer reprovado no CI, ou sem teste novo, volta para o próprio Developer consertar na mesma branch, com o
  final do log do CI (lido pela API do Actions). Depois de 2 consertos sem passar, o PR é fechado (pode ser reaberto,
  a branch fica) e o item volta para a fila. Nada fica parado esperando você.
- Verificação local igual ao CI: antes de enviar, o Developer roda o mesmo `ruff check` do CI, além dos testes. Se o
  ruff faltar na máquina do loop, ele é instalado uma vez via pip.
- Claude Code que termina com erro (`is_error`: limite da conta, máximo de passos) não conta mais como sucesso. Antes,
  a saída 0 com trabalho pela metade virava PR. Agora o trabalho parcial é descartado. No limite da conta, o Developer
  espera o horário de reset ("resets 4:30am") em vez de tentar de novo a cada giro.
- `ruff` entra nas dependências `dev`.

## 1.4.1 — 2026-10-18

- CI, job Constituição: compara o merge do PR com a main atual (`HEAD^1`), não com a main de quando o PR abriu.
  Antes, uma mudança sua na main depois de o PR abrir aparecia como "constituição alterada por agente".

## 1.3.3 — 2026-10-18

- Gate de merge: se o token não tiver a permissão Checks, lê os mesmos jobs do CI pela API do Actions.

## 1.3.2 — 2026-10-18

- Testes herméticos: os testes que o Developer roda antes de abrir PR não herdam chaves nem o repositório, e nenhum
  Developer ou gate de verdade nasce dentro de testes. Antes, rodando na máquina do loop, um teste acordava outro
  Developer (Claude Code dentro de Claude Code).
- Item do roteiro preso em "em andamento" por execução interrompida volta sozinho para a fila ao reiniciar.

## 1.3.1 — 2026-10-18

- Valor esperado por tarefa no porteiro do gasto: o item do roteiro (seu pedido ou erro recorrente) vale mais que manutenção; antes o Developer era recusado por 0,39 contra 0,40. O Jev vê qual item seria feito.
- Tudo o que o Developer tenta aparece na linha do tempo, inclusive adiado, sem mudança e testes reprovados.

## 1.3.0 — 2026-10-18

- Cascata completa quando o Jev está em dúvida: resposta perto de 50% com confiança abaixo de `jev_incerto` (0,25) fica
  registrada e a regra determinística decide. Antes, o "não sei" do Jev reprovava todos os portões (o Developer nunca
  passava do `should_evolve`) e o loop girava sem evoluir.
- Developer: o Claude Code usa o login da sua conta Claude; a `ANTHROPIC_API_KEY` do loop só vai junto com
  `CIRCULO_CODE_AGENT_USA_API=1` (uma chave sem crédito não derruba mais o Developer).

## 1.2.2 — 2026-10-18

- Chave da Anthropic sem workspace: `ANTHROPIC_WORKSPACE_ID` opcional, enviado no cabeçalho `anthropic-workspace-id`.

## 1.2.1 — 2026-10-18

- Teste de conexões mostra o erro inteiro (com o corpo da resposta) e em qual passo falhou; teste do Claude usa o modelo pequeno da política; permissão certa do token do GitHub (Checks em leitura).

## 1.2.0 — 2026-10-18

- Roteiro: você pode desativar qualquer item que ainda não foi entregue. O Developer nunca pega item desativado; reativar
  devolve o item ao lugar dele na fila. A mudança aparece na linha do tempo da evolução e o progresso ignora os desativados.
- Falar com o loop virou conversa: suas mensagens e as respostas do loop ligadas a cada uma, estado (na fila, lido e em
  quanto tempo, falhou), sugestões, Enter para enviar. Pedido ao loop responde com o número do item no roteiro e quantos
  estão na frente.

## 1.1.0 — 2026-10-18 · o loop trabalhando à vista

**Ritmo**
- Giro rápido quando há trabalho (missões, código, PRs abertos) e descanso longo só quando não há nada a fazer.
- Escolha das tarefas pela cascata: regra antes do Jev. Trabalho real tem precedência; a manutenção gira em rodízio e o Jev
  escolhe entre as três mais esquecidas (antes ele repetia a mesma tarefa e o trabalho real nunca vinha).

**Registro de modelos**
- Toda chamada de LLM fica guardada (tabela `llm_calls`): papel, modelo, quem escolheu (Jev, decisor local ou padrão do
  harness), confiança, contexto, tokens, duração, erro, início da entrada e da saída, e se o ciclo foi aceito.
- O histórico de cada nível de modelo por papel vira contexto da próxima escolha do Jev.

**Painel**
- Números ao vivo no topo (giros, commits, PRs, versão, evoluções, decisões por minuto, chamadas de LLM).
- "Agora": o passo atual com o tempo correndo e os últimos passos, com o que cada um fez.
- Giros: cada giro como uma barra com a duração de cada etapa.
- Decisões ao vivo em console: agrupadas por giro, filtros Jev/local/LLM, congelar, ritmo dos últimos 30 minutos.
- Evolução: linha do tempo única de regras, ajustes do próprio loop, ciclos, evidências, PRs, merges, prompts em A/B,
  versões, roteiro e erros.
- Modelos escolhidos pelo Jev: resumo por modelo e cada chamada com entrada e saída.
- Roteiro com progresso, grupos (em andamento, na fila, parciais, entregues), origem de cada item e links para os commits.
- Commits do repositório no card do Loop.

## 1.0.5 — 2026-10-17

- Ao subir, o loop testa de verdade as conexões (Jev, Claude e GitHub, só leitura) e registra o resultado no painel: chave errada aparece na hora.

## 1.0.4 — 2026-10-17

- Salvar a configuração acorda o loop do descanso na hora (antes esperava o próximo giro, até alguns minutos).

## 1.0.3 — 2026-10-17

- Developer autentica fetch/push no GitHub com o `GITHUB_TOKEN` (por variável de ambiente do git, fora da linha de comando) e nunca fica esperando senha.

## 1.0.2 — 2026-10-17

- Serviço 24/7 roda dentro da pasta de dados e usa o executável `circulo` do ambiente. Antes, no macOS, o clone `~/Projects/circulo` escondia o pacote instalado e o loop caía ao subir.

## 1.0.1 — 2026-10-17

- O loop percebe quando o arquivo de configuração muda (você salvou as chaves) e reinicia sozinho já com elas; o serviço 24/7 o sobe de novo.

## 1.0.0 — 2026-10-17 · primeira versão

O loop autoevolutivo completo, pronto para rodar 24/7 sem depender de interação.

**Núcleo**
- Loop infinito com estado persistente, batimento, pausa por orçamento e retomada à meia-noite, recuperação após queda.
- Jev First em todas as etapas: `worth_spending`, `should_evolve`, `route`, `pick_model`, `verify_output`,
  `meets_bar`, `relevant`, `remember`, `should_advance` + contraprova. Cliente real da API TypeSafe e decisor local
  com o mesmo contrato.
- Política versionada com guard, shadow mode, rollback automático, destilação da cascata.

**Missões**
- Qualquer pedido vira missão (Intake pelo Jev). Motor genérico: pesquisa na web, régua com critérios ocultos,
  construção, verificação pós-LLM, avaliação composta, catraca, reflexão.
- Evidência por ciclo e gatilho de avanço com autoconsistência do Jev; missão cumprida com evidência.
- Portfólio autogerenciado, várias missões em paralelo por giro, orçamento por missão.
- Grafo de missões: relações pelo Jev, memória (RAG BM25 + rerank do Jev) e contexto compartilhados,
  integração na régua, lições que viajam entre missões, reabertura quando a missão ligada muda.
- Kit de finanças da família (registro rápido, categorização, aprendizado de regras, reclassificação automática).

**O Loop (missão zero)**
- Roteiro com evidência, registro de erros agrupado, quarentena com backoff, Developer que corrige o próprio
  código por PR (Claude Code headless), harness de prompts evoluindo por A/B.

**Autonomia e guardrails**
- Zero espera pelo humano: constituição imutável para o loop, evidência reforçada para código de dinheiro,
  fora do alcance registrado sem fila.
- Gate de merge no próprio loop; CI com testes, constituição e propriedades financeiras.
- Snapshots e restauração, orçamento de mudanças, bloqueio de oscilação, alerta de estagnação, modo seguro.

**Painel e operação**
- Painel local ao vivo: missões em cards com indicadores, o círculo tocando cada etapa, autonomia, evidências,
  conexões, entregas.
- Configuração única: `circulo configurar`, `circulo diagnostico`, `circulo instalar` (launchd/systemd).

**Limites conhecidos**
- Produto de software ainda sai como especificação (Markdown), não como repositório de código.
- Perguntas do Jev e parâmetros do portfólio ainda não evoluem sozinhos (limiares e prompts evoluem).
- Calibrado com o decisor local e LLM simulada; o primeiro dia com o Jev e a LLM reais deve ajustar limiares.

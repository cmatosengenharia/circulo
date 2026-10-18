# Changelog

## 1.9.3 — 2026-10-18

O gate mergeou o PR #4 com CI verde, mas o CI tinha rodado sobre a main antiga, antes da 1.9.1, e a main ficou
vermelha. Correções:

- **PR atrás da main não entra**: o gate traz a main para a branch (update-branch) e espera o CI de novo, agora sobre a
  main atual. Se der conflito, o Developer resolve (1.9.2).
- **Neurônio `gate:main`**: CI da main vermelho vira lição de estrutura na hora (`gate:main_vermelha`), com item no
  topo da fila.
- Corpo: checa a main a cada 10 minutos, além de logo depois de cada merge. Antes eram 60 giros, que no descanso
  longo davam horas. A validação antes da troca já provou seu valor: recusou rodar a main quebrada (4ccc632) e
  registrou a lição #2.
- As duas correções da lição #1 convivem: a troca direta (1.9.1) e o caminho livre que o Developer escreveu sozinho
  (PR #4, `corpo_caminho.py`). O teste do PR #4 foi ajustado para isso.

## 1.9.2 — 2026-10-18

Dois jeitos de o Developer ficar parado para sempre esperando um PR, achados enquanto ele resolvia a lição #1 sozinho
(PR #4, que acabou superado pela correção da 1.9.1):

- **PR em conflito com a main** volta para o Developer: o gate lê `mergeable` e devolve com "conflito com a main".
  No conserto, a main é trazida para a branch e o agente resolve os conflitos. Novo portão nato antes do PR:
  **sem marcador de conflito** nas linhas novas.
- **PR fechado ou mergeado fora do gate** (por você, no GitHub): o Developer é liberado. Se o PR foi fechado sem
  merge, o item volta para a fila; se foi mergeado, o item vira feito.
- O conserto que só traz a main (sem mudança do agente) também é enviado.

## 1.9.1 — 2026-10-18

Primeira lição real da máquina do loop (#1, estrutural), registrada sozinha minutos depois da 1.9.0. A troca de corpo
falhava porque o código novo trazia arquivos que já existiam lá sem rastreio (cópias manuais) e o `git checkout`
recusava. O ciclo funcionou: monitorou, registrou a lição, criou o portão, isolou a etapa e mandou o Developer corrigir.
Só que a correção fica em `corpo.py`, que é constituição, e por isso coube ao humano.

- Corpo: `checkout -f` depois de guardar o patch local. Teste de regressão "lição #1".
- Developer: correção que exige mexer na constituição não fica sendo tentada a cada 10 giros. Vai para você
  ("depende de você"), com aviso.
- Erro em que o agente não acha o que mudar fica **em observação**, fora da fila. Vira feito quando o erro para de
  acontecer, e a lição reabre o item se o erro voltar.

## 1.9.0 — 2026-10-18

O loop passa a rodar o código que ele mesmo evoluiu. Antes, um PR mergeado pelo gate (ex.: #3, feito sozinho em
7 minutos: planejar → estudar → Developer → portões → PR → CI → merge) só existia no GitHub, e a máquina do loop
seguia no código antigo até alguém atualizar à mão.

- **Neurônio `corpo:atualizar`** (`corpo.py`): quando a main anda (logo depois de um merge, e a cada 60 giros):
  - portões ANTES de trocar: num worktree separado com o código novo, importa os módulos do serviço e roda a suíte
    de testes. Se reprovar, o corpo não muda, a lição `corpo:validacao_falhou` (estrutural) é registrada e aquele
    código não é tentado de novo;
  - troca: a mudança local é guardada em patch na pasta de dados (arquivo não rastreado nunca é apagado). O código
    vai para a main e o loop reinicia limpo;
  - **evidência depois**: os 5 primeiros giros precisam rodar sem erro. Com 2 giros com erro, o loop volta para o
    código anterior, reinicia e registra `corpo:regressao_pos_atualizacao`.
- `corpo.py` entra na constituição: agente nenhum afrouxa a troca do próprio corpo.

## 1.8.0 — 2026-10-18

O pedido é uma hipótese, não uma ordem gravada em pedra. O loop só executa depois de estudar em fontes confiáveis,
e só desobedece com evidência.

- **Neurônio de estudo** (`estudo.py`), antes de o Developer pegar seu pedido ou um item planejado pelo loop:
  - o Jev decide o gasto;
  - pesquisa na web (com citações) das principais referências e do que cada uma faz de melhor;
  - veredito:
    - **adotar**: o estudo é anexado ao item e entra na tarefa do Developer;
    - **adaptar**: o item é reescrito pela evidência, o pedido original fica registrado e você é avisado;
    - **contestar**: o item não é executado e o loop explica com as fontes. Pelo botão "Executar mesmo assim" no
      roteiro, você reafirma e ele segue, com a decisão registrada.
- **Portão mecânico**: adaptar ou contestar exige pelo menos 2 fontes distintas. Sem evidência, o loop não desobedece.
  Depois o Jev confere se a evidência sustenta o veredito (só pode deixar mais conservador). Sinapse: `estudo:pedido`.
  Resposta inválida vira a lição `estudo:saida_invalida`.
- O Developer só pega pedido (seu ou do loop) já estudado. Erro do próprio loop não passa pelo estudo: a evidência é o
  próprio erro. O planejador não cria item novo enquanto houver item esperando estudo.
- **Missões** (ex.: portal admin de fotógrafo): a pesquisa trata o pedido como hipótese, busca as principais
  referências do mercado e o melhor de cada uma, com URL. A régua só nasce com evidência suficiente (≥2 achados
  aceitos pelo Jev, de ≥2 fontes distintas); senão pesquisa de novo, até 3 vezes. Se a evidência sugerir ajustar o
  pedido ("CONTESTA"), você é avisado e a régua considera o ajuste. Sinapse: `missao:pesquisa`.
- Painel: grupo "Contestados pelo estudo" no roteiro.

## 1.7.0 — 2026-10-18

Cérebros e neurônios. Cada ponto do fluxo segue o mesmo contrato, e o loop cria portões novos a partir dos próprios erros.

- **Contrato do neurônio** (`neuronios.py`): estímulo → Jev primeiro → ação → **portões de saída** (todos precisam
  aprovar para a saída seguir) → sinapse (`verificacoes`) → aprendizado (`licoes`).
- **O PR só nasce se todos os portões aprovarem** (neurônio `developer:abrir_pr`): antes de existir PR, o Developer
  passa localmente pelo mesmo que o gate do merge exige (constituição intacta, tamanho, teste novo), mais lint e testes
  iguais ao CI e os portões aprendidos. Se barrar, ele corrige no mesmo worktree com a lista do que falhou e só desiste
  depois disso. Vale também para o conserto de PR reprovado.
- **Neurogênese**: a lição vira portão executável (tabela `portoes`), como dado e não como texto num prompt:
  - lição de lint vira portão `ruff --select <código>`;
  - lição de teste vira portão `pytest <teste>`;
  - lição de estrutura com item vira portão obrigatório: o PR desse item precisa trazer um teste que cite "lição #N".
    É esse teste, rodando no CI para sempre, que impede o erro de voltar.
  Comandos só da allowlist (ruff, pytest). Os portões aprendidos aparecem na tarefa do Developer.
- **Cérebros no painel**: Cérebro do Loop, um cérebro por missão e Cérebro Financeiro, com os neurônios de cada um,
  disparos, quantos foram barrados e os portões aprendidos.
- O ruff é instalado uma única vez quando falta (nunca dentro de testes).

## 1.6.0 — 2026-10-18

Maturidade: o loop aprende com os próprios erros como um humano, e o mesmo erro de estrutura só acontece uma vez.
Ciclo: estudar (evidência) → testar → **validar** → aprender → corrigir → **evidenciar** → evoluir.

- **Todo ponto de verificação é monitorado** (tabela `verificacoes`): lint e testes locais do Developer, saída do
  Claude Code, reprovação no CI e no gate, merge, saída do planejador, verificação pós-LLM e evidência das missões,
  shadow, rollback de saúde e exceções do giro. O painel mostra a taxa de acerto por ponto nas últimas 24 h.
- **Falha vira lição** (tabela `licoes`) com assinatura estável da causa (`gate:ci:lint:B905`,
  `planejador:saida_invalida`, `incidente:<digital>`...):
  - estrutural (erro do próprio loop): vira item do roteiro na **primeira** vez (antes: só a partir da 2ª);
  - trabalho (lint/teste no PR, rollback de evolução): vira prevenção nos prompts;
  - ambiente (limite de conta, rede): só vira item se repetir 5x em 24 h.
- A lição fecha com duas provas: **validada** (o item foi feito: PR mergeado ou incidente resolvido) e **evidenciada**
  (200 giros sem reaparecer).
- **Reincidência**: assinatura que volta depois de corrigida. Gera alerta, o item volta para o topo da fila e a contagem
  fica no painel. Zero reincidências é o indicador de maturidade.
- **Só se autoevolui depois de corrigir**: com lição estrutural aberta, o planejador não propõe item novo e a
  meta-evolução do círculo para; só o domínio (suas correções) continua.
- **Lições no contexto**: o Developer (tarefa e conserto) e o planejador recebem a lista "erros que o círculo já
  cometeu. Não repita nenhum deles".
- Painel do loop: seção "Lições" com reincidências, estados, assinaturas e verificações.
- Planejador: `max_tokens` 1500 e resposta em uma linha. Com 700, a resposta saía cortada e o JSON ficava inválido.
  Foi o primeiro erro que motivou a lição `planejador:saida_invalida`.

## 1.5.0 — 2026-10-18

O loop nunca fica sem o que evoluir. Com o PR #2 mergeado, o roteiro ficou sem nada que o Developer pudesse pegar, o
ritmo adaptativo passou ao descanso longo (300 s entre giros) e o giro só fazia manutenção.

- Planejador do roteiro (`planejador.py`): com o roteiro vazio para o Developer e nenhum PR aberto, o loop junta a
  própria evidência e propõe UM item pequeno e mensurável para o próprio código. A evidência inclui as decisões em que o
  Jev ficou abaixo de `jev_incerto` por pergunta, as chamadas de LLM e falhas dos últimos 7 dias, os incidentes
  abertos, as avaliações recentes do gate, o roteiro e a saúde. O item entra com origem "loop" ("do loop" no painel), e
  o Developer pega como qualquer outro: worktree, Claude Code, lint e testes, PR, CI e gate.
- O Jev decide o gasto (`worth_spending`) e o modelo (`pick_model`); a chamada fica em `llm_calls` com o papel
  "planejador". Limites: uma tentativa a cada 30 min, no máximo 6 itens por dia, título repetido descartado,
  constituição fora do alcance. No modo seguro, não planeja.
- Ordem do Developer: erro recorrente, depois seu pedido, depois item planejado pelo loop.

## 1.4.3 — 2026-10-18

- Item do roteiro cujo PR do Developer entrou na main vira "feito" sozinho, com a evidência "PR #n mergeado". Isso vale
  no merge e também ao religar, para PRs que já tinham entrado (o item #26 estava "em andamento" com o PR #1 mergeado).

## 1.4.2 — 2026-10-18

- Conserto só vale para a versão do PR que foi reprovada: se a branch mudou depois (commit novo, main atualizada no PR),
  o Developer não conserta nem fecha o PR, e espera o gate avaliar a versão nova.

## 1.4.1 — 2026-10-18

- CI, job Constituição: compara o merge do PR com a main atual (`HEAD^1`), não com a main de quando o PR abriu.
  Antes, uma mudança sua na main depois de o PR abrir aparecia como "constituição alterada por agente".

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

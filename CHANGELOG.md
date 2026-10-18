# Changelog

## 1.18.0 — 2026-10-18

**Pausar missão por missão**, sem parar o loop nem as outras missões.

- Botão **"Pausar esta missão" / "Retomar esta missão"** no painel de cada missão. Quando pausada, aparece uma
  faixa explicando o estado, e a tela inicial mostra o selo "pausada" no card.
- Pausada, a missão:
  - sai da escolha do motor: nenhum ciclo novo começa e não há gasto de tokens;
  - guarda os pedidos para ela na fila, enquanto os das outras missões e as missões novas seguem; ao retomar,
    os guardados são atendidos na ordem.
- **Pausa verificável**, como a parada do loop: se um ciclo da missão já estava rodando, o estado fica "parando"
  até ele terminar. O resultado desse ciclo **não é aplicado** (fica registrado como descartado) e a entrega atual
  não muda. Ciclo interrompido pela pausa não conta como platô.
- Cada pausa e retomada vira alerta e entra no rastro da missão (`/rastros`, "missão N").
- Central de confiança: card "Missões pausadas por você".
- O próprio loop não se pausa por missão: para ele continua o botão "Pausar o loop".
- API: `POST /api/missao/pausa {id, acao: pausar|retomar}`, com o mesmo cabeçalho de proteção do painel.

## 1.17.0 — 2026-10-18

**Rastreabilidade de ponta a ponta e observabilidade**, nos padrões consolidados do mercado (OpenTelemetry,
W3C Trace Context, sinais de ouro e SLOs do Google SRE, Prometheus).

- **Fio de ponta a ponta** (`rastro.py`, tabela `elos`): cada mudança do loop é ligada da origem até a prova no
  código rodando: pedido seu, pergunta do conselho ou lição de erro → estudo → sessões do Developer → portões →
  PR → gate/CI → merge → versão que entrou no código rodando → giros de evidência → concluído.
  - Elos gravados onde o loop age (pedido, estudo, Developer, PR, corpo). O **corpo liga exatamente** cada PR à
    versão em que entrou (o gate faz squash com "(#N)" no título; o git diz quais PRs vieram).
  - O histórico antigo também ganha fio, derivado da branch do PR, dos merges e das verificações do corpo:
    nos dados reais, 9 de 9 entregas com fio completo.
  - Cada item tem um **trace_id W3C** estável. O `traceparent` vai para o Claude Code (variável TRACEPARENT), para
    o commit (trailers `Circulo-Item` e `Circulo-Trace`) e para o corpo do PR. O traço de cada giro aponta para o
    fio dos itens em que trabalhou (*span links* do OTel).
  - **Lacuna vira lição**: o neurônio `rastro:cadeia` confere cada entrega mergeada uma vez. Classe trabalho:
    fica registrada sem travar a evolução.
- **Observabilidade** (`observabilidade.py`):
  - sinais de ouro em 24 h e 1 h: tráfego, latência, erros e saturação;
  - RED por operação (cada verificação e cada papel de LLM);
  - **5 SLOs com orçamento de erro**, calibrados nos dados reais do loop: giros sem erro ≥ 99%, giro leve no
    tempo ≥ 95%, LLM sem falha ≥ 90%, painel em tempo real ≥ 99% e entregas com fio completo ≥ 95%. Limite de uso
    e rede fora do ar contam como saturação, não como erro.
- **Para ferramentas de mercado**:
  - `/metrics` no formato do Prometheus: o Grafana raspa direto;
  - exportação **OTLP/HTTP** dos traços para qualquer coletor (Grafana Tempo, Jaeger, Honeycomb, Datadog…)
    quando `OTEL_EXPORTER_OTLP_ENDPOINT` estiver cadastrado em Integrações. Roda em segundo plano, e o cursor só
    avança depois do 2xx: nada se perde se o coletor cair.
- **Tela Rastros** (`/rastros`, botão na tela inicial e "Rastro do item #N" em cada item do roteiro):
  - busca por qualquer ponta;
  - o fio passo a passo, com link para cada giro e PR;
  - SLOs, sinais de ouro, fios recentes e RED, ao vivo a cada 5 s.
- Central de confiança: cards "Rastro de ponta a ponta" e "Objetivos de serviço (SLOs)".

## 1.16.0 — 2026-10-18

Produto, parte 2: **giros em paralelo na mesma missão** e **missões que se conhecem sob o seu controle**.

- **Giros em paralelo** (1 a 4 por missão, no painel da missão): a cada ciclo o motor gera N variantes ao mesmo
  tempo, cada uma por um **ângulo diferente**:
  - na construção, prioriza um critério de peso alto da régua;
  - na melhoria, parte de uma pergunta de uma perspectiva diferente, sobre um critério fraco diferente.
  As variantes que passam na verificação disputam um **torneio na régua** (visível e depois oculta). Só a vencedora
  segue para a catraca, o portão de avanço do Jev e a evidência, como sempre. As perguntas das que perderam contam
  como "não rendeu" no placar das perspectivas. O resultado do torneio fica na nota do ciclo ("3 giros em paralelo;
  venceu a variante 2 (v1: 0.40, v2: 0.85, v3: 0.40)"). **Limitado pelo orçamento**: se não couber, roda um só.
- **Missões que se conhecem**: o grafo de missões que o Jev mantém (contexto e memória compartilhados, integração na
  régua, lições que viajam entre missões) virou recurso de produto no painel:
  - **Ligar** uma missão a outra (complementa, usa a saída, mesmo público, compartilha dados) e **Separar**;
  - a ligação feita por você **vale acima do Jev**: ele não muda nem apaga. Separar também impede o Jev de religar;
  - ao ligar com "complementa" ou "usa a saída", a integração entra na régua das duas na hora;
  - cada conexão mostra quem ligou e quantas lições já trocaram.
- APIs: `POST /api/missao/paralelo {id, n}` e `POST /api/ligacoes {a, b, relacao}`, com alerta em cada mudança.

## 1.15.0 — 2026-10-18

Produto, parte 1: **cadastro de chaves de integração no painel**, guardadas com segurança.

- Nova tela **Integrações** (`/integracoes`, botão na tela inicial), com as chaves do Jev, da LLM, do GitHub e do
  repositório, mais **qualquer outra integração** que você cadastrar (nome em MAIÚSCULAS).
- **Cofre do sistema** (`cofre.py`), escolhido sozinho:
  - **macOS: Keychain** (criptografado pelo sistema). O valor vai para o comando `security` pelo stdin, nunca na
    linha de comando, e por isso não aparece no `ps`;
  - **Linux: Secret Service** (`secret-tool`);
  - sem cofre do sistema: o arquivo de configuração com permissão 600.
  Também dá para forçar com `CIRCULO_COFRE=keychain|secret-service|arquivo`.
- **A tela e a API nunca devolvem o valor de uma chave**: só se está cadastrada, onde está, os 4 últimos caracteres e
  o resultado do teste de conexão.
- Proteções do cadastro: cabeçalho do painel, origem local e **Host local** (contra DNS rebinding); nome validado e
  valor sem quebra de linha.
- Cada mudança vira alerta ("Você trocou a chave X (final …abcd) no keychain") e **reinicia o loop limpo** para
  valer. Na volta, o diagnóstico testa as conexões e a tela mostra o resultado.
- **Mover para o cofre**: um botão seu move as chaves que ainda estão em texto no arquivo. Cada uma só é apagada do
  arquivo depois de lida de volta, igual, no cofre.
- Ao iniciar, o loop lê o arquivo e depois o cofre, sem sobrescrever o que já veio do ambiente.

## 1.14.0 — 2026-10-18

- **Limite diário da API customizável pelo painel**: no número "% da API hoje" (✎), você escolhe o limite em tokens ou
  volta ao padrão da política. Vale na hora para todo o loop: porteiro do gasto, pausa por orçamento, Central de
  confiança e painel. Piso de 10 mil e teto duro em `CIRCULO_HARD_DAILY_TOKENS` (padrão 2 milhões), inclusive se o
  valor for adulterado direto no banco. Cada mudança vira alerta ("Você mudou o limite diário da API: 200.000 →
  400.000") e fica no histórico (kv `orcamento_limite`).

## 1.13.0 — 2026-10-18

As perguntas deixam de ser só fixas. Elas vêm de uma **LLM especializada nesse tipo de evolução** (pedido do Cássio),
sem perder a economia.

- **Questionador** (`perguntas.py`): papel de LLM com prompt de especialista em evolução de sistemas autônomos.
  Conhece SRE e pre-mortem, Jobs-to-be-Done e "5 porquês", método científico e Lei de Goodhart, economia de IA (quando
  NÃO chamar a LLM) e red team. Ele:
  - cria perguntas novas e diversas, e cria **perspectivas novas** quando falta um olhar (ex.: "novato");
  - prende **cada pergunta a uma métrica de um catálogo medido por SQL** (conflitos de PR, tokens por PR, regra no
    lugar do Jev, recusas de gasto, lições abertas, estagnação…). Assim a priorização continua sem LLM, pelo tamanho
    da dor;
  - fala **no máximo 1 vez por dia**, ou antes (3 h) se as perguntas atuais se esgotarem (nenhuma candidata com
    prioridade ≥ 0,3). O modelo é escolhido pelo Jev, como tarefa de alta complexidade;
  - pergunta gerada que só rende item contestado, repetido ou sem item (3 vezes, nenhuma entrega) é desativada sozinha.
- As 8 perspectivas e perguntas da 1.12 continuam como **semente** e como plano B sem LLM.
- **Perguntas por tipo de missão**: o Questionador cria **uma vez por tipo** as perspectivas de quem usa, decide ou paga
  (ex.: portal de fotógrafo → fotógrafo, cliente final, assistente). Cada ciclo de melhoria da missão parte de uma
  pergunta "Como <perspectiva>, o que na entrega atual mais atrapalha <critério mais fraco>?", **sem LLM extra**:
  ela entra no prompt do Improver que já ia rodar. Rodízio entre perspectivas, com placar por tipo de missão (versão
  aceita = entregue).

## 1.12.0 — 2026-10-18

A autoevolução parte de **perguntas**, feitas por um **conselho de perspectivas**, com economia primeiro.

Exemplo de pergunta (pedido do Cássio): "Como usuário, qual componente devo melhorar para facilitar a visualização das
métricas no painel?". Quem faz esse tipo de pergunta no loop é o conselho (`perguntas.py`):

| Persona | Olhar |
|---|---|
| usuário | entender rápido, confiar, não precisar perguntar |
| economista | menos tokens e menos LLM por resultado entregue |
| operador (SRE) | não travar, não ficar cego, se recuperar sozinho |
| cientista | toda mudança prova que melhorou algo |
| arquiteto | menos retrabalho onde o código mais quebra |
| auditor | guardrail que nunca barrou nada pode estar quebrado |
| cético | indicador que diz "tudo bem" e pode estar mentindo |
| financeiro | o cérebro financeiro só aprende com dados reais |

- **Gerar e priorizar perguntas não gasta LLM.** Cada pergunta tem um sinal calculado por SQL nos dados do loop
  (quanto dói agora) e a evidência que a sustenta; pergunta sem dor não entra.
  Prioridade = relevância × placar da persona × diversidade ÷ custo. Persona usada nas últimas 3 perguntas pesa 0,35,
  para o conselho não ficar preso num olhar só. A regra estreita para as 3 melhores e o Jev escolhe.
- **Só a pergunta escolhida vai para a LLM** (planejador), que responde com UM item, ou com `sem_item` quando a
  resposta já existe ou exige mexer na constituição. Isso corrige o caso do #35, que propôs algo já feito. Pergunta em
  andamento não é refeita.
- **As perguntas evoluem**: cada persona tem um placar (Beta). Item entregue soma; contestado, repetido ou sem item
  subtrai. Quem pergunta melhor pergunta mais.
- Rastro completo: tabela `perguntas`, item do roteiro com "pergunta do conselho: <persona>", alerta "Conselho
  (persona) perguntou: … → item #n", painel ("Última pergunta do conselho") e `/api/conselho` (placar, últimas
  perguntas e as próximas candidatas).

## 1.12.0 — 2026-10-18

Central de confiança em três níveis (Endsley), sinais de ouro, trilha write-ahead e parada testada (item #32).

- **Trilha write-ahead** (`circulo/intencoes.py`): cada pedido e cada tarefa do loop gravam a intenção antes de rodar.
  O registro leva ator, motivo, a regra que decidiu (regra, Jev ou LLM, com o valor e o limiar do gasto) e as entradas.
  Se o registro falhar, a ação não roda. A tabela `intencoes` é só de acréscimo (gatilhos recusam UPDATE e DELETE) e
  cada linha é encadeada pelo hash da anterior. `divergencia()` conta ações executadas sem intenção prévia; o alvo é 0.
- **Perceber · Entender · Projetar**: Perceber traz o estado e os quatro sinais de ouro (latência do giro em p99,
  tráfego, erros, saturação). Entender mostra por que a última ação foi tomada e qual regra decidiu, lido da trilha, e
  não do push. Projetar mostra o próximo passo e o risco. Cada card tem fato, significado e projeção, mais a idade da
  leitura ("lido há X s"), marcada **obsoleto** acima de 3 s.
- **Frescor como SLO**: cada medição do painel fica guardada (tabela `frescor`), e `painel:frescor` verifica o p99 das
  últimas 24 h (meta ≤ 3 s), não a última leitura. O painel envia a pior idade vista a cada 10 s, ou seja, a cauda.
- **Parada verificável** (`circulo/parada.py`): o botão **Parar** grava a intenção, liga a pausa e só mostra
  "Parado e verificado ✓" quando o loop confirma no giro e nenhuma ação começa depois disso (`GET /api/parada`). O
  próprio loop aperta o botão quando sobe e depois toda semana, gira, confere pelo mesmo caminho e retoma. O
  resultado é o neurônio `loop:parada` (falha vira lição de estrutura).

## 1.11.3 — 2026-10-18

- Esperar o espaçamento entre tentativas não conta como estagnação: o vigia de progresso só considera o trabalho que
  pode rodar agora. Antes, o conserto do PR #6 esperando a vez contaria como "parado" e geraria uma lição falsa.
- Espaçamento do Developer: 2 giros, não 10. Com o descanso longo de 5 min, 10 giros viravam 50 min de espera para
  consertar um PR.

## 1.11.2 — 2026-10-18

- **Batimento durante o giro**: o loop só escrevia o batimento entre giros. Com o Developer trabalhando 8 minutos no
  item #32, o painel mostrava "Desligado" e "Atenção" com o loop trabalhando normalmente. Agora um pulso escreve o
  batimento a cada 5 s também durante o giro, e a etapa em curso continua "Trabalhando" pelo tempo que durar.

## 1.11.1 — 2026-10-18

Achado na validação das 12:57: o Developer trabalhou 6 min (56 passos) no item #32, bateu no limite de uso da
assinatura do Claude Code e todo o trabalho foi descartado. Depois do reset, ele recomeçaria do zero, com risco de bater
no limite de novo, sem fim.

- **Trabalho parcial é retomado, não refeito**: sessão interrompida (limite da conta, máximo de passos) vira um commit
  local na branch, sem push e sem PR. A próxima sessão continua de onde parou ("CONTINUAÇÃO: … não recomece").
  Neurônio `developer:retomada`: depois de 4 sessões sem terminar, registra a lição "item grande demais".
- Assinatura estável para erro de ambiente: `…:limite_de_uso` e `…:timeout`. Antes, o log bruto do agente gerava uma
  assinatura nova a cada vez (lição #3), e repetições não eram reconhecidas.

## 1.11.0 — 2026-10-18

Incidente: das 11:20 às 12:13 o loop girou a cada 15 s sem avançar. Os dois pedidos do Cássio (#33 e #34) ficaram sem
estudo, e o item #31, já estudado, ficou sem Developer. O painel dizia "Pode confiar". Três causas, todas de estrutura:

1. **Orçamento contado errado**: os tokens do Claude Code (Developer, que roda na assinatura da sua conta e não nos
   créditos da API) entravam no orçamento diário da API, cerca de 100 mil de 145 mil. Com "72% gasto", o porteiro do
   gasto recusava tudo o que custava.
2. **Dois porteiros com limiares diferentes**: o loop aprovava a tarefa (0,67 ≥ 0,4), e o estudo ou o Developer
   perguntavam de novo com outro limiar e recusavam (0,33 < 0,5). A tarefa contava como "feita", e no giro seguinte
   tudo se repetia. O aprendiz do Jev (PR #3) ainda imitava essas recusas.
3. **Ninguém vigiava o progresso**: girar sem avançar não era tratado como erro.

Correções:
- Developer fora do orçamento da API. Os tokens da assinatura ficam contados à parte (`assinatura_tokens`); o limite da
  assinatura já tem tratamento próprio (espera o reset). Correção única: o que foi do Developer volta ao orçamento.
- **Um porteiro só**: chamados pelo loop, estudo, planejador e Developer não perguntam o gasto de novo. Custo
  estimado do estudo corrigido para ~30 mil tokens, o valor real com a busca.
- **Neurônio de progresso** (`loop:progresso`): havendo trabalho e nada avançando (roteiro, estudos, LLM, PRs,
  merges, código, entregas) por 10 giros, a estagnação vira lição de estrutura com a causa ("estudar_pedido recusado
  27x"), aparece um alerta, o painel mostra **"Avançando? Não"** como falha e o ritmo vai para o descanso longo.
- **Recusa com espera crescente**: tarefa recusada pelo porteiro espera 1, 2, 4… até 64 giros antes de tentar de novo.

## 1.10.0 — 2026-10-18

Central de confiança: o painel responde primeiro "posso confiar no loop agora?", em tempo real e em tudo.

Estudo (pedido do Cássio, seguindo o princípio do loop de buscar as práticas consolidadas):
- consciência situacional (Endsley): três níveis, **perceber** o que acontece, **entender** se está seguro e
  **projetar** o que vem a seguir ([Perceptual Edge](https://www.perceptualedge.com/blog/?p=45),
  [Endsley/DTIC](https://apps.dtic.mil/sti/tr/pdf/ADA616862.pdf));
- **frescor do dado**: "dado de quando" pela fonte e não pela tela; "ao vivo" só quando é de verdade; alertar quando o
  dado para de avançar ([Basedash](https://www.basedash.com/blog/data-freshness-how-current-your-dashboard-data-really-is));
- **supervisão humana de agentes**: trilha da decisão (quem decidiu e com que confiança), ações em tempo real, parada
  verificável ([Airia](https://www.airia.com/blog/human-oversight-for-ai-agents-what-it-means-and-how-to-implement-it-in-the-enterprise/));
- **sinais de ouro / RED** e menos carga cognitiva: cada painel responde a uma pergunta, cores consistentes, exceções à
  vista ([AWS Grafana](https://docs.aws.amazon.com/grafana/latest/userguide/v10-dash-bestpractices.html));
- **calibrar a confiança**: mais informação quando a confiança está baixa, sem afogar o humano
  ([arXiv 2004.07176](https://arxiv.org/pdf/2004.07176)).

O que mudou:
- Topo da tela do loop: veredito (Pode confiar · Em observação · Atenção · Loop parado), com a frase do porquê, e três
  colunas:
  - **Agora**: processo vivo (batimento), etapa e há quanto tempo, última decisão (pela regra, pelo Jev ou pela LLM,
    com a confiança) e quem decide nas últimas 24 h;
  - **Segurança**: código rodando (validado e evidenciado), CI da main, reincidências, erros de estrutura abertos,
    portões, erros nos últimos giros, etapas isoladas, orçamento, invariantes do dinheiro e Developer;
  - **A seguir**: próximo giro, próximo trabalho do Developer, pedidos esperando estudo, planejador e próxima checagem
    do código.
- Cada item mostra **de quando é o dado** (relógio da fonte), contando ao vivo, e acusa "dado velho" quando passa do
  limite. A pausa é **verificável**: mostra o horário do último giro.
- Indicador **ao vivo** no cabeçalho: "dado de 0,4 s atrás", "atrasado" depois de 3 s e "sem conexão" depois de 10 s.
- Selo de confiança em todas as telas.
- Tudo **empurrado** pelo servidor (SSE): a confiança a cada mudança e no mínimo a cada 2 s, e as **sinapses ao
  vivo**, isto é, cada verificação de cada neurônio no momento em que acontece, com o filtro "só o que foi barrado".
- **O painel também é um neurônio** (`painel:frescor`): ele mede o próprio atraso entre o dado e a tela e manda para o
  loop (no máximo 1 vez por minuto). Acima de 3 s vira lição de estrutura.
- **O painel evolui sozinho daqui para frente**: novo item no roteiro, "Painel de confiança em tempo real, evoluindo por
  evidência". Ele passa pelo estudo (fontes confiáveis) e depois pelo Developer.
- Semente do roteiro: nunca desfaz o que o loop já entregou (item feito por PR continua feito).

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

# Changelog

## 1.45.0 — 2026-10-20

**Os gargalos medidos no Mac (24 h: 1,5 M tokens do Desenvolvedor para 7 itens entregues).**

- **Desenvolvedor roda testes, lint e git de leitura sozinho.** O Claude Code em `-p` com `acceptEdits` só podia editar:
  42 de 168 chamadas "ok" terminavam em "aprove os comandos", o item voltava barrado nos portões e tudo recomeçava
  (~12 chamadas por PR). Agora vai com `--allowedTools` (`FERRAMENTAS`: pytest, ruff, python, git diff/status/log/stash/show,
  ls/cat/grep/…; nada que saia do worktree). `CIRCULO_CODE_AGENT_FERRAMENTAS` sobrescreve.
- **Portão aprendido com teste inexistente vira obsoleto.** A lição #27 (teste citado que já não existe) bloqueou 135
  vezes com `pytest` exit 4; agora o portão é desativado, a lição marcada obsoleta e o PR segue. (Fecha o item #104.)
- **Estudo sem texto tenta de novo sem busca.** 14 de 40 estudos voltaram vazios (~13 mil tokens cada, 0 bytes de
  resposta): o teto de 2500 tokens era engolido pelas buscas. Teto 8000 (leve 4000) e, se ainda vier vazio, uma segunda
  chamada sem busca com o mesmo teto. (Lição #22/#45.)
- **Aviso de saúde igual não repete na mesma hora** (eram 372 por dia, 20× o mesmo texto).
- **Espera vencida do Desenvolvedor some do banco**: não fica "Desenvolvedor parado" fantasma na faixa nem no "Precisa de você".

## 1.44.0 — 2026-10-20

**A memória do time (RAG) compartilhada com toda a equipe — a começar pelo Product owner.** Até aqui só o Desenvolvedor,
o Arquiteto e o Gerente de produto consultavam a memória; o PO classificava perguntas sem saber o que já tinha sido
perguntado ou entregue, e o Médico julgava um padrão sem ver os diagnósticos anteriores.

- **Índice** ganha dois tipos: `pergunta` (texto, persona, status: validada/entregue/descartada/estudada) e `diagnostico`
  (do Médico, com status/ação). Ao lado de lição, item, estudo, revisão, gate, incidente, episódio e PR.
- **Uma receita por agente** (`memoria.RECEITA`): a mesma memória, no recorte que serve a cada papel — `Memoria.para(agente,
  assunto)` para prompts de LLM e `Memoria.lembrancas(assunto)` (tipo, título, resultado, há quantos dias) para o estado
  que vai ao Jev. Vazio quando não há nada parecido: nunca inventa contexto.
- **Quem passou a consultar**: PO (cada candidata vai ao Jev com `memoria`: perguntas e itens parecidos e o que deu —
  pergunta já entregue/descartada não é pertinente), Questionador (lições reincidentes sem pergunta), Gerente de produto
  (pergunta → item e ao dividir: "se já foi feito ou contestado, proponha o próximo passo"), Prompts A/B, Médico (o Jev
  vê diagnósticos/incidentes/lições parecidos antes de decidir bloqueia/dono/remédio), Revisor (revisões e gates
  parecidos na evidência) e as missões (pesquisa com o que o time já viu daquele tipo de pedido).
- Painel, cartão Memória do time: quem consultou em 24 h e quantas consultas acharam lembrança.
- O PO já roda a cada giro em que há vaga de pergunta (5 min com fome, 30 min quando a última passagem não achou nada);
  não mudou — mudou o que ele sabe quando pergunta.

## 1.43.0 — 2026-10-20

**Todo consumo do loop pela API, e qualquer API de IA.**

- **Desenvolvedor pela API por padrão.** O Claude Code passa a receber a `ANTHROPIC_API_KEY` do loop em vez de depender do
  login da conta (sessão OAuth que expira sem ninguém para relogar — foi o que parou o Desenvolvedor por horas em 20/10).
  `CIRCULO_CODE_AGENT_USA_API=0` volta ao login da assinatura. Cada correção de código aparece no consumo por papel.
- **Provedor de IA plugável** (`circulo/llm.py`): `CIRCULO_LLM_PROVEDOR` escolhe quem atende a LLM dos agentes —
  `anthropic` (padrão, SDK, com busca na web) ou, no contrato OpenAI e só com a biblioteca padrão, `openai`, `gemini`,
  `groq`, `mistral`, `deepseek`, `xai`, `openrouter`, `together`, `ollama` (local, sem chave) e `compat`
  (`CIRCULO_LLM_BASE_URL` para qualquer outro, ex.: LM Studio, vLLM). Chave em `CIRCULO_LLM_API_KEY` ou na variável
  própria do provedor. O harness continua pedindo por porte (pequena/grande) e o cliente traduz para o modelo do
  provedor (`CIRCULO_LLM_MODELO_PEQUENA/GRANDE` sobrescrevem o padrão da tabela — confira os nomes no seu provedor).
  Uso medido do mesmo jeito (entrada, saída, cache); sem busca na web fora da Anthropic, e o painel diz isso.
- Diagnóstico (`circulo diagnostico`), Integrações (chaves novas no cofre) e a faixa de conexões mostram o provedor em uso.

## 1.42.0 — 2026-10-20

**Conexões ao vivo na Gestão do loop.** Uma faixa logo abaixo do cabeçalho mostra, em tempo real (3 s), se cada
dependência externa está respondendo: **Jev** (decisões), **Claude Code** (Desenvolvedor), **LLM** (API da Anthropic),
**GitHub** (PRs e CI) e o próprio **Loop** (batimento). Por serviço: estado (respondendo / instável / fora / parado /
no limite / sem chamada / sem chave), latência mediana da última hora, última resposta, último erro com hora, contagem
de ok e falhas em 1 h e uma linha do tempo dos últimos 24 pulsos (altura = latência, vermelho = falha). A bolinha pisca
quando o serviço acabou de responder; vermelha pulsando quando caiu.

- **`circulo/conexoes.py`**: tabela `conexoes` de pulsos (serviço, ok, ms, erro, hora; 7 dias). O Jev grava um pulso a
  cada `ask_many` real (o decisor local não conta); o GitHub avisa por um `ouvinte` no `GitHubREST` que o SRE liga ao
  subir (a constituição não importa nada novo); LLM e Claude Code vêm de `llm_calls`; o Loop, do batimento.
- Claude Code mostra a espera do Desenvolvedor como está ("parado: deslogado · tenta de novo às 18:07" ou "no limite").
- `GET /api/conexoes`. Olhar a faixa nunca chama ninguém: só lê o que as chamadas reais deixaram.

## 1.41.1 — 2026-10-20

- Painel: aba fechada pelo navegador no meio de um `/api/...` gerava `BrokenPipeError` com traceback no `loop.err`; agora é ignorado (outros erros do servidor continuam no log).

## 1.41.0 — 2026-10-20

**O Médico do loop: plano de controle que diagnostica gargalos por padrão medido e responde pela escada mais barata —
desenhado para não virar ruído.** Motivação: em 20/10 o treino do aluno quebrou 8× seguidas (quarentena isolou, ninguém
corrigiu), o Redator abriu 4 PRs em cadeia (para o loop, sucesso) e o Desenvolvedor ficou 30 min mudo (OAuth expirado)
antes de alguém avisar. Quem achou os três foi uma pessoa lendo o banco.

- **`circulo/medico.py`**, rodando na thread do SRE (em paralelo ao giro), uma passagem por minuto.
- **Uma fonte só**: `incidents`/`run_errors`, `prs`, `alerts`, `llm_calls`. Três sondas de **padrão**: erro repetido
  (mesma impressão digital ≥ 3× em 1 h), repetição sem progresso (PRs da mesma origem ou o mesmo item tentado ≥ 3×
  em 1 h), agente mudo (Desenvolvedor com erro, 0 tokens e < 2 s, ≥ 3×). Evento isolado não é nada.
- **Impressão digital**: um diagnóstico por causa; aberto, só conta `vezes`. Fecha pelo **sintoma** (30 min sem
  ocorrência); se volta, reabre com reincidência.
- **O Jev decide** com a evidência medida: bloqueia o progresso? (noul) · de quem é a causa? (choice: código do
  loop / ambiente / humano / custo) · resposta segura? (score observar/conter/corrigir). Dúvida → observa.
- **Escada**: observar → **conter** (determinístico, custo zero: pausa a tarefa que repete por 6 h; põe o
  Desenvolvedor mudo em espera e avisa) → **corrigir** (item `origem='erro'`, "Urgente: …", na frente da fila, com o
  trace; o Desenvolvedor pega antes de tudo; dispensado de estudo) → **escalar** (Precisa de você, prioridade 0).
- **Orçamento**: 6 ações por dia (depois só escala) e 1 item urgente em voo. **Autoexclusão**: o que é sobre o
  Médico, o SRE ou a constituição escala direto. **Contexto conhecido** (Desenvolvedor deslogado, loop pausado por
  você, orçamento no limite) silencia as sondas de fila parada — a causa já está em Precisa de você.
- **Medido**: `/api/medico` e card "Médico do loop" na aba Saúde e estado: abertos, fechados, reaberturas, ações do
  dia, precisão das correções (itens urgentes feitos ÷ abertos), mediana até conter. O canal `#equipe` mostra cada
  diagnóstico e ação.
- Não entrou (de propósito): um segundo Desenvolvedor em thread. O item urgente passa à frente da fila; dois
  Desenvolvedores disputando o mesmo Claude Code e o mesmo estado de worktree é risco maior que o ganho hoje.
- Testes (`test_medico`, 8): os três casos do Mac, um diagnóstico por padrão, item urgente na frente da fila e um só
  em voo, conter pausando a tarefa, escalada em Precisa de você, regras contra ruído (dúvida/custo/próprio/contexto),
  orçamento de ações e fechamento pelo sintoma, SRE roda o Médico e o painel expõe.

## 1.40.2 — 2026-10-20

**Dois defeitos que o loop real expôs em 3 h de 1.40.x, corrigidos com teste:**

- **Treino do aluno quebrava** (8 erros seguidos na etapa meta no Mac): o estado gravado com a decisão era o JSON
  cortado em 1.500 caracteres — inválido — e `json.loads` derrubava o treino inteiro. Agora o estado é compactado
  antes de virar JSON (`aluno.compactar`: textos encurtados, listas e dicionários cortados, chaves maiores removidas
  até caber) e o treino ignora registros antigos cortados em vez de parar.
- **O Redator técnico abria PR atrás de PR** (#34, #35, #36, #37): a própria doc mergeada contava como "entrega
  nova". PRs de `circulo/docs-*` deixam de contar; só entrega do loop (ou 24 h) dispara nova doc.

## 1.40.1 — 2026-10-20

**Diagnóstico do "travado na 1.32.1" (medido no Mac às 14:17):** o loop não estava travado nem na 1.32.1 — rodava a
1.39.0 (reiniciou às 14:04 depois de puxar o `abcad8d`, 5 giros de prova ok). Dois problemas reais por trás da impressão:

- **A versão do painel era fixa.** `circulo/__init__.py` tinha `__version__ = "1.32.1"` escrito à mão e o painel
  mostrava isso. Agora `__version__` é lida do `pyproject.toml` (fonte única); teste garante que as duas batem.
- **O Desenvolvedor estava deslogado do Claude Code.** O agente respondia em 26 ms "Failed to authenticate: OAuth
  session expired and could not be refreshed"; o loop tentava o mesmo item a cada giro (9 vezes em 15 min, lição
  #42 subindo de camada) sem sair do lugar e sem avisar você. Agora essa resposta é tratada como o limite da conta:
  o Desenvolvedor espera 30 min antes de tentar de novo, o SRE mostra a trava, e **"Precisa de você" abre no topo**:
  "Desenvolvedor parado: Claude Code deslogado no Mac — abra o Terminal, rode `claude` e faça login".

## 1.40.0 — 2026-10-20

**O Redator técnico: documentação profissional do loop, gerada da autoevolução e publicada por PR.**

- **`circulo/documentador.py`** — agente novo (`documentar`, "Redator técnico") que gera `docs/` a partir de fontes
  medidas: docstrings dos módulos (ast), perguntas ao Jev lidas do código (`jev_cobertura`), telas e APIs do mapa de
  verificação, nomes e papéis dos agentes, tarefas do giro (lidas do fonte de `loop.py`), PRs mergeados com a
  linhagem pergunta → item → PR, lições e o CHANGELOG. Sem LLM: texto derivado de dado é fiel e custa zero.
- **O Jev classifica cada entrega** do loop (choice: funcionalidade, correção, velocidade, observabilidade, segurança,
  documentação) e diz se ela muda o que o humano vê (noul) — uma vez por PR, em lote, com cache em kv.
- **Documentos**: `docs/README.md` (índice), `agentes.md`, `arquitetura.md` (constituição, módulos, telas, APIs),
  `decisoes.md` (catálogo Jev First), `evolucao.md` (versões + entregas do loop por tipo), `licoes.md`.
- **Publicação segura**: branch `circulo/docs-<momento>` a partir de `origin/main`, commit como Círculo, PR aberto
  pela API; o **gate aceita PR de documentação só se todos os arquivos estão em `docs/`** e o CI está verde (sem o
  teto de 800 linhas, sem exigir teste), e recusa como fora do alcance se tocar código. Sem GitHub, escreve no clone.
- **Quando roda**: tarefa ociosa de custo zero, quando há PR do loop mergeado desde a última doc, ou a cada 24 h;
  um PR de docs por vez (a tabela `prs` diz quando o gate fechou o anterior). Aparece no canal `#equipe`.
- Primeira versão de `docs/` já no repo (gerada agora; a próxima vem do Mac, com as entregas reais).
- Arquitetura preservada: o gate não importa o Redator, o Redator não importa o loop; `loop.py` em 900 linhas.
- Testes (`test_documentador`, 4): gera do código/banco/CHANGELOG com o Jev classificando uma vez; roda quando há
  entrega nova e publica no local sem GitHub; gate aceita só docs/ e recusa código; PR de docs fechado libera o próximo.

## 1.39.0 — 2026-10-20

**Sistema de design: o Círculo sobre o Primer (GitHub).** Escolha: entre os sistemas prontos que funcionam sem build
(Primer, Tabler, Shoelace, Radix/Open Props, Pico), o Primer é o que fala a língua do loop (PRs, merges, CI) e tem
tema escuro oficial. Adotados os **primitives** (cores, tipografia, raio, sombra, formas de botão e Label) em cima da
infraestrutura que já existia — `tema.py` escreve o mesmo bloco em toda página e o teste confere os contrastes — sem
carregar a folha de estilo inteira (evita choque de classes e mantém as telas offline).

- **Tokens** = Primer light/dark: canvas `#f6f8fa`/`#0d1117`, superfície `#ffffff`/`#151b23`, texto `#1f2328`/`#f0f6fc`,
  done (decisões/Jev) `#8250df`/`#ab7df8`, attention `#9a6700`/`#d29922`, success `#1a7f37`/`#3fb950`, danger
  `#d1242f`/`#f85149`, accent (links/foco) `#0969da`/`#1f6feb`, e dois novos: `--primary` (botão primário verde
  `#1f883d`/`#238636`) e `--on-primary`. Todos os pares de contraste (4,5:1 texto, 3:1 marcas) continuam cumpridos
  nos dois temas; bordas de componente usam o cinza de texto secundário do Primer (3:1+), não a borda clara dele.
- **Tipografia de sistema** (a pilha do Primer, 14 px), sem Google Fonts: as telas abrem offline. Raio 6 px em
  botões/abas/campos e 12 px em cartões; Labels em pílula com borda `currentColor`; botão padrão com fundo
  `canvas` e sombra de 1 px; foco com anel de 2 px em `accent`.
- **Parar o loop** vira botão de perigo (vermelho no hover); **Retomar** é o primário verde — irreversível é vermelho.
- **Design System "Círculo" publicado** no seu artefato do Claude: README (princípios, cores, tipografia, componentes,
  o que não fazer), `tokens.json` com os dois temas, componentes com preview (Botão, Rótulo, Selo, Cartão) e a capa.
  `circulo/DESIGN.md` é a cópia no repo; o prompt do Desenvolvedor manda seguir esse arquivo quando o item toca uma
  tela e rodar `python -m circulo.tema` antes de terminar.
- Teste novo em `test_tema`: tokens do Primer, nenhuma fonte externa, raio nos tokens, DESIGN.md citado no Desenvolvedor.

## 1.38.0 — 2026-10-20

**Precisa de você, dúvidas do Jev estudadas, e o Jev usado até o fim da doc.**

- **Precisa de você** (`/aprovacoes`, no menu de toda tela, com selo de contagem — vermelho quando há algo urgente):
  tudo o que, no loop inteiro, espera uma decisão humana, com a ação do lado. Fontes: loop pausado por você
  (retomar), orçamento esgotado no modo com limite (mudar para sem limite), itens que "dependem de você" (tirar da
  fila), itens contestados pelo estudo (executar mesmo assim / deixar de lado), etapas em quarentena, travas do SRE
  com gravidade ≥ 0,7 abertas há mais de 6 h, lançamentos de finanças esperando revisão (está certo), avisos não
  lidos (visto) e peças de configuração paradas (com o como-ligar). Cada ação passa pelo mesmo caminho do botão que
  já existia e fica registrada como alerta de controle. `GET /api/aprovacoes` (`?so=n` só a contagem) e
  `POST /api/aprovacoes/acao`.
- **Dúvidas do Jev vão para o Arquiteto** (`circulo/duvidas.py`): a pergunta que o Jev não soube classificar
  (status "inconclusa") não espera mais 6 h para voltar igual. Uma por passagem do Product owner, a mais antiga é
  estudada em modo leve (1 busca, ~9 mil tokens, pelo porteiro do gasto; a memória do time entra de graça): fatos com
  base medido/inferido, parecer sobre pertinência, eixo e ação, e a pergunta reescrita se a dúvida vinha de vagueza.
  Com a evidência nova, o Jev classifica de novo na hora. Se continuar em dúvida, descarta com o motivo: dúvida não
  gira. A original fecha como "estudada"; a nova carrega `apos_estudo` e de onde veio. O canal `#equipe` mostra o
  Arquiteto avisando o Product owner; o card do Product owner mostra quantas dúvidas foram estudadas e quantas
  viraram válidas.
- **Jev — o que a doc ainda oferecia** (docs.typesafe.ai, set/2026): o loop já usava os três tipos, critérios,
  várias perguntas por chamada, inglês, probabilidades/legenda e o registro da versão. Faltava **fixar a versão**:
  agora o loop sobe com a versão exata que o Jev respondeu da última vez (kv `jev_modelo`), para os limiares
  calibrados não derivarem com o alias `jev-latest`; `JEV_MODEL` explícito continua valendo mais. Se a versão fixa
  sair da API (400/404), o cliente volta ao alias na mesma chamada e registra alerta. Também confirmado na doc:
  Noul não tem campo de confiança (o loop deriva de |2p−1|, como já fazia); estado irrelevante degrada a precisão
  (o `estado` gravado por decisão desde a 1.37.0 permite medir o tamanho por pergunta); limites 64 mil tokens por
  chamada e 1.200 chamadas/min, longe do uso atual.
- `loop.py` fica em 898 linhas (a dúvida é estudada dentro de `indagador.rodar`); `decision.py` em 1.000.
- Testes (`test_aprovacoes_duvidas`, 5): reúne tudo com ação e cada ação resolve; página, API e selo no menu;
  dúvida vai ao Arquiteto e volta ao Jev na hora; sem LLM fica marcada e não trava; pin automático da versão do Jev.

## 1.37.0 — 2026-10-20

**O aluno do Jev: aprendizado a partir das decisões, em sombra.** Onde o fine-tuning encaixa no loop é na camada de
decisão: um degrau novo na cascata (regra → **aluno** → Jev → LLM), com o Jev como professor e árbitro. Nesta versão
ele só palpita em paralelo e a concordância fica medida; nada é decidido por ele.

- **Estado gravado com cada decisão** (`decisions.estado`): o que o Jev viu agora fica junto com o que respondeu —
  é o dataset de destilação (1,8 mil decisões/dia no Mac).
- **`circulo/aluno.py`**: um modelo por pergunta (nome normalizado: `indaga_pert_5` → `indaga_pert`), regressão
  logística multiclasse sobre features em hash (categorias, números em faixas log e normalizados, palavras dos
  textos, listas e dicionários rasos), treinada por SGD em Python puro, sem dependência. Rótulo = resposta do Jev
  com confiança ≥ 0,8 (escolhas como estão; números em faixas de 0,1). Validação temporal: últimos 20 % como
  holdout, acurácia comparada com a classe majoritária. Critérios: ≥ 120 exemplos, acurácia ≥ 90 % e ≥ 3 pontos
  acima do baseline → "pronto para sombra"; em sombra, concordância ≥ 95 % em ≥ 300 palpites → "pronto para decidir".
- **Sombra na cascata**: a cada decisão final do Jev, `aluno.observar` palpita e grava em `aluno_sombra`
  (previsto, probabilidade, resposta do Jev, concorda). A decisão continua sendo do Jev.
- **Treino automático**: o Cientista de dados (`MetaLearner.step`) retreina a cada 6 h ou a cada 200 decisões novas
  do Jev, e registra no log do giro.
- **Painel**: card "Aluno do Jev" na aba Decisões (Jev First) com, por pergunta, exemplos, classes, acurácia vs
  maioria, concordância em sombra e o selo "pronta para decidir"; `/api/aluno`.
- Fora por desenho: perguntas por critério/trecho (`crit_`, `rel_`, `ach_`) e o Desenvolvedor/gate/constituição.
  Ligar o aluno como decisor será uma chave de política explícita, só para perguntas provadas, com rollback pelas
  versões de política — próxima versão, depois de dias de sombra medida.
- Testes (`test_aluno`, 5): features e rótulos estáveis; o aluno aprende uma regra escondida de um Jev sintético
  (categoria ≥ 95 %, worth_spending > baseline) e mede no holdout; poucos exemplos não viram modelo; retreino só
  quando precisa; em sombra palpita sem decidir e "pronto" exige prova; MetaLearner treina e o painel expõe.
  `decision.py` continua em 1.000 linhas (comentários encurtados para caber o gancho).

## 1.36.0 — 2026-10-20

**Varredura do dash: o que aparecia em duas telas agora aparece numa só.** Levantamento tela a tela (todas as abas
de Gestão do loop, Equipe ao vivo, Bastidores do giro, Rastros, Missões, Integrações) e remoção do que repetia:

- **Gestão do loop**
  - aba "Equipe ao vivo" (um iframe da própria tela Equipe ao vivo, que já está no menu do topo): removida;
  - "O círculo ao vivo" (anel com as mesmas etapas de "Etapas do ciclo" e o mesmo passo atual de "Agora"): removido,
    junto com a máquina de animação (cometa, raias no centro, faíscas) e seu CSS;
  - "Giros" em Mais detalhes (as Raias do giro em Bastidores mostram o mesmo, melhor): removido;
  - "Evolução" (linha do tempo = o canal #equipe) e "Evoluções" (= Versões da política): removidos;
  - "Saúde do loop" (medidores já cobertos por "Posso confiar": invariantes, correções, eficiência, erros, tokens):
    removido;
  - "Sinapses ao vivo" (feed de verificações = Lições → verificações + o canal): removido;
  - "Números da missão" (= KPIs): removido;
  - a aba "Mais detalhes" sobrou com dois cartões (Autonomia, Versões da política) e foi dissolvida em Segurança e
    confiança. De 6 abas para 4: Saúde e estado · Decisões (Jev First) · Autoevolução · Segurança e confiança;
  - cartões do loop inteiro (Revisor, Memória do time, Product owner, Consumo de tokens) deixam de aparecer nas
    páginas das outras missões, onde não têm contexto.
- **Bastidores do giro** (`/fluxo`): o anel animado com o cartão "Agora" e o diário, a grade "Agentes" e "O que cada
  agente construiu" repetiam a Equipe ao vivo e saíram; ficam as **Raias do giro** e o **Jev** (perguntas e
  laboratório), que só existem aqui. Título e texto refletem isso.
- `painel.html` de 1 466 para 1 176 linhas; `fluxo.html` de 511 para 278. O teste de higiene do tema (nenhum id
  procurado pelo script sem existir na página) continua valendo: o código morto saiu, não foi só escondido.
- Testes: `test_fluxo`/`test_tema`/`verificacao` atualizados para as telas novas.

## 1.35.0 — 2026-10-20

**Orçamento sem corte, medindo.** Medido no Mac: o loop bateu 393 mil de 400 mil tokens ontem e 383 mil às 9 h de
hoje — e ia pausar até a meia-noite no meio do trabalho. Decisão do Cássio: neste primeiro momento não limitar os
tokens da LLM, mas guardar as métricas para escolher o limite com dados.

- **Modo do orçamento** (kv `orcamento_modo`): `ilimitado` (padrão a partir desta versão) ou `limite`. No modo
  ilimitado `Budget.can_spend` é sempre verdadeiro, `exhausted` é falso, `left_ratio` é 1,0 e o loop nunca pausa
  por orçamento; `charge` continua gravando cada token (tabela `budget` por dia; `llm_calls` por chamada e papel).
  No modo `limite` tudo funciona como antes (porteiro do gasto, pausa até a meia-noite, piso e teto).
- **`budget.consumo()` / `/api/consumo`**: tokens por dia (14 dias), por papel (chamadas, tokens, maior chamada,
  falhas), por hora do dia, mediana e máximo dos dias completos e uma **sugestão de limite** = p90 dos dias
  completos arredondado para cima em 50 mil (só com 3 dias completos; só dado, a escolha é sua).
- **Painel**: o KPI mostra "N mil tokens hoje · sem limite · medindo"; o formulário do orçamento ganhou o seletor
  "Sem limite (medindo) / Com limite diário"; card **Consumo de tokens** em Segurança e confiança com barras por
  dia, papéis e hora de pico. `POST /api/orcamento {"modo": ...}` muda o modo e registra alerta de controle.
- **SRE-Vigia**: no modo ilimitado a sonda "orçamento não paga o próximo estudo" fica muda; entra `consumo_alto`,
  informativa (gravidade 0,4), quando o dia passa de 2× a mediana medida e de 200 mil tokens.
- Convive com o PR #27 do próprio loop (padrão de 1 M/dia por `CIRCULO_TOKENS_DIA`, avisos em 50/80/100 % e uso
  por entrada/saída/cache e por job em `llm_calls`): o padrão de 1 M vale quando o modo é `limite`; no ilimitado os
  avisos de marco ficam mudos e a medição por job alimenta o consumo.
- Testes: 5 novos em `test_orcamento` (padrão ilimitado não corta e segue medindo; `consumo` e p90; Vigia só avisa;
  painel muda o modo e expõe o consumo; marcos mudos); os 9 testes que provam o corte passam a ligar o modo `limite`.

## 1.34.0 — 2026-10-19

**Memória do time: RAG dentro do loop.** Medido no código: todo agente montava o prompt com SQL fixo. O Desenvolvedor
recebia as mesmas 15 lições globais em qualquer tarefa (ordenadas por reincidência, não por parecença); o Arquiteto
estudava do zero um assunto já estudado (28–40 mil tokens cada); o Gerente de produto só barrava título idêntico;
nada do que o Desenvolvedor aprendia ao fechar um PR voltava para a próxima tarefa.

- **`circulo/memoria.py`** — índice de texto com o FTS5 do próprio SQLite (sem dependência; sem FTS5 cai para um
  BM25 em Python) sobre lições, itens feitos/contestados, estudos, revisões, recusas do gate, incidentes, PRs e
  **episódios** do Desenvolvedor. Reindexação incremental por `updated_at` (no máximo a cada 60 s).
- **Recuperação por relevância** (`buscar`): BM25 × peso do resultado (lição reincidente pesa mais; item contestado
  pesa menos) × recência (meia-vida de 90 dias). `contexto()` monta um bloco *just-in-time* de até 1.600 caracteres
  com o resultado de cada lembrança, exclui a própria tarefa e registra cada uso em `memoria_uso`.
- **Desenvolvedor**: recebe o que já aconteceu de parecido com *esta* tarefa (lições, episódios, revisões, gates) e só
  5 lições globais; cada PR mergeado, fechado ou abandonado vira episódio (arquivos, consertos, última revisão).
- **Arquiteto**: assunto já estudado há menos de 30 dias com título ≥ 60 % parecido → **reaproveita o estudo (0
  tokens)**, registra de onde veio e quanto poupou; senão, o prompt leva o que o time já sabe do assunto, para as
  buscas focarem no que falta.
- **Gerente de produto**: item com a mesma ideia em outras palavras (≥ 70 % dos termos) não é aberto; a pergunta
  fica ligada ao item que já existe.
- **Telas**: card "Memória do time" na aba Autoevolução (`/api/memoria`: lembranças por tipo, consultas, reaproveitamentos
  e tokens poupados em 24 h, últimas consultas); no canal `#equipe` cada agente diz o que lembrou antes de começar e
  quando reaproveitou um estudo.
- Decidido **não** fazer agora: cache de chamadas idênticas de LLM (quase nenhum prompt se repete à letra; o ganho
  real é o reaproveitamento de estudo) e embeddings (FTS5 cobre o volume atual sem rede nem dependência).
- Testes: `test_memoria` (7: termos/parecença, índice com e sem FTS5, estudo e item parecidos, Arquiteto reaproveita
  sem gastar, Desenvolvedor recebe memória e grava episódio, canal mostra o que lembrou, Gerente de produto não
  duplica); `test_fatiador` passa a separar a tarefa do bloco de memória.

## 1.33.0 — 2026-10-19

**A equipe ao vivo virou um canal de chat; o quadro anda em tempo real; a gestão do loop ocupa a tela toda; e os
agentes têm nome de gente de time em todas as telas.**

- **Equipe ao vivo como canal (`#equipe`)**: cada agente é um integrante com avatar, nome e cargo; mensagens seguidas
  do mesmo integrante se agrupam; pergunta ao Jev e resposta aparecem como "em resposta a…"; etiquetas de tom (tarefa,
  entrega, devolução, alerta); "fulano está trabalhando…" enquanto o giro roda; separador por dia; botão "N novas
  mensagens" quando você não está no fim; filtro "só o que importa" esconde o rotineiro sem deixar cabeçalhos vazios.
- **Quadro em tempo real**: toda mensagem que fala de um item traz a coluna em que ele fica agora (`coluna`); o
  cartão muda de coluna no instante em que a mensagem chega, com o avatar de quem o moveu "carregando" o cartão
  (voa do integrante até o cartão, que desliza para a coluna nova e fica destacado). A cada 4 s o quadro se confere
  com o banco; colunas mostram até 8 cartões e "+ N na fila". A reprise inicial não anima: o quadro vem do retrato.
- **Fonte única de nomes (`circulo/nomes.py`)**: Tech lead (Orquestrador), Jev (head de engenharia), Product owner
  (Indagador), Gerente de produto (Planejador), Arquiteto (Estudo), Desenvolvedor (Developer), Revisor de código,
  QA e release (Gate), DevOps (Corpo), SRE (Vigia), Curador de lições, Monitor de saúde, Cientista de dados
  (Meta-Learner), Simulação (Shadow), Gerente de missões, Operações… Etapas (`camadas`), raias (`fluxo`), equipe,
  painel, integrações e confiança usam o mesmo nome; o nome antigo fica em `antes` (tooltip). Agente que nascer da
  autoevolução entra com o próprio nome.
- **Gestão do loop em tela cheia e responsiva**: sem a caixa de 1240 px; em monitores largos (≥ 1440 px) "Saúde e
  estado" e o SRE ficam lado a lado; a aba Equipe ao vivo usa a altura da janela; no celular os botões do cabeçalho
  ocupam a linha inteira, os KPIs viram duas colunas e o menu do topo rola na horizontal em vez de quebrar em três.
- Testes: `test_nomes` (todas as telas com o mesmo nome), `test_equipe` (mensagens de item carregam `coluna`; página
  com canal, integrantes, colunas e `moverCard`), mapa de verificação atualizado.

## 1.32.1 — 2026-10-19

**O loop parou às 22 h porque o orçamento do dia acabou — quase todo em estudos com busca na web.** Medido no Mac:
392 mil dos 400 mil tokens do dia gastos; 11 estudos a 28–40 mil cada (o porteiro achava que custavam 9 mil); três
itens esperando estudo, Developer parado, e ninguém dizendo o porquê (o Vigia apontava "fila cheia").

- **Estudo proporcional à evidência**: item do loop nascido de medida interna (Vigia, jardineiro, lição) é
  **dispensado** (0 tokens: a evidência já é medida); item do loop nascido de pergunta do conselho tem estudo **leve**
  (1 busca, ~9 mil); pedido seu tem estudo **completo** (4 buscas). O modo fica registrado no estudo e na chamada.
- **Custo honesto no porteiro**: o Jev e o orçamento decidem com a mediana medida dos últimos estudos do mesmo modo,
  não com uma constante. Estudo dispensado não passa pelo porteiro (não há gasto a decidir).
- **Limite duro respeitado**: a roteirização por confiança (1.31.1) nunca autoriza gasto que o orçamento não cobre.
- **Vigia `orcamento_curto`**: há item esperando estudo e o que sobra do dia não paga o estudo dele → trava com os
  números (limite, usado, resta, custo) e a sugestão (subir o limite no painel ou esperar a meia-noite).

## 1.32.0 — 2026-10-19

**Círculo perfeito: a fábrica (`fabrica/`), reconstruída do básico.** Um pacote novo e independente no mesmo repo
(o `circulo/` continua rodando no Mac), feito a partir das ideias da Lauren Tan (@poteto): confiança antes de
paralelismo, corrigir na camada mais forte, verificar rodando o software, separar julgamento de trabalho mecânico,
transformar operação resolvida em ferramenta, parar antes do irreversível.

- **Seis estações de uma fábrica de software**: Gerente de produto → Arquiteto → Desenvolvedor → QA → Revisor →
  Release, e o círculo fecha: achados viram o próximo cartão quando a fila esvazia. Um cartão por vez.
- **Evidência rotulada** (`medido` / `inferido` / `chutado`); só a medida avança o cartão. O QA copia os testes novos
  para a base e exige que falhem lá e passem na branch; o Revisor mede tamanho, protegidos e padrões proibidos; o
  Release abre PR, espera CI, mescla e só implanta com permissão. Três devoluções seguidas = bloqueado, para o humano.
- **Painel à mão livre** (`python -m fabrica demo`): as estações num círculo desenhado em SVG próprio (sem biblioteca,
  offline), a nota amarela do cartão viajando, balões com a mensagem real, quadro de achados em post-its, diário, fila,
  e um campo para pedir. Fonte manuscrita com fallback do sistema.
- CLI: `iniciar`, `pedir`, `rodar [--painel]`, `painel`, `achados`, `demo`. Executor: Claude Code se existir; senão
  simulado. GitHub por REST (`repo_github` + `GITHUB_TOKEN`); sem remoto, mescla local.
- Testes em `tests/test_fabrica.py`: o círculo completo num repositório de exemplo, devolução até bloquear, caminho
  protegido, CI vermelho, achado virando cartão, painel e a demonstração.

## 1.31.1 — 2026-10-19

**O loop parou de evoluir por 4 h: o Jev recusava o estudo com confiança média.** Medido no Mac (17:24 → 21:30): dois
itens planejados esperando estudo, Developer parado, e o porteiro do gasto respondendo p≈0,3 com confiança 0,3–0,4 ao
"vale gastar ~30 mil tokens no estudo?", a cada giro. O Jev dizia "não" sem evidência do que o estudo destravava, e o
loop obedecia para sempre.

- **Evidência para o porteiro do estudo**: o item esperando, a origem, quantos esperam, a fila do Developer e
  `desbloqueia_fila` (o estudo é o que separa o loop do trabalho); valor 0,95 quando o Developer está parado. O critério
  do Jev (PT e EN do laboratório) e a regra passam a cobrir "item esperando estudo", como já cobriam a pergunta validada.
- **Roteirização por confiança no porteiro**: um "não" do Jev com confiança abaixo de 0,5 numa tarefa que destrava a
  fila não age — a regra determinística decide, e a resposta do Jev fica registrada para o aprendiz. "Não" com
  confiança alta continua barrando.

## 1.31.0 — 2026-10-19

**Equipe ao vivo: os agentes como um time de engenharia, conversando e entregando em tempo real.** E um menu único no
alto de todas as telas, com nomes que dizem o que cada tela é.

- **Tela nova `/equipe`** (`equipe.py` + `equipe.html`): a sala com cada integrante e seu cargo (Indagador = product
  owner, Jev = decisor, Planejador = gerente de produto, Estudo = arquiteto, Developer, Revisor, Gate = QA/release,
  Corpo = DevOps, Vigia = SRE, Curador = qualidade, Aprendiz, Rotinas, LLM e GitHub como parceiros), quem está com a
  bola (cartão pulsando), a carga de cada um (perguntas válidas, itens prontos, PRs nas vagas, travas, lições) e o
  balão com a mensagem que acabou de chegar.
- **Conversa da equipe**: cada mensagem nasce de um registro real (perguntas, roteiro, PRs, gate, revisões, Vigia,
  lições, alertas) e tem tom: pergunta, resposta, tarefa, entrega, devolução, alerta, status. A mensagem voa do remetente
  ao destinatário (forma por tom, igual à legenda) e fica no registro à direita. "Só o que importa" esconde o rotineiro;
  "tudo" mostra cada pergunta ao Jev e chamada de LLM. Velocidade tempo real / 3× / pausar.
- **Quadro de entregas**: Perguntas válidas → Planejado → Estudado, pronto → Em desenvolvimento → Em revisão/CI →
  Em produção (24 h) → Devolvidos/esperando, com o dono de cada cartão; o cartão anima de uma coluna à outra quando o
  estado muda.
- **Menu de cima em todas as telas** (gerado por `tema.py`): Missões · Equipe ao vivo · Gestão do loop (`/loop`) ·
  Bastidores do giro · Rastros e SLOs · Integrações. Abas da gestão do loop renomeadas: Saúde e estado, Equipe ao
  vivo (embutida), Decisões (Jev First), Autoevolução, Segurança e confiança, Mais detalhes.
- O SSE do fluxo passa a levar também as mensagens da equipe (`event: mensagem`), com `?minutos=` para abrir já com a
  conversa recente; `/api/equipe` dá o retrato (membros, carga, quadro).
- Decisões de desenho (críticas): sem escritório em pixel art nem framework CSS externo — o painel roda offline em
  Python puro, e o que diferencia esta tela é que cada balão cita um dado medido (confiança do Jev, motivo do gate,
  arquivo que cruzou), não uma animação. Um só agente trabalha por vez no giro (desenho do loop); a tela diz isso.

## 1.30.0 — 2026-10-19

**O Indagador vira um dos agentes mais atuantes.** Medido no Mac (3 h, 62 giros): rodou 3 vezes, 0,0 min — embora TODOS
os itens do loop do dia tenham nascido de uma pergunta dele. Dois motivos: era manutenção em rodízio com outras 8
tarefas, e as perguntas do conselho têm chave fixa (uma vez julgadas, somem por 3 dias), então ele ficava sem o que
perguntar.

- **Perguntas por assunto, com evidência medida** (`candidatas_especialista`): cada lição que repete ou reincide, cada
  trava aberta do Vigia, cada pergunta em que o Jev duvida (≥30% pela regra ou confiança <0,3 em 24 h), cada neurônio
  barrado ≥3 vezes, cada PR fechado sem merge, cada arquivo que cruzou PRs paralelos, cada item 3× mais lento que a
  mediana e cada missão ativa sem régua vira uma pergunta própria. Assunto novo = pergunta nova; nada de LLM.
- **Ritmo**: indagar passa a ser trabalho real do giro (roda assim que precisa, não no rodízio). Com vaga na fila de
  válidas volta em 5 min; com a fila cheia (agora 5 perguntas) em 1 h; sem candidata nova, em 30 min. Cada passagem
  custa uma chamada ao Jev.
- Ordem das candidatas: funil da autoevolução → especialista (por relevância) → conselho; o que já foi julgado não volta.

## 1.29.0 — 2026-10-19

**Vários PRs do Developer em paralelo, com o Revisor validando cada um dentro do ecossistema.** (Mudança na constituição
pedida por você.) Até aqui um PR por vez: medido no Mac, cada item esperava 60 a 90 min pela vaga enquanto um PR
emperrava no CI. Agora o Developer abre até 3 PRs ao mesmo tempo e um agente novo garante que a paralelização não traz
conflito nem quebra.

- **Revisor** (`revisor.py`, agente novo, Jev First): antes de empurrar cada PR, no worktree, traz a main de agora para a
  branch (conflito = rejeita), roda lint e testes de novo sobre ela (quebra = rejeita), compara os arquivos mudados com
  os dos outros PRs abertos (arquivo compartilhado = rejeita; o mais antigo tem prioridade) e simula o merge com cada
  branch aberta (`git merge-tree`). No gate, confere de novo o cruzamento com PRs mais antigos. O Jev classifica cada
  revisão (`revisor_seguro`) com a evidência medida e decide o risco residual quando nada foi medido.
- **Rejeitado = volta para a fila**: o PR não abre (ou é fechado, a branch fica) e o item volta a 'pendente' com o
  motivo; se cruza com um PR aberto, só volta à fila do Developer depois que aquele PR fechar, e é refeito sobre a main
  nova. Nada de conserto por cima de conflito.
- **Estado por PR** na tabela `prs` (item, arquivos, conserto, consertos): o conserto de um PR reprovado no CI não
  bloqueia os outros; o gate libera cada vaga ao mesclar. `self_dev_aberto` vira retrato (último PR + vagas) para
  painel, Vigia e fluxo. Tabela `revisoes` guarda cada revisão.
- Painel: card "Revisor: vários PRs em paralelo" (vagas em uso, PRs abertos com seus arquivos, últimas revisões) e
  `/api/revisor`; o Revisor entra no fluxo ao vivo e nas obras.

## 1.28.0 — 2026-10-19

**O loop não dorme 5 min com trabalho a caminho.** Varredura medida no Mac (3 h, 62 giros, 6 PRs mesclados): 121 dos
180 minutos eram "descanso" longo — o PR estava no CI, ou o Developer/gate esperava os 2 giros de espaçamento, e nada
disso contava como "trabalho pendente", então o loop dormia 5 min por giro. O Developer trabalhou 39 min; estudo,
planejador e Indagador somaram menos de 4.

- **Ritmo em três níveis** (`loop.ritmo`): rápido (15 s) com trabalho pronto; **em voo (45 s)** quando há PR aberto
  esperando CI/gate, tarefa com trabalho dentro do espaçamento ou corpo validando código novo; ocioso (5 min) só sem
  nada a caminho. O espaçamento de 2 giros do gate e do Developer passa de ~10 min para ~1,5 min.
- O modo atual fica em kv `ritmo` (rápido / em voo / ocioso) para o painel e o relatório.

## 1.27.0 — 2026-10-19

**O Indagador vira especialista no próprio funil, e um 502 do GitHub não trava mais a evolução.** Medido no Mac à tarde:
com a 1.26.0 o ritmo subiu (3 PRs mesclados em 40 min), e então o planejador parou de novo por "lição estrutural
aberta" — um `HTTP Error 502: Bad Gateway` do GitHub em `revisar_prs` classificado como erro do loop, que abriu item
para o Developer "consertar" e criou portão. Em paralelo, o Indagador rejulgava a mesma pergunta a cada passagem
(3 vezes em 14 h, mesmo veredito) e não olhava para a etapa mais lenta da evolução.

- **Erro de ambiente é ambiente**: `HTTP Error 5xx`, `Bad Gateway`, `Service Unavailable`, `Gateway Timeout` entram na
  regra; lição aberta como estrutural com esse texto é reclassificada na hora, o item que ela abriu é descartado e o
  planejador não espera por ela.
- **Funil da autoevolução medido** (`indagador.funil`): minutos da pergunta validada ao item, do item ao PR e do PR ao
  merge (mediana, pior, alvo), PRs mesclados vs fechados e o motivo atual de o planejador não planejar. A etapa mais
  atrasada vira a PRIMEIRA pergunta do loop, com a evidência medida; aparece no card do Indagador e em `/api/indagador`.
- **Indagador não repete**: chave descartada ou entregue não volta por 3 dias; inconclusa volta só depois de 6 h e no
  máximo 2 vezes — cada passagem classifica perguntas novas, não as mesmas.

## 1.26.0 — 2026-10-19

**Velocidade e continuidade da autoevolução.** Medido no Mac: depois do PR #16 (01:12) o loop ficou ~10 h sem item novo,
com 3 perguntas validadas pelo Jev esperando e o Developer parado. A causa era o teto fixo de 6 itens por dia do
planejador (atingido à 01:31); o Vigia via a trava, mas já a dava por tratada e não agiu de novo em 777 passagens.

- **Planejador sem teto que trava**: até 24 itens em 24 h enquanto os PRs passam; volta a 6 só quando a maioria dos
  últimos PRs fecha sem merge (velocidade sem qualidade vira retrabalho). Com a fila vazia replaneja em 2 min (antes
  30); com um item na fila, em 15 min.
- **Motivo medido**: cada decisão de não planejar grava o porquê (`planejador_gate`: fila cheia, Claude Code no limite,
  lição estrutural, intervalo, teto). O Vigia cita essa causa na trava "pergunta validada parada", em vez de adivinhar.
- **Vigia não fica mudo**: trava que continua aberta 2 h depois da ação, sem item em andamento, gera nova ação com a
  evidência atual.
- **Indagador não seca**: sem nenhuma pergunta válida esperando, volta a indagar em 30 min (antes, só a cada 6 h).
- Resposta "sem item novo" do planejador deixa de ser registrada como falha de JSON.

## 1.25.0 — 2026-10-18

**Cores, legendas e botões legíveis em todas as telas.** As cores estavam difíceis de ver: no modo claro o verde (3,96:1)
e o âmbar (3,45:1) de texto ficavam abaixo do mínimo, o cinza de "inativo" (1,9:1) sumia e a borda dos botões (1,3:1)
quase não aparecia.

- **Um tema só** (`tema.py`): os mesmos tokens nas cinco telas (painel, home, fluxo, rastros, integrações), nos dois
  modos. Texto e status ≥ 4,5:1; bordas, marcas e cores de legenda ≥ 3:1 (conferido por `tema.conferir()` e pelo teste).
  `python -m circulo.tema` reescreve as páginas e é idempotente.
- **Botões**: borda visível, hover, pressionado, desativado tracejado, botão principal com a cor de destaque, abas e
  seletores com o estado ativo em tinta cheia, campos com borda e foco de 3 px (anel visível no teclado).
- **Cor nunca é a única pista**: chips ganham glifo (✓ ✕ ! ◆); a legenda do fluxo usa formas (círculo, losango,
  quadrado, triângulo, anel, tracejado) com texto em tinta, e a bolinha que viaja entre agentes usa a mesma forma da
  legenda (passagem ●, Jev ◆, LLM ■, falha ▲, regra decidiu ○).
- Cores fixas antigas do Vigia e das etapas do giro trocadas por tokens.

## 1.24.0 — 2026-10-18

**Vigia: o validador paralelo das travas da autoevolução.** Para você não precisar perguntar no chat se o loop está
evoluindo.

- **Thread própria** (`vigia.py`, a cada 60 s, independente do giro; pega inclusive giro travado). Para junto com o loop.
- **13 sondas** com evidência medida (SQL, sem LLM): pergunta validada parada, porteiro recusando a mesma tarefa 3+
  vezes, Developer parado com item pronto, fila seca, PR preso, corpo atrás do GitHub / validação longa, lição de
  estrutura bloqueando há horas, Jev em dúvida crônica numa pergunta, estagnação, missão sem ciclo, Claude Code no
  limite, giro travado numa etapa, orçamento esgotado.
- **Jev First**: cada achado novo vai ao Jev na mesma chamada: `vigia_trava` (sim/não, os dois lados descritos) e
  `vigia_acao` (abrir item · alertar · observar, com a situação de cada um). Roteamento por confiança: alta → faz o que
  o Jev escolheu; média → no máximo alerta; baixa/regra → observa e pergunta de novo. A heurística da regra mora no
  módulo do agente.
- **Age sozinho**: abre item no roteiro (origem loop, evidência e sugestão; segue estudo → Developer → portões), alerta
  na linha do tempo, ou registra. Sem duplicar: trava aberta não é realertada; quando a sonda para de disparar, marca
  resolvida e avisa quanto tempo durou.
- Painel: card "Vigia da autoevolução" no topo da Visão geral (estado, travas abertas com veredito, confiança, ação,
  desde quando, sugestão; resolvidas recentes); `GET /api/vigia`; o Vigia aparece no Fluxo e em "o que cada agente
  construiu". Tabela nova `vigia`.
- Testes: sondas só com evidência, classificação e ação por confiança, item único, dúvida observa, thread paralela,
  painel.

## 1.23.1 — 2026-10-18

- **Pergunta validada pelo Jev agora vira trabalho.** No Mac, 3 perguntas válidas do Indagador ficaram paradas: o
  planejador (quem as transforma em item) era escolhido, mas o porteiro do gasto o barrava (Jev 0,32–0,37 < 0,40)
  sem saber que havia pergunta validada esperando e o Developer sem fila. Agora o porteiro recebe `pergunta_validada`,
  `eixo`, `pertinencia` e `fila_do_developer`; o valor vem da pertinência que o próprio Jev deu; o critério do "sim"
  descreve essa situação (também na variante em inglês do laboratório); a regra local, quando decide, não trava o
  planejador nesse caso. `indagador.espiar` mostra a pergunta sem consumi-la.

## 1.23.0 — 2026-10-18

**Fluxo ao vivo no padrão do mercado (grafo + raias + obras) e a fila do Developer com folga.**

A validação nos dados do Mac (277 giros/24 h) mostrou a autoevolução funcionando de ponta a ponta (pergunta → item →
estudo → Developer → PR → gate → merge → corpo), mas com o pipeline em fila única: o planejador só planejava quando a
fila estava vazia, então a cada item o Developer esperava planejamento + estudo (~10 min).

- **Fila com folga** (`planejador.FOLGA = 2`): o planejador planeja enquanto há menos de 2 itens prontos ou a caminho,
  mesmo com o Developer ocupado; só não planeja com o Claude Code no limite ou com lição bloqueando.
- **Raias do giro** (`/api/fluxo/giro`, `fluxo.giro`/`giros_recentes`): uma raia por agente, intervalos em escala de
  tempo com as passagens de bastão, marcas das perguntas ao Jev (cinza quando a regra decidiu) e das chamadas de LLM,
  falhas em vermelho, giro em andamento tracejado; seletor dos giros recentes ou "ao vivo"; clique no trecho abre o
  detalhe. É o trio que Honeycomb (Agent Timeline), Langfuse (graph view) e LayerLens (AgentGraph) usam: grafo da
  topologia, swimlanes e detalhe por passo.
- **O que cada agente construiu** (`/api/fluxo/obras`): a última obra concreta de cada agente com link quando existe
  (PR, merge, item, estudo e veredito, versão rodando, pergunta do Indagador, lição, ciclo da missão, proposta).
- Indagador entra no círculo com o próprio ícone.
- Testes: raias (ordem, Jev no trecho certo, API, HTML), obras, fila com folga.

## 1.22.0 — 2026-10-18

**Indagador: o agente da autoevolução. As perguntas são o ponto de partida, e o Jev classifica cada uma.**

- **Novo agente `indagar`** (`indagador.py`), tarefa do giro como qualquer outra (aparece no Fluxo ao vivo). A cada
  passagem olha o contexto de uma missão (a do loop ou qualquer missão cadastrada, em rodízio pelo mais esquecido, no
  máximo a cada 6 h por missão) e levanta perguntas sem LLM, cada uma com evidência medida: critério mais fraco da
  régua, ciclos rejeitados seguidos (Goodhart), verificação da saída falhando, gasto desproporcional; para o loop,
  as candidatas do conselho de perspectivas.
- **O Jev classifica cada pergunta, na mesma chamada**: `pertinente` (sim/não, com os dois lados descritos), `eixo`
  (arquitetura · missão · operação · nenhum) e `acionável` (3 situações). Só a pertinente, com eixo e acionável vira
  **válida**; em dúvida do Jev (a regra decidiu) fica **inconclusa** e volta depois — inconclusivo não passa; a
  descartada fica registrada com a classificação completa.
- **Ponto de partida**: o planejador do loop parte da pergunta válida (antes de voltar ao conselho) e o ciclo de melhoria
  de cada missão parte da pergunta válida daquela missão (antes do modelo persona × critério).
- **Seus pedidos entram pela mesma porta**: continuam virando item do roteiro (fila de estudo → Developer → portões),
  nunca descartados; o Jev só anota eixo e pertinência no item e no registro de perguntas.
- Painel: cartão “Indagador” na aba Evolução, com placar e as últimas classificações; `GET /api/indagador`.
- Colunas novas em `perguntas`: `eixo`, `pertinencia`, `acionavel`, `classificacao`. A heurística da regra mora no
  próprio módulo (`decision.py` fica abaixo do teto de 1000 linhas).
- Testes: `tests/test_indagador.py` (classificação pelo Jev, descarte da genérica, dúvida vira inconclusa, consumo pelo
  planejador/missão, pedido seu só anotado, rodízio e intervalo, painel).

## 1.21.1 — 2026-10-18

- **Fluxo ao vivo sem balões:** a bolinha passa de agente em agente sem o balão de texto por cima do desenho. O que cada
  agente fez continua no cartão “Agora” e no registro ao lado. Teste: a página não traz mais o balão.

## 1.21.0 — 2026-10-18

**O Jev explorado ao máximo, com o loop conferindo isso sozinho.**

A auditoria (`jev_cobertura.py`, a partir da documentação da TypeSafe) mostrou que o loop usava pouco da API:
35 perguntas, só 37% com critérios, nenhum Noul com a situação do sim e do não, dois Scores com graus
("baixo/médio/alto", anti-padrão da doc), e `probabilities`/`legend` da resposta jogados fora.

- **Critérios em todas as 35 perguntas** (97% → o teste `test_jev_cobertura.py` não deixa entrar pergunta nova
  sem critérios):
  - Noul agora manda `criteria` com `true`/`false` descrevendo a situação de cada lado, citando os campos do
    estado entre crases (helper `SN`);
  - Choice com descrição por opção (ex.: "qual tarefa" diz o que cada tarefa faz e há quantos giros está esquecida;
    "qual modelo" descreve o tipo de tarefa de cada nível);
  - Score com níveis que descrevem situações: régua das entregas, relevância de trechos e valor do próximo ciclo.
- **A distribuição não é mais jogada fora**: `probabilities` e `legend` ficam na decisão (coluna
  `decisions.probabilidades`), e `ultima_decisao` expõe a distribuição a quem decide:
  - empate técnico no Jev (< 10 pontos entre as duas primeiras tarefas) → a regra desempata pela mais esquecida;
  - **roteamento por confiança** no gate de merge: aprovação automática só com o Jev seguro; em dúvida, "precisa de
    ajustes" (padrão da doc: agir com confiança alta, revisar na média).
- **Jev como verificador** (caso de uso da doc): o dado que o planejador cita como evidência é conferido pelo
  Jev contra a evidência real; se não está lá, o item vira "chutado" e é descartado.
- **Laboratório** cobre 8 perguntas (antes 3): `review_code`, `should_advance`, `contraprova`, `pick_model` e
  `remember` também vão em dobro, em inglês e com critérios, e a melhor forma vence com evidência.
- **Cobertura ao vivo** na aba Decisões e Jev: quantas perguntas têm critérios, estão em inglês e citam o estado.

## 1.20.0 — 2026-10-18

**As práticas da Lauren Tan (poteto: React Compiler, Grok Bot) para entregar rápido e seguro com agentes.**
A tese dela, "primeiro confiança, depois paralelismo", virou cinco travas no loop.

- **Reprodução primeiro** (`reproducao.py`, playbook de bug fix do pstack): os testes novos de uma mudança precisam
  **falhar no código antigo** e passar no novo. Teste novo que já passava antes não prova nada, e o PR não é aberto.
  Fica em duas camadas:
  - no portão do Developer antes do PR, lendo a árvore de trabalho;
  - num job novo do CI ("Reprodução primeiro") nos PRs de agente, que o gate exige verde.

  A tarefa do Developer agora manda escrever o teste e vê-lo falhar antes de corrigir.
- **Corrigir na camada mais forte**: cada lição registra em que camada está a prevenção (revisão, regra, CI ou
  arquitetura). Lição que reincide, ou que se repete 5 vezes, **sobe uma camada**, e o item do roteiro pede a
  prevenção nela, como um teste ou lint que barra no CI ou uma estrutura que torna o erro impossível. O painel
  mostra a camada de cada lição.
- **Verificação de ponta a ponta com mapa de funcionalidades** (`verificacao.py`, `circulo verificar`):
  - sobe o painel num banco novo e confere cada tela e o que ela mostra;
  - confere se todo id que o script procura existe na página e se toda tela tem a regra única do `[hidden]`
    (foi isso que deixou a faixa vazia aparecer no 1.18);
  - confere as APIs e o `/metrics`;
  - roda no CI e na validação do corpo; com o Playwright, também abre num navegador e falha com erro de JS.
- **Fronteiras da arquitetura no CI** (`tests/test_arquitetura.py`):
  - o painel nunca importa quem age (Developer, gate, corpo, loop);
  - a constituição não ganha dependência nova de módulo que o Developer pode mudar;
  - só a linha de comando sobe o loop;
  - nenhum módulo passa de 1000 linhas;
  - os padrões ruins não passam do teto de hoje.
- **Jardineiro** (agente novo, aparece no fluxo): a cada 6 h mede no próprio código os `except Exception`, os
  `noqa`, as funções longas, os módulos grandes e os TODO. Crescimento acima de 10% em uma semana vira item do
  roteiro para podar: primeiro para de crescer, depois limpa.
- **Evidência marcada, e inconclusivo não passa**:
  - no estudo, cada achado é medido, inferido ou chutado; adaptar ou contestar exige 2 achados medidos ou inferidos
    de fontes distintas;
  - no planejador, item "chutado" é descartado, e o medido leva o dado no detalhe;
  - o PR do Developer traz a evidência da reprodução.

## 1.19.0 — 2026-10-18

**Gestão mais clara: fluxo dos agentes ao vivo, painel do loop em abas e tudo o que o Jev oferece.**

- **Fluxo ao vivo** (`/fluxo`, botão na tela inicial e aba no painel do loop):
  - cada agente do loop é um nó num círculo, com o Jev no centro e a LLM e o GitHub ao lado;
  - a cada passagem de etapa, uma bolinha vai do agente que terminou ao próximo, e um balão diz o que ele fez;
  - quando um agente pergunta ao Jev, a bolinha vai até o centro e volta, na cor de quem decidiu: Jev, ou a regra
    quando o Jev ficou em dúvida. O mesmo vale para chamadas de LLM e para o GitHub. Verificações piscam verde ou
    vermelho e erros tremem o nó;
  - log narrado ao lado ("Developer chamou a LLM…") e velocidade ajustável (tempo real, 3×, pausar);
  - os eventos chegam por SSE (`/api/fluxo/eventos`) assim que entram no banco.
- **Agentes que nascerem na autoevolução** (uma tarefa nova na trilha) entram sozinhos no círculo, com a mesma
  animação, o selo "novo" e as métricas: execuções, duração p50 e tendência ("↓ 12% mais rápido"), falhas e tokens.
- **Painel do loop em abas**: Visão geral · Fluxo ao vivo · Decisões e Jev · Evolução · Segurança · Detalhes.
  A aba escolhida fica guardada. Corrigido: a faixa de pausa e o formulário do limite apareciam vazios em telas
  onde deveriam estar escondidos.
- **Jev, a partir da documentação da TypeSafe**:
  - **laboratório de perguntas** (`jev_lab.py`): as perguntas mais usadas (vale gastar, qual tarefa, evoluir?)
    vão em dobro na mesma chamada, a atual e uma variante em inglês com a condição explícita e os campos do estado
    entre crases, como a doc recomenda. O custo é quase zero, porque perguntas na mesma chamada saem quase pelo
    preço de uma. Com 40 pares e ganho de 15 pontos de confiança, a variante vira a oficial sozinha, com alerta;
    se o ganho sumir, volta;
  - **versão exata registrada**: a resposta traz o modelo versionado (ex.: jev-1.13.0), e uma troca de versão
    vira alerta, porque os limiares foram calibrados na anterior. A versão pode ser fixada com `JEV_MODEL`;
  - **retentativa** com espera exponencial em 429/529/5xx, como a doc pede;
  - decisões gravadas com horário fracionado, para ordenar certo no fluxo.
- Prometheus: `circulo_jev_lab_confianca_ratio{pergunta,forma}`.

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

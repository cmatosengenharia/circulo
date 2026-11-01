# ADR 0001 — Absorção: ECC — Everything Claude Code

- Status: aceito (01/11/2026)
- Fonte: https://github.com/affaan-m/everything-claude-code
- Licença: MIT
- Frentes: engenharia do loop, criação de produto, venda e marketing

## Contexto

Harness de agentes mais estrelado do ranking Claude (≈290 mil estrelas em 01/11; o nome oficial agora é affaan-m/ECC). 71 agentes, 314 skills, hooks de memória, aprendizado contínuo por 'instintos', verificação, custo e segurança (AgentShield). O loop já tem várias dessas peças (lições, validador, worktree, medição de tokens); entra só o que falta e é pequeno o bastante para um PR, portado para Python com teste.

## Decisão — o que entrou

### ECC-1 — Escudo das skills: auditar .claude/ antes que uma skill de terceiro entre no prompt do Developer

- Frente: engenharia do loop · alvo: `circulo` · prioridade: `loop`
- Como está na fonte: AgentShield (`npx ecc-agentshield scan`): segredos e injeção no CLAUDE.md, flags de bypass no settings.json, hooks com exfiltração, agentes sem restrição
- Como entra: `circulo/escudo.py` varre `.claude/skills/*/SKILL.md`, `.claude/settings*.json` e hooks: caractere invisível, ordem de ignorar regras, `curl|sh`, envio de variável de ambiente para fora, segredo literal, bypass de permissão. Skill com achado crítico sai da escolha do Jev em `skills.para_tarefa`.
- Prova (validação automática): `tests/test_escudo.py`

### ECC-2 — Revisão dupla independente (Santa): Validador LLM e rubrica do Jev precisam aprovar, sem contexto compartilhado

- Frente: engenharia do loop · alvo: `circulo` · prioridade: `loop`
- Como está na fonte: skill `santa-method`: dois revisores com a mesma rubrica e sem contexto comum; os dois passam ou corrige e revisa de novo; teto de iterações
- Como entra: Em `SelfDeveloper._validar`, depois do `validador.revisar_pr`, uma segunda opinião barata: o Jev pontua o diff contra a mesma rubrica (Score por critério, sem ver o veredito do Validador). Discordância → rodada de correção; 2 rodadas sem acordo → item volta com a lista de achados. Mede quantos PRs a segunda opinião barrou e quantos desses o CI depois confirmaria.
- Prova (validação automática): `tests/test_revisao_dupla.py`

### ECC-3 — Confiança das lições como nos 'instintos': sobe com confirmação, cai com contradição, promove entre repositórios

- Frente: engenharia do loop · alvo: `circulo` · prioridade: `loop`
- Como está na fonte: skill `continuous-learning-v2`: instinto atômico com `confidence` 0,3–0,9, escopo de projeto, promovido a global quando aparece em ≥2 projetos com média ≥0,8
- Como entra: Coluna `confianca` em `licoes` (0,3 ao nascer). Prevenção que segura → +0,1; reincidência → −0,2; abaixo de 0,2 a lição volta para quarentena. Lição do loop com confiança ≥0,8 vira candidata ao AGENTS.md do repositório cliente (esteira).
- Prova (validação automática): `tests/test_licoes_confianca.py`

### ECC-4 — Operador do loop: mesmo traceback 2× ou 2 checkpoints sem progresso troca a estratégia em vez de repetir

- Frente: engenharia do loop · alvo: `circulo` · prioridade: `loop`
- Como está na fonte: agente `loop-operator`: escala com 'nenhum progresso em dois checkpoints', 'stack trace idêntico repetindo', custo fora da janela
- Como entra: Impressão digital do traceback (últimas 3 linhas sem números) por item; na 2ª repetição o Developer recebe o traceback anterior e a instrução de mudar de abordagem, e o item ganha a marca `estrategia_trocada`; na 3ª, o item é fatiado pelo `fatiador` em vez de tentar de novo.
- Prova (validação automática): `tests/test_operador_loop.py`

### ECC-5 — GateGuard no Developer: primeira edição só depois de listar fatos (quem importa, contrato, dado real)

- Frente: engenharia do loop · alvo: `circulo` · prioridade: `loop`
- Como está na fonte: hook `gateguard-fact-force.js` (PreToolUse): nega a 1ª Edit/Write, exige os fatos, libera a nova tentativa; A/B do repositório: 9,0 contra 6,75
- Como entra: No worktree do Developer, `.claude/settings.json` com hook PreToolUse em Python que nega a primeira edição de cada arquivo até o transcript conter a lista de importadores (`grep`) do arquivo. Experimento com janela de 7 dias (experimentos.py): taxa de PR reprovado no Validador com e sem o portão.
- Prova (validação automática): `tests/test_gateguard.py`

### ECC-6 — Esteira: skills .NET do ECC (dotnet-patterns, csharp-testing) no .claude/skills do repositório

- Frente: criação de produto · alvo: `esteira` · prioridade: `mvp`
- Como está na fonte: skills `dotnet-patterns`, `csharp-testing` e regras `rules/csharp` do ECC (MIT)
- Como entra: Copiar as duas skills e as regras de C# para `.claude/skills/` e `.claude/rules/` da esteira, com atribuição em THIRD_PARTY_NOTICES.md; conferir que não contradizem o CLAUDE.md (Clean Architecture, TreatWarningsAsErrors, CancellationToken).
- Prova (validação automática): `tests/Esteira.UnitTests/Repo/AgentSkillsTests.cs`

### ECC-7 — Esteira: verificação do render em fases (duração, cortes/min, LUFS, legenda presente) com relatório PASS/FAIL

- Frente: criação de produto · alvo: `esteira` · prioridade: `mvp`
- Como está na fonte: skill `verification-loop` (6 fases com relatório PASS/FAIL e 'próximo passo permitido') aplicada ao vídeo
- Como entra: `RenderVerifier`: ffprobe confere duração alvo ±5% e 1080x1920; `ebur128` mede o loudness integrado (alvo −14 LUFS ±1); cortes por minuto do EDL dentro do intervalo da style bible; faixa de legenda queimada (frame amostrado). Falha → job volta para `plan` uma vez, depois `Failed` com o relatório.
- Prova (validação automática): `tests/Esteira.UnitTests/Media/RenderVerifierTests.cs`

## Descartado

- **Os 314 skills e 71 agentes em bloco** — contexto redundante custa tokens sem ganho; entra só o que tem gatilho e teste
- **Persistência de memória por hooks SessionStart/PreCompact** — o loop já guarda memória no SQLite e no Graft, fora da sessão do agente
- **cost-tracker e ccusage** — o loop já mede tokens por chamada em `llm_calls` e `budget`
- **Isolamento por worktree e padrões de loop (Ralph, claude -p sequencial)** — já existe: worktree por item, corpo validado em worktree
- **social-publisher (SocialClaw)** — depende de serviço pago de terceiros; a esteira publica por API oficial ou modo assistido (CLAUDE.md)
- **remotion-video-creation do ECC** — Remotion core é proibido na esteira (licença comercial); ver ADR 0008

## Consequências

Quatro técnicas de engenharia do loop entram como itens (uma já como código: o escudo), e duas aceleram o MVP da esteira (skills .NET para o agente e verificação do render). O ECC volta a ser estudado pelo garimpo quando subir de versão.

Validação: `circulo.absorcao.evidencias` marca cada técnica como `validada` só quando o PR do item foi mergeado e o arquivo da prova existe no repositório; o estado fica no kv `absorcao_evidencias` e no painel.

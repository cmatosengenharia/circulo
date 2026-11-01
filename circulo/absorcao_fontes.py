"""Catálogo da absorção de 01/11: o que entrou de cada repositório e o que foi descartado (dado, não instrução).

Cada fonte gera um ADR em docs/adr/ (`python -m circulo.absorcao adr`). Cada técnica tem:
- `alvo`: `circulo` (vira item do roteiro do loop) ou `esteira` (vira pedido no repositório cliente da esteira);
- `prio`: `mvp` (acelera o MVP da esteira: vídeo, cortes, postagem), `venda` (ajuda a vender) ou `loop` (engenharia do loop);
- `prova`: o arquivo de teste que prova a técnica (validação automática em `absorcao.evidencias`);
- `entregue`: a versão em que a técnica já entrou como código (então não vira item).
Levantamento feito por clone dos repositórios em 01/11/2026; estrelas aproximadas na data.
"""
from __future__ import annotations

DATA = "01/11/2026"

# O que precisa existir antes para que as técnicas da esteira saiam do papel.
PREREQUISITOS = (
    {"id": "PRE-1", "titulo": "Fábrica: o Developer trabalha os pedidos abertos dos repositórios cliente (esteira primeiro)",
     "frente": "produto", "alvo": "circulo", "prio": "mvp",
     "origem": "achado da varredura: `repo_cliente.receber` cria o clone e a branch `circulo/<n>`, mas nenhum agente pega os `pedidos_repo` abertos",
     "detalhe": "Um job do Developer por pedido aberto em `pedidos_repo`: roda o mesmo harness (Claude Code headless) no clone do pedido, "
                "com o CLAUDE.md do cliente como contexto e as skills de `.claude/skills` dele; depois chama `repo_cliente.entregar` "
                "(testes do cliente + portões de `[tool.circulo.etapas]`); vermelho volta ao agente com a saída, no máximo 2 rodadas.",
     "prova": "tests/test_fabrica_developer.py"},
)

FONTES = (
    # ------------------------------------------------------------------ 1. ECC
    {"slug": "ecc", "adr": 1, "nome": "ECC — Everything Claude Code", "repo": "https://github.com/affaan-m/everything-claude-code",
     "aliases": ("https://github.com/affaan-m/ECC",),
     "licenca": "MIT", "frentes": ("loop", "produto", "venda"), "data": DATA,
     "contexto": "Harness de agentes mais estrelado do ranking Claude (≈290 mil estrelas em 01/11; o nome oficial agora é affaan-m/ECC). "
                 "71 agentes, 314 skills, hooks de memória, aprendizado contínuo por 'instintos', verificação, custo e segurança "
                 "(AgentShield). O loop já tem várias dessas peças (lições, validador, worktree, medição de tokens); entra só o que "
                 "falta e é pequeno o bastante para um PR, portado para Python com teste.",
     "tecnicas": (
         {"id": "ECC-1", "titulo": "Escudo das skills: auditar .claude/ antes que uma skill de terceiro entre no prompt do Developer",
          "frente": "loop", "alvo": "circulo", "prio": "loop", "entregue": "1.74.0",
          "origem": "AgentShield (`npx ecc-agentshield scan`): segredos e injeção no CLAUDE.md, flags de bypass no settings.json, hooks com exfiltração, agentes sem restrição",
          "detalhe": "`circulo/escudo.py` varre `.claude/skills/*/SKILL.md`, `.claude/settings*.json` e hooks: caractere invisível, "
                     "ordem de ignorar regras, `curl|sh`, envio de variável de ambiente para fora, segredo literal, bypass de permissão. "
                     "Skill com achado crítico sai da escolha do Jev em `skills.para_tarefa`.",
          "prova": "tests/test_escudo.py"},
         {"id": "ECC-2", "titulo": "Revisão dupla independente (Santa): Validador LLM e rubrica do Jev precisam aprovar, sem contexto compartilhado",
          "frente": "loop", "alvo": "circulo", "prio": "loop",
          "origem": "skill `santa-method`: dois revisores com a mesma rubrica e sem contexto comum; os dois passam ou corrige e revisa de novo; teto de iterações",
          "detalhe": "Em `SelfDeveloper._validar`, depois do `validador.revisar_pr`, uma segunda opinião barata: o Jev pontua o diff contra a "
                     "mesma rubrica (Score por critério, sem ver o veredito do Validador). Discordância → rodada de correção; 2 rodadas sem acordo → item volta "
                     "com a lista de achados. Mede quantos PRs a segunda opinião barrou e quantos desses o CI depois confirmaria.",
          "prova": "tests/test_revisao_dupla.py"},
         {"id": "ECC-3", "titulo": "Confiança das lições como nos 'instintos': sobe com confirmação, cai com contradição, promove entre repositórios",
          "frente": "loop", "alvo": "circulo", "prio": "loop",
          "origem": "skill `continuous-learning-v2`: instinto atômico com `confidence` 0,3–0,9, escopo de projeto, promovido a global quando aparece em ≥2 projetos com média ≥0,8",
          "detalhe": "Coluna `confianca` em `licoes` (0,3 ao nascer). Prevenção que segura → +0,1; reincidência → −0,2; abaixo de 0,2 a lição "
                     "volta para quarentena. Lição do loop com confiança ≥0,8 vira candidata ao AGENTS.md do repositório cliente (esteira).",
          "prova": "tests/test_licoes_confianca.py"},
         {"id": "ECC-4", "titulo": "Operador do loop: mesmo traceback 2× ou 2 checkpoints sem progresso troca a estratégia em vez de repetir",
          "frente": "loop", "alvo": "circulo", "prio": "loop",
          "origem": "agente `loop-operator`: escala com 'nenhum progresso em dois checkpoints', 'stack trace idêntico repetindo', custo fora da janela",
          "detalhe": "Impressão digital do traceback (últimas 3 linhas sem números) por item; na 2ª repetição o Developer recebe o "
                     "traceback anterior e a instrução de mudar de abordagem, e o item ganha a marca `estrategia_trocada`; na 3ª, o "
                     "item é fatiado pelo `fatiador` em vez de tentar de novo.",
          "prova": "tests/test_operador_loop.py"},
         {"id": "ECC-5", "titulo": "GateGuard no Developer: primeira edição só depois de listar fatos (quem importa, contrato, dado real)",
          "frente": "loop", "alvo": "circulo", "prio": "loop",
          "origem": "hook `gateguard-fact-force.js` (PreToolUse): nega a 1ª Edit/Write, exige os fatos, libera a nova tentativa; A/B do repositório: 9,0 contra 6,75",
          "detalhe": "No worktree do Developer, `.claude/settings.json` com hook PreToolUse em Python que nega a primeira edição de cada arquivo "
                     "até o transcript conter a lista de importadores (`grep`) do arquivo. Experimento com janela de 7 dias (experimentos.py): "
                     "taxa de PR reprovado no Validador com e sem o portão.",
          "prova": "tests/test_gateguard.py"},
         {"id": "ECC-6", "titulo": "Esteira: skills .NET do ECC (dotnet-patterns, csharp-testing) no .claude/skills do repositório",
          "frente": "produto", "alvo": "esteira", "prio": "mvp",
          "origem": "skills `dotnet-patterns`, `csharp-testing` e regras `rules/csharp` do ECC (MIT)",
          "detalhe": "Copiar as duas skills e as regras de C# para `.claude/skills/` e `.claude/rules/` da esteira, com atribuição em THIRD_PARTY_NOTICES.md; "
                     "conferir que não contradizem o CLAUDE.md (Clean Architecture, TreatWarningsAsErrors, CancellationToken).",
          "prova": "tests/Esteira.UnitTests/Repo/AgentSkillsTests.cs"},
         {"id": "ECC-7", "titulo": "Esteira: verificação do render em fases (duração, cortes/min, LUFS, legenda presente) com relatório PASS/FAIL",
          "frente": "produto", "alvo": "esteira", "prio": "mvp",
          "origem": "skill `verification-loop` (6 fases com relatório PASS/FAIL e 'próximo passo permitido') aplicada ao vídeo",
          "detalhe": "`RenderVerifier`: ffprobe confere duração alvo ±5% e 1080x1920; `ebur128` mede o loudness integrado (alvo −14 LUFS ±1); "
                     "cortes por minuto do EDL dentro do intervalo da style bible; faixa de legenda queimada (frame amostrado). Falha → job "
                     "volta para `plan` uma vez, depois `Failed` com o relatório.",
          "prova": "tests/Esteira.UnitTests/Media/RenderVerifierTests.cs"},
     ),
     "descartes": (
         {"o_que": "Os 314 skills e 71 agentes em bloco", "por_que": "contexto redundante custa tokens sem ganho; entra só o que tem gatilho e teste"},
         {"o_que": "Persistência de memória por hooks SessionStart/PreCompact", "por_que": "o loop já guarda memória no SQLite e no Graft, fora da sessão do agente"},
         {"o_que": "cost-tracker e ccusage", "por_que": "o loop já mede tokens por chamada em `llm_calls` e `budget`"},
         {"o_que": "Isolamento por worktree e padrões de loop (Ralph, claude -p sequencial)", "por_que": "já existe: worktree por item, corpo validado em worktree"},
         {"o_que": "social-publisher (SocialClaw)", "por_que": "depende de serviço pago de terceiros; a esteira publica por API oficial ou modo assistido (CLAUDE.md)"},
         {"o_que": "remotion-video-creation do ECC", "por_que": "Remotion core é proibido na esteira (licença comercial); ver ADR 0008"},
     ),
     "consequencias": "Quatro técnicas de engenharia do loop entram como itens (uma já como código: o escudo), e duas aceleram o MVP da esteira "
                      "(skills .NET para o agente e verificação do render). O ECC volta a ser estudado pelo garimpo quando subir de versão."},

    # ------------------------------------------------------------------ 2. awesome-claude-code
    {"slug": "awesome-claude-code", "adr": 2, "nome": "awesome-claude-code (lista curada)", "repo": "https://github.com/hesreallyhim/awesome-claude-code",
     "licenca": "CC BY-NC-ND 4.0", "frentes": ("loop", "produto", "venda"), "data": DATA,
     "contexto": "Lista curada (≈57 mil estrelas) gerada de um CSV (`THE_RESOURCES_TABLE_NEW.csv`: nome, categoria, link, ativo, descrição, "
                 "obsoleto). A licença proíbe uso comercial e obra derivada da LISTA; ler a lista para descobrir repositórios é permitido, "
                 "redistribuí-la não. Por isso entra como fonte de descoberta, nunca como conteúdo copiado.",
     "tecnicas": (
         {"id": "ACC-1", "titulo": "Garimpo lê o CSV da lista: recurso ativo, não obsoleto, de categoria útil vai para a fila com a frente do Jev",
          "frente": "loop", "alvo": "circulo", "prio": "loop", "entregue": "1.74.0",
          "origem": "`THE_RESOURCES_TABLE_NEW.csv` (gera o README por `generate_readme.py`)",
          "detalhe": "`absorcao.parse_awesome` lê o CSV; `varrer_ranking` manda até 3 por dia para a fila do garimpo, preferindo as categorias "
                     "de orquestração, skills, memória, segurança, mídia criativa e testes; só o link e a descrição curta entram, como dado.",
          "prova": "tests/test_absorcao.py"},
         {"id": "ACC-2", "titulo": "Esteira: agente verifica a própria interface no navegador (Playwright) antes de abrir PR do painel",
          "frente": "produto", "alvo": "esteira", "prio": "mvp",
          "origem": "Dev Browser (SawyerHood/dev-browser): o agente dirige um navegador para checar o trabalho de UI",
          "detalhe": "Quando o painel React de aprovação existir (Fase 1, item 5), teste e2e Playwright: login, lista de jobs, player do master, "
                     "aprovar. Roda na CI da esteira; screenshot anexado ao PR como evidência.",
          "prova": "web/e2e/aprovacao.spec.ts"},
         {"id": "ACC-3", "titulo": "Esteira: posts de lançamento por rede a partir de ganchos extraídos de posts virais",
          "frente": "venda", "alvo": "esteira", "prio": "venda",
          "origem": "LinkedIn Skills (sergebulaev/linkedin-skills): extrai fórmulas de gancho de posts virais e planeja a semana",
          "detalhe": "No worker `Copy`, o mesmo molde da style bible vale para o texto: gancho, promessa e CTA extraídos do viral de referência "
                     "viram template de copy por rede (limites de `network-specs.json`).",
          "prova": "tests/Esteira.UnitTests/Copy/CopyTemplateTests.cs"},
     ),
     "descartes": (
         {"o_que": "Copiar ou republicar a lista", "por_que": "CC BY-NC-ND: sem uso comercial e sem derivada"},
         {"o_que": "Ralph Wiggum, ralph-harness, Claude Code Harness", "por_que": "o loop já roda processo novo por item em worktree próprio"},
         {"o_que": "Compound Engineering, Hivemind, roampal", "por_que": "o loop já transforma erro em lição com prevenção e quarentena; reavaliar só se a taxa de reincidência não cair"},
         {"o_que": "capcut-cli, motion-skills, Vox director", "por_que": "editor fechado ou vídeo gerado do zero; a esteira edita o vídeo bruto do cliente pelo molde do viral"},
     ),
     "consequencias": "A lista vira uma segunda fonte automática do garimpo (a primeira é o ranking, ADR 0003)."},

    # ------------------------------------------------------------------ 3. Github-Ranking-AI
    {"slug": "github-ranking-ai", "adr": 3, "nome": "Github-Ranking-AI (Top100/Claude.md)", "repo": "https://github.com/yuxiaopeng/Github-Ranking-AI",
     "licenca": "MIT", "frentes": ("loop",), "data": DATA,
     "contexto": "Ranking gerado todo dia por GitHub Actions (cron 03:05 UTC, API de busca do GitHub ordenada por estrelas) em 15 "
                 "categorias; `Top100/Claude.md` é uma tabela Markdown com posição, projeto, estrelas, forks, linguagem, issues, descrição e "
                 "último commit. É a forma mais barata de saber o que está em alta sem gastar a cota de busca do loop.",
     "tecnicas": (
         {"id": "RANK-1", "titulo": "Varredura diária do ranking Claude: quem subiu desde ontem e o que é novo vai para o garimpo",
          "frente": "loop", "alvo": "circulo", "prio": "loop", "entregue": "1.74.0",
          "origem": "`Top100/Claude.md` (tabela) e `.github/workflows/auto-update.yml` (cron diário)",
          "detalhe": "`absorcao.parse_ranking` lê a tabela (descrição com `|` não quebra a linha); `varrer_ranking` guarda as estrelas de cada "
                     "leitura, ordena os novos pelo ganho de estrelas e manda até 5 por dia para a fila do garimpo, com a frente decidida pelo Jev.",
          "prova": "tests/test_absorcao.py"},
     ),
     "descartes": (
         {"o_que": "As outras 14 categorias (LLM, RAG, MoE…)", "por_que": "ruído para o objetivo; o garimpo por necessidade já cobre RAG e memória"},
         {"o_que": "Rodar o gerador próprio (source/process.py)", "por_que": "duplicaria a busca que o ranking já publica pronta todo dia"},
     ),
     "consequencias": "A varredura periódica pedida (repos novos em alta) fica automática; o garimpo continua dirigido pela necessidade."},

    # ------------------------------------------------------------------ 4. Wondel.ai
    {"slug": "wondelai-skills", "adr": 4, "nome": "Wondel.ai Agent Skills", "repo": "https://github.com/wondelai/skills",
     "licenca": "MIT", "frentes": ("venda", "produto"), "data": DATA,
     "contexto": "65 skills (51 de métodos consagrados de produto, marketing, UX e arquitetura; 14 metaskills de ponta a ponta). É a "
                 "fonte que faltava para a frente de VENDA: oferta, posicionamento, conversão e preço.",
     "tecnicas": (
         {"id": "WON-1", "titulo": "Esteira: página de oferta com posicionamento e preço definidos antes (obviously-awesome, monetizing-innovation)",
          "frente": "venda", "alvo": "esteira", "prio": "venda",
          "origem": "skills `obviously-awesome` (alternativas, valor único, cliente-alvo), `monetizing-innovation` (preço antes de construir), `hundred-million-offers`",
          "detalhe": "`docs/oferta.md` na esteira com: alternativas que o cliente usa hoje (editor freelancer, CapCut, Opus Clip), valor único "
                     "(replica o molde de um viral do nicho), público inicial e 3 planos por minutos de render; a landing e a cobrança (Fase 1, item 7) leem dele.",
          "prova": "tests/Esteira.UnitTests/Billing/PlanCatalogTests.cs"},
         {"id": "WON-2", "titulo": "Esteira: métrica-chave única por estágio (lean-analytics) no painel: vídeos publicados por cliente por semana",
          "frente": "venda", "alvo": "esteira", "prio": "venda",
          "origem": "skill `lean-analytics`: uma métrica que importa por modelo de negócio e estágio",
          "detalhe": "Endpoint `GET /metrics/weekly` por tenant: jobs concluídos, publicados e minutos de render; o painel mostra só a métrica-chave e a tendência.",
          "prova": "tests/Esteira.UnitTests/Metrics/WeeklyMetricsTests.cs"},
         {"id": "WON-3", "titulo": "Entrevistas no formato Mom Test entram como pergunta do PM no conselho do loop",
          "frente": "venda", "alvo": "circulo", "prio": "venda",
          "origem": "skill `mom-test`: perguntar sobre comportamento passado, não sobre a ideia",
          "detalhe": "Nova persona no Indagador (`cliente`) para produtos da fábrica: perguntas sobre o que o cliente já faz e já pagou; "
                     "o Jev veta pergunta que pede opinião sobre a ideia (Noul `mom_test_valida`).",
          "prova": "tests/test_persona_cliente.py"},
     ),
     "descartes": (
         {"o_que": "Skills de organização (traction-eos, high-output-management, team-topologies)", "por_que": "o produto ainda é de uma pessoa; sem gatilho"},
         {"o_que": "Skills de código (clean-code, ddd, ddia)", "por_que": "a esteira já fixa Clean Architecture no CLAUDE.md; o loop já tem superpowers no catálogo"},
         {"o_que": "Metaskills create-business/grow-business inteiras", "por_que": "amplas demais para um PR; entram as peças com teste (oferta, métrica)"},
     ),
     "consequencias": "A frente de venda ganha artefatos verificáveis (catálogo de planos, métrica semanal) em vez de texto solto."},

    # ------------------------------------------------------------------ 5. SEO
    {"slug": "claude-seo", "adr": 5, "nome": "claude-seo (e marketingskills)", "repo": "https://github.com/AgriciDaniel/claude-seo",
     "licenca": "MIT (marketingskills: licença não confirmada)", "frentes": ("venda",), "data": DATA,
     "contexto": "Orquestrador de SEO com ≈24 sub-skills e nota de saúde 0–100 ponderada (conteúdo 23%, técnico 22%, on-page 20%, schema 10%, "
                 "performance 10%, prontidão para IA 10%, imagens 5%). coreyhaines31/marketingskills (≈41 mil estrelas) tem o seo-audit "
                 "mais instalado, mas a licença não foi confirmada: só referência.",
     "tecnicas": (
         {"id": "SEO-1", "titulo": "Esteira: nota de SEO 0–100 da landing na CI, com os pesos do claude-seo e Core Web Vitals",
          "frente": "venda", "alvo": "esteira", "prio": "venda",
          "origem": "pesos da nota de saúde do claude-seo; metas LCP < 2,5 s, INP < 200 ms, CLS < 0,1",
          "detalhe": "Script de CI que roda Lighthouse na landing e checa title/meta/H1/JSON-LD (SoftwareApplication com oferta); nota ponderada "
                     "abaixo de 80 reprova o PR da landing. FAQPage e HowTo não contam (rich results retirados).",
          "prova": "web/seo/seo-score.test.ts"},
         {"id": "SEO-2", "titulo": "Esteira: worker Copy gera título, descrição e hashtags com regras de SEO por rede",
          "frente": "venda", "alvo": "esteira", "prio": "mvp",
          "origem": "fórmulas de título e meta description da skill `seo` do ECC e do claude-seo (palavra-chave no início, limite de caracteres, sem clickbait vazio)",
          "detalhe": "Etapa 8 do mapa (`copy`): a partir da transcrição e da palavra-chave do nicho, regra determinística valida o texto da LLM: "
                     "limites do YouTube (título ≤100, descrição ≤5000), Instagram (legenda ≤2200, ≤30 hashtags), TikTok (≤2200); "
                     "fora do limite → corta ou refaz uma vez.",
          "prova": "tests/Esteira.UnitTests/Copy/CopyRulesTests.cs"},
     ),
     "descartes": (
         {"o_que": "seo-local, seo-maps, seo-hreflang, seo-ecommerce", "por_que": "produto SaaS de uma língua, sem loja física; sem gatilho"},
         {"o_que": "15 agentes de auditoria em paralelo", "por_que": "custo alto para uma landing de uma página; a nota na CI cobre"},
     ),
     "consequencias": "Venda medida: a landing não sobe sem nota de SEO; o copy de cada vídeo publicado respeita os limites da rede."},

    # ------------------------------------------------------------------ 6. Expo
    {"slug": "expo-skills", "adr": 6, "nome": "Expo skills (oficial)", "repo": "https://github.com/expo/skills",
     "licenca": "MIT", "frentes": ("produto",), "data": DATA,
     "contexto": "Skills oficiais da Expo para app React Native (router, UI nativa, data fetching, web-to-native, EAS). A esteira ainda "
                 "não tem app: o MVP é painel web + publicação por API.",
     "tecnicas": (
         {"id": "EXPO-1", "titulo": "Skills da Expo no catálogo do loop, instaladas só quando um produto pedir app móvel",
          "frente": "produto", "alvo": "circulo", "prio": "loop",
          "origem": "`npx skills add expo/skills`; skills expo-overview, expo-router, expo-ui, expo-data-fetching, expo-web-to-native",
          "detalhe": "Entradas no `skills.CATALOGO` com área `mobile`; o Jev só as escolhe quando a tarefa fala de app, iOS, Android ou Expo. "
                     "Regra registrada para o futuro app da esteira: começar pelo 'strangler fig' (casca nativa, telas web trocadas uma a uma).",
          "prova": "tests/test_skills_mobile.py"},
     ),
     "descartes": (
         {"o_que": "App móvel da esteira agora", "por_que": "fora do MVP: o cliente sobe vídeo e aprova no painel web"},
         {"o_que": "Skills de EAS (build, update, hosting)", "por_que": "serviço pago da Expo; decidir só com app real e receita"},
     ),
     "consequencias": "Mobile fica pronto para o segundo produto da fábrica, sem custo de contexto hoje."},

    # ------------------------------------------------------------------ 7. Supabase
    {"slug": "supabase-agent-skills", "adr": 7, "nome": "Supabase agent skills (oficial)", "repo": "https://github.com/supabase/agent-skills",
     "licenca": "MIT", "frentes": ("produto",), "data": DATA,
     "contexto": "Skills `supabase` e `supabase-postgres-best-practices` (regras por impacto: consulta, conexão, segurança e RLS como "
                 "CRITICAL). A esteira usa Postgres com filtro global de TenantId no EF Core: a lição útil é a defesa em profundidade.",
     "tecnicas": (
         {"id": "SUPA-1", "titulo": "Esteira: Row Level Security por tenant no Postgres além do filtro do EF Core, com índice na coluna da política",
          "frente": "produto", "alvo": "esteira", "prio": "venda",
          "origem": "regras `security-rls-performance` (indexar a coluna usada no USING) e o padrão `(select auth.uid()) = user_id` (avaliado uma vez por consulta)",
          "detalhe": "Migration com `ENABLE ROW LEVEL SECURITY` nas tabelas com TenantId e política `USING (tenant_id = (select current_setting('app.tenant_id')::uuid))`; "
                     "o DbContext seta `app.tenant_id` por conexão; índice em tenant_id. Teste com dois tenants e SQL cru: nenhum vê o outro.",
          "prova": "tests/Esteira.UnitTests/Persistence/RowLevelSecurityTests.cs"},
         {"id": "SUPA-2", "titulo": "Regras de Postgres da Supabase no catálogo de skills do loop (substitui a entrada sem licença)",
          "frente": "produto", "alvo": "circulo", "prio": "loop",
          "origem": "`supabase/agent-skills/skills/supabase-postgres-best-practices` (o catálogo apontava para `supabase/skills`, que não é o oficial)",
          "detalhe": "Corrigir a entrada `postgres-best-practices` em `skills.CATALOGO`: repositório `supabase/agent-skills`, caminho certo, licença MIT.",
          "prova": "tests/test_skills_catalogo.py"},
     ),
     "descartes": (
         {"o_que": "Supabase como backend da esteira", "por_que": "a esteira já tem .NET + Postgres + RabbitMQ (ADR 0001 dela); trocar seria reescrever"},
         {"o_que": "Edge Functions, Realtime, Storage da Supabase", "por_que": "mesma razão; sem gatilho"},
     ),
     "consequencias": "Isolamento entre clientes deixa de depender só do código: requisito para vender a mais de um tenant."},

    # ------------------------------------------------------------------ 8. Remotion
    {"slug": "remotion-skills", "adr": 8, "nome": "Remotion skills", "repo": "https://github.com/remotion-dev/skills",
     "licenca": "Remotion License (gratuita até 3 pessoas; empresa: US$ 0,01 por render, mínimo US$ 100/mês para automação)", "frentes": ("produto",), "data": DATA,
     "contexto": "O repositório oficial é remotion-dev/skills (≈6 mil estrelas em 01/11; nenhum repositório de skill do Remotion tem ≈15 mil — "
                 "o número provavelmente é o do monorepo ou de uma cópia comunitária). Skills: best-practices, markup (timing, sequencing, "
                 "silence-detection, captions, transitions), captions, create, render, saas. O CLAUDE.md da esteira proíbe o core do Remotion "
                 "(licença comercial para produto que renderiza para clientes); o que serve são os PADRÕES, reimplementados em ffmpeg/Hyperframes.",
     "tecnicas": (
         {"id": "REM-1", "titulo": "Esteira: limiar de silêncio adaptativo pelo loudnorm (padrão do silence-detection.md) no SilenceEditPlanner",
          "frente": "produto", "alvo": "esteira", "prio": "mvp",
          "origem": "regra `silence-detection.md`: primeiro `loudnorm=print_format=json` para ler `input_thresh`, depois `silencedetect` com esse limiar",
          "detalhe": "Hoje o limiar vem fixo do contrato (`params.silenceThresholdDb`). Medir `input_thresh` no ingest (já tem o WAV) e usar "
                     "min(contrato, input_thresh) no `SilenceDetector`: em áudio baixo o limiar desce junto e a fala deixa de virar 'nada para manter'.",
          "prova": "tests/Esteira.UnitTests/Media/AdaptiveThresholdTests.cs"},
         {"id": "REM-2", "titulo": "Esteira: legendas e camadas presas ao mesmo trecho do vídeo (padrão Sequence) no EDL e no TimelineMapper",
          "frente": "produto", "alvo": "esteira", "prio": "mvp",
          "origem": "regras `display-captions.md` e `sequencing.md`: vídeo e legenda no mesmo `<Sequence>`, trim e velocidade no pai",
          "detalhe": "No EDL, cada `keep[]` carrega as palavras e camadas dele; o `TimelineMapper` remapeia legenda, zoom e título pelo mesmo trim. "
                     "Teste: cortar um trecho do meio não desalinha a legenda seguinte em mais de 1 frame.",
          "prova": "tests/Esteira.UnitTests/Media/TimelineMapperTests.cs"},
         {"id": "REM-3", "titulo": "Esteira: transições e zoom com curva spring (interpolate + clamp) no render ffmpeg",
          "frente": "produto", "alvo": "esteira", "prio": "mvp",
          "origem": "regra `timing.md`: `interpolate` com `Easing.spring({damping: 200})` e clamp nas duas pontas",
          "detalhe": "Função de easing spring em C# gerando a expressão do `zoompan`/`scale` por frame (camadas `zoom` punch/kenburns da Fase 1); "
                     "valores fora de [0,1] nunca saem (clamp).",
          "prova": "tests/Esteira.UnitTests/Media/SpringEasingTests.cs"},
     ),
     "descartes": (
         {"o_que": "Remotion core, @remotion/renderer e Lambda", "por_que": "licença comercial: um SaaS de vídeo automatizado paga por render; a esteira usa ffmpeg/Hyperframes"},
         {"o_que": "@remotion/whisper-webgpu", "por_que": "exige GPU compatível e não roda em Linux arm64; a esteira já usa whisper.cpp"},
         {"o_que": "remotion-saas e Player", "por_que": "deixaria o cliente renderizar no produto: caso explicitamente pago na licença"},
         {"o_que": "Agrupamento de legendas TikTok", "por_que": "já portado (CaptionGrouper, THIRD_PARTY_NOTICES da esteira)"},
     ),
     "consequencias": "O vídeo ganha o 'acabamento Remotion' sem a licença: limiar adaptativo, legenda presa ao corte, movimento com spring."},

    # ------------------------------------------------------------------ 9. pipeline de vídeo open source
    {"slug": "pipeline-video-oss", "adr": 9, "nome": "Pipeline de vídeo open source (cortes, reframe, transcrição, postagem)",
     "repo": "https://github.com/SamurAIGPT/AI-Youtube-Shorts-Generator", "licenca": "MIT (Shorts Generator); Unlicense (auto-editor); MIT (whisper.net); AGPL-3.0 (postiz: só leitura)",
     "frentes": ("produto", "venda"), "data": DATA,
     "contexto": "Para o MVP (vídeo, cortes, postagem), o que acelera não é skill: é algoritmo pequeno de repositórios de mídia. "
                 "AI-Youtube-Shorts-Generator: LLM pontua trechos (score, gancho, motivo), funde quase-duplicados e recorta 9:16 seguindo o "
                 "rosto com suavização. auto-editor: margem e mínimo de clipe (já portado). whisper.net: binding .NET do whisper.cpp. "
                 "postiz: OAuth e upload por rede, mas AGPL.",
     "tecnicas": (
         {"id": "VID-1", "titulo": "Esteira: cortes (clips[]) com nota de viralidade, gancho e motivo, e fusão de trechos sobrepostos",
          "frente": "produto", "alvo": "esteira", "prio": "mvp",
          "origem": "AI-Youtube-Shorts-Generator (MIT): prompt de destaques (score, hook, reason por trecho) e junção de clipes quase duplicados",
          "detalhe": "No `IEditPlanner` com LLM (Fase 1, item 2): `clips[]` com `score` 0–100, `hook`, `reason`; regra determinística funde "
                     "clipes com sobreposição > 50%, descarta < 15 s ou > 60 s e mantém os 3 melhores. Registrar em THIRD_PARTY_NOTICES.md.",
          "prova": "tests/Esteira.UnitTests/Media/ClipSelectionTests.cs"},
         {"id": "VID-2", "titulo": "Esteira: reframe 9:16 que segue o rosto com suavização (média móvel) e corte fixo por cena como fallback",
          "frente": "produto", "alvo": "esteira", "prio": "mvp",
          "origem": "AI-Youtube-Shorts-Generator (MIT): detecção de rosto por quadro + suavização do centro do recorte",
          "detalhe": "Detecção de rosto por processo externo (amostra 2 fps), centro do recorte suavizado (média móvel de 1 s, passo máximo por quadro), "
                     "sem rosto → centro fixo da cena; vira filtro `crop` com expressão por tempo.",
          "prova": "tests/Esteira.UnitTests/Media/FaceReframeTests.cs"},
         {"id": "VID-3", "titulo": "Esteira: conector YouTube por upload resumable e modo Assisted, sem código do postiz",
          "frente": "venda", "alvo": "esteira", "prio": "mvp",
          "origem": "YouTube Data API v3 `videos.insert` (upload resumable, 1.600 unidades de cota por upload); postiz (AGPL) lido só como referência de fluxo",
          "detalhe": "`YouTubePublisher : ISocialPublisher` com OAuth por tenant (tokens cifrados em `SocialAccount`), upload resumable com retomada, "
                     "Shorts quando 9:16 ≤ 60 s; sem credencial → modo Assisted (pacote com arquivo, copy e instruções). Teste com servidor HTTP falso.",
          "prova": "tests/Esteira.UnitTests/Publishing/YouTubePublisherTests.cs"},
         {"id": "VID-4", "titulo": "Esteira: transcrição em processo pelo whisper.net quando disponível, CLI do whisper.cpp como fallback",
          "frente": "produto", "alvo": "esteira", "prio": "mvp",
          "origem": "sandrohanea/whisper.net (MIT): bindings .NET com segmentos e timestamps",
          "detalhe": "`WhisperNetTranscriber : ITranscriber` atrás de configuração (`Media:Transcriber=whispernet|cli`); mesmo contrato de palavras; "
                     "teste compara as duas saídas no `samples/demo.mp4` com tolerância de 80 ms por palavra.",
          "prova": "tests/Esteira.UnitTests/Media/TranscriberParityTests.cs"},
     ),
     "descartes": (
         {"o_que": "Código do postiz (AGPL-3.0)", "por_que": "oferecer como serviço obrigaria abrir o código da esteira; só a leitura do fluxo"},
         {"o_que": "Modo padrão do Shorts Generator com MuAPI", "por_que": "serviço pago de terceiro"},
         {"o_que": "whisperX (alinhamento forçado)", "por_que": "só Python; reavaliar se a legenda palavra a palavra do whisper.cpp não bastar"},
         {"o_que": "auto-editor de novo", "por_que": "margem e mínimo de clipe já portados no SilenceDetector"},
     ),
     "consequencias": "As quatro peças que faltam entre 'vídeo editado' e 'vídeo publicado' viram pedidos na esteira, cada um com teste."},
)

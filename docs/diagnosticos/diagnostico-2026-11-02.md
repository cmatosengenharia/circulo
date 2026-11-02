# Diagnóstico do Círculo — 2026-11-02

> Auditoria somente leitura (nada alterado, nada commitado). Fontes: repo `cmatosengenharia/circulo` (main `f9f044b`, v1.76.4),
> GitHub Actions (últimos 418 runs, inclusive tentativas ocultas por re-run), banco vivo `~/Projects/circulo-dados/circulo.db`,
> launchd, painel 127.0.0.1:8765, repo cliente `cmatosengenharia/esteira` (main `a84cb29`). Horários em BRT.

## 1. Resumo executivo — nota de saúde: **4/10**

1. **O loop roda, mas não se corrige**: processo vivo (launchd, PID 38784, tick 22.4 mil), porém o Developer está **isolado por 320 giros** (incidente #10: `pytest -q -x` local estourou 900 s sete vezes hoje) — 49 itens prontos, 0 sessões de código em 4 h, PR #340 vermelho por flake sem ninguém para consertar.
2. **A Esteira parou**: 34 pedidos, **7 entregues e 27 vermelhos com 3/3 tentativas esgotadas**; 94 % dos planos (149/159) são reprovados pelo próprio portão de formato do Fabricante (`passo sem 'verificar'` / `plano sem 'Arquivos:'`). 6 PRs verdes (#3–#8) esperam merge humano.
3. **Autoevolução gira em torno de si**: em 7 dias, 163 commits, 91 % do loop; **6,7 % produto, 27 % ruído** (22 PRs de docs automáticos, 166 propostas para o projeto "Finanças da família" que está pausado desde 18/10, lições #47/#59/#60 "corrigidas" 2–7 vezes e reincidentes). Nos 2 dias, o produto andou (Esteira), mas puxado pelo humano.
4. **CI**: nenhuma regressão real. As 4 falhas citadas são 2 flakes (poluição do `~/.nuget` entre testes, corrigida pelo humano; `Barrier(timeout=5)` em `test_capacidade.py`, aberta). Taxa 7 d: main 99 %, PRs 98 %. A v1.76.3 nunca foi taggeada. Nenhum relatório diário das 21h50 existe (o que existe é `resumos/AAAA-MM-DD.md` a cada 288 giros e a pauta das 8h).
5. **Riscos altos no repo público**: o gate mergeia qualquer PR com branch `circulo/…` sem checar se vem de fork; a trava de dinheiro está anulada no próprio gate (`touches_money_code=False` fixo) e o rótulo `aprovado-humano` é "legado"; main sem proteção; scanner de segredos só pré-PR e só regex; 93,6 % dos tokens (12,7 M/13,6 M em 7 d) vão para `evoluir_loop`, e o Fabricante não mede nada.

## 2. Saúde atual

### 2.1 Arquitetura real (resumo)

- Pacote Python `circulo/` com **174 módulos, 35,5 mil linhas** (+9 templates HTML); `tests/` com 209 arquivos, 1.417 testes; `fabrica/` (6 estações PO→release) **não é usado pelo loop** (zero `from fabrica` em `circulo/`).
- Processo único `circulo run --painel` (launchd `com.circulo.loop`, dados em `~/Projects/circulo-dados`, SQLite/WAL 78 MB, 55 tabelas) + plano de controle (`circulo.controle`: painel e SRE) em processo próprio.
- Giro: orçamento → fila (caixa de arquivos / pedidos) → tarefa do idle escolhida por valor (`fabricar` > `corrigir_codigo` > `estudar_pedido` > `planejar_roteiro` > …) → Meta-Learner → saúde/rollback.
- Cascata de custo: regra/cache → **Jev (TypeSafe)** → LLM. 63 perguntas ao Jev catalogadas; 6.962 chamadas Jev em 7 d; sem chave, `LocalJev` responde por regra fixa (mais permissivo, não mais rígido).
- LLM: `AssinaturaLLM` via `claude -p` quando `CIRCULO_CONTA=max` (caso atual); fallback API Anthropic; `llm.py` tem tabela de 11 provedores (openai, gemini, groq, ollama…) nunca exercitada fora de teste.
- Agentes por papel (`nomes.py`): Tech lead, PO, Gerente de produto, Arquiteto, Desenvolvedor (Claude Code em worktree, até 2 em paralelo), **Fabricante** (repo cliente: plano → teste vermelho → código → técnicas → validador → PR), Revisor, QA/Gate, DevOps (`atualizar_corpo`), SRE (Vigia), Curador de lições, Médico, Redator, Jardineiro.
- Gate de merge **mora no loop** (`merge_gate.py`), não no GitHub: PR `circulo/…` + checks verdes + ≤800 linhas + teste novo + Jev → merge com SHA travado. Constituição (`merge_gate/policy/budget/guardrails/self_dev/corpo/.github`) protegida por job de CI e convenção.
- Memória: `memoria` (FTS5, 3.326 registros) + `memory` + Graft (vetores/grafo, perfil `circulo-loop`, em uso: 50 buscas/dia) — três módulos de memória.
- Duas missões convivem no código: **controle financeiro da família** (`finance.py`, `money.py`, `ledger`, `policy.py` com regras ifood/fralda; descrição do repo e do `pyproject` ainda é essa) e **fábrica de software** (`fabricante.py`, `repo_cliente.py`, `produto_novo.py`, `landing.py`). Mais uma terceira: ferramenta pessoal "Meu trabalho" (daily, Cursor, GAIA).
- CI: 7 checks (Testes 3.11/3.12/3.13 com lint+pytest+wheel+diagnóstico+fumaça de 50 giros, Constituição, Reprodução primeiro, Evidência reforçada, Container); run médio 6,5 min; Release automática por tag quando o CI da main passa.

### 2.2 Tabela de falhas da CI

| Run | Commit / branch | Job | Erro | Classificação | Loop se corrigiu? |
|---|---|---|---|---|---|
| 41380768894 | `ff4776e` push main (1.76.3) | Testes 3.11 | `test_produto_novo…[dotnet]`: `NuGet.Config is not valid XML` / `Root element is missing` | **Flaky de ambiente**: `test_fabricante.py` (fixture com `dotnet test` real, 1.76.1) corrompe `~/.nuget` do runner antes de `test_produto_novo.py` | **Não**: humano corrigiu no PR #346 (`tests/test_fabricante.py:208` → `pytest` em vez de `dotnet test`). Main ficou vermelha nesse SHA, Release *skipped*, **tag v1.76.3 não existe**. Sem lição/alerta no banco (lição #50 `gate:main_vermelha` parada desde 25/10) |
| 41379186595 t.1 | `f91dffb` main (1.76.2) | Testes 3.12 | mesmo flake dotnet | Flaky (mesma causa) | Re-run **manual** escondeu a falha (aparece como success); Release saiu no 2º run |
| 41383244424 | `ac61f03` PR #346 `cassio/…` | Testes 3.12 | mesmo flake dotnet | Flaky | Corrigido 2 commits depois na mesma branch |
| 41384096279 | `94bea0d` PR #346 | Testes 3.11 | mesmo flake (o "aquecimento" `dotnet nuget list source` não resolveu) | Flaky; diagnóstico intermediário errado | Corrigido em `7e2b7c3` |
| 41397453385 | `dc1e434` PR #340 `circulo/fix-371` (loop) | Testes 3.12 | `test_capacidade.py::test_escalador_com_3_estudados…[11]`: `threading.BrokenBarrierError` (`Barrier(2, timeout=5)`) | **Flaky puro**: o commit só mudou `docs/*`; mesmo teste já caiu na rodada `[6]` em 3.13 | **Parcial**: lição #97 criada 03:20 e fechada 09:20 como "passou 2× na main", mas o PR segue aberto e vermelho; o gate só re-executa jobs *não iniciados*, nunca flake; o Developer que consertaria está isolado |
| 41373471855 | `1f236f9` PR #341 `circulo/skills-…` | Constituição | "Constituição alterada por agente: circulo/self_dev.py" | **Guardrail funcionando** (commit humano em branch `circulo/`) | Humano reabriu como `cassio/…` (#342) e mergeou |

Ocorrências do flake dotnet: 7 runs / 8 jobs em 1h50 (01:50–03:43 UTC), em 3.11, 3.12 e 3.13; 4 delas invisíveis no `gh run list` por re-run manual.
Taxas: últimos 30 runs **82 %** (main 90 %, PRs 78 %; ~72 % contando tentativas ocultas); 7 dias **98 %** (main 157/159, PRs `circulo/` 228/230).

### 2.3 Testes locais × CI

- CI: ~1.620 testes, 4–8 min por versão de Python, verde em `f9f044b`.
- Local (`.venv` 3.12, no Mac do loop, com o loop rodando ao lado) — três execuções hoje:
  1. `pytest -q -x` completo: **travou aos 16 min com 0 % de CPU** (handles abertos em um `circulo.db` temporário `circulo-verificar-*`, criado por `verificacao.py:83`, que sobe um painel em thread sobre banco novo); morto por mim.
  2. Reexecução verbosa: travou de novo, em outro ponto (`tests/test_equipe.py`, 28 %, 0 % de CPU por 4,5 min); `tests/test_equipe.py` sozinho passa em 7 s → o travamento é **dependente da ordem** (estado/thread vazando entre testes), não de um teste quebrado.
  3. Suíte completa sem `test_equipe.py`: **1.607 passed, 10 skipped, 0 failed — em 20 min 34 s**. Só `tests/test_validador_segredos.py` leva 413 s (6 testes de 55–100 s cada; na CI a suíte inteira leva 4–8 min).
- Conclusão: o código está verde, mas a suíte local **leva 20 min (> 900 s do timeout do Developer) e às vezes pendura**. É isso que gera o incidente #10 e isola o Developer. A CI não vê o problema porque roda em runner limpo e sem o loop ao lado.
- Diferenças relevantes: no Mac, dotnet/node reais estão no PATH (os esqueletos "reais" não são pulados); o loop roda ao mesmo tempo até 2 worktrees de Developer + a suíte do Validador, concorrendo com a suíte do item.

### 2.4 O loop está rodando?

| Pergunta | Evidência |
|---|---|
| Processo | `launchctl list` → `com.circulo.loop` PID 38784, iniciado hoje 03:18 (`KeepAlive`); `loop.log` tem **376 reinícios** desde 17/10 (reinício a cada `atualizar_corpo`); `loop.err` parou de crescer em 25/10 ("database disk image is malformed", restaurado) |
| Giros | Tick 22.4 mil; só **5 ciclos de missão em 24 h**; `cycles` e `decisions` caindo (3.123 decisões Jev em 27/10 → 1.220 hoje) |
| Commits por agente | 7 d: 163 commits na main, 149 do loop (PR `circulo/`), 14 humanos; por dia 10/22/17/7/38/22/44/3; por hora: picos 07h, 16h, 17h, 22h, 23h; vale 14h e 20–21h |
| Developer | **Isolado** (incidente #10, nível 6, 320 giros, desde 10:42); Vigia: "Item #297 pronto há 63 min e o Developer não pegou" (48 vezes); "2 lições de estrutura abertas há 2 h sem correção" (333 vezes) |
| Orçamento | Hoje 711 mil tokens de 400 mil "limite" — modo **ilimitado** (padrão desde 1.35, decisão de 29/10): mede, não corta. 1,9–3,2 M tokens/dia na semana |
| Relatório das 21h50 | **Não existe**: sem cron, sem launchd, sem scheduled-task, nenhum `21:50` no código. O que existe: `loop.write_summary` → `circulo-dados/resumos/AAAA-MM-DD.md` a cada 288 giros (horário varia: 23:47, 18:17, 06:28, 11:35…) e `daily.py` às **8h** com notificação macOS. O resumo de hoje abre com "Patrimônio líquido R$ 512.000 … casa 60,2 % de R$ 850.000" (dado de exemplo da missão financeira) |
| Sessão Claude Max | `conta_sessao.logado=true`, método `claude.ai`, 0 quedas registradas; **sem `CLAUDE_CODE_OAUTH_TOKEN`** → quando cair, abre Terminal e espera clique no navegador |

## 3. A autoevolução está funcionando?

### 3.1 Classificação dos 163 commits (26/10 → 02/11)

| Categoria | Commits | % | Linhas | % ponderado |
|---|---|---|---|---|
| (a) produto / valor de mercado | 11 | 6,7 % | 5.746 | 21,7 % (15,4 % sem as 1.985 linhas de skills vendorizadas do #342) |
| (b) infraestrutura do loop | 85 | 52,1 % | 14.630 | 55,4 % |
| (b*) ferramenta pessoal (Meu trabalho, Finanças da família) | 16 | 9,8 % | 1.553 | 5,9 % |
| (c) correção | 7 | 4,3 % | 1.329 | 5,0 % |
| (d) ruído / retrabalho | 44 | 27,0 % | 3.170 | 12,0 % |

Só o loop (149 commits): produto 7 (4,7 %), ruído 44 (29,5 %). Os 7 PRs de produto do loop são todos de 01/11, depois do pedido humano "vender resultado".
Ruído com nome: 22 PRs `docs: documentação do loop atualizada pelo Redator técnico`; lição #60 `painel:frescor` com 7 PRs e fechada "por prazo"; #47 `loop:estagnado` com 2 PRs em 2 h e **reincidente** (43 ocorrências, 10 reincidências, última hoje); "entrega sem uso vira item" em 4 variantes (#200/#205/#206/#210); 8 PRs de ingestão de extratos para o projeto Finanças, pausado; disjuntor de crédito baixo feito 2× (#217, #280); cache do planejador 2× (#271, #283); #223 com 556 linhas de lixo `.shim259/` commitadas.
Versões: 14 tags no período, todas lançadas pelo humano; CHANGELOG tem 1.73.0, 1.75.0 e 1.76.3 sem tag.

### 3.2 Regra da janela de 2 dias (desde 31/10)

69 commits: produto 15,9 % (loop sozinho **12 %**); 89 % dos tokens em `evoluir_loop`. A Esteira (repo .NET 10) foi criada pelo humano + Claude em uma tarde (01/11); o loop abriu 7 PRs nela, 1 mergeado (pelo humano). **Veredito**: a fábrica vendável começou a existir, mas puxada pelo humano; o loop ainda gira em torno de si. Não é caso de reescrever a Esteira (ela compila, 36 testes verdes, e2e com vídeo real): é caso de **parar a evolução interna e consertar o portão de plano do Fabricante**, que hoje queima as 3 tentativas de cada pedido por formato.

### 3.3 Erros e lições

- 98 lições; status: 58 obsoletas (por TTL, não por correção), 22 evidenciadas, 6 validadas, 5 sem prevenção, 2 abertas, 1 reincidente. **Não há nível de confiança** (o item #371 "confiança como instintos" está `em_andamento` no PR #340 vermelho).
- As lições **são lidas** (`self_dev._licoes_txt` → prompt do Developer; também planejador, indagador, garimpo, contexto do Cursor), mas **sem filtro de obsoletas**: 58 entram no prompt com o texto "Obsoleta por prazo…", e as duas que lideram (#59 `maximo_de_passos`, 12 reincidências; #47 `loop:estagnado`) são estruturais do loop, não comportamento do Developer — por isso reincidem mesmo "lidas". `docs/PRATICAS.md`: 1 prática, "usada 0, atingiu 0".
- Checagens que sempre falham e viram ruído: `validador:worktree` "lixo apagado antes do commit" 164/165; `validador:scanner_segredos` "gitleaks não instalado" 29/29; `estudo:pedido` "só 0 fonte(s)" 69/160.
- Mesmo erro repetindo: sim — 63 de 98 lições com ≥2 ocorrências, 23 com reincidência após "corrigida". A regra "o mesmo erro estrutural só acontece uma vez" não está em vigor.

### 3.4 Tokens e LLM (7 dias, `llm_calls`: 743 chamadas, 13,58 M tokens)

| Papel | Chamadas | Tokens | % |
|---|---|---|---|
| planejador | 204 | 3,52 M | 25,9 % |
| estudo (web) | 129 | 2,96 M | 21,8 % |
| developer (Claude Code, opus) | 238 | 2,87 M | 21,2 % |
| validador (haiku) | 111 | 2,76 M | 20,3 % |
| questionador / estudo_duvida / builder / mercado | 61 | 1,47 M | 10,8 % |

Por job: **`evoluir_loop` 93,6 %**, `landing_page` 3,8 %, produto_software 0,4 %. Decisões sim/não estão de fato no Jev (14.340 `source=jev` vs 21 `llm`).
Desperdício identificável ≈ **21 % (2,8 M)**: estudos sem fonte (~1,27 M), validador revalidando o mesmo PR (24 revalidações, 590 k), sessões extra do Developer na mesma tarefa (63 sessões, 537 k), estudos repetidos (272 k), falhas (187 k). `llm_cache` em sombra: 7 linhas, 0 acertos. `retry` = 0 em 100 % das linhas. `desfechos.rendeu` = 1 em 99 % (métrica sem poder de freio).
**Ponto cego**: o Fabricante (`fabricante.py`, `fabrica_developer.py`) não grava em `llm_calls` — 34 pedidos × até 6 planos reprovados rodaram sem medição; `kv.assinatura_tokens` só guarda o dia corrente (hoje: 3.972).
Docs do Redator custam 0 tokens de LLM, mas 22 PRs × ~5 min de CI ≈ 100 min de CI/semana e 22 passagens pelo gate.

## 4. Frentes paradas

| Frente | Status | Parada há | Por que travou | O que destrava |
|---|---|---|---|---|
| **Developer do loop** (`corrigir_codigo`) | isolado (nível 6, 320 giros) | ~10 h | `pytest -q -x` da suíte local estourou 900 s ×7 (suíte trava, não só demora: 0 % CPU) | Suíte local leva 20 min (> 900 s) e às vezes pendura (§2.3): timeout por teste, suíte rápida para o Developer, `test_validador_segredos.py` (413 s) e o vazamento de thread do painel em `verificacao.py`; zerar o incidente #10 |
| **Esteira — 27 pedidos vermelhos** (projeto 6, `pedidos_repo`) | esgotados 3/3 | 0–1 dia | 21 × "sem plano válido" (portão de formato: regex `verificar` + lista `Arquivos:`), 5 × "Bloqueado: depende do que o repo não tem" (painel React, worker Copy, approve/publish), 1 × teste do cliente falha no clone (skill `csharp-testing` ausente) | Corrigir prompt/validador de plano; zerar tentativas; ordenar por dependência (Copy → render multi-aspecto → approve/publish → conector YouTube → relatório) |
| **Esteira — PRs #3–#8** (oferta, métrica, corte de erros, spring/zoom, face-track, mapa animado) | abertos, CI verde | 3–8 h | Merge é manual no repo cliente; item #376 (auto-merge) pendente | Mergear (humano) ou aprovar auto-merge com CI verde + validador |
| PR #340 (item #371 confiança das lições) | aberto, 3.12 vermelho | 13 h | Flake `Barrier`; gate não re-executa flake; Developer isolado | Re-run do job ou push vazio; regra "lição evidenciada como flaky → re-run 1×" |
| Lições estruturais abertas #96 (timeout pytest) e #98 (`fabrica:promessa`, 22 oc.) | abertas | hoje | Dependem do Developer isolado | Idem Developer |
| 49 itens prontos na fila (#297, #188, #189, #376–#382 pedidos de hoje: auto-merge do Fabricante, Fabricante na Equipe ao vivo, card Técnicas, missão Vender resultado) | pendente | 0–8 dias | Developer isolado | Idem |
| 38 itens `referencia` (técnicas de repos garimpados: xlsx, Expo, Supabase, ponytail…) | pendente | 0–1 dia | Absorção gera 3 técnicas + 4 perguntas por repo/dia; fila cresce mais rápido que a entrega | Cota diária e classe Jev `ferramenta` com prioridade mínima |
| Item #25 "backlog de tech lead" | descartado → reescrito em 10 pedidos (#203–#212), **todos feitos** (PRs #161–#170) | — | — | Nada; inclui "#212 alinhar kit ao GAIA da Localiza" (feito) |
| Itens #30 (dividido), #117 (observação), #6/#9 (parcial), #177/#218 (proposto) | zumbis | 7–15 dias | Nunca fechados/decididos | Fechar ou desativar |
| Projeto 1 "Finanças da família" | `pausada=1` desde 18/10, mas **ativo** no código | 15 dias | `propor_feature` gerou **166 propostas em 7 d** (188 no total: `share_delivery_30d`, `ticket_medio_30d_cents`…); resumo diário mostra patrimônio de exemplo | Arquivar a missão (ou separar em repo próprio) |
| Projeto 3 "Migrar chatbots Blip → Amazon Connect" e tela "Meu trabalho"/GAIA | ativo | — | Trabalho do empregador no loop (sem dados/código, "plano genérico") | Decidir se sai do loop público |
| Issues GitHub | **zero** (circulo e esteira) | — | Backlog vive só no SQLite | — |
| Branches | 350 remotas (339 `circulo/`), **4.695 locais**, 304 de PR mergeado nunca apagadas; retrabalho `fix-120` ×16, `fix-95` ×11, `fix-94` ×11, `fix-138` ×8, `fix-115` ×5 | desde 21/10 | Nenhum código apaga branch | Delete-on-merge no GitHub + poda local |
| Worktrees órfãos `.circulo-wt-25`, `.circulo-wt-29`, `.circulo-wt-orfaos/` | órfãos | 6–12 dias | Itens já descartados | `git worktree prune` + remover |
| Disco | `circulo-dados/` 15 GB: `snapshots/` 14 GB (246 arquivos no `arquivo/`, "não são apagados pelo círculo"), `fabrica/` 1 GB | crescendo | Sem política de retenção | Reter 7 dias + 1 por semana |

### Integrações

| Integração | Código | Configurada | Funcionando | Falta |
|---|---|---|---|---|
| Graft (memória semântica) | sim (`graft.py`) | sim (`graft` 0.2.0, perfis `circulo`/`circulo-loop`) | **sim**: 50 buscas/dia, manutenção às 10:19 | 2 `graftd` duplicados; log "cannot decode batches"; perfil antigo sujo |
| Skills absorvidas (Superpowers, Karpathy, ADHD, Octopus) | sim (`tecnicas.py`, `skills.py`, `escudo.py`) | sim (`.claude/skills/` no circulo e na esteira) | **parcial**: técnicas medidas no Fabricante/Validador; `skills_uso` tem 1 registro; revisor externo Octopus (`codex`) nunca aparece no log | Medir uso real; `systematic-debugging` marcado pelo escudo (lê Keychain) |
| Secrets | `configuracao.py`, `cofre.py` | 7 variáveis preenchidas em `~/.config/circulo/env` (600); `ANTHROPIC_API_KEY` **e** `CIRCULO_CONTA=max` juntas | sim | `CLAUDE_CODE_OAUTH_TOKEN` (token de 1 ano) ausente; `gitleaks` não instalado |
| Máquina 24/7 | launchd + Dockerfile | launchd no **Mac do dono** | sim enquanto o Mac não dorme/desloga (`hibernatemode 3`) | Máquina dedicada ou container; `caffeinate`/`pmset` |
| Provedor plugável | sim (`llm.py`, 11 provedores + `CompatLLM`) | nenhum alternativo | só Anthropic (assinatura) | Teste real com um segundo provedor |
| Relogin Max | sim (`conta.py`: checa a cada 300 s, abre `claude auth login`) | sim | logado | Sem clique humano só com token de 1 ano |
| RAG compartilhado | `memoria` FTS5 + `memory` + Graft | sim | sim (3.326 registros; `memoria_uso` 5.440) | Três módulos de memória; `poupou_tokens` = 0 |
| Dashboard hand-drawn / equipe conversando | `equipe.html` (SSE, canal `#equipe`), `fluxo.html` | sim | painel responde; Equipe ao vivo existe | **Estilo hand-drawn não existe** (Primer/GitHub); Fabricante não aparece na Equipe (#377) |
| Relatório 21h50 | não existe | — | — | Agendar, se for requisito |
| Gate aprovado-humano | `HUMAN_LABEL` "legado: não é mais exigido" | — | não | Ver riscos |
| `fabrica/` + papéis por profissão | `fabrica/papeis.py` (po, arquiteto, dev, qa, revisor, release) | CLI separado | **não usado pelo loop**; `agents.py` ainda é da era finanças | Unificar com `fabricante.py` ou arquivar |

### Esteira: distância ao MVP

MVP definido no próprio repo: "3 clientes pagando a segunda mensalidade"; promessa: 3 cortes/semana/cliente em 48 h, R$ 1,5–3 mil/mês. `dotnet build` 6 s, 36/36 testes, e2e com vídeo real.

| Capacidade | Estado |
|---|---|
| Ingest → transcrição (whisper.cpp) → corte de silêncio → legendas → render 9:16; multi-tenant, JWT, filas, orçamento por job | **pronto** (Fase 0) |
| Copy por rede (template) | parcial (PR #2); worker `Copy` com LLM faltando |
| Corte de erros, spring/zoom, reframe face-track, oferta/preço, métrica no painel, estilo mapa | **PRs abertos** #3–#8 |
| Render 16:9/1:1, `verify` (duração, LUFS), clips com nota, extração de molde, planner LLM, descoberta de virais | faltando (pedidos vermelhos) |
| Painel de aprovação + approve/publish, conectores YouTube/Reels/TikTok, worker `Publish` | faltando (stub `NotImplementedSocialPublisher`) |
| Cobrança, storage remoto, relatório semanal ao cliente, taxa de promessa cumprida medida | faltando |

Estimativa: **30–40 PRs** na granularidade atual; caminho crítico Copy → render multi-aspecto/verify → painel/approve → YouTube (assisted) → relatório → cobrança. Nenhum dos 6 PRs abertos encurta "publicado sem o cliente tocar".

## 5. Conflitos e riscos

### Contradições

| Tema | Doc / regra | Código | Evidência |
|---|---|---|---|
| Plano Max × API | "roda no Max, não via API" | **Default do código é a API** (`CIRCULO_CODE_AGENT_USA_API="1"`, provedor `anthropic`); só vira assinatura com `CIRCULO_CONTA=max`. No env há as duas chaves | `self_dev.py:193-197`, `llm.py:49,98`, `conta.py:44-52` |
| Relogin automático | "o loop cuida do login" | abre Terminal com `claude auth login` e **espera clique no navegador**; token de 1 ano não configurado | `conta.py:81-101,150-166` |
| Gate aprovado-humano | "código de dinheiro nunca entra sem revisão humana" (`agents.py:233`) | `HUMAN_LABEL` legado, `human_approved()` nunca chamada; gate passa `touches_money_code=False` **fixo** | `merge_gate.py:37,127,211-219` |
| Constituição intocável | job de CI + convenção | **cumprido** (todos os commits nela são humanos), mas `CIRCULO_PROTEGIDOS`/`CIRCULO_REQUIRED_CHECKS` por env redefinem a lista; main sem branch protection; CODEOWNERS inativo | `merge_gate.py:45-54`, `gh api …/protection` → 404 |
| Missão do produto | README: fábrica de software | `pyproject`/descrição do repo: "controle financeiro da família"; fumaça da CI é `add "38,90 ifood almoço"`; 3 missões no mesmo código | `pyproject.toml:4`, `ci.yml:46`, `policy.py:71-88` |
| "PR só nasce com todos os gates" | regra | Validador LLM **aprova por default** em falha/timeout/JSON inválido; `LocalJev` aprova tudo ≤400 linhas | `validador.py:14`, `decision.py:319-324` |
| "Sem limite de tokens" × "orçamento não pode ser desligado" | `policy.py:4` guarda uma proteção | `budget.py` padrão `ilimitado`: teto duro só vale em modo `limite` | `budget.py:34`, `policy.py:17` |
| Jev revisa o merge | README | Jev vê 3 números (`tests_ok`, `lines_changed`, `touches_money_code`), nunca o diff | `agents.py:224-238` |
| Fronteira Localiza | "nada da Localiza" | sem código/credencial; **contexto do empregador no repo público**: "migração Blip → Amazon Connect", "segunda via de boleto", `aws connect list-contact-flows`, GAIA (`assuntos.py:1`, `trabalho.py:34-48`, `trabalho.html`, `perguntas.py:288`, `docs/evolucao.md:225` "framework GAIA da Localiza"); no banco local 1.163 linhas citam Localiza | — |

### Agentes pisando no trabalho um do outro

- Partição do Developer paralelo é por `modulo`/pegada estimada, não lock de arquivo; conflito só é tratado depois no gate. 0 PRs devolvidos por conflito em 7 d, mas **80 merges adiados por "branch atrás da main: CI roda de novo"** (retrabalho de CI, 49 na tabela `merges`).
- Mesmo item virando PR repetido: `fix-120` ×16, `fix-95` ×11, `fix-94` ×11 (madrugada de 21/10, 31 PRs recusados); lições #47/#59/#60 "corrigidas" 2–7 vezes.
- Duplicação: `def _git` em **12 módulos**; 3 memórias (`memoria.py`/`memory.py`/`graft.py`); 6 módulos de lições; 4 de validação; 6 de tela; 48 linhas idênticas em ≥3 templates HTML; >30 micro-módulos nascidos de "pergunta #N".

### Gates contornáveis e segurança (repo público)

| Sev. | Achado | Evidência |
|---|---|---|
| **Alta** | PR de **fork** com branch `circulo/…` pode ser mergeado automaticamente: o gate só checa o prefixo do `head_ref`, não `head.repo`/autor; basta CI verde, ≤800 linhas, 1 arquivo em `tests/`; merge com o token admin do loop | `merge_gate.py:142-146,417-420`; `revisor.py:372-373` |
| **Alta** | Trava de dinheiro anulada pelo próprio gate (`touches_money_code=False` fixo); `aprovado-humano` legado | `merge_gate.py:213` |
| **Alta** | Main sem proteção (404), sem rulesets; se o loop cai ou outro processo tem o token, mergeia o que quiser | `.github/CODEOWNERS` inativo |
| Média | Scanner de segredos só pré-PR, só regex (sem base64/concat), só dentro do loop; CI não roda scanner; `gitleaks` ausente | `segredos.py:28-39`, `validador.py:208` |
| Média | Limite de 800 linhas por PR, não cumulativo (o `fatiador` divide por desenho) | `merge_gate.py:206-209` |
| Média | Gate reconfigurável por variável de ambiente (`CIRCULO_PROTEGIDOS`, `CIRCULO_REQUIRED_CHECKS`, `CIRCULO_HARD_DAILY_TOKENS`) | `merge_gate.py:45-54` |
| Média | Validador e LocalJev degradam para "mais permissivo" em falha | `validador.py:14`, `decision.py:319-324` |
| Média | `GITHUB_TOKEN` (PAT) em texto no env e no ambiente do launchd (`launchctl print`) | `merge_gate.py:584-590` |
| Baixa | CI usa `pull_request` sem secrets e `permissions: read` — fork não acessa segredos (OK) | `ci.yml:3-11` |

### Dados e segredos

- **Nenhum segredo real** no repo nem no histórico (só fixtures de teste); nenhum `.db`/`.env`/`data/` jamais commitado; `data_fix_out.txt` na raiz (0 bytes, lixo).
- Sem dados pessoais/financeiros da família (0 CPF, 0 "R$" em docs); `policy.py:71-88` revela perfil de consumo (filho, casa_obra, lojas de BH) e `jobs_rotulados.json` tem 31 frases de exemplo.
- Contexto do empregador (acima) e 1 caminho absoluto `/Users/cassiomatos/…` em `docs/licoes.md:52`.
- Licenças: skills vendorizadas (MIT) fora do `THIRD_PARTY_NOTICES.md`; `awesome-claude-code` (uso não comercial) baixado em runtime como descoberta; catálogo `skills.py` com entradas de licença "desconhecida" instaláveis por PR.

### Dependências frágeis / dependência oculta do humano

| Dependência | Situação |
|---|---|
| Máquina | LaunchAgent de usuário no Mac (morre no logout; `hibernatemode 3`); Docker existe e não é usado |
| Sessão Claude | sem token de 1 ano → queda exige clique |
| Gate no loop | loop caído = nada mergeia; PRs do loop ficam órfãos |
| Esperas por humano | 137 ocorrências de `aprovar/humano/precisa_de_voce` (0 `input()`): chave/login, risco HIGH do Developer, CI bloqueado por cobrança, oscilação/estagnação "só humano reabre", merge na Esteira, lançar versão/tag, re-run de flake |
| Dependências Python | `dependencies = []`, extras só com piso; Claude Code CLI `latest` (quebra `auth status`/`-p`/`--allowedTools`); Playwright sem `install chromium` na CI (gate de telas vira `SEM_NAVEGADOR`) |
| Jev | sem `TYPESAFE_API_KEY`, `LocalJev` aprova |
| Disco/branches | 15 GB, 4.695 branches locais, 0 limpas |

## 6. Melhorias priorizadas (impacto × esforço)

| # | Melhoria | Impacto | Esforço | Quem |
|---|---|---|---|---|
| 1 | Destravar o Developer (suíte local que trava) | alto | baixo | loop (pedido na caixa) + humano zera o incidente |
| 2 | Portão de plano do Fabricante tolerante + refila dos 27 pedidos | alto | baixo | loop |
| 3 | CI verde sozinha: flake → re-run, main vermelha → lição, tag faltante | alto | baixo | loop (gate é constituição: parte humana) |
| 4 | Cortar ruído: arquivar missão Finanças/Meu trabalho, Redator 1×/dia, dedupe de lições | alto | médio | loop + humano decide o arquivamento |
| 5 | Fechar o gate: origem do PR, dinheiro/constituição com `aprovado-humano`, branch protection, scanner na CI | alto (segurança) | médio | **humano** (constituição) |
| 6 | Medir e cortar tokens: Fabricante em `llm_calls`, cache de validação, estudo sem fonte encerra cedo | médio | médio | loop |
| 7 | Operação sem o dono: token de 1 ano, Mac sem dormir/container, poda de snapshots e branches | médio | baixo | humano (token/pmset) + loop (poda) |

### 6.1 Destravar o Developer
- **Problema**: etapa `corrigir_codigo` isolada por 320 giros; o loop não se corrige, 49 itens prontos, PR #340 preso.
- **Evidência**: incidente #10 (`TimeoutExpired` 900 s ×7 desde 01:16); reprodução local hoje (§2.3): suíte completa leva 20 min 34 s (1.607 verdes) e pendurou 2× com 0 % de CPU; `test_validador_segredos.py` sozinho gasta 413 s; lição #96 aberta.
- **Solução**: (a) corrigir o vazamento do painel em thread de `verificacao.verificar` (fechar `srv` no `finally`) e cortar `test_validador_segredos.py` (6 × 60–100 s: simular em vez de executar); (b) `pytest-timeout` com `timeout=120` por teste (falha nomeada em vez de suíte pendurada); (c) marcar testes que invocam ferramenta real (dotnet/node/claude) como `skipif` fora da CI ou em `-m lento`, rodando no Developer só a suíte rápida; (d) `self_dev.verificar`: `timeout` 900 → 600 e registrar o último teste iniciado no incidente.
- **Como o loop faz sozinho**: pedido na caixa (`pedido_cassio`) com o teste nomeado; o Developer (depois de o humano zerar o incidente #10 ou o Médico escalar) abre o PR; `reproducao` prova com o teste travando na main.
- **Gate**: `developer:testes` ok em 3 giros seguidos, duração da suíte < 600 s registrada em `verificacoes`; incidente #10 "não ocorre há 200 giros".
- **Executado em 2/11 (1.76.5, branch `cassio/destravar-developer`)**: causa real encontrada — com o `codex` no PATH do Mac, cada `revisar_pr` dos testes chamava o revisor externo de verdade (2,7 s × centenas de chamadas); desligado no conftest e no ambiente dos testes do Developer. Fluxos SSE do painel agora encerram com o servidor (`circulo/servidor.py`), `verificacao.verificar` e as fixtures fecham o socket; `pytest-timeout` (300 s) e `faulthandler` (240 s) por teste; prazo estourado em `SelfDeveloper.verificar` vira reprovação `developer:testes` com o fim da saída (via `rodar_com_prazo`, que mata o grupo de processos), prazo em `CIRCULO_TESTES_PRAZO`. Resultado local: ver CHANGELOG 1.76.5.

### 6.2 Portão de plano do Fabricante
- **Problema**: 94 % dos planos reprovados por formato; 27/34 pedidos da Esteira esgotados; taxa de promessa cumprida ≈ 21 %.
- **Evidência**: `etapas_repo` `plano` 149 falhas / 10 ok; motivos `passo sem 'verificar'` (67×), `plano sem a lista 'Arquivos:'`; kv `fabrica_wip` com `tentativas=3`; lição #98 (22 oc.).
- **Solução**: prompt do plano com exemplo literal do formato; validador aceita sinônimos (`verificar|validar|testar|conferir`) e deriva `Arquivos:` dos passos quando falta; uma reprovação de formato **não consome tentativa**; comando `circulo refilar <projeto>` zera `tentativas` dos vermelhos; ordem da fila por dependência (pedidos "Bloqueado:" entram atrás do que os destrava).
- **Como o loop faz sozinho**: pedido na caixa; `fabricante.py` não é constituição; teste novo reproduz os 67 planos reprovados por `verificar`.
- **Gate**: `fabrica:plano` ok ≥ 80 % em 24 h; ≥ 3 pedidos entregues/dia; `promessa_cumprida` sobe no Norte.

### 6.3 CI verde e se mantendo verde sozinha
- **Problema**: flakes derrubam main/PRs; o gate não re-executa; falha na main não vira lição; re-run manual esconde histórico; v1.76.3 sem tag.
- **Evidência**: `Barrier(2, timeout=5)` em `tests/test_capacidade.py:112/121` (2 quedas em 25 runs, 60 rodadas por run); flake NuGet corrigido só pelo humano; lição #50 parada desde 25/10; `merge_gate.py:275/542` só refaz jobs não iniciados.
- **Solução**: (a) `Barrier` timeout 5 → 30 s e `pytest-rerunfailures` (1 retry) só nos testes marcados `paralelismo`; (b) regra: falha de CI em teste com lição `evidenciada` como flaky → `rerun-failed-jobs` 1× antes de chamar o Developer; (c) `_vigiar_main` abre lição + item quando push na main fica vermelho; (d) `Release` também roda em `workflow_dispatch` para taggear versão perdida; (e) fixture de teste nunca invoca ferramenta real do cliente (já é lição no CHANGELOG, virar checagem no `escudo`).
- **Como o loop faz sozinho**: (a), (c), (e) são código fora da constituição; (b) e (d) tocam `merge_gate.py`/`.github` → PR `cassio/` do humano.
- **Gate**: 7 dias com main 100 % verde sem re-run manual; `attempt > 1` = 0; toda falha na main com lição em < 1 h.

### 6.4 Cortar o ruído e devolver foco ao produto
- **Problema**: 27 % dos commits são ruído; 93,6 % dos tokens em `evoluir_loop`; três missões no mesmo código; lições reincidentes consumindo PRs.
- **Evidência**: 22 PRs de docs/semana; 166 propostas financeiras em 7 d para projeto pausado; #47/#59/#60; 38 itens `referencia` gerados por garimpo; `desfechos.rendeu` 99 %.
- **Solução**: (a) arquivar a missão "Finanças da família" e a tela "Meu trabalho" (mover para repo privado ou `_arquivo/`), trocar descrição do repo/pyproject; `propor_feature` nunca roda em projeto `pausada=1`; (b) Redator: 1 PR/dia e só se mudou algo além de contagens; (c) cota de itens `referencia` 3/dia e classe Jev `ferramenta` só com fila de produto vazia; (d) `Licoes.contexto` exclui `obsoleta`; lição reincidente ≥ 2× bloqueia novo PR "de correção" e vira item estrutural com causa raiz obrigatória; (e) Norte: alerta se produto < 50 % dos commits do loop em 2 dias (regra da janela).
- **Como o loop faz sozinho**: (b), (c), (d), (e) são itens normais; (a) é decisão do dono (pedido na caixa).
- **Gate**: fração de produto ≥ 50 % e ruído ≤ 10 % nos commits do loop em janela de 2 dias; 0 PRs para lição já `evidenciada`.

### 6.5 Fechar o gate de segurança (humano — constituição)
- **Problema**: merge automático explorável por fork; dinheiro/constituição sem aprovação humana real; main aberta; segredos sem scanner na CI.
- **Evidência**: `merge_gate.py:142-146,213,417-420`; branch protection 404; `gitleaks` ausente; `validador.py:14` aprova em falha.
- **Solução**: (a) `open_prs()` lê `head.repo.full_name == CIRCULO_REPO` e autor = conta do loop; (b) `touches_money_code=bool(dinheiro)` e exigir label `aprovado-humano` para `finance.py/money.py` e constituição (o rótulo já existe); (c) ativar branch protection na main (repo público: disponível no Free) com os 7 checks obrigatórios e "no direct push"; (d) `gitleaks-action` no CI; (e) Validador em falha = **reprovado**, não aprovado; LocalJev nunca aprova merge.
- **Como o loop faz**: não faz — é constituição; o loop pode abrir o item e escrever os testes (PR de fork simulado recusado; PR de dinheiro sem label recusado), o humano mergeia por `cassio/`.
- **Gate**: testes acima verdes; `gh api …/protection` 200; 0 merges de PR cujo `head.repo` ≠ repo.

### 6.6 Medir e cortar tokens
- **Problema**: 21 % de desperdício mensurável; Fabricante invisível na medição; cache de LLM nunca ligou.
- **Evidência**: 24 revalidações (590 k), 63 sessões extra (537 k), 69 estudos com 0 fontes (~1,27 M), `llm_cache` 7 linhas / 0 acertos, `retry`=0, `kv.assinatura_tokens` só do dia.
- **Solução**: `registrar_llm` em `fabricante.py`/`fabrica_developer.py` com `job=fabrica` e `papel=fabricante`; Validador cacheia veredito por `sha` do diff; estudo com 0 fontes após 1ª busca encerra por regra (sem 2ª chamada); ligar `llm_cache` fora de sombra para prompts idênticos; `assinatura_tokens` por dia em tabela, não em kv sobrescrito; experimento (já existe, #326) mede tokens/PR mergeado.
- **Como o loop faz sozinho**: itens normais, fora da constituição.
- **Gate**: 100 % das chamadas com `job` preenchido; tokens por PR mergeado −20 % em 7 dias; revalidação do mesmo sha = 0.

### 6.7 Operação sem o dono
- **Problema**: 24×7 e relogin dependem do Mac acordado e de um clique; disco e branches sem poda.
- **Evidência**: launchd de usuário, `hibernatemode 3`, `conta.py:86-92`, `CLAUDE_CODE_OAUTH_TOKEN` ausente, 14 GB de snapshots, 4.695 branches locais, 2 worktrees órfãos.
- **Solução**: humano gera `claude setup-token` (1 ano) e põe no env; `caffeinate -s` no plist ou `pmset -c sleep 0`, ou mover para o container já existente numa máquina dedicada; loop: retenção de snapshots (7 dias + 1/semana), apagar branch após merge (API `deleteBranchOnMerge` + `git branch -D` local), `git worktree prune` diário no SRE.
- **Como o loop faz sozinho**: poda e prune são ações de risco baixo (`risco.py` hoje classifica "apagar branch" como alto: criar exceção para branch já mergeada).
- **Gate**: `circulo-dados` < 3 GB; branches remotas < 30; `conta_sessao.caiu_em` nunca com `precisa_de_voce` > 10 min.

---
Próximo passo sugerido ao dono: escolher por onde começar entre 6.1 (Developer) e 6.2 (Fabricante) — os dois são pequenos e destravam tudo o resto — e decidir 6.5 (segurança), que só o humano pode mergear.

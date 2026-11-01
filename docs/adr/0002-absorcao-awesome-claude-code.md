# ADR 0002 — Absorção: awesome-claude-code (lista curada)

- Status: aceito (01/11/2026)
- Fonte: https://github.com/hesreallyhim/awesome-claude-code
- Licença: CC BY-NC-ND 4.0
- Frentes: engenharia do loop, criação de produto, venda e marketing

## Contexto

Lista curada (≈57 mil estrelas) gerada de um CSV (`THE_RESOURCES_TABLE_NEW.csv`: nome, categoria, link, ativo, descrição, obsoleto). A licença proíbe uso comercial e obra derivada da LISTA; ler a lista para descobrir repositórios é permitido, redistribuí-la não. Por isso entra como fonte de descoberta, nunca como conteúdo copiado.

## Decisão — o que entrou

### ACC-1 — Garimpo lê o CSV da lista: recurso ativo, não obsoleto, de categoria útil vai para a fila com a frente do Jev

- Frente: engenharia do loop · alvo: `circulo` · prioridade: `loop`
- Como está na fonte: `THE_RESOURCES_TABLE_NEW.csv` (gera o README por `generate_readme.py`)
- Como entra: `absorcao.parse_awesome` lê o CSV; `varrer_ranking` manda até 3 por dia para a fila do garimpo, preferindo as categorias de orquestração, skills, memória, segurança, mídia criativa e testes; só o link e a descrição curta entram, como dado.
- Prova (validação automática): `tests/test_absorcao.py`

### ACC-2 — Esteira: agente verifica a própria interface no navegador (Playwright) antes de abrir PR do painel

- Frente: criação de produto · alvo: `esteira` · prioridade: `mvp`
- Como está na fonte: Dev Browser (SawyerHood/dev-browser): o agente dirige um navegador para checar o trabalho de UI
- Como entra: Quando o painel React de aprovação existir (Fase 1, item 5), teste e2e Playwright: login, lista de jobs, player do master, aprovar. Roda na CI da esteira; screenshot anexado ao PR como evidência.
- Prova (validação automática): `web/e2e/aprovacao.spec.ts`

### ACC-3 — Esteira: posts de lançamento por rede a partir de ganchos extraídos de posts virais

- Frente: venda e marketing · alvo: `esteira` · prioridade: `venda`
- Como está na fonte: LinkedIn Skills (sergebulaev/linkedin-skills): extrai fórmulas de gancho de posts virais e planeja a semana
- Como entra: No worker `Copy`, o mesmo molde da style bible vale para o texto: gancho, promessa e CTA extraídos do viral de referência viram template de copy por rede (limites de `network-specs.json`).
- Prova (validação automática): `tests/Esteira.UnitTests/Copy/CopyTemplateTests.cs`

## Descartado

- **Copiar ou republicar a lista** — CC BY-NC-ND: sem uso comercial e sem derivada
- **Ralph Wiggum, ralph-harness, Claude Code Harness** — o loop já roda processo novo por item em worktree próprio
- **Compound Engineering, Hivemind, roampal** — o loop já transforma erro em lição com prevenção e quarentena; reavaliar só se a taxa de reincidência não cair
- **capcut-cli, motion-skills, Vox director** — editor fechado ou vídeo gerado do zero; a esteira edita o vídeo bruto do cliente pelo molde do viral

## Consequências

A lista vira uma segunda fonte automática do garimpo (a primeira é o ranking, ADR 0003).

Validação: `circulo.absorcao.evidencias` marca cada técnica como `validada` só quando o PR do item foi mergeado e o arquivo da prova existe no repositório; o estado fica no kv `absorcao_evidencias` e no painel.

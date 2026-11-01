# ADR 0004 — Absorção: Wondel.ai Agent Skills

- Status: aceito (01/11/2026)
- Fonte: https://github.com/wondelai/skills
- Licença: MIT
- Frentes: venda e marketing, criação de produto

## Contexto

65 skills (51 de métodos consagrados de produto, marketing, UX e arquitetura; 14 metaskills de ponta a ponta). É a fonte que faltava para a frente de VENDA: oferta, posicionamento, conversão e preço.

## Decisão — o que entrou

### WON-1 — Esteira: página de oferta com posicionamento e preço definidos antes (obviously-awesome, monetizing-innovation)

- Frente: venda e marketing · alvo: `esteira` · prioridade: `venda`
- Como está na fonte: skills `obviously-awesome` (alternativas, valor único, cliente-alvo), `monetizing-innovation` (preço antes de construir), `hundred-million-offers`
- Como entra: `docs/oferta.md` na esteira com: alternativas que o cliente usa hoje (editor freelancer, CapCut, Opus Clip), valor único (replica o molde de um viral do nicho), público inicial e 3 planos por minutos de render; a landing e a cobrança (Fase 1, item 7) leem dele.
- Prova (validação automática): `tests/Esteira.UnitTests/Billing/PlanCatalogTests.cs`

### WON-2 — Esteira: métrica-chave única por estágio (lean-analytics) no painel: vídeos publicados por cliente por semana

- Frente: venda e marketing · alvo: `esteira` · prioridade: `venda`
- Como está na fonte: skill `lean-analytics`: uma métrica que importa por modelo de negócio e estágio
- Como entra: Endpoint `GET /metrics/weekly` por tenant: jobs concluídos, publicados e minutos de render; o painel mostra só a métrica-chave e a tendência.
- Prova (validação automática): `tests/Esteira.UnitTests/Metrics/WeeklyMetricsTests.cs`

### WON-3 — Entrevistas no formato Mom Test entram como pergunta do PM no conselho do loop

- Frente: venda e marketing · alvo: `circulo` · prioridade: `venda`
- Como está na fonte: skill `mom-test`: perguntar sobre comportamento passado, não sobre a ideia
- Como entra: Nova persona no Indagador (`cliente`) para produtos da fábrica: perguntas sobre o que o cliente já faz e já pagou; o Jev veta pergunta que pede opinião sobre a ideia (Noul `mom_test_valida`).
- Prova (validação automática): `tests/test_persona_cliente.py`

## Descartado

- **Skills de organização (traction-eos, high-output-management, team-topologies)** — o produto ainda é de uma pessoa; sem gatilho
- **Skills de código (clean-code, ddd, ddia)** — a esteira já fixa Clean Architecture no CLAUDE.md; o loop já tem superpowers no catálogo
- **Metaskills create-business/grow-business inteiras** — amplas demais para um PR; entram as peças com teste (oferta, métrica)

## Consequências

A frente de venda ganha artefatos verificáveis (catálogo de planos, métrica semanal) em vez de texto solto.

Validação: `circulo.absorcao.evidencias` marca cada técnica como `validada` só quando o PR do item foi mergeado e o arquivo da prova existe no repositório; o estado fica no kv `absorcao_evidencias` e no painel.

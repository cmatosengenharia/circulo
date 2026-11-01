# ADR 0005 — Absorção: claude-seo (e marketingskills)

- Status: aceito (01/11/2026)
- Fonte: https://github.com/AgriciDaniel/claude-seo
- Licença: MIT (marketingskills: licença não confirmada)
- Frentes: venda e marketing

## Contexto

Orquestrador de SEO com ≈24 sub-skills e nota de saúde 0–100 ponderada (conteúdo 23%, técnico 22%, on-page 20%, schema 10%, performance 10%, prontidão para IA 10%, imagens 5%). coreyhaines31/marketingskills (≈41 mil estrelas) tem o seo-audit mais instalado, mas a licença não foi confirmada: só referência.

## Decisão — o que entrou

### SEO-1 — Esteira: nota de SEO 0–100 da landing na CI, com os pesos do claude-seo e Core Web Vitals

- Frente: venda e marketing · alvo: `esteira` · prioridade: `venda`
- Como está na fonte: pesos da nota de saúde do claude-seo; metas LCP < 2,5 s, INP < 200 ms, CLS < 0,1
- Como entra: Script de CI que roda Lighthouse na landing e checa title/meta/H1/JSON-LD (SoftwareApplication com oferta); nota ponderada abaixo de 80 reprova o PR da landing. FAQPage e HowTo não contam (rich results retirados).
- Prova (validação automática): `web/seo/seo-score.test.ts`

### SEO-2 — Esteira: worker Copy gera título, descrição e hashtags com regras de SEO por rede

- Frente: venda e marketing · alvo: `esteira` · prioridade: `mvp`
- Como está na fonte: fórmulas de título e meta description da skill `seo` do ECC e do claude-seo (palavra-chave no início, limite de caracteres, sem clickbait vazio)
- Como entra: Etapa 8 do mapa (`copy`): a partir da transcrição e da palavra-chave do nicho, regra determinística valida o texto da LLM: limites do YouTube (título ≤100, descrição ≤5000), Instagram (legenda ≤2200, ≤30 hashtags), TikTok (≤2200); fora do limite → corta ou refaz uma vez.
- Prova (validação automática): `tests/Esteira.UnitTests/Copy/CopyRulesTests.cs`

## Descartado

- **seo-local, seo-maps, seo-hreflang, seo-ecommerce** — produto SaaS de uma língua, sem loja física; sem gatilho
- **15 agentes de auditoria em paralelo** — custo alto para uma landing de uma página; a nota na CI cobre

## Consequências

Venda medida: a landing não sobe sem nota de SEO; o copy de cada vídeo publicado respeita os limites da rede.

Validação: `circulo.absorcao.evidencias` marca cada técnica como `validada` só quando o PR do item foi mergeado e o arquivo da prova existe no repositório; o estado fica no kv `absorcao_evidencias` e no painel.

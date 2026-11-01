# ADR 0006 — Absorção: Expo skills (oficial)

- Status: aceito (01/11/2026)
- Fonte: https://github.com/expo/skills
- Licença: MIT
- Frentes: criação de produto

## Contexto

Skills oficiais da Expo para app React Native (router, UI nativa, data fetching, web-to-native, EAS). A esteira ainda não tem app: o MVP é painel web + publicação por API.

## Decisão — o que entrou

### EXPO-1 — Skills da Expo no catálogo do loop, instaladas só quando um produto pedir app móvel

- Frente: criação de produto · alvo: `circulo` · prioridade: `loop`
- Como está na fonte: `npx skills add expo/skills`; skills expo-overview, expo-router, expo-ui, expo-data-fetching, expo-web-to-native
- Como entra: Entradas no `skills.CATALOGO` com área `mobile`; o Jev só as escolhe quando a tarefa fala de app, iOS, Android ou Expo. Regra registrada para o futuro app da esteira: começar pelo 'strangler fig' (casca nativa, telas web trocadas uma a uma).
- Prova (validação automática): `tests/test_skills_mobile.py`

## Descartado

- **App móvel da esteira agora** — fora do MVP: o cliente sobe vídeo e aprova no painel web
- **Skills de EAS (build, update, hosting)** — serviço pago da Expo; decidir só com app real e receita

## Consequências

Mobile fica pronto para o segundo produto da fábrica, sem custo de contexto hoje.

Validação: `circulo.absorcao.evidencias` marca cada técnica como `validada` só quando o PR do item foi mergeado e o arquivo da prova existe no repositório; o estado fica no kv `absorcao_evidencias` e no painel.

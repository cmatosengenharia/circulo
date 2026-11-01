# ADR 0009 — Absorção: Pipeline de vídeo open source (cortes, reframe, transcrição, postagem)

- Status: aceito (01/11/2026)
- Fonte: https://github.com/SamurAIGPT/AI-Youtube-Shorts-Generator
- Licença: MIT (Shorts Generator); Unlicense (auto-editor); MIT (whisper.net); AGPL-3.0 (postiz: só leitura)
- Frentes: criação de produto, venda e marketing

## Contexto

Para o MVP (vídeo, cortes, postagem), o que acelera não é skill: é algoritmo pequeno de repositórios de mídia. AI-Youtube-Shorts-Generator: LLM pontua trechos (score, gancho, motivo), funde quase-duplicados e recorta 9:16 seguindo o rosto com suavização. auto-editor: margem e mínimo de clipe (já portado). whisper.net: binding .NET do whisper.cpp. postiz: OAuth e upload por rede, mas AGPL.

## Decisão — o que entrou

### VID-1 — Esteira: cortes (clips[]) com nota de viralidade, gancho e motivo, e fusão de trechos sobrepostos

- Frente: criação de produto · alvo: `esteira` · prioridade: `mvp`
- Como está na fonte: AI-Youtube-Shorts-Generator (MIT): prompt de destaques (score, hook, reason por trecho) e junção de clipes quase duplicados
- Como entra: No `IEditPlanner` com LLM (Fase 1, item 2): `clips[]` com `score` 0–100, `hook`, `reason`; regra determinística funde clipes com sobreposição > 50%, descarta < 15 s ou > 60 s e mantém os 3 melhores. Registrar em THIRD_PARTY_NOTICES.md.
- Prova (validação automática): `tests/Esteira.UnitTests/Media/ClipSelectionTests.cs`

### VID-2 — Esteira: reframe 9:16 que segue o rosto com suavização (média móvel) e corte fixo por cena como fallback

- Frente: criação de produto · alvo: `esteira` · prioridade: `mvp`
- Como está na fonte: AI-Youtube-Shorts-Generator (MIT): detecção de rosto por quadro + suavização do centro do recorte
- Como entra: Detecção de rosto por processo externo (amostra 2 fps), centro do recorte suavizado (média móvel de 1 s, passo máximo por quadro), sem rosto → centro fixo da cena; vira filtro `crop` com expressão por tempo.
- Prova (validação automática): `tests/Esteira.UnitTests/Media/FaceReframeTests.cs`

### VID-3 — Esteira: conector YouTube por upload resumable e modo Assisted, sem código do postiz

- Frente: venda e marketing · alvo: `esteira` · prioridade: `mvp`
- Como está na fonte: YouTube Data API v3 `videos.insert` (upload resumable, 1.600 unidades de cota por upload); postiz (AGPL) lido só como referência de fluxo
- Como entra: `YouTubePublisher : ISocialPublisher` com OAuth por tenant (tokens cifrados em `SocialAccount`), upload resumable com retomada, Shorts quando 9:16 ≤ 60 s; sem credencial → modo Assisted (pacote com arquivo, copy e instruções). Teste com servidor HTTP falso.
- Prova (validação automática): `tests/Esteira.UnitTests/Publishing/YouTubePublisherTests.cs`

### VID-4 — Esteira: transcrição em processo pelo whisper.net quando disponível, CLI do whisper.cpp como fallback

- Frente: criação de produto · alvo: `esteira` · prioridade: `mvp`
- Como está na fonte: sandrohanea/whisper.net (MIT): bindings .NET com segmentos e timestamps
- Como entra: `WhisperNetTranscriber : ITranscriber` atrás de configuração (`Media:Transcriber=whispernet|cli`); mesmo contrato de palavras; teste compara as duas saídas no `samples/demo.mp4` com tolerância de 80 ms por palavra.
- Prova (validação automática): `tests/Esteira.UnitTests/Media/TranscriberParityTests.cs`

## Descartado

- **Código do postiz (AGPL-3.0)** — oferecer como serviço obrigaria abrir o código da esteira; só a leitura do fluxo
- **Modo padrão do Shorts Generator com MuAPI** — serviço pago de terceiro
- **whisperX (alinhamento forçado)** — só Python; reavaliar se a legenda palavra a palavra do whisper.cpp não bastar
- **auto-editor de novo** — margem e mínimo de clipe já portados no SilenceDetector

## Consequências

As quatro peças que faltam entre 'vídeo editado' e 'vídeo publicado' viram pedidos na esteira, cada um com teste.

Validação: `circulo.absorcao.evidencias` marca cada técnica como `validada` só quando o PR do item foi mergeado e o arquivo da prova existe no repositório; o estado fica no kv `absorcao_evidencias` e no painel.

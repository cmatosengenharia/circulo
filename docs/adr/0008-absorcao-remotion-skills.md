# ADR 0008 — Absorção: Remotion skills

- Status: aceito (01/11/2026)
- Fonte: https://github.com/remotion-dev/skills
- Licença: Remotion License (gratuita até 3 pessoas; empresa: US$ 0,01 por render, mínimo US$ 100/mês para automação)
- Frentes: criação de produto

## Contexto

O repositório oficial é remotion-dev/skills (≈6 mil estrelas em 01/11; nenhum repositório de skill do Remotion tem ≈15 mil — o número provavelmente é o do monorepo ou de uma cópia comunitária). Skills: best-practices, markup (timing, sequencing, silence-detection, captions, transitions), captions, create, render, saas. O CLAUDE.md da esteira proíbe o core do Remotion (licença comercial para produto que renderiza para clientes); o que serve são os PADRÕES, reimplementados em ffmpeg/Hyperframes.

## Decisão — o que entrou

### REM-1 — Esteira: limiar de silêncio adaptativo pelo loudnorm (padrão do silence-detection.md) no SilenceEditPlanner

- Frente: criação de produto · alvo: `esteira` · prioridade: `mvp`
- Como está na fonte: regra `silence-detection.md`: primeiro `loudnorm=print_format=json` para ler `input_thresh`, depois `silencedetect` com esse limiar
- Como entra: Hoje o limiar vem fixo do contrato (`params.silenceThresholdDb`). Medir `input_thresh` no ingest (já tem o WAV) e usar min(contrato, input_thresh) no `SilenceDetector`: em áudio baixo o limiar desce junto e a fala deixa de virar 'nada para manter'.
- Prova (validação automática): `tests/Esteira.UnitTests/Media/AdaptiveThresholdTests.cs`

### REM-2 — Esteira: legendas e camadas presas ao mesmo trecho do vídeo (padrão Sequence) no EDL e no TimelineMapper

- Frente: criação de produto · alvo: `esteira` · prioridade: `mvp`
- Como está na fonte: regras `display-captions.md` e `sequencing.md`: vídeo e legenda no mesmo `<Sequence>`, trim e velocidade no pai
- Como entra: No EDL, cada `keep[]` carrega as palavras e camadas dele; o `TimelineMapper` remapeia legenda, zoom e título pelo mesmo trim. Teste: cortar um trecho do meio não desalinha a legenda seguinte em mais de 1 frame.
- Prova (validação automática): `tests/Esteira.UnitTests/Media/TimelineMapperTests.cs`

### REM-3 — Esteira: transições e zoom com curva spring (interpolate + clamp) no render ffmpeg

- Frente: criação de produto · alvo: `esteira` · prioridade: `mvp`
- Como está na fonte: regra `timing.md`: `interpolate` com `Easing.spring({damping: 200})` e clamp nas duas pontas
- Como entra: Função de easing spring em C# gerando a expressão do `zoompan`/`scale` por frame (camadas `zoom` punch/kenburns da Fase 1); valores fora de [0,1] nunca saem (clamp).
- Prova (validação automática): `tests/Esteira.UnitTests/Media/SpringEasingTests.cs`

## Descartado

- **Remotion core, @remotion/renderer e Lambda** — licença comercial: um SaaS de vídeo automatizado paga por render; a esteira usa ffmpeg/Hyperframes
- **@remotion/whisper-webgpu** — exige GPU compatível e não roda em Linux arm64; a esteira já usa whisper.cpp
- **remotion-saas e Player** — deixaria o cliente renderizar no produto: caso explicitamente pago na licença
- **Agrupamento de legendas TikTok** — já portado (CaptionGrouper, THIRD_PARTY_NOTICES da esteira)

## Consequências

O vídeo ganha o 'acabamento Remotion' sem a licença: limiar adaptativo, legenda presa ao corte, movimento com spring.

Validação: `circulo.absorcao.evidencias` marca cada técnica como `validada` só quando o PR do item foi mergeado e o arquivo da prova existe no repositório; o estado fica no kv `absorcao_evidencias` e no painel.

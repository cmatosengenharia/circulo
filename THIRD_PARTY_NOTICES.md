# Avisos de terceiros

Técnicas portadas (reescritas, não copiadas) de projetos de terceiros. Cada uma tem o seu ADR em `docs/adr/`.

## Wondel.ai Agent Skills

- Fonte: https://github.com/wondelai/skills (ADR 0004)
- Licença: MIT
- Portado: skill `mom-test` → `circulo/persona_cliente.py` (persona `cliente` do conselho; Noul `mom_test_valida`).
  Só o método (perguntar sobre comportamento passado, não sobre a ideia); nenhum texto ou código da fonte foi copiado.

## Expo skills (oficial)

- Fonte: https://github.com/expo/skills (ADR 0006)
- Licença: MIT
- Portado: só as entradas do catálogo em `circulo/skills.py` (área `mobile`: expo-overview, expo-router, expo-ui,
  expo-data-fetching, expo-web-to-native) e a regra do strangler fig para o futuro app. Nenhum SKILL.md foi copiado:
  a cópia acontece por PR do item de instalação, com a licença conferida nele.

## Supabase agent skills (oficial)

- Fonte: https://github.com/supabase/agent-skills (ADR 0007)
- Licença: MIT
- Portado: só a entrada `postgres-best-practices` do catálogo em `circulo/skills.py` (SUPA-2: repositório, caminho
  `skills/supabase-postgres-best-practices` e licença). Nenhum SKILL.md foi copiado: a cópia acontece por PR do item
  de instalação, com a licença conferida nele.

## everything-claude-code (ECC)

- Fonte: https://github.com/affaan-m/everything-claude-code (ADR 0001)
- Licença: MIT
- Portado: skill `santa-method` → `circulo/revisao_dupla.py` (ECC-2: dois revisores, mesma rubrica, sem contexto
  comum, teto de rodadas). Só o método; nenhum texto ou código da fonte foi copiado.
- Portado: skill `continuous-learning-v2` → `circulo/licoes_confianca.py` (ECC-3: a confiança dos 'instintos' nasce
  baixa, sobe com confirmação, cai com contradição e promove acima de um limiar). Só o método; nada da fonte foi copiado.
- Portado: hook `gateguard-fact-force.js` → `circulo/gateguard.py` (ECC-5: a primeira edição de um arquivo existente
  espera o grep de quem o importa). Reescrito em Python; nenhum código da fonte foi copiado.

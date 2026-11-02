# Avisos de terceiros

Técnicas portadas (reescritas, não copiadas) de projetos de terceiros. Cada uma tem o seu ADR em `docs/adr/`.

## Wondel.ai Agent Skills

- Fonte: https://github.com/wondelai/skills (ADR 0004)
- Licença: MIT
- Portado: skill `mom-test` → `circulo/persona_cliente.py` (persona `cliente` do conselho; Noul `mom_test_valida`).
  Só o método (perguntar sobre comportamento passado, não sobre a ideia); nenhum texto ou código da fonte foi copiado.

## everything-claude-code (ECC)

- Fonte: https://github.com/affaan-m/everything-claude-code (ADR 0001)
- Licença: MIT
- Portado: skill `santa-method` → `circulo/revisao_dupla.py` (ECC-2: dois revisores, mesma rubrica, sem contexto
  comum, teto de rodadas). Só o método; nenhum texto ou código da fonte foi copiado.

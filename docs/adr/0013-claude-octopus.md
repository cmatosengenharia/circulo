# ADR 0013 — nyldn/claude-octopus: só o revisor cruzado de outro fornecedor

- **Status**: aceito (parcial, opcional) · **Data**: 2026-11-01 · **Versão**: 1.75.0
- **Fonte**: https://github.com/nyldn/claude-octopus (MIT, v11): 63 skills, 54 comandos, 31 personas, 12 fornecedores
  externos (Codex, Gemini/Antigravity, Copilot, Ollama…), conselho multi-LLM com quórum de 75 %.

## O que entrou
- `validador.revisor_externo`: se `codex` ou `gemini` estiver no PATH (e `CIRCULO_REVISOR_EXTERNO` ≠ 0), o mesmo prompt do
  Validador vai ao CLI externo; o veredito JSON entra como problemas concretos (prefixo "revisor externo (codex)") e
  reprova junto com o Validador. Nenhum instalado = nada acontece (Cássio: "opcional, só se houver Codex/Gemini
  configurado"). Falha, timeout ou JSON inválido nunca param a entrega.
- `validador.modelo_cruzado`: mesmo sem fornecedor externo, o Validador nunca revisa com o mesmo modelo do Developer
  (ideia central do octopus: "every model has blind spots"). Medido em `tecnica:revisao_cruzada`.

## O que ficou de fora e por quê
- Os 54 comandos `/octo:*`, personas, Double Diamond, Dark Factory, conselho com quórum: o loop já tem conselho
  (`conselho`/Indagador), fábrica (Developer+gate), e a regra de contexto mínimo — trazer 63 skills para `.claude/skills`
  faria o Jev escolher entre ruído.
- Roteamento de modelo por benchmark: o loop já tem `pick_model` pelo Jev com histórico por papel (`registro.historico`).
- Memória cross-sessão via plugins de terceiros: o loop tem `memoria.py` + graft.

## Consequências
Zero custo quando não há CLI externo; quando há, uma chamada a mais por PR, fora do orçamento de tokens da API (conta do
fornecedor). A medida de revisão cruzada passa a existir em toda entrega.

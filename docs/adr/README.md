# ADRs de absorção de repositórios

Gerados de `circulo/absorcao_fontes.py` por `python -m circulo.absorcao adr`.

| ADR | Fonte | Frentes | Técnicas | Descartes |
|---|---|---|---|---|
| [0001](0001-absorcao-ecc.md) | ECC — Everything Claude Code | loop, produto, venda | 7 | 6 |
| [0002](0002-absorcao-awesome-claude-code.md) | awesome-claude-code (lista curada) | loop, produto, venda | 3 | 4 |
| [0003](0003-absorcao-github-ranking-ai.md) | Github-Ranking-AI (Top100/Claude.md) | loop | 1 | 2 |
| [0004](0004-absorcao-wondelai-skills.md) | Wondel.ai Agent Skills | venda, produto | 3 | 3 |
| [0005](0005-absorcao-claude-seo.md) | claude-seo (e marketingskills) | venda | 2 | 2 |
| [0006](0006-absorcao-expo-skills.md) | Expo skills (oficial) | produto | 1 | 2 |
| [0007](0007-absorcao-supabase-agent-skills.md) | Supabase agent skills (oficial) | produto | 2 | 2 |
| [0008](0008-absorcao-remotion-skills.md) | Remotion skills | produto | 3 | 4 |
| [0009](0009-absorcao-pipeline-video-oss.md) | Pipeline de vídeo open source (cortes, reframe, transcrição, postagem) | produto, venda | 4 | 4 |

## ADRs de decisão (0010 em diante)

Escritos à mão, um por decisão. Cada ADR de skill absorvida diz: o que entrou, o que ficou de fora e por quê, e qual
medida prova que a técnica está ativa (`circulo tecnicas`, ponto `tecnica:<nome>` em `verificacoes`).

| nº | título |
| --- | --- |
| [0010](0010-superpowers.md) | obra/superpowers absorvido: plano e teste antes do código, verificação antes de declarar pronto, revisão por olhos novos |
| [0011](0011-karpathy-guidelines.md) | andrej-karpathy-skills absorvido: simplicidade e mudança cirúrgica como portões |
| [0012](0012-i-have-adhd.md) | i-have-adhd absorvido: resposta direta medida |
| [0013](0013-claude-octopus.md) | nyldn/claude-octopus: só o revisor cruzado de outro fornecedor |
| [0014](0014-fabricante.md) | Fabricante: o loop evolui repositórios cliente (primeiro produto: Esteira de Vídeo) — fecha o PRE-1 |
| [0015](0015-vender-resultado.md) | Vender resultado, não ferramenta: Norte do lado do cliente, promessa cumprida, classe Jev |

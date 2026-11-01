# ADR 0003 — Absorção: Github-Ranking-AI (Top100/Claude.md)

- Status: aceito (01/11/2026)
- Fonte: https://github.com/yuxiaopeng/Github-Ranking-AI
- Licença: MIT
- Frentes: engenharia do loop

## Contexto

Ranking gerado todo dia por GitHub Actions (cron 03:05 UTC, API de busca do GitHub ordenada por estrelas) em 15 categorias; `Top100/Claude.md` é uma tabela Markdown com posição, projeto, estrelas, forks, linguagem, issues, descrição e último commit. É a forma mais barata de saber o que está em alta sem gastar a cota de busca do loop.

## Decisão — o que entrou

### RANK-1 — Varredura diária do ranking Claude: quem subiu desde ontem e o que é novo vai para o garimpo

- Frente: engenharia do loop · alvo: `circulo` · prioridade: `loop`
- Como está na fonte: `Top100/Claude.md` (tabela) e `.github/workflows/auto-update.yml` (cron diário)
- Como entra: `absorcao.parse_ranking` lê a tabela (descrição com `|` não quebra a linha); `varrer_ranking` guarda as estrelas de cada leitura, ordena os novos pelo ganho de estrelas e manda até 5 por dia para a fila do garimpo, com a frente decidida pelo Jev.
- Prova (validação automática): `tests/test_absorcao.py`

## Descartado

- **As outras 14 categorias (LLM, RAG, MoE…)** — ruído para o objetivo; o garimpo por necessidade já cobre RAG e memória
- **Rodar o gerador próprio (source/process.py)** — duplicaria a busca que o ranking já publica pronta todo dia

## Consequências

A varredura periódica pedida (repos novos em alta) fica automática; o garimpo continua dirigido pela necessidade.

Validação: `circulo.absorcao.evidencias` marca cada técnica como `validada` só quando o PR do item foi mergeado e o arquivo da prova existe no repositório; o estado fica no kv `absorcao_evidencias` e no painel.

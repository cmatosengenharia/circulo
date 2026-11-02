# ADR 0015 — Vender resultado, não ferramenta

- **Status**: aceito · **Data**: 2026-11-01 · **Versão**: 1.76.0
- **Fonte**: pedido de Cássio "Vender resultado, não ferramenta" (tese de Julian Beck/Sequoia: a maior empresa da era da IA
  será um software que se apresenta como agência; para cada dólar em software, seis em serviço).

## Contexto
O Norte media só o lado do loop (PRs, lead time, fração de produto). Um loop que só olha os próprios PRs converge para
"mesclar PRs", não para "cliente atendido". A esteira nasce como primeiro produto, e a promessa dela precisa ser a
régua. Ordem pedida: C (confiabilidade e PRE-1) → A (Norte do cliente) → B (promessa) → D → G, E, F pelo idle.

## Decisão (o que entrou nesta versão)
| letra | o que | onde | prova |
| --- | --- | --- | --- |
| C | PRE-1: trabalhador que entrega `pedidos_repo` (já em 1.75: o Fabricante) | `fabricante.py` | `test_fabricante.py` |
| C | **Taxa de promessa cumprida** = pedidos de cliente entregues no prazo (48 h, kv `promessa_prazo_h`) e sem intervenção ÷ abertos (7 dias); meta 90 %; no Norte e no painel (`/api/norte`, `lado: cliente`) | `resultado.promessa_cumprida` | `test_resultado.py` |
| C | Falha de entrega para cliente (pedido esgotou 3 tentativas) = lição **estrutural** com item de prevenção, acima de lição interna | `fabricante._vermelho` → `licoes` | `test_pedido_que_esgota_*` |
| A | 3 resultados do lado do cliente no Norte: promessa cumprida, pedidos de cliente entregues/semana, publicações/semana nos canais-piloto (reportadas por arquivo `tipo: resultado` na caixa: `projeto; metrica; valor`) | `resultado.medir` ← `norte.medir` | `test_norte_ganha_tres_*` |
| A/B | **Classificação Jev** de cada item pendente: `resultado` / `confiabilidade` / `ferramenta` (pergunta `classe_do_item`, regra local por palavras; 1×/dia via `norte.cobrar(dl=…)`). A cota de produto (`norte.item_de_produto`) ordena resultado > confiabilidade > ferramenta: meta-trabalho puro perde prioridade | `resultado.classificar*` | `test_item_de_produto_poe_resultado_antes_*` |
| B | `PROMESSA.md` por produto com 5 campos (trabalho que substitui, resultado prometido, cadência, preço, o cliente nunca precisa); o Fabricante registra `fabrica:promessa_md` em toda entrega (evidência; não barra enquanto a esteira nasce). Esteira: escrito nesta versão | `resultado.promessa`, `esteira/PROMESSA.md` | `test_promessa_*` |
| D | Validador reprova landing/demo/README de oferta com título de "IA/plataforma/ferramenta" antes do resultado | `resultado.discurso_de_plataforma` ← `validador.revisar_pr` | `test_discurso_de_plataforma_*` |
| F | Garimpo ganha os temas "serviços operados por IA" e "skills de vídeo e motion"; a pesquisa semanal pergunta que trabalho pago por pessoa o concorrente substituiu e por quanto cobra | `garimpo.TEMAS`, `mercado.SYSTEM` | — |

## O que ficou para o loop (pedidos na caixa, mesma data)
D (MVP como serviço: entrada mínima + relatório semanal), G (dogfooding da esteira nos canais do Cássio; catálogo de 3–5
estilos animados com experimento; voz como entrada; corte de erros; funil de duas camadas; prova social no Norte),
E (catálogo de trabalhos ranqueado pelo Jev), skills da Wondel para revisar a PROMESSA.md (não estão no repositório;
entram pelo garimpo/skills quando aparecerem).

## Fora do alcance
Cobrar dinheiro real; publicar em canais de terceiros sem permissão permanente; prometer prazo a cliente antes de a taxa
passar de 90 % em teste. Código, credenciais e dados da Localiza não entram.

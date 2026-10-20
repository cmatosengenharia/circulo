# Círculo — sistema de design das telas do loop

> Fonte: `circulo/tema.py` (tokens e componentes) e este arquivo (regras). O mesmo sistema está publicado como Design System no Claude, com previews. Toda mudança de tela segue o que está aqui; cor nova entra em `tema.py` com o par de contraste, nunca solta numa página.

O sistema de design do loop (Círculo autoevolutivo Jev First), construído sobre os **primitives do Primer**, o sistema do GitHub: as mesmas cores de canvas, texto, borda, accent, done, attention, success e danger, nos temas claro e escuro; tipografia de sistema; raio 6/12 px; Labels em pílula. O loop fala a língua do GitHub (PRs, merges, CI), e as telas agora têm a mesma cara.

## Princípios

1. **Medido, não decorado.** Todo número na tela vem de um registro; nada é estimado para "ficar bonito". Um cartão sem dado diz "—", não inventa.
2. **Cor nunca é a única pista.** Cada tom de status tem glifo (✓ feito · ✕ recusado · ! atenção · ◆ em andamento), as legendas usam formas, botões têm foco (anel de 2 px em `accent`), pressionado e desativado visíveis.
3. **Contraste é regra, não gosto.** Texto e ícone de status ≥ 4,5:1 sobre a superfície e sobre o fundo suave do próprio chip, nos dois temas; bordas de componente e marcas ≥ 3:1 (`border`, `idle`); `line` só divide. O teste `tests/test_tema.py` barra qualquer par que falhe.
4. **Uma fonte só.** `circulo/tema.py` escreve o mesmo bloco de tokens e componentes em todas as páginas; nenhuma página define cor própria.
5. **Agentes são pessoas de um time.** Nomes de papel (Tech lead, Product owner, Arquiteto, Desenvolvedor, Revisor de código, QA e release, DevOps, SRE, Curador de lições), avatares com iniciais e cor do grupo; nunca nomes de função interna na interface.
6. **Irreversível é vermelho.** Parar o loop, fechar PR, tirar da fila: botão `perigo`. O primário (verde) é para seguir em frente.

## Cores

Os tokens têm nome de função, não de matiz: `jev` é "decisão", `llm` é "atenção/custo", `ok` é "entregue", `bad` é "falha/perigo". Use sempre o token; nunca um hex solto. Fundos suaves (`*-soft`) só sob texto no tom correspondente.

## Tipografia

Pilha de sistema (a do Primer), 14 px de corpo, sem fonte externa — as telas funcionam offline. Títulos de tela em 26/800; títulos de cartão 16/700; seções em caixa alta 12/600 com 0,6 px de espaçamento; código em mono 12,5.

## Componentes

- **Botão** (`.btn`): fundo `bg`, borda `border`, raio 6, 32 px de altura; `primary` verde para a ação principal; `perigo` fica vermelho no hover; desativado é tracejado, não transparente.
- **Rótulo / chip** (`.chip`, `.tag`): pílula com borda em `currentColor`, 12 px, glifo por tom.
- **Selo** (`.selo`): contador no menu "Precisa de você"; roxo (`jev`) normal, vermelho (`bad`) quando há urgente.
- **Cartão** (`.panel`, `.card`): superfície, borda `line` 1,5 px, raio 12, padding 14–18 px; um cartão de alerta usa borda esquerda de 5 px no tom.
- **Nav do topo** (`.topo`): fixa, marca à esquerda, telas no meio, estado à direita; a tela atual ganha borda `border` e fundo `bg`.

## O que não fazer

Gradientes, sombras fortes, emoji em cartões, fontes externas, cor como único sinal, nomes internos de agente na tela, número estimado apresentado como medido.

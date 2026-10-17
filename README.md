# Círculo — loop autoevolutivo Jev First

Loop infinito do Sistema de Controle da Vida. Recebe pedidos, decide tudo primeiro com o Jev,
entrega, aprende com as correções e evolui as regras de domínio **e** a si mesmo — com shadow mode,
guard de proteções e rollback automático.

## Rodar

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # sem dependências obrigatórias; [llm] adiciona o SDK da Anthropic
export TYPESAFE_API_KEY=...        # opcional: sem chave usa o decisor local (mesmo contrato)
export ANTHROPIC_API_KEY=...       # opcional: fallback LLM, só quando o Jev autorizar

circulo add "38,90 ifood almoço"   # enfileira
circulo run --painel               # loop infinito + painel em http://127.0.0.1:8765
circulo demo                       # loop acelerado com pedidos simulados, para ver o painel vivo
circulo respostas                  # o que o círculo respondeu
circulo status                     # painel + orçamento + versão da política
circulo resumo                     # resumo diário (também gerado sozinho)
pytest -q
```

Mensagens que ele entende: `38,90 ifood almoço` · `+5000 salário` · `corrige 12 mercado impulso` · `ok 12`.

## Um giro (tick)

1. Orçamento esgotado? → pausa (`pausado_orcamento`) e retoma sozinho após a meia-noite (America/Sao_Paulo).
2. Pedido na fila → Collector (Jev: tipo) → Categorizer (Jev: categoria ‖ tag numa chamada) → LLM só se o Jev estiver inseguro **e** `worth_spending` autorizar → grava em centavos dentro de transação; invariante violado desfaz o lançamento.
3. Sem pedido → evolução natural: Jev decide se roda (`should_run_idle`), qual tarefa (`idle_task`) e se vale o gasto (`worth_spending`).
4. Meta-Learner: descobre candidatos por SQL (custo zero) → `should_evolve` → guard → Reviewer Finance (replay do histórico + invariantes + Jev) → nível 1 aplica; nível 2 vai para **shadow**.
5. Shadow: mesma decisão real avaliada pela versão nova; promove só se a utilidade for maior.
6. Health Monitor: invariante violado ou taxa de correção subiu após mudança → **rollback automático**.
7. Métricas por tick; resumo diário em `data/resumos/AAAA-MM-DD.md`.

## O que a auto-evolução NÃO pode mudar (`policy.guard`)

Invariantes ligados · rollback ligado · limite diário de tokens (≤ teto do `CIRCULO_HARD_DAILY_TOKENS`) ·
limiares em [0,1] · `should_evolve.circle ≥ 0.7` · auto-accept ≥ 0.6 · intervalo ≥ 5s · categoria `outros`.
`finance.py` (cálculos e invariantes) não é editável pelos agentes.

## 24/7

- macOS: `deploy/com.circulo.loop.plist` → `~/Library/LaunchAgents/` e `launchctl load` (ajuste os caminhos).
- Linux/VPS: `deploy/circulo.service` (systemd).

Estado em `data/circulo.db` (SQLite/WAL). Matar o processo a qualquer momento é seguro: o evento em
andamento volta para a fila na próxima partida.

## CI

`.github/workflows/ci.yml` roda lint, testes (Python 3.11–3.13) e 50 giros do loop em todo push/PR.
PRs que mexem em `finance.py`, `money.py`, `policy.py`, `budget.py` ou `.github/` só passam com o label
`aprovado-humano` — é o gate que impede os agentes de alterarem dinheiro e proteções sozinhos.

## Gate de merge (no próprio círculo)

O GitHub Free não aplica proteção de branch em repositório privado, então o gate mora em `circulo/merge_gate.py`
e roda como tarefa de evolução natural (`revisar_prs`) quando `GITHUB_TOKEN` e `CIRCULO_REPO` estão definidos.

Regras duras (não evoluem; o arquivo é protegido pelo CI):
1. Só PRs de agente (branch `circulo/…`), sem rascunho.
2. Os 4 checks obrigatórios verdes na última execução, e nenhum outro check falhando.
3. Até 800 linhas.
4. Mexeu em `finance.py`, `money.py`, `policy.py`, `budget.py`, `merge_gate.py` ou `.github/` → precisa do
   label `aprovado-humano` colocado **por você** (`CIRCULO_HUMANO`), e não removido depois.
5. Reviewer Code (Jev) aprova — o Jev pode endurecer, nunca liberar o que as regras barraram.
6. Merge squash com o SHA avaliado travado: commit novo depois da avaliação faz o GitHub recusar.

Limite honesto: é convenção, não bloqueio do GitHub. Quem tem push direto (você, um token) ainda escreve na `main`.

## Painel local

`circulo run --painel` (ou `circulo painel` em outro processo) serve o painel em `http://127.0.0.1:8765`,
só na sua máquina.

**Tela de projetos** (`/`): cada pedido vira um card (tipo, status, pedido original, propósito, giros,
decisões, % sem LLM, evoluções, atividade nas últimas 24h; o mini-círculo gira no projeto em que o loop
está agora). O card "Novo pedido" manda o texto para o Intake, que classifica o tipo com o Jev. Se já existe
kit para o tipo (hoje: finanças), o projeto nasce ativo; senão fica "aguardando kit", registrado.

**Estado do loop ao vivo** (topo da tela de projetos, via SSE): Trabalhando (em qual projeto e etapa),
Rodando (entre giros, com contagem até o próximo), Modo seguro, Pausado por você, Pausado por orçamento
(com contagem até a meia-noite), Desligado (sem batimento há mais de 20s: o processo não está rodando) e
Sem conexão (o servidor do painel caiu). O loop emite batimento a cada 5s, inclusive descansando, e acorda
cedo quando chega pedido novo. Cada card mostra também o que o loop está fazendo com aquele projeto.

**Tela do projeto** (`/projeto/<id>`): Mostra o giro atual no círculo, cada decisão do Jev ao vivo (com confiança e se subiu
para LLM), saúde contra os limites, orçamento, o que aguarda você, evoluções e versões da política.

Controles que funcionam no loop de verdade:
- **Pausar / Retomar**: o loop para no próximo giro e confere o botão a cada 2s.
- **Modo seguro**: congela a evolução das regras e do próprio círculo (meta-learner, shadow, merges,
  features); pedidos continuam sendo atendidos e a saúde continua podendo fazer rollback.
- **Novo pedido**: entra na mesma fila das mensagens.

Os comandos exigem o cabeçalho `X-Circulo` e origem local, então outro site aberto no navegador não
consegue mandar comandos para o painel.

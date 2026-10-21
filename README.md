# Círculo — loop autoevolutivo Jev First

Um ecossistema que recebe qualquer pedido, transforma em **missão**, pesquisa o que existe de melhor, constrói,
mede, aprende e continua evoluindo — a missão e a si mesmo — sem esperar ninguém. Toda decisão passa primeiro
pelo **Jev** (TypeSafe); LLM só entra quando o Jev autoriza.

## Começar (configuração única)

```bash
git clone https://github.com/cmatosengenharia/circulo ~/Projects/circulo
cd ~/Projects/circulo
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[llm]"

circulo configurar     # cria ~/.config/circulo/env (permissão 600) — preencha as chaves e salve
circulo diagnostico    # o que está ligado, o que está parado e por quê (--testar chama as APIs)
circulo instalar       # roda 24/7 (launchd no macOS, systemd no Linux), com painel
```

Painel: **http://127.0.0.1:8765**. Depois disso, nada exige você: pedidos novos entram pelo card "Nova missão".

| Chave | Liga | Sem ela |
|---|---|---|
| `TYPESAFE_API_KEY` | Jev real | decisor local com o mesmo contrato |
| `ANTHROPIC_API_KEY` | motor das missões, pesquisa na web, evolução do harness | missões ficam registradas, sem construir |
| `GITHUB_TOKEN` + `CIRCULO_REPO` | gate de merge (PRs de agente entram sozinhos) | sem merge automático |
| `CIRCULO_REPO_DIR` + Claude Code (`claude`) | Developer: o loop corrige o próprio código por PR | sem autocorreção de código |
| `CIRCULO_CONTA=max` | tudo na assinatura do Claude (Max/Pro) pelo Claude Code, sem a API; o loop cuida do login (abre `claude auth login` no Mac quando a sessão cai; `claude setup-token` dá um token de 1 ano) | consumo pela `ANTHROPIC_API_KEY` |
| `graft` no PATH ([Graft](https://github.com/AEndrix03/Graft), `ops/instalar-graft.command`) | memória semântica local do time: vetores + grafo ao lado do FTS; item/estudo repetido dito com outras palavras é reconhecido; o Developer consulta e grava no mesmo grafo (perfil `circulo`) | memória do time só pelo índice de texto |

Para ver tudo funcionando sem chave nenhuma: `circulo demo` (LLM simulada, dados separados, rotulado no painel).

## Como funciona

**Um giro**: orçamento → pedido na fila (ou evolução natural) → missões evoluindo **em paralelo** → Meta-Learner
→ shadow → saúde (rollback) → descanso com batimento. Só pausa por orçamento (retoma à meia-noite) ou se você pausar.

**Cascata de custo (Jev First)**: regra/cache → Jev → LLM pequena → LLM grande. O Jev decide o degrau, o modelo,
se vale gastar, e confere a saída da LLM (formato, injeção, dados pessoais, aderência) antes de ela seguir.
Decisões repetidas descem a cascata sozinhas (destilação).

**Missão**: pesquisa na web → régua mensurável (com critérios **ocultos** que quem constrói não vê) → construção →
verificação → avaliação → **catraca** (versão pior é descartada, nada é apagado) → lição em quarentena.

**Como o loop sabe que acertou**: cada versão gera uma evidência — nota antes/depois (visível e oculta),
verificação, integração com missões ligadas e duas perguntas ao Jev em sentidos opostos que precisam concordar.
Bateu a meta com evidência: **missão cumprida**. Volta sozinha quando a pesquisa, uma missão ligada ou o tempo
trazem algo novo.

**Missões se conhecem**: o Jev decide a relação entre elas; missões ligadas compartilham memória e contexto,
ganham critério de integração na régua, trocam lições confirmadas e se reabrem quando a outra muda.

**O Loop é a missão zero**: tem roteiro (seus pedidos + erros recorrentes que ele registra), registro de erros,
quarentena com backoff para etapas que falham, e um Developer que corrige o próprio código por PR.

## Autonomia e guardrails

Nada espera você. Onde haveria uma aprovação, há evidência, recusa imediata ou nada:

- **Constituição** (`merge_gate.py`, `policy.py`, `budget.py`, `guardrails.py`, `self_dev.py`, `.github/`):
  o loop nunca altera. PR de agente que toca nela é recusado na hora (gate e CI), sem fila.
- **Código de dinheiro** (`finance.py`, `money.py`): entra sozinho só com o check **Evidência reforçada**
  (propriedades financeiras em 5.000 casos aleatórios) além dos testes.
- **Fora do alcance**: gastar dinheiro real, publicar, contatar terceiros. O loop entrega pronto e não executa.
- Catraca e critérios ocultos contra "trapaça na régua"; snapshots diários e antes de toda mudança de política
  (`circulo restaurar`); orçamento de mudanças; bloqueio de oscilação; alerta de estagnação; modo seguro.

Merge automático (GitHub Free não protege branch privada, então o gate mora no loop): só PR de agente
(`circulo/…`), checks obrigatórios verdes (`Testes 3.11–3.13`, `Constituição`, `Evidência reforçada`), até 800
linhas, revisão do Jev, merge com SHA travado.

## Painel

- **Missões** (`/`): estado do loop ao vivo (trabalhando, rodando, pausado, desligado…), e um card por missão com
  o indicador principal, versão, ciclos, evoluções, PRs, % sem LLM, erros, conexões e IAs usadas.
- **Missão** (`/missao/<id>`): o círculo tocando cada etapa de cada giro em tempo real, decisões ao vivo,
  autonomia (intervenções suas: meta zero), evidências, conexões, entrega (HTML isolado), régua, ciclos, pesquisa.
- **O Loop**: tudo isso para todas as missões, mais roteiro e erros registrados.

Só escuta em 127.0.0.1; comandos exigem cabeçalho próprio e origem local.

## Comandos

```
circulo configurar | diagnostico [--testar] | instalar | desinstalar
circulo run [--painel] | painel | demo
circulo add "38,90 ifood almoço" | respostas | status | resumo
circulo snapshot | restaurar <arquivo> | dev [--item N] | tick [-n N]
```

Estado em `data/circulo.db` (SQLite/WAL); entregas em `data/projetos/<id>/vN.*`. Matar o processo é seguro:
o que estava em andamento volta para a fila.

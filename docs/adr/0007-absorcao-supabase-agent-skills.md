# ADR 0007 — Absorção: Supabase agent skills (oficial)

- Status: aceito (01/11/2026)
- Fonte: https://github.com/supabase/agent-skills
- Licença: MIT
- Frentes: criação de produto

## Contexto

Skills `supabase` e `supabase-postgres-best-practices` (regras por impacto: consulta, conexão, segurança e RLS como CRITICAL). A esteira usa Postgres com filtro global de TenantId no EF Core: a lição útil é a defesa em profundidade.

## Decisão — o que entrou

### SUPA-1 — Esteira: Row Level Security por tenant no Postgres além do filtro do EF Core, com índice na coluna da política

- Frente: criação de produto · alvo: `esteira` · prioridade: `venda`
- Como está na fonte: regras `security-rls-performance` (indexar a coluna usada no USING) e o padrão `(select auth.uid()) = user_id` (avaliado uma vez por consulta)
- Como entra: Migration com `ENABLE ROW LEVEL SECURITY` nas tabelas com TenantId e política `USING (tenant_id = (select current_setting('app.tenant_id')::uuid))`; o DbContext seta `app.tenant_id` por conexão; índice em tenant_id. Teste com dois tenants e SQL cru: nenhum vê o outro.
- Prova (validação automática): `tests/Esteira.UnitTests/Persistence/RowLevelSecurityTests.cs`

### SUPA-2 — Regras de Postgres da Supabase no catálogo de skills do loop (substitui a entrada sem licença)

- Frente: criação de produto · alvo: `circulo` · prioridade: `loop`
- Como está na fonte: `supabase/agent-skills/skills/supabase-postgres-best-practices` (o catálogo apontava para `supabase/skills`, que não é o oficial)
- Como entra: Corrigir a entrada `postgres-best-practices` em `skills.CATALOGO`: repositório `supabase/agent-skills`, caminho certo, licença MIT.
- Prova (validação automática): `tests/test_skills_catalogo.py`

## Descartado

- **Supabase como backend da esteira** — a esteira já tem .NET + Postgres + RabbitMQ (ADR 0001 dela); trocar seria reescrever
- **Edge Functions, Realtime, Storage da Supabase** — mesma razão; sem gatilho

## Consequências

Isolamento entre clientes deixa de depender só do código: requisito para vender a mais de um tenant.

Validação: `circulo.absorcao.evidencias` marca cada técnica como `validada` só quando o PR do item foi mergeado e o arquivo da prova existe no repositório; o estado fica no kv `absorcao_evidencias` e no painel.

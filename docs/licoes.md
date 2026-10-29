# Lições

Cada erro que o loop cometeu vira uma lição com ponto de verificação; a lição só fecha com a correção validada e
evidenciada (o erro não voltou). Esta lista é o banco de lições como está hoje.

| # | Lição | Classe | Status | Ocorrências | Reincidências | Prevenção |
|---|---|---|---|---|---|---|
| 59 | developer:agente:maximo_de_passos | trabalho | validada | 23 | 12 | Checagem: teste tests/test_developer.py::test_licao_59_parada_no_maximo_de_passos_devolve_a_tarefa_ao_fatiador; não repe |
| 15 | rastro:lacuna | trabalho | sem_prevencao | 18 | 8 | Sem prevenção verificável: falta um teste de regressão (lição #15) ou checagem determinística; não repetir: rastro:cadei |
| 47 | loop:estagnado | estrutural | evidenciada | 12 | 5 | Já corrigido (PR #150 mergeado); não repetir: loop:progresso: havia trabalho pendente e nada avançou em 10 giros; causa  |
| 2 | corpo:validacao_falhou | estrutural | obsoleta | 8 | 4 | Obsoleta por TTL: 6 h sem reincidir com o caminho exercitado; reincide se a assinatura voltar |
| 60 | painel:frescor_atrasado | ambiente | evidenciada | 211 | 3 | Já corrigido (PR #176 mergeado); checagem: portão #36 teste de regressão marcado com a lição #60; não repetir: painel:fr |
| 50 | gate:main_vermelha | estrutural | sem_prevencao | 15 | 2 | Sem prevenção verificável: falta um teste de regressão (lição #50) ou checagem determinística; não repetir: gate:main: C |
| 22 | estudo:saida_invalida | estrutural | evidenciada | 14 | 2 | Já corrigido (PR #41 mergeado); não repetir: estudo:pedido: resposta sem JSON válido: tps://github.com/cgwalters-forge/a |
| 26 | developer:reparo:- aprendido#n: teste tests/test_vigia_trava_estado | trabalho | evidenciada | 3 | 2 | arquitetura (erro impossível): developer:reparo: ERROR: file or directory not found: tests/test_vigia_trava_estado.py::t |
| 36 | developer:abrir_pr:lint:F811 | trabalho | evidenciada | 28 | 1 | CI (teste ou lint): developer:abrir_pr: - lint e testes (iguais ao CI): tests/test_revisor.py:156:16: F811 Redefinition  |
| 29 | developer:sub_item_falhou | trabalho | evidenciada | 9 | 1 | arquitetura (erro impossível): developer:fatiador: sub-item #60 “Extrair features das tentativas do planejador (minutos, |
| 17 | gate:ci:teste:tests/test_arquitetura.py::test_padroes_ruins_nao_cresce | trabalho | evidenciada | 4 | 1 | Fechada: tests/test_arquitetura.py::test_padroes_ruins_nao_crescem passou no main (sha b91013bd13c1, exit 0 em 2 execuçõ |
| 4 | gate:ci:conflito com a main: o developer precisa trazer a  | trabalho | evidenciada | 3 | 1 | CI (teste ou lint): gate:ci: conflito com a main: o Developer precisa trazer a main para a branch |
| 73 | developer:testes:.................................................. | trabalho | evidenciada | 3 | 1 | Fechada: pytest --collect-only verde no main (sha e9657e0c2baf, exit 0); não repetir: developer:testes: ================ |
| 9 | developer:testes:ImportError | trabalho | evidenciada | 2 | 1 | CI (teste ou lint): developer:testes: ==================================== ERRORS ==================================== |
| 19 | developer:testes:timeout | ambiente | evidenciada | 2 | 1 | Já corrigido (PR #141 mergeado); não repetir: developer:testes: __ test_5xx_e_timeout_sao_repetidos_uma_vez_com_espera_c |
| 35 | developer:reparo:lint:F811 | trabalho | evidenciada | 2 | 1 | CI (teste ou lint): developer:reparo: ERROR: file or directory not found: tests/test_vigia_trava_estado.py::test_200_dec |
| 68 | incidente:c8d7b601a88abc41 | estrutural | evidenciada | 2 | 1 | Já corrigido (reincidência da lição #68 · erro não ocorre há 200 giros); não repetir: execucao:idle:planejar_roteiro: Va |
| 70 | developer:testes:lint:B905,E501,F541 | trabalho | evidenciada | 1 | 1 | Reaberta: o erro voltou na lição #79 (developer:testes:lint:B905,F811); não repetir: developer:testes: E       Assertion |
| 71 | developer:reparo:lint:B905,E501,F541 | trabalho | sem_prevencao | 1 | 1 | Sem prevenção verificável: falta um teste de regressão (lição #71) ou checagem determinística; não repetir: developer:re |
| 76 | developer:testes:lint:B905,E501,F401 | trabalho | evidenciada | 1 | 1 | Reaberta: o erro voltou na lição #79 (developer:testes:lint:B905,F811); não repetir: developer:testes: E       Assertion |
| 77 | developer:reparo:lint:B905,E501,F401 | trabalho | sem_prevencao | 1 | 1 | Sem prevenção verificável: falta um teste de regressão (lição #77) ou checagem determinística; não repetir: developer:re |
| 27 | developer:abrir_pr:- aprendido#n: teste tests/test_vigia_trava_estado | trabalho | evidenciada | 137 | 0 | CI (teste ou lint): developer:abrir_pr: ERROR: file or directory not found: tests/test_vigia_trava_estado.py::test_200_d |
| 53 | gate:ci:constituicao | estrutural | evidenciada | 42 | 0 | Já corrigido (PR #90 mergeado); não repetir: gate:ci: checks falhando: Evidência reforçada, Container, Testes (Python 3. |
| 63 | developer:testes:teste:tests/test_capacidade.py::test_desenvolvedor_pe | trabalho | evidenciada | 27 | 0 | Já corrigido (PR #119 mergeado); não repetir: developer:testes: tests/test_capacidade.py:112: AssertionError |
| 3 | developer:agente:saida_ilegivel | ambiente | evidenciada | 25 | 0 | Não repetir: developer:agente: isabled_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,"requested":{"backgro |
| 72 | developer:abrir_pr:lint:B905,E501,F541 | trabalho | evidenciada | 18 | 0 | CI (teste ou lint): developer:abrir_pr: --> tests/test_vigia_drena.py:93:89 |
| 54 | developer:agente:credit_balance_is_too_low | trabalho | evidenciada | 11 | 0 | Já corrigido (PR #91 mergeado); não repetir: developer:agente: credit balance is too low — Credit balance is too low |
| 43 | incidente:da69e2d5c9071056 | estrutural | evidenciada | 8 | 0 | Já corrigido (PR #42 · erro não ocorre há 200 giros); não repetir: execucao:meta: JSONDecodeError: Unterminated string s |
| 7 | developer:testes:teste:tests/test_jev_replay.py::test_200_decisoes_do_ | trabalho | evidenciada | 7 | 0 | Fechada: tests/test_jev_replay.py::test_200_decisoes_do_worth_spending_saem_da_duvida_concordando_com_a_regra passou no  |
| 56 | incidente:c2588a6ecd342aff | estrutural | evidenciada | 7 | 0 | Já corrigido (PR #92 mergeado); não repetir: execucao:idle:propor_feature: RuntimeError: claude -p: API Error: Claude's  |
| 78 | developer:abrir_pr:lint:B905,E501,F401 | trabalho | evidenciada | 7 | 0 | Já corrigido (PR #152 mergeado); não repetir: developer:abrir_pr: --> tests/test_vigia_drena.py:93:89 |
| 49 | incidente:03a21ad43587aafd | estrutural | evidenciada | 5 | 0 | Já corrigido (lição #49 · erro não ocorre há 200 giros); não repetir: execucao:idle:corrigir_codigo: RuntimeError: git w |
| 67 | developer:base:timeout | ambiente | evidenciada | 5 | 0 | Não repetir: developer:base: tests/test_capacidade.py:97: in test_arquiteto_estuda_varios_itens_ao_mesmo_tempo |
| 33 | developer:testes:teste:tests/test_espera.py::test_pr_29_reexecucao_de_ | trabalho | obsoleta | 4 | 0 | Não repetir: developer:testes: tests/test_espera.py:55: in test_pr_29_reexecucao_de_ci_por_atraso_da_main_e_a_espera_evi |
| 37 | developer:testes:teste:tests/test_reparo.py::test_commit_na_constituic | trabalho | obsoleta | 4 | 0 | Não repetir: developer:testes: tests/test_reparo.py:212: in test_commit_na_constituicao_depois_da_ultima_rodada_e_revert |
| 62 | developer:testes:teste:tests/test_capacidade.py::test_arquiteto_estuda | trabalho | evidenciada | 4 | 0 | Fechada: tests/test_capacidade.py::test_arquiteto_estuda_varios_itens_ao_mesmo_tempo passou no main (sha 4582daeebe18, e |
| 1 | incidente:ad2e0d2fe26d7ab2 | estrutural | evidenciada | 3 | 0 | Já corrigido (PR #4 mergeado); não repetir: execucao:idle:atualizar_corpo: RuntimeError: git checkout -q -B main 538d0f4 |
| 12 | developer:testes:teste:tests/test_reparo.py::test_constituicao_editada | trabalho | evidenciada | 3 | 0 | Fechada: tests/test_reparo.py::test_constituicao_editada_pelo_agente_e_revertida_em_cada_rodada_e_o_pr_sai passou no mai |
| 14 | developer:testes:teste:tests/test_vigia.py::test_porteiro_grava_a_deci | trabalho | evidenciada | 3 | 0 | Fechada: tests/test_vigia.py::test_porteiro_grava_a_decisao_sobre_a_pergunta_a_cada_ciclo passou no main (sha 39c2b8bf95 |
| 34 | developer:lint:lint:F811 | trabalho | evidenciada | 3 | 0 | Não repetir: developer:lint: tests/test_revisor.py:156:16: F811 Redefinition of unused `repo` from line 12: `repo` redef |
| 44 | corpo:regressao_pos_atualizacao | estrutural | evidenciada | 3 | 0 | Já corrigido (PR #86 mergeado); não repetir: corpo:evidencia: erros nos primeiros giros do código novo: ['meta:JSONDecod |
| 57 | gate:ci:ImportError | trabalho | evidenciada | 3 | 0 | Não repetir: gate:ci: checks falhando: Testes (Python 3.11), Testes (Python 3.12), Testes (Python 3.13) |
| 61 | developer:testes:teste:tests/test_jev_passe.py::test_po_manda_ao_jev_s | trabalho | evidenciada | 3 | 0 | Fechada: tests/test_jev_passe.py::test_po_manda_ao_jev_se_a_pergunta_ja_foi_feita_e_se_a_base_e_medida passou no main (s |
| 11 | developer:abrir_pr:- constituição intacta: altera a constituição: .gi | trabalho | evidenciada | 2 | 0 | Não repetir: developer:abrir_pr: - constituição intacta: altera a constituição: .github/workflows/ci.yml, circulo/self_d |
| 13 | developer:testes:teste:tests/test_fatiador.py::test_tres_falhas_divide | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_fatiador.py::test_tres_falhas_dividem_o_item_e_ele_nao_e_reexecutado_inteiro passou no main (sha 39c |
| 16 | incidente:a177d1fac10c373b | ambiente | evidenciada | 2 | 0 | Já corrigido (lição reclassificada como ambiente: não é erro do loop · erro não ocorre há 200 giros); não repetir: execu |
| 21 | developer:testes:teste:tests/test_tentativas_planejador.py::test_vigia | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_tentativas_planejador.py::test_vigia_cita_a_ultima_tentativa_real_e_nao_o_intervalo passou no main ( |
| 23 | developer:testes:teste:tests/test_arquitetura.py::test_nenhum_modulo_g | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_arquitetura.py::test_nenhum_modulo_gigante passou no main (sha d459a9f7f9f9, exit 0 em 2 execuções s |
| 24 | developer:testes:teste:tests/test_vigia_trava_estado.py::test_200_deci | trabalho | obsoleta | 2 | 0 | Não repetir: developer:testes: tests/test_vigia_trava_estado.py:79: in test_200_decisoes_de_vigia_trava_saem_da_duvida_c |
| 25 | developer:testes:teste:tests/test_vigia_trava_estado.py::test_estados_ | trabalho | obsoleta | 2 | 0 | Não repetir: developer:testes: tests/test_vigia_trava_estado.py:102: in test_estados_distintos_produzem_confianca_distin |
| 32 | developer:testes:teste:tests/test_arquitetura.py::test_referencias_de_ | trabalho | obsoleta | 2 | 0 | Não repetir: developer:testes: tests/test_arquitetura.py:95: in test_referencias_de_teste_em_licoes_existem |
| 40 | developer:testes:teste:tests/test_loop.py::test_giro_rapido_quando_ha_ | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_loop.py::test_giro_rapido_quando_ha_trabalho_e_descanso_longo_quando_nao passou no main (sha e9c1d3a |
| 46 | gate:ci:checks falhando: reprodução primeiro finished with | trabalho | evidenciada | 2 | 0 | Não repetir: gate:ci: checks falhando: Reprodução primeiro |
| 48 | gate:ci:teste:tests/test_orcamento.py::test_consumo_resume_a_medicao_e | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_orcamento.py::test_consumo_resume_a_medicao_e_sugere_limite_pelo_p90 passou no main (sha ca17717cf77 |
| 58 | developer:testes:teste:tests/test_ci_indisponivel.py::test_espera_de_c | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_ci_indisponivel.py::test_espera_de_ci_nao_iniciado_cai_assim_que_os_jobs_rodam passou no main (sha 4 |
| 64 | developer:base:teste:tests/test_memoria.py::test_estudo_parecido_e_ite | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_memoria.py::test_estudo_parecido_e_item_parecido passou no main (sha 4582daeebe18, exit 0 em 2 execu |
| 66 | developer:abrir_pr:- reprodução primeiro: os testes novos já passam n | trabalho | evidenciada | 2 | 0 | Não repetir: developer:abrir_pr: - reprodução primeiro: os testes novos já passam no código antigo, então não provam a m |
| 5 | developer:testes:teste:tests/test_camadas.py::test_merge_vira_marco_no | trabalho | evidenciada | 1 | 0 | Fechada: tests/test_camadas.py::test_merge_vira_marco_no_grafico passou no main (sha 960bf25528e3, exit 0 em 2 execuções |
| 6 | developer:lint:lint:B905 | trabalho | evidenciada | 1 | 0 | Não repetir: developer:lint: 269 /         falhou_antes = {n for s, n in zip(seq, nomes) if s["status"]["code"] == "ERRO |
| 10 | developer:reparo:- constituição intacta: altera a constituição: .gi | trabalho | evidenciada | 1 | 0 | Não repetir: developer:reparo: rodada 1/1 não resolveu; 15041 tokens |
| 20 | incidente:853e54efc4a445c1 | ambiente | evidenciada | 1 | 0 | Não repetir: execucao:idle:revisar_prs: URLError: <urlopen error timed out> |
| 28 | developer:reparo:ImportError | trabalho | evidenciada | 1 | 0 | Não repetir: developer:reparo: ERROR: file or directory not found: tests/test_vigia_trava_estado.py::test_200_decisoes_d |
| 30 | developer:testes:e errors ________________________ error at setup o | trabalho | evidenciada | 1 | 0 | Não repetir: developer:testes: ==================================== ERRORS ==================================== |
| 31 | developer:reparo:- lint e testes iguais ao ci : e errors __________ | trabalho | evidenciada | 1 | 0 | Não repetir: developer:reparo: ERROR: file or directory not found: tests/test_vigia_trava_estado.py::test_200_decisoes_d |
| 38 | developer:lint:tests/test_fatiador.py:n:n: invalid-syntax: unexpe | trabalho | evidenciada | 1 | 0 | Não repetir: developer:lint: tests/test_fatiador.py:68:1: invalid-syntax: Unexpected indentation |
| 39 | developer:reparo:- lint e testes iguais ao ci : tests/test_fatiador | trabalho | evidenciada | 1 | 0 | Não repetir: developer:reparo: ERROR: file or directory not found: tests/test_vigia_trava_estado.py::test_200_decisoes_d |
| 41 | developer:base:teste:tests/test_loop.py::test_run_forever_respeita_max | trabalho | evidenciada | 1 | 0 | Fechada: tests/test_loop.py::test_run_forever_respeita_max_ticks passou no main (sha 5699c3c2b39b, exit 0 em 2 execuções |
| 45 | planejador:saida_invalida | estrutural | evidenciada | 1 | 0 | Já corrigido (PR #87 mergeado); não repetir: planejador:saida: resposta sem JSON válido (cortada pelo limite de tokens o |
| 51 | developer:reparo:- tamanho: n linhas n: quebre em partes | trabalho | evidenciada | 1 | 0 | Não repetir: developer:reparo: rodada 1/1 não resolveu; 7610 tokens |
| 52 | developer:abrir_pr:- tamanho: n linhas n: quebre em partes | trabalho | evidenciada | 1 | 0 | Não repetir: developer:abrir_pr: - tamanho: 2516 linhas > 800: quebre em partes |
| 55 | developer:agente:deslogado | trabalho | evidenciada | 1 | 0 | Não repetir: developer:agente: deslogado — Failed to authenticate: OAuth session expired and could not be refreshed |
| 65 | developer:reparo:- reprodução primeiro: os testes novos já passam n | trabalho | evidenciada | 1 | 0 | Não repetir: developer:reparo: - reprodução primeiro: os testes novos já passam no código antigo, então não provam a mud |
| 69 | developer:agente:timeout | ambiente | evidenciada | 1 | 0 | Não repetir: developer:agente: on: sdk opt in required subagent stats:  — on": "sdk_opt_in_required", "subagent_stats":  |
| 74 | developer:reparo:- lint e testes iguais ao ci : ................... | trabalho | evidenciada | 1 | 0 | Não repetir: developer:reparo: --> tests/test_vigia_drena.py:93:89 |
| 75 | developer:abrir_pr:- lint e testes iguais ao ci : ................... | trabalho | evidenciada | 1 | 0 | Fechada: pytest --collect-only verde no main (sha 985793980f7b, exit 0); não repetir: developer:abrir_pr: ============== |
| 79 | developer:testes:lint:B905,F811 | trabalho | evidenciada | 1 | 0 | Não repetir: developer:testes: alvo.write_text(COM_ERROS) |
| 80 | developer:reparo:lint:B905,F811 | trabalho | evidenciada | 1 | 0 | Não repetir: developer:reparo: --> tests/test_vigia_drena.py:93:89 |
| 81 | gate:ci:teste:tests/test_autonomia.py::test_missoes_evoluem_em_paralel | trabalho | evidenciada | 1 | 0 | Fechada: tests/test_autonomia.py::test_missoes_evoluem_em_paralelo passou no main (sha d396c81b6f66, exit 0 em 2 execuçõ |
| 82 | developer:testes:lint:F811 | trabalho | evidenciada | 1 | 0 | Não repetir: developer:testes: tests/test_base_vermelha.py:51: |
| 83 | developer:agente:y_subagents:_n_completed:_n_failed:_n_ki | trabalho | evidenciada | 1 | 0 | Não repetir: developer:agente: y subagents: n completed: n failed: n ki — y_subagents": 0, "completed": 0, "failed": 0,  |
| 84 | developer:testes:lint:B007,B905,E501 | trabalho | evidenciada | 1 | 0 | Não repetir: developer:testes: E       AssertionError: B007 Loop control variable `i` not used within loop body |
| 85 | developer:agente:n_started_in_background:_n_max_depth:_n_ | trabalho | evidenciada | 1 | 0 | Não repetir: developer:agente: n started in background: n max depth: n  — 0}, "started_in_background": 0, "max_depth": 0 |
| 86 | developer:agente:unset:_n_started_in_background:_n_max_de | trabalho | evidenciada | 1 | 0 | Não repetir: developer:agente: unset: n started in background: n max de — "unset": 0}, "started_in_background": 0, "max_ |

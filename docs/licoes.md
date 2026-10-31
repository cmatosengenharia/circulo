# Lições

Cada erro que o loop cometeu vira uma lição com ponto de verificação; a lição só fecha com a correção validada e
evidenciada (o erro não voltou). Esta lista é o banco de lições como está hoje.

| # | Lição | Classe | Status | Ocorrências | Reincidências | Prevenção |
|---|---|---|---|---|---|---|
| 59 | developer:agente:maximo_de_passos | trabalho | validada | 24 | 12 | Checagem: teste tests/test_developer.py::test_licao_59_parada_no_maximo_de_passos_devolve_a_tarefa_ao_fatiador; não repe |
| 47 | loop:estagnado | estrutural | reincidente | 23 | 8 | Já corrigido (PR #244 mergeado); checagem: portão #28 teste de regressão marcado com a lição #47; não repetir: loop:prog |
| 15 | rastro:lacuna | trabalho | obsoleta | 18 | 8 | Obsoleta por prazo: evidenciada há 30 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar;  |
| 60 | painel:frescor_atrasado | ambiente | obsoleta | 274 | 6 | Obsoleta por prazo: evidenciada há 30 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar;  |
| 2 | corpo:validacao_falhou | estrutural | obsoleta | 8 | 4 | Obsoleta por TTL: 6 h sem reincidir com o caminho exercitado; reincide se a assinatura voltar |
| 50 | gate:main_vermelha | estrutural | sem_prevencao | 15 | 2 | Sem prevenção verificável: falta um teste de regressão (lição #50) ou checagem determinística; não repetir: gate:main: C |
| 22 | estudo:saida_invalida | estrutural | obsoleta | 14 | 2 | Obsoleta por prazo: evidenciada há 16781 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 73 | developer:testes:.................................................. | trabalho | evidenciada | 4 | 2 | Fechada: pytest --collect-only verde no main (sha 374a415dd938, exit 0); não repetir: developer:testes: ================ |
| 26 | developer:reparo:- aprendido#n: teste tests/test_vigia_trava_estado | trabalho | obsoleta | 3 | 2 | Obsoleta por prazo: evidenciada há 16700 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 36 | developer:abrir_pr:lint:F811 | trabalho | obsoleta | 28 | 1 | Obsoleta por prazo: evidenciada há 15029 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 29 | developer:sub_item_falhou | trabalho | obsoleta | 9 | 1 | Obsoleta por prazo: evidenciada há 15196 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 17 | gate:ci:teste:tests/test_arquitetura.py::test_padroes_ruins_nao_cresce | trabalho | evidenciada | 4 | 1 | Fechada: tests/test_arquitetura.py::test_padroes_ruins_nao_crescem passou no main (sha b91013bd13c1, exit 0 em 2 execuçõ |
| 4 | gate:ci:conflito com a main: o developer precisa trazer a  | trabalho | obsoleta | 3 | 1 | Obsoleta por prazo: evidenciada há 16580 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 9 | developer:testes:ImportError | trabalho | evidenciada | 2 | 1 | CI (teste ou lint): developer:testes: ==================================== ERRORS ==================================== |
| 19 | developer:testes:timeout | ambiente | obsoleta | 2 | 1 | Obsoleta por prazo: evidenciada há 7278 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 35 | developer:reparo:lint:F811 | trabalho | obsoleta | 2 | 1 | Obsoleta por prazo: evidenciada há 15099 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 68 | incidente:c8d7b601a88abc41 | estrutural | obsoleta | 2 | 1 | Obsoleta por prazo: evidenciada há 6753 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 70 | developer:testes:lint:B905,E501,F541 | trabalho | obsoleta | 1 | 1 | Obsoleta por prazo: evidenciada há 6158 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 71 | developer:reparo:lint:B905,E501,F541 | trabalho | sem_prevencao | 1 | 1 | Sem prevenção verificável: falta um teste de regressão (lição #71) ou checagem determinística; não repetir: developer:re |
| 76 | developer:testes:lint:B905,E501,F401 | trabalho | obsoleta | 1 | 1 | Obsoleta por prazo: evidenciada há 6158 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 77 | developer:reparo:lint:B905,E501,F401 | trabalho | sem_prevencao | 1 | 1 | Sem prevenção verificável: falta um teste de regressão (lição #77) ou checagem determinística; não repetir: developer:re |
| 27 | developer:abrir_pr:- aprendido#n: teste tests/test_vigia_trava_estado | trabalho | obsoleta | 137 | 0 | Obsoleta por prazo: evidenciada há 15944 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 53 | gate:ci:constituicao | estrutural | obsoleta | 42 | 0 | Obsoleta por prazo: evidenciada há 15988 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 63 | developer:testes:teste:tests/test_capacidade.py::test_desenvolvedor_pe | trabalho | evidenciada | 27 | 0 | Já corrigido (PR #119 mergeado); não repetir: developer:testes: tests/test_capacidade.py:112: AssertionError |
| 3 | developer:agente:saida_ilegivel | ambiente | obsoleta | 25 | 0 | Obsoleta por prazo: evidenciada há 18606 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 72 | developer:abrir_pr:lint:B905,E501,F541 | trabalho | obsoleta | 18 | 0 | Obsoleta por prazo: evidenciada há 6401 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 54 | developer:agente:credit_balance_is_too_low | trabalho | obsoleta | 11 | 0 | Obsoleta por prazo: evidenciada há 15978 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 43 | incidente:da69e2d5c9071056 | estrutural | obsoleta | 8 | 0 | Obsoleta por prazo: evidenciada há 16778 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 7 | developer:testes:teste:tests/test_jev_replay.py::test_200_decisoes_do_ | trabalho | evidenciada | 7 | 0 | Fechada: tests/test_jev_replay.py::test_200_decisoes_do_worth_spending_saem_da_duvida_concordando_com_a_regra passou no  |
| 56 | incidente:c2588a6ecd342aff | estrutural | obsoleta | 7 | 0 | Obsoleta por prazo: evidenciada há 15980 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 78 | developer:abrir_pr:lint:B905,E501,F401 | trabalho | obsoleta | 7 | 0 | Obsoleta por prazo: evidenciada há 6419 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 49 | incidente:03a21ad43587aafd | estrutural | obsoleta | 5 | 0 | Obsoleta por prazo: evidenciada há 16480 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 67 | developer:base:timeout | ambiente | obsoleta | 5 | 0 | Obsoleta por prazo: evidenciada há 7796 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 33 | developer:testes:teste:tests/test_espera.py::test_pr_29_reexecucao_de_ | trabalho | obsoleta | 4 | 0 | Não repetir: developer:testes: tests/test_espera.py:55: in test_pr_29_reexecucao_de_ci_por_atraso_da_main_e_a_espera_evi |
| 37 | developer:testes:teste:tests/test_reparo.py::test_commit_na_constituic | trabalho | obsoleta | 4 | 0 | Não repetir: developer:testes: tests/test_reparo.py:212: in test_commit_na_constituicao_depois_da_ultima_rodada_e_revert |
| 62 | developer:testes:teste:tests/test_capacidade.py::test_arquiteto_estuda | trabalho | evidenciada | 4 | 0 | Fechada: tests/test_capacidade.py::test_arquiteto_estuda_varios_itens_ao_mesmo_tempo passou no main (sha 4582daeebe18, e |
| 1 | incidente:ad2e0d2fe26d7ab2 | estrutural | obsoleta | 3 | 0 | Obsoleta por prazo: evidenciada há 19107 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 12 | developer:testes:teste:tests/test_reparo.py::test_constituicao_editada | trabalho | evidenciada | 3 | 0 | Fechada: tests/test_reparo.py::test_constituicao_editada_pelo_agente_e_revertida_em_cada_rodada_e_o_pr_sai passou no mai |
| 14 | developer:testes:teste:tests/test_vigia.py::test_porteiro_grava_a_deci | trabalho | evidenciada | 3 | 0 | Fechada: tests/test_vigia.py::test_porteiro_grava_a_decisao_sobre_a_pergunta_a_cada_ciclo passou no main (sha 39c2b8bf95 |
| 34 | developer:lint:lint:F811 | trabalho | obsoleta | 3 | 0 | Obsoleta por prazo: evidenciada há 16960 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 44 | corpo:regressao_pos_atualizacao | estrutural | obsoleta | 3 | 0 | Obsoleta por prazo: evidenciada há 16024 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 57 | gate:ci:ImportError | trabalho | obsoleta | 3 | 0 | Obsoleta por prazo: evidenciada há 15876 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 61 | developer:testes:teste:tests/test_jev_passe.py::test_po_manda_ao_jev_s | trabalho | evidenciada | 3 | 0 | Fechada: tests/test_jev_passe.py::test_po_manda_ao_jev_se_a_pergunta_ja_foi_feita_e_se_a_base_e_medida passou no main (s |
| 11 | developer:abrir_pr:- constituição intacta: altera a constituição: .gi | trabalho | evidenciada | 2 | 0 | Não repetir: developer:abrir_pr: - constituição intacta: altera a constituição: .github/workflows/ci.yml, circulo/self_d |
| 13 | developer:testes:teste:tests/test_fatiador.py::test_tres_falhas_divide | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_fatiador.py::test_tres_falhas_dividem_o_item_e_ele_nao_e_reexecutado_inteiro passou no main (sha 39c |
| 16 | incidente:a177d1fac10c373b | ambiente | obsoleta | 2 | 0 | Obsoleta por prazo: evidenciada há 18210 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 21 | developer:testes:teste:tests/test_tentativas_planejador.py::test_vigia | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_tentativas_planejador.py::test_vigia_cita_a_ultima_tentativa_real_e_nao_o_intervalo passou no main ( |
| 23 | developer:testes:teste:tests/test_arquitetura.py::test_nenhum_modulo_g | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_arquitetura.py::test_nenhum_modulo_gigante passou no main (sha d459a9f7f9f9, exit 0 em 2 execuções s |
| 24 | developer:testes:teste:tests/test_vigia_trava_estado.py::test_200_deci | trabalho | obsoleta | 2 | 0 | Não repetir: developer:testes: tests/test_vigia_trava_estado.py:79: in test_200_decisoes_de_vigia_trava_saem_da_duvida_c |
| 25 | developer:testes:teste:tests/test_vigia_trava_estado.py::test_estados_ | trabalho | obsoleta | 2 | 0 | Não repetir: developer:testes: tests/test_vigia_trava_estado.py:102: in test_estados_distintos_produzem_confianca_distin |
| 32 | developer:testes:teste:tests/test_arquitetura.py::test_referencias_de_ | trabalho | obsoleta | 2 | 0 | Não repetir: developer:testes: tests/test_arquitetura.py:95: in test_referencias_de_teste_em_licoes_existem |
| 40 | developer:testes:teste:tests/test_loop.py::test_giro_rapido_quando_ha_ | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_loop.py::test_giro_rapido_quando_ha_trabalho_e_descanso_longo_quando_nao passou no main (sha e9c1d3a |
| 46 | gate:ci:checks falhando: reprodução primeiro finished with | trabalho | obsoleta | 2 | 0 | Obsoleta por prazo: evidenciada há 16604 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 48 | gate:ci:teste:tests/test_orcamento.py::test_consumo_resume_a_medicao_e | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_orcamento.py::test_consumo_resume_a_medicao_e_sugere_limite_pelo_p90 passou no main (sha ca17717cf77 |
| 58 | developer:testes:teste:tests/test_ci_indisponivel.py::test_espera_de_c | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_ci_indisponivel.py::test_espera_de_ci_nao_iniciado_cai_assim_que_os_jobs_rodam passou no main (sha 4 |
| 64 | developer:base:teste:tests/test_memoria.py::test_estudo_parecido_e_ite | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_memoria.py::test_estudo_parecido_e_item_parecido passou no main (sha 4582daeebe18, exit 0 em 2 execu |
| 66 | developer:abrir_pr:- reprodução primeiro: os testes novos já passam n | trabalho | obsoleta | 2 | 0 | Obsoleta por prazo: evidenciada há 15091 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 89 | developer:testes:teste:tests/test_decision.py::test_jev_fora_do_ar_nao | desconhecida | sem_prevencao | 2 | 0 | Sem prevenção verificável: causa desconhecida, o timeout não prova erro de ambiente; falta tests/test_licao_89_regressao |
| 5 | developer:testes:teste:tests/test_camadas.py::test_merge_vira_marco_no | trabalho | evidenciada | 1 | 0 | Fechada: tests/test_camadas.py::test_merge_vira_marco_no_grafico passou no main (sha 960bf25528e3, exit 0 em 2 execuções |
| 6 | developer:lint:lint:B905 | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 18575 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 10 | developer:reparo:- constituição intacta: altera a constituição: .gi | trabalho | evidenciada | 1 | 0 | Não repetir: developer:reparo: rodada 1/1 não resolveu; 15041 tokens |
| 20 | incidente:853e54efc4a445c1 | ambiente | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 17655 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 28 | developer:reparo:ImportError | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 17134 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 30 | developer:testes:e errors ________________________ error at setup o | trabalho | evidenciada | 1 | 0 | Não repetir: developer:testes: ==================================== ERRORS ==================================== |
| 31 | developer:reparo:- lint e testes iguais ao ci : e errors __________ | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 17090 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 38 | developer:lint:tests/test_fatiador.py:n:n: invalid-syntax: unexpe | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 16919 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 39 | developer:reparo:- lint e testes iguais ao ci : tests/test_fatiador | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 16919 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 41 | developer:base:teste:tests/test_loop.py::test_run_forever_respeita_max | trabalho | evidenciada | 1 | 0 | Fechada: tests/test_loop.py::test_run_forever_respeita_max_ticks passou no main (sha 5699c3c2b39b, exit 0 em 2 execuções |
| 45 | planejador:saida_invalida | estrutural | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 16008 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 51 | developer:reparo:- tamanho: n linhas n: quebre em partes | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 16500 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 52 | developer:abrir_pr:- tamanho: n linhas n: quebre em partes | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 16500 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 55 | developer:agente:deslogado | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 16413 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 65 | developer:reparo:- reprodução primeiro: os testes novos já passam n | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 15093 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura volta |
| 69 | developer:agente:timeout | ambiente | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 6774 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 74 | developer:reparo:- lint e testes iguais ao ci : ................... | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 6407 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 75 | developer:abrir_pr:- lint e testes iguais ao ci : ................... | trabalho | evidenciada | 1 | 0 | Fechada: pytest --collect-only verde no main (sha 985793980f7b, exit 0); não repetir: developer:abrir_pr: ============== |
| 79 | developer:testes:lint:B905,F811 | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 6158 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 80 | developer:reparo:lint:B905,F811 | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 6158 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 81 | gate:ci:teste:tests/test_autonomia.py::test_missoes_evoluem_em_paralel | trabalho | evidenciada | 1 | 0 | Fechada: tests/test_autonomia.py::test_missoes_evoluem_em_paralelo passou no main (sha d396c81b6f66, exit 0 em 2 execuçõ |
| 82 | developer:testes:lint:F811 | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 4206 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 83 | developer:agente:y_subagents:_n_completed:_n_failed:_n_ki | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 3622 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 84 | developer:testes:lint:B007,B905,E501 | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 3049 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 85 | developer:agente:n_started_in_background:_n_max_depth:_n_ | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 2089 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 86 | developer:agente:unset:_n_started_in_background:_n_max_de | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 2086 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar |
| 87 | incidente:37e8abc2882fd909 | estrutural | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 30 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar;  |
| 88 | developer:agente:nd:_n_max_depth:_n_spawned_by_subagents: | trabalho | obsoleta | 1 | 0 | Obsoleta por prazo: evidenciada há 30 giros sem reincidir (regra: 30 giros ou 7 dias); reincide se a assinatura voltar;  |

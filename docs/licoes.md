# Lições

Cada erro que o loop cometeu vira uma lição com ponto de verificação; a lição só fecha com a correção validada e
evidenciada (o erro não voltou). Esta lista é o banco de lições como está hoje.

| # | Lição | Classe | Status | Ocorrências | Reincidências | Prevenção |
|---|---|---|---|---|---|---|
| 15 | rastro:lacuna | trabalho | validada | 6 | 2 | arquitetura (erro impossível): rastro:cadeia: item planejado pelo loop sem a pergunta do conselho que o originou |
| 18 | developer:agente:s fast_mode_state:off fast_mode_disabled_reason:sd | trabalho | reincidente | 3 | 2 | arquitetura (erro impossível): developer:agente: s","fast_mode_state":"off","fast_mode_disabled_reason":"sdk_opt_in_requ |
| 22 | estudo:saida_invalida | estrutural | evidenciada | 9 | 1 | Já corrigido (PR #33 mergeado); não repetir: estudo:pedido: resposta sem JSON válido: tps://github.com/cgwalters-forge/a |
| 9 | developer:testes:ImportError | trabalho | validada | 2 | 1 | CI (teste ou lint): developer:testes: ==================================== ERRORS ==================================== |
| 26 | developer:reparo:- aprendido#n: teste tests/test_vigia_trava_estado | trabalho | reincidente | 2 | 1 | CI (teste ou lint): developer:reparo: ERROR: file or directory not found: tests/test_vigia_trava_estado.py::test_200_dec |
| 27 | developer:abrir_pr:- aprendido#n: teste tests/test_vigia_trava_estado | trabalho | aberta | 128 | 0 | CI (teste ou lint): developer:abrir_pr: ERROR: file or directory not found: tests/test_vigia_trava_estado.py::test_200_d |
| 42 | developer:agente:d_reason:sdk_opt_in_required subagent_stats: spawn | trabalho | aberta | 13 | 0 | CI (teste ou lint): developer:agente: d_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,"requested":{"backgr |
| 7 | developer:testes:teste:tests/test_jev_replay.py::test_200_decisoes_do_ | trabalho | evidenciada | 7 | 0 | Fechada: tests/test_jev_replay.py::test_200_decisoes_do_worth_spending_saem_da_duvida_concordando_com_a_regra passou no  |
| 29 | developer:sub_item_falhou | trabalho | aberta | 6 | 0 | CI (teste ou lint): developer:fatiador: sub-item #60 “Extrair features das tentativas do planejador (minutos, categoria, |
| 33 | developer:testes:teste:tests/test_espera.py::test_pr_29_reexecucao_de_ | trabalho | obsoleta | 4 | 0 | Não repetir: developer:testes: tests/test_espera.py:55: in test_pr_29_reexecucao_de_ci_por_atraso_da_main_e_a_espera_evi |
| 37 | developer:testes:teste:tests/test_reparo.py::test_commit_na_constituic | trabalho | obsoleta | 4 | 0 | Não repetir: developer:testes: tests/test_reparo.py:212: in test_commit_na_constituicao_depois_da_ultima_rodada_e_revert |
| 1 | incidente:ad2e0d2fe26d7ab2 | estrutural | evidenciada | 3 | 0 | Já corrigido (PR #4 mergeado); não repetir: execucao:idle:atualizar_corpo: RuntimeError: git checkout -q -B main 538d0f4 |
| 12 | developer:testes:teste:tests/test_reparo.py::test_constituicao_editada | trabalho | evidenciada | 3 | 0 | Fechada: tests/test_reparo.py::test_constituicao_editada_pelo_agente_e_revertida_em_cada_rodada_e_o_pr_sai passou no mai |
| 14 | developer:testes:teste:tests/test_vigia.py::test_porteiro_grava_a_deci | trabalho | evidenciada | 3 | 0 | Fechada: tests/test_vigia.py::test_porteiro_grava_a_decisao_sobre_a_pergunta_a_cada_ciclo passou no main (sha 39c2b8bf95 |
| 34 | developer:lint:lint:F811 | trabalho | aberta | 3 | 0 | Não repetir: developer:lint: tests/test_revisor.py:156:16: F811 Redefinition of unused `repo` from line 12: `repo` redef |
| 4 | gate:ci:conflito com a main: o developer precisa trazer a  | trabalho | evidenciada | 2 | 0 | Não repetir: gate:ci: conflito com a main: o Developer precisa trazer a main para a branch |
| 11 | developer:abrir_pr:- constituição intacta: altera a constituição: .gi | trabalho | evidenciada | 2 | 0 | Não repetir: developer:abrir_pr: - constituição intacta: altera a constituição: .github/workflows/ci.yml, circulo/self_d |
| 13 | developer:testes:teste:tests/test_fatiador.py::test_tres_falhas_divide | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_fatiador.py::test_tres_falhas_dividem_o_item_e_ele_nao_e_reexecutado_inteiro passou no main (sha 39c |
| 16 | incidente:a177d1fac10c373b | ambiente | evidenciada | 2 | 0 | Já corrigido (lição reclassificada como ambiente: não é erro do loop · erro não ocorre há 200 giros); não repetir: execu |
| 17 | gate:ci:teste:tests/test_arquitetura.py::test_padroes_ruins_nao_cresce | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_arquitetura.py::test_padroes_ruins_nao_crescem passou no main (sha cd0df6f1c4b7, exit 0 em 2 execuçõ |
| 21 | developer:testes:teste:tests/test_tentativas_planejador.py::test_vigia | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_tentativas_planejador.py::test_vigia_cita_a_ultima_tentativa_real_e_nao_o_intervalo passou no main ( |
| 23 | developer:testes:teste:tests/test_arquitetura.py::test_nenhum_modulo_g | trabalho | evidenciada | 2 | 0 | Fechada: tests/test_arquitetura.py::test_nenhum_modulo_gigante passou no main (sha d459a9f7f9f9, exit 0 em 2 execuções s |
| 24 | developer:testes:teste:tests/test_vigia_trava_estado.py::test_200_deci | trabalho | obsoleta | 2 | 0 | Não repetir: developer:testes: tests/test_vigia_trava_estado.py:79: in test_200_decisoes_de_vigia_trava_saem_da_duvida_c |
| 25 | developer:testes:teste:tests/test_vigia_trava_estado.py::test_estados_ | trabalho | obsoleta | 2 | 0 | Não repetir: developer:testes: tests/test_vigia_trava_estado.py:102: in test_estados_distintos_produzem_confianca_distin |
| 32 | developer:testes:teste:tests/test_arquitetura.py::test_referencias_de_ | trabalho | obsoleta | 2 | 0 | Não repetir: developer:testes: tests/test_arquitetura.py:95: in test_referencias_de_teste_em_licoes_existem |
| 36 | developer:abrir_pr:lint:F811 | trabalho | aberta | 2 | 0 | Não repetir: developer:abrir_pr: - lint e testes (iguais ao CI): tests/test_revisor.py:156:16: F811 Redefinition of unus |
| 40 | developer:testes:teste:tests/test_loop.py::test_giro_rapido_quando_ha_ | trabalho | validada | 2 | 0 | Fechada: tests/test_loop.py::test_giro_rapido_quando_ha_trabalho_e_descanso_longo_quando_nao passou no main (sha e9c1d3a |
| 2 | corpo:validacao_falhou | estrutural | evidenciada | 1 | 0 | Já corrigido (PR #5 mergeado); não repetir: corpo:atualizar: >       with pytest.raises(RuntimeError):                   |
| 3 | developer:agente:isabled_reason:sdk_opt_in_required subagent_stats: | ambiente | evidenciada | 1 | 0 | Não repetir: developer:agente: isabled_reason":"sdk_opt_in_required","subagent_stats":{"spawned":0,"requested":{"backgro |
| 5 | developer:testes:teste:tests/test_camadas.py::test_merge_vira_marco_no | trabalho | evidenciada | 1 | 0 | Fechada: tests/test_camadas.py::test_merge_vira_marco_no_grafico passou no main (sha 960bf25528e3, exit 0 em 2 execuções |
| 6 | developer:lint:lint:B905 | trabalho | evidenciada | 1 | 0 | Não repetir: developer:lint: 269 /         falhou_antes = {n for s, n in zip(seq, nomes) if s["status"]["code"] == "ERRO |
| 10 | developer:reparo:- constituição intacta: altera a constituição: .gi | trabalho | evidenciada | 1 | 0 | Não repetir: developer:reparo: rodada 1/1 não resolveu; 15041 tokens |
| 19 | developer:testes:timeout | ambiente | evidenciada | 1 | 0 | Não repetir: developer:testes: __ test_5xx_e_timeout_sao_repetidos_uma_vez_com_espera_curta_e_jitter[falha0] __ |
| 20 | incidente:853e54efc4a445c1 | ambiente | evidenciada | 1 | 0 | Não repetir: execucao:idle:revisar_prs: URLError: <urlopen error timed out> |
| 28 | developer:reparo:ImportError | trabalho | validada | 1 | 0 | Não repetir: developer:reparo: ERROR: file or directory not found: tests/test_vigia_trava_estado.py::test_200_decisoes_d |
| 30 | developer:testes:e errors ________________________ error at setup o | trabalho | validada | 1 | 0 | Não repetir: developer:testes: ==================================== ERRORS ==================================== |
| 31 | developer:reparo:- lint e testes iguais ao ci : e errors __________ | trabalho | validada | 1 | 0 | Não repetir: developer:reparo: ERROR: file or directory not found: tests/test_vigia_trava_estado.py::test_200_decisoes_d |
| 35 | developer:reparo:lint:F811 | trabalho | validada | 1 | 0 | Não repetir: developer:reparo: ERROR: file or directory not found: tests/test_vigia_trava_estado.py::test_200_decisoes_d |
| 38 | developer:lint:tests/test_fatiador.py:n:n: invalid-syntax: unexpe | trabalho | aberta | 1 | 0 | Não repetir: developer:lint: tests/test_fatiador.py:68:1: invalid-syntax: Unexpected indentation |
| 39 | developer:reparo:- lint e testes iguais ao ci : tests/test_fatiador | trabalho | aberta | 1 | 0 | Não repetir: developer:reparo: ERROR: file or directory not found: tests/test_vigia_trava_estado.py::test_200_decisoes_d |
| 41 | developer:base:teste:tests/test_loop.py::test_run_forever_respeita_max | trabalho | validada | 1 | 0 | Fechada: tests/test_loop.py::test_run_forever_respeita_max_ticks passou no main (sha 5699c3c2b39b, exit 0 em 2 execuções |

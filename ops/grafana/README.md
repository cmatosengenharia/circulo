# Grafana (opcional)

O loop não depende do Grafana: ele só expõe as métricas; o Grafana é uma camada de visualização em cima.

1. Instale o extra e ligue o `/metrics` do loop (desligado por padrão):

   ```sh
   pip install 'circulo[metricas]'
   circulo run --metricas-porta 9464        # ou CIRCULO_METRICS_PORT=9464 (CIRCULO_METRICS_ADDR muda o endereço, padrão 127.0.0.1)
   ```

2. Aponte o Prometheus (ou o Grafana Alloy) para ele:

   ```yaml
   scrape_configs:
     - job_name: circulo
       static_configs:
         - targets: ["127.0.0.1:9464"]
   ```

3. No Grafana: Dashboards → Import → envie `circulo-loop.json` e escolha a fonte Prometheus.

Séries: `circulo_loop_decisoes_jev_total{fonte,resultado}`, `circulo_loop_prs_total{estado}`,
`circulo_loop_etapa_duracao_seconds` (histograma por `etapa`) e `circulo_loop_ultimo_ciclo_timestamp_seconds`
(alerta sugerido: `time() - circulo_loop_ultimo_ciclo_timestamp_seconds > 3600`).

O `/metrics` do painel (porta 8765, `circulo/observabilidade.py`) continua existindo: lê o banco (SLOs, lições,
roteiro); este aqui mede o processo do loop por dentro.

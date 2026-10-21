#!/bin/sh
# Entrypoint do container: equivale ao serviço launchd/systemd. Configuração por variáveis de ambiente (--env-file) ou
# pelo arquivo /dados/env; dados persistentes em /dados; o repositório cuidado em /repo.
set -e
mkdir -p /dados
if [ ! -f /dados/env ]; then
  circulo configurar >/dev/null 2>&1 || true
fi
if [ -d /repo/.git ]; then
  git config --global --add safe.directory /repo
fi
exec circulo --data /dados "$@"

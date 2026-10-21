# O loop num container: o mesmo `circulo run --painel` do launchd/systemd, com o Claude Code instalado.
#   docker build -t circulo .
#   docker run -d --name circulo -p 8765:8765 --env-file circulo.env -v circulo-dados:/dados -v /caminho/do/repo:/repo circulo
# As chaves vão no --env-file (nunca na imagem). O repositório que o loop cuida é montado em /repo (CIRCULO_REPO_DIR).
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY circulo ./circulo
COPY fabrica ./fabrica
RUN pip install --no-cache-dir -e ".[llm]" && pip install --no-cache-dir ruff pytest

ENV CIRCULO_ENV=/dados/env \
    CIRCULO_REPO_DIR=/repo \
    CIRCULO_CODE_AGENT=claude \
    PYTHONUNBUFFERED=1
VOLUME ["/dados", "/repo"]
EXPOSE 8765
COPY ops/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["run", "--painel", "--porta", "8765"]

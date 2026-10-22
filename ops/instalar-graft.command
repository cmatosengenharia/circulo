#!/bin/zsh
# Instala o Graft (memória semântica local, github.com/AEndrix03/Graft) para o círculo no Mac. Dois cliques.
# - binário pelo Homebrew; perfil `circulo` (o grafo do loop não mistura com as suas anotações);
# - as skills do Graft no Claude Code (~/.claude/skills), para o Developer usar /recall e /memoryze;
# - primeira chamada carrega o modelo de embeddings (~600 MB, uma vez).
set -e
echo "Círculo: instalando o Graft (memória semântica do time)."
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew não encontrado. Instale em https://brew.sh e rode este arquivo de novo."; exit 1
fi
if ! command -v graft >/dev/null 2>&1; then
  brew tap AEndrix03/graft https://github.com/AEndrix03/Graft.git
  # O Homebrew recusa fórmula de tap de terceiros até você confiar nela. Confia só na fórmula do Graft
  # (não no tap inteiro): é o código de instalação dele que roda aqui. Para desfazer: brew untrust --formula aendrix03/graft/graft
  echo "Confiando só na fórmula aendrix03/graft/graft (github.com/AEndrix03/Graft)."
  brew trust --formula aendrix03/graft/graft 2>/dev/null || true      # Homebrew antigo não tem `trust` nem precisa
  brew install aendrix03/graft/graft
fi
graft --version
graft profile add circulo-loop 2>/dev/null || true
export GRAFT_PROFILE=circulo-loop
echo "Carregando o modelo e conferindo o daemon (pode levar alguns minutos na primeira vez)…"
graft stats
graft setup claudecode 2>/dev/null || echo "(skills do Graft para o Claude Code não vêm no pacote do Homebrew: opcional, o loop usa o graft pela linha de comando)"
echo
echo "Pronto. O loop percebe o Graft sozinho na próxima passagem (diagnóstico: Memória semântica (Graft) · ligado)."
echo "Para desligar sem desinstalar: CIRCULO_GRAFT=0 no ~/.config/circulo/env."

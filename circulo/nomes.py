"""Os nomes dos agentes, num lugar só, para todas as telas falarem a mesma língua.

Cada agente é apresentado como um papel numa equipe de engenharia (o que ele é para o time), com o nome técnico
antigo guardado em `antes` para quem já conhecia o loop. Telas e APIs usam `nome()`, `cargo()` e `curto()`.
"""
from __future__ import annotations

# chave interna → como aparece para pessoas
AGENTES: dict[str, dict[str, str]] = {
    "cassio":           {"nome": "Cássio",             "cargo": "Cliente",                 "curto": "Cássio",       "antes": "pedido"},
    "orquestrador":     {"nome": "Tech lead",          "cargo": "Abre e distribui o giro", "curto": "Tech lead",    "antes": "Orquestrador"},
    "jev":              {"nome": "Jev",                "cargo": "Head de engenharia",      "curto": "Jev",          "antes": "Jev"},
    "pedido":           {"nome": "Atendimento",        "cargo": "Recebe o seu pedido",     "curto": "Atendimento",  "antes": "Pedido seu"},
    "decisao":          {"nome": "Decisão do Jev",     "cargo": "Vale gastar agora?",      "curto": "Decisão",      "antes": "Escolha"},
    "indagar":          {"nome": "Product owner",      "cargo": "Faz as perguntas certas", "curto": "PO",           "antes": "Indagador"},
    "planejar_roteiro": {"nome": "Gerente de produto", "cargo": "Transforma pergunta em item", "curto": "GP",       "antes": "Planejador"},
    "estudar_pedido":   {"nome": "Arquiteto",          "cargo": "Estuda antes de construir", "curto": "Arquiteto",  "antes": "Estudo / Pesquisa"},
    "corrigir_codigo":  {"nome": "Desenvolvedor",      "cargo": "Escreve código e teste",  "curto": "Dev",          "antes": "Developer"},
    "revisor":          {"nome": "Revisor de código",  "cargo": "Confere cada PR antes de entrar", "curto": "Revisor", "antes": "Revisor"},
    "revisar_prs":      {"nome": "QA e release",       "cargo": "CI verde, teste novo, merge", "curto": "QA",       "antes": "Gate"},
    "atualizar_corpo":  {"nome": "DevOps",             "cargo": "Sobe para produção e prova", "curto": "DevOps",    "antes": "Corpo"},
    "vigia":            {"nome": "SRE",                "cargo": "Mede se a evolução anda", "curto": "SRE",          "antes": "Vigia"},
    "licoes":           {"nome": "Curador de lições",  "cargo": "Erro vira lição e portão", "curto": "Curador",     "antes": "Lições"},
    "saude":            {"nome": "Monitor de saúde",   "cargo": "Mede o loop e pede rollback", "curto": "Saúde",    "antes": "Saúde"},
    "jardinagem":       {"nome": "Jardineiro",         "cargo": "Dívida técnica",          "curto": "Jardineiro",   "antes": "Jardinagem"},
    "meta_learner":     {"nome": "Cientista de dados", "cargo": "Aprende regras com as correções", "curto": "Dados", "antes": "Aprendiz / Meta-Learner"},
    "shadow":           {"nome": "Simulação",          "cargo": "Testa mudanças em sombra", "curto": "Simulação",   "antes": "Shadow"},
    "evoluir_projeto":  {"nome": "Gerente de missões", "cargo": "Entrega as missões suas",  "curto": "Missões",     "antes": "Missões"},
    "manutencao":       {"nome": "Manutenção",         "cargo": "Rotinas quando não há pedido", "curto": "Manutenção", "antes": "Manutenção"},
    "rotinas":          {"nome": "Operações",          "cargo": "Regressão, padrões, resumo", "curto": "Operações", "antes": "Rotinas"},
    "analisar_padroes": {"nome": "Analista de padrões", "cargo": "Procura repetição nos erros", "curto": "Padrões", "antes": "Padrões"},
    "revisar_baixa_confianca": {"nome": "Revisão de dúvidas", "cargo": "Reabre decisões em dúvida", "curto": "Dúvidas", "antes": "Revisão"},
    "rodar_regressao":  {"nome": "Regressão",          "cargo": "Roda a suíte de novo",    "curto": "Regressão",    "antes": "Regressão"},
    "resumo":           {"nome": "Relator",            "cargo": "Resume o dia",            "curto": "Relator",      "antes": "Resumo"},
    "propor_feature":   {"nome": "Melhorias",          "cargo": "Propõe o próximo passo",  "curto": "Melhorias",    "antes": "Melhorias"},
    "evoluir_harness":  {"nome": "Prompts A/B",        "cargo": "Testa prompts lado a lado", "curto": "Prompts",    "antes": "Prompts A/B"},
    "conectar_missoes": {"nome": "Integrador",         "cargo": "Liga missões que se conhecem", "curto": "Integrador", "antes": "Conexões"},
    "medico":           {"nome": "Médico do loop",     "cargo": "Diagnostica gargalos e contém o dano", "curto": "Médico", "antes": "Médico"},
    "documentar":       {"nome": "Redator técnico",    "cargo": "Documenta o que o loop é e fez", "curto": "Redator", "antes": "Documentador"},
    "llm":              {"nome": "Consultor (LLM)",    "cargo": "Raciocina quando a regra não basta", "curto": "LLM", "antes": "LLM"},
    "github":           {"nome": "GitHub",             "cargo": "Repositório e CI",        "curto": "GitHub",       "antes": "GitHub"},
    "descanso":         {"nome": "Descanso",           "cargo": "Entre giros",             "curto": "Descanso",     "antes": "Descanso"},
    "pausado":          {"nome": "Pausado",            "cargo": "Esperando você",          "curto": "Pausado",      "antes": "Pausado"},
}


def nome(chave: str) -> str:
    a = AGENTES.get(chave)
    return a["nome"] if a else chave.replace("_", " ").capitalize()


def cargo(chave: str) -> str:
    a = AGENTES.get(chave)
    return a["cargo"] if a else "agente criado pela autoevolução"


def curto(chave: str) -> str:
    a = AGENTES.get(chave)
    return a["curto"] if a else chave.replace("_", " ").capitalize()


def antes(chave: str) -> str:
    a = AGENTES.get(chave)
    return a["antes"] if a else chave


def tabela() -> list[dict[str, str]]:
    """Para as telas: uma lista com chave, nome, cargo, curto e o nome antigo."""
    return [{"chave": k, **v} for k, v in AGENTES.items()]

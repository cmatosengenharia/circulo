"""Impressão digital de PR: título normalizado + conjunto de checks falhos, num hash.

Circuit breaker aplicado a PRs (pergunta #265): o PR de pré-checagem foi aberto e fechado 3 vezes (#48, #49, #50)
com os mesmos checks falhando. Quando o histórico já tem LIMITE aberturas fechadas com a mesma impressão, a próxima
é 'bloquear': a tarefa sai de developer:abrir_pr e vai para o fatiador ou para revisão humana. Função pura; quem
monta o histórico e age sobre o veredito é o chamador.
"""
import hashlib
import re
import unicodedata

LIMITE = 2


def _titulo(titulo):
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", titulo) if not unicodedata.combining(c))
    return " ".join(sem_acento.casefold().split()).strip(" .")


def impressao(titulo, checks_falhos):
    checks = sorted({re.sub(r"\s+", " ", c.strip().casefold()) for c in checks_falhos})
    return hashlib.sha256("\n".join([_titulo(titulo), *checks]).encode()).hexdigest()[:16]


def veredito_abertura(titulo, checks_falhos, historico):
    """'bloquear' se o histórico ({titulo, checks_falhos, estado}) já tem LIMITE fechados com a mesma impressão."""
    alvo = impressao(titulo, checks_falhos)
    fechados = sum(1 for h in historico
                   if h["estado"] == "fechado" and impressao(h["titulo"], h["checks_falhos"]) == alvo)
    return "bloquear" if fechados >= LIMITE else "abrir"

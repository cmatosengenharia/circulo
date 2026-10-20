"""Círculo perfeito: uma fábrica de software autônoma, pequena e verificável.

Um cartão por vez passa pelas estações de uma fábrica de software — Gerente de produto, Arquiteto, Desenvolvedor,
QA, Revisor, Release — e volta ao começo com o que aprendeu (achados). Cada estação devolve evidência rotulada
(medido, inferido, chutado) e só o que foi verificado na superfície real segue adiante.

Princípios (Lauren Tan, @poteto): confiança antes de paralelismo; corrigir na camada mais forte (arquitetura, depois
lint/CI, depois regras, por último revisão); verificar rodando o software, não só lendo testes; separar julgamento de
trabalho mecânico; transformar operação resolvida em ferramenta; parar antes de ação irreversível.
"""
__version__ = "0.1.0"

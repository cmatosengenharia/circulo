"""Entrada manual de uma linha ('mercado 45,90 ontem') → lançamento, sem LLM.

`parse_linha_manual` é pura: data (hoje, ontem, dd/mm ou dd/mm/aaaa; sem data é hoje), valor com vírgula decimal
(saída, salvo '+' ou categoria renda), categoria e tag pela primeira regra de palavra-chave da política, e o resto
como descrição. Linha ambígua (sem valor, dois valores, duas datas, data inexistente, sem descrição) vira uma
pergunta curta e nada é gravado. A chave é a do extrato sem FITID (`chave_hash`), então repetir a linha insere 0 e
o mesmo gasto já visto no extrato também. Dois gastos iguais no mesmo dia são legítimos: o segundo leva '#2' (a
ocorrência), e a repetição sem sufixo devolve a pergunta que ensina isso. `registrar_lote` aplica o mesmo a cada linha
de um texto colado: a ambígua vira pergunta sem abortar as demais, e o retorno resume gravadas/duplicadas/ambíguas
e quantos lançamentos faltam para o mínimo do cérebro financeiro."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import NamedTuple

from . import financeiro
from .decision import LocalJev, norm
from .lancamentos_import import Linha, _centavos, _descricao, chave_hash, gravar
from .policy import DEFAULT_POLICY, PolicyStore
from .state import Store

_VALOR = re.compile(r"[+-]?(?:r\$)?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?")
_DATA = re.compile(r"(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?")
_OCORRENCIA = re.compile(r"#(\d{1,2})")
_RELATIVA = {"hoje": 0, "ontem": 1, "anteontem": 2}


class Manual(NamedTuple):
    data: str        # ISO, AAAA-MM-DD
    centavos: int    # negativo = saída, positivo = entrada
    descricao: str   # normalizada como a dos importadores
    categoria: str
    tag: str
    ocorrencia: int  # 0 na primeira; '#2' na linha é 1


def _dia(token: str, hoje: date) -> date | None:
    if token in _RELATIVA:
        return hoje - timedelta(days=_RELATIVA[token])
    d, m, a = _DATA.fullmatch(token).groups()
    ano = int(a) + (2000 if len(a) == 2 else 0) if a else hoje.year
    try:
        dia = date(ano, int(m), int(d))
        return date(ano - 1, int(m), int(d)) if not a and dia > hoje else dia     # dd/mm no futuro é do ano passado
    except ValueError:
        return None


def parse_linha_manual(texto: str, hoje: date, regras: list[dict] | None = None) -> Manual | str:
    """O lançamento da linha, ou uma pergunta curta (str terminada em '?') quando a linha é ambígua."""
    datas, valores, ocorrencias, palavras = [], [], [], []
    for token in texto.split():
        t = norm(token)
        if t in _RELATIVA or _DATA.fullmatch(t):
            datas.append(token)
        elif _VALOR.fullmatch(t):
            valores.append(token)
        elif _OCORRENCIA.fullmatch(t):
            ocorrencias.append(int(t[1:]))
        elif t != "r$":
            palavras.append(token)
    descricao = _descricao(" ".join(palavras))
    if not valores:
        return f"Qual foi o valor de '{descricao[:40]}'?" if descricao else "Qual foi o gasto? Ex.: 'mercado 45,90 ontem'?"
    if len(valores) > 1:
        return f"Qual é o valor: {' ou '.join(valores[:3])}?"
    if len(datas) > 1:
        return f"Qual é a data: {' ou '.join(datas[:3])}?"
    dia = _dia(norm(datas[0]), hoje) if datas else hoje
    if dia is None:
        return f"A data {datas[0]} não existe; qual foi o dia?"
    if not descricao:
        return f"O que foi esse lançamento de {valores[0]}?"
    centavos = _centavos(norm(valores[0]))
    if centavos == 0:
        return "Valor zero não vira lançamento; qual foi o valor?"
    if len(ocorrencias) > 1 or (ocorrencias and ocorrencias[0] < 1):
        return f"Qual é a ocorrência: {' ou '.join(f'#{n}' for n in ocorrencias[:3])}?"
    regra = LocalJev.match_rule(descricao, DEFAULT_POLICY["rules"] if regras is None else regras)
    categoria, tag = (regra["category"], regra["tag"]) if regra else ("outros", "escolha")
    if categoria == "renda" or valores[0].startswith("+"):
        centavos = abs(centavos)
    elif not valores[0].startswith("-"):
        centavos = -centavos
    return Manual(dia.isoformat(), centavos, descricao, categoria, tag, ocorrencias[0] - 1 if ocorrencias else 0)


def _registrar(store: Store, texto: str, hoje: date, regras: list[dict]) -> tuple[int, str | None, bool]:
    """(novos, pergunta, duplicada) de uma linha, com as regras da política já lidas."""
    m = parse_linha_manual(texto, hoje, regras)
    if isinstance(m, str):
        return 0, m, False
    chave = chave_hash(m.data, m.centavos, m.descricao, m.ocorrencia)
    if gravar(store, [Linha(m.data, m.centavos, m.descricao, chave, m.categoria, m.tag)]):
        return 1, None, False
    dia = date.fromisoformat(m.data).strftime("%d/%m")
    return 0, f"Já registrei {m.descricao} em {dia}. É outro igual? Mande a linha com #{m.ocorrencia + 2}.", True


def registrar_linha_manual(store: Store, texto: str, hoje: date) -> tuple[int, str | None]:
    """(lançamentos novos, pergunta): (1, None) gravou; (0, pergunta) se a linha é ambígua ou já está no ledger."""
    _, politica = PolicyStore(store).active()
    return _registrar(store, texto, hoje, politica.get("rules", []))[:2]


class Lote(NamedTuple):
    gravadas: int
    duplicadas: int
    ambiguas: list[tuple[str, str]]   # (linha, pergunta curta)
    faltam_lancamentos: int

    def resumo(self) -> str:
        cabeca = (f"{self.gravadas} gravadas, {self.duplicadas} duplicadas, {len(self.ambiguas)} ambíguas; "
                  f"faltam {self.faltam_lancamentos} lançamentos para o mínimo de {financeiro.MINIMO_LANCAMENTOS}.")
        return "\n".join([cabeca, *(f"{linha} → {pergunta}" for linha, pergunta in self.ambiguas)])


def registrar_lote(store: Store, texto: str, hoje: date) -> Lote:
    """Cada linha não vazia do texto colado passa pelo mesmo parser e pela mesma dedupe por hash da linha única."""
    _, politica = PolicyStore(store).active()
    regras = politica.get("rules", [])
    gravadas = duplicadas = 0
    ambiguas: list[tuple[str, str]] = []
    for linha in filter(None, (bruta.strip() for bruta in texto.splitlines())):
        novos, pergunta, duplicada = _registrar(store, linha, hoje, regras)
        gravadas += novos
        duplicadas += duplicada
        if pergunta and not duplicada:
            ambiguas.append((linha, pergunta))
    return Lote(gravadas, duplicadas, ambiguas, financeiro.prontidao(store)["faltam_lancamentos"])

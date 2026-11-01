"""Produto que cria produtos: cada produto ganha uma landing em docs/ (nome, proposta, 3 telas, repositório), e o Jev
a avalia pela régua de clareza (noul) antes de publicar."""
from html.parser import HTMLParser

import pytest

from circulo import landing
from circulo.decision import Decision, LocalJev

EXEMPLO = landing.Produto(
    nome="Caderneta",
    proposta="Anote os gastos da casa em segundos e veja no fim do mês para onde foi o dinheiro.",
    telas=(landing.Tela("Lançar", "Um campo de valor e uma categoria, salvo com um toque."),
           landing.Tela("Mês", "O total por categoria comparado com o mês anterior."),
           landing.Tela("Metas", "Quanto falta para cada meta da família, em reais.")),
    repo="https://github.com/cassio/caderneta")


class _Texto(HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1, self.h3, self.links, self._em = [], [], [], None

    def handle_starttag(self, tag, attrs):
        self._em = tag
        if tag == "a":
            self.links.append(dict(attrs).get("href"))

    def handle_data(self, data):
        if self._em in ("h1", "h3") and data.strip():
            getattr(self, self._em).append(data.strip())


class _Dl:
    """DecisionLayer de mentira: o LocalJev (regra local da régua) ou uma resposta fixa do Jev."""
    def __init__(self, p=None):
        self.p, self.estados = p, []

    def ask(self, nome, q, estado):
        self.estados.append(estado)
        if self.p is None:
            return LocalJev().ask_many(estado, {nome: q})[0][nome]
        return Decision(nome, "noul", self.p, abs(2 * self.p - 1), "jev")


def test_produto_de_exemplo_gera_landing_e_passa_na_regua(tmp_path):
    html = landing.gerar(EXEMPLO)
    t = _Texto()
    t.feed(html)
    assert t.h1 == ["Caderneta"] and t.h3 == ["Lançar", "Mês", "Metas"]
    assert EXEMPLO.proposta in html and "https://github.com/cassio/caderneta" in t.links
    dl = _Dl()
    r = landing.publicar(tmp_path, EXEMPLO, dl)
    assert r["publicada"] and r["p"] >= landing.LIMIAR and r["motivos"] == []
    assert (tmp_path / "docs" / "index.html").read_text(encoding="utf-8") == html
    assert dl.estados[0]["n_telas"] == 3 and dl.estados[0]["nome_no_titulo"]


def test_landing_confusa_nao_e_publicada(tmp_path):
    confuso = landing.Produto(nome="Plataforma Integrada de Soluções Sinérgicas Caderneta", proposta="Solução inovadora.",
                              telas=(landing.Tela("A", ""), landing.Tela("B", "x"), landing.Tela("C", "y")),
                              repo="https://github.com/cassio/caderneta")
    r = landing.publicar(tmp_path, confuso, _Dl())
    assert not r["publicada"] and r["p"] < landing.LIMIAR and not (tmp_path / "docs").exists()
    assert {"nome longo", "proposta vaga", "tela sem descrição"} <= set(r["motivos"])


def test_jev_decide_quando_responde(tmp_path):
    assert not landing.publicar(tmp_path, EXEMPLO, _Dl(p=0.2))["publicada"]
    r = landing.publicar(tmp_path, EXEMPLO, _Dl(p=0.9))
    assert r["publicada"] and r["fonte"] == "jev"


def test_nome_e_texto_sao_escapados():
    p = landing.Produto(nome="<b>X</b>", proposta=EXEMPLO.proposta, telas=EXEMPLO.telas, repo=EXEMPLO.repo)
    assert "<b>X</b>" not in landing.gerar(p) and "&lt;b&gt;X&lt;/b&gt;" in landing.gerar(p)


def test_sem_tres_telas_ou_repo_https_o_produto_nao_existe():
    with pytest.raises(ValueError):
        landing.Produto(nome="X", proposta=EXEMPLO.proposta, telas=EXEMPLO.telas[:2], repo=EXEMPLO.repo)
    with pytest.raises(ValueError):
        landing.Produto(nome="X", proposta=EXEMPLO.proposta, telas=EXEMPLO.telas, repo="javascript:alert(1)")

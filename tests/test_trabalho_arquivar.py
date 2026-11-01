"""Nota sem assunto pela tela: o endpoint devolve 3 opções com o trecho da nota, o clique arquiva e grava o par
(termos da nota, assunto) como regra local, e a mesma nota não pede decisão de novo."""
from circulo import assuntos, trabalho
from circulo.decision import Decision


def test_nota_sem_palavra_em_comum_arquiva_em_2_passos_e_a_regra_e_reusada(circle):
    s, dados = circle.store, circle.data_dir
    trabalho.semear(s, dados)
    frase = "nota: lembrar de beber água entre as reuniões"
    r, st = trabalho.api_post(s, dados, "/api/trabalho/anotar", {"texto": frase})
    assert st == 200 and "não sei em que assunto" in r["erro"]                        # passo 1: a tela pergunta
    d = r["decidir"]
    assert d["trecho"] == frase and len(d["opcoes"]) == 3 and len({o["id"] for o in d["opcoes"]}) == 3
    escolha = d["opcoes"][2]
    r, st = trabalho.api_post(s, dados, "/api/trabalho/arquivar", {"texto": frase, "assunto": escolha["id"]})
    assert st == 200 and r["nota"]["assunto"] == escolha["nome"]                       # passo 2: o clique arquiva
    assert s.one("SELECT COUNT(*) n FROM assunto_notas WHERE origem=?", (frase,))["n"] == 1
    r, st = trabalho.api_post(s, dados, "/api/trabalho/anotar", {"texto": frase})   # a mesma nota de novo
    assert st == 200 and "decidir" not in r and r["nota"]["assunto"] == escolha["nome"]
    r, st = trabalho.api_post(s, dados, "/api/trabalho/anotar", {"texto": "pendência: beber água nas reuniões"})
    assert r["nota"]["assunto"] == escolha["nome"]                                     # mesmos termos, outra frase


def test_arquivar_recusa_assunto_que_nao_existe_e_nota_com_credencial(circle):
    s, dados = circle.store, circle.data_dir
    trabalho.semear(s, dados)
    assert trabalho.api_post(s, dados, "/api/trabalho/arquivar", {"texto": "nota: qualquer coisa", "assunto": 99999})[1] == 400
    assert trabalho.api_post(s, dados, "/api/trabalho/arquivar", {"texto": "nota: token: abc123", "assunto": 1})[1] == 400
    assert trabalho.api_post(s, dados, "/api/trabalho/arquivar", {"texto": "nota: qualquer coisa", "assunto": "1"})[1] == 400


def test_jev_decide_antes_da_regra_aprendida(circle):
    s, dados = circle.store, circle.data_dir
    trabalho.semear(s, dados)
    frase = "nota: lembrar de beber água entre as reuniões"
    ids = {a["nome"]: a["id"] for a in s.q("SELECT id, nome FROM assuntos")}
    assuntos.arquivar(s, frase, ids["GAIA"])

    class Jev:
        source = "jev"

        def ask(self, qid, q, state):
            return Decision(qid, "choice", f"a{ids['svc-sms']}", 0.9, self.source)
    assert assuntos.anotar(s, Jev(), frase)["assunto"] == "svc-sms"                    # no loop, o Jev decide antes
    assert trabalho.anotar(s, frase)["assunto"] == "GAIA"                              # sem Jev, a regra aprendida

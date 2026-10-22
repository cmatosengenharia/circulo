"""Pergunta do conselho #54 (economista): o Jev decidia `dado_na_evidencia` com dúvida (27% pela regra, confiança 0.28)
porque não havia regra para ela (caía em `_unknown`: 0.5, confiança 0) e o estado não dizia se o número do dado está,
como token, na evidência. Estado com features medidas; regra que decide por elas."""
import json

from circulo import jev_lab
from circulo.decision import SN, LocalJev, Question

Q = Question("noul", "O dado citado pelo planejador aparece de fato na evidência do loop?", SN("sim", "não"))
EV = json.dumps({"tokens_24h": 9900, "taxa": 18.5, "confianca_media": 0.50, "licao": 42, "decisoes_24h": 26})


def decide(dado, base="medido", ev=EV):
    return LocalJev().ask_many(jev_lab.estado_dado(dado, ev, base), {"dado_na_evidencia": Q})[0]["dado_na_evidencia"]


def test_estado_tem_features_medidas_com_casamento_por_token_numerico():
    st = jev_lab.estado_dado("lição 42 com 26 decisões em 24 h", EV, "inferido")
    assert st["dado_tem_digito"] is True and st["numero_literal_na_evidencia"] == "sim" and st["base"] == "inferido"
    assert st["n_numeros_evidencia"] == 7                     # 24 (de tokens_24h), 9900, 18.5, 0.5, 42, 24 (de decisoes_24h), 26
    assert jev_lab.estado_dado("1900 tokens", EV)["numero_literal_na_evidencia"] == "nao"      # 1900 não casa dentro de 9900
    assert jev_lab.estado_dado("taxa de 18", EV)["numero_literal_na_evidencia"] == "nao"       # 18 não é 18.5
    assert jev_lab.estado_dado("confiança 0,5", EV)["numero_literal_na_evidencia"] == "sim"    # 0,5 normalizado é 0.50
    assert jev_lab.estado_dado("42 e 7", EV)["numero_literal_na_evidencia"] == "parte"
    sem = jev_lab.estado_dado("o estudo falha mais à noite", EV)
    assert sem["dado_tem_digito"] is False and sem["numero_literal_na_evidencia"] == "nao_verificavel"


def test_estados_distintos_dao_confiancas_distintas_e_dado_ausente_e_nao_com_confianca_alta():
    ausente, todos, parte = decide("1900 tokens em 7 dias"), decide("lição 42 com 26 decisões"), decide("lição 42 com 7 decisões")
    assert ausente.value < 0.5 and ausente.confidence >= 0.8
    assert todos.value > 0.5 and todos.confidence >= 0.8
    assert len({ausente.confidence, todos.confidence, parte.confidence}) == 3
    assert decide("lição 42 com 26 decisões", "inferido").confidence < todos.confidence     # a base declarada pesa
    assert decide("o estudo falha mais à noite").confidence < 0.25                        # sem dígito: não verificável

"""Contrato de saída JSON (lição #22): as chaves obrigatórias do esquema chegam inteiras, ou um motivo tipado diz por quê."""
import json

import pytest

from circulo.saida_json import Motivo, ler

ESTUDO = ("veredito", "justificativa")

# lição #22: o limite de tokens cortou a resposta dentro do item novo, depois de veredito, justificativa e achados
LICAO_22 = ('{"veredito": "adaptar", "justificativa": "a constituição já veta no merge",'
            ' "achados": [{"ideia": "x", "fonte": "gh", "url": "https://github.com/cgwalters-forge/agentic-job/issues/556",'
            ' "base":"inferido"}],"item":{"titulo":"Veto determinístico da c')
# incidente JSONDecodeError 'Unterminated string' no char 59: cortado dentro da justificativa
CHAR_59 = '{"veredito": "adaptar", "achados": ["x"], "justificativa": "A fonte oficial mostra que a causa'


def test_licao_22_cortada_no_item_devolve_o_que_chegou_inteiro_e_so_as_chaves_do_esquema():
    s = ler(LICAO_22, ESTUDO, opcionais=("achados", "item"))
    assert s.motivo is Motivo.OK and s.cortada
    assert s.dados["veredito"] == "adaptar" and s.dados["achados"][0]["base"] == "inferido"
    assert "item" not in s.dados                     # valor cortado não é fabricado: some, não vira "Veto determinístico da c"


def test_unterminated_string_no_char_59_vira_falta_de_chave_obrigatoria_e_nao_valor_inventado():
    with pytest.raises(json.JSONDecodeError, match=r"Unterminated string .*\(char 59\)"):
        json.loads(CHAR_59)
    s = ler(CHAR_59, ESTUDO, opcionais=("achados",))
    assert s.dados is None and s.motivo is Motivo.FALTA_CHAVE
    assert s.faltam == ("justificativa",) and s.cortada
    assert "justificativa" in str(s) and "cortada" in str(s)


def test_cortada_logo_depois_de_um_valor_inteiro_fecha_as_chaves_e_nao_perde_o_ultimo_valor():
    s = ler('{"veredito": "adotar", "justificativa": "segue o pedido"', ESTUDO)
    assert s.motivo is Motivo.OK and s.dados == {"veredito": "adotar", "justificativa": "segue o pedido"} and s.cortada


def test_chaves_fora_do_esquema_nao_passam():
    s = ler('Vou pesquisar {tema}. {"veredito": "adotar", "justificativa": "ok", "extra": 1}', ESTUDO)
    assert s.dados == {"veredito": "adotar", "justificativa": "ok"} and not s.cortada


def test_motivos_tipados():
    assert ler("", ESTUDO).motivo is Motivo.VAZIA
    assert ler("não achei nada", ESTUDO).motivo is Motivo.SEM_JSON
    s = ler('{"veredito": "adotar"}', ESTUDO)
    assert s.motivo is Motivo.FALTA_CHAVE and s.faltam == ("justificativa",) and not s.cortada
    recusa = ler('{"veredito": "talvez", "justificativa": "x"}', ESTUDO, aceita=lambda d, _c: d if d["veredito"] == "adotar" else None)
    assert recusa.motivo is Motivo.RECUSADA and recusa.dados is None

"""Experimento universal: o item do Planejador carrega hipótese, métrica, baseline, alvo, margem de não inferioridade,
janela e n_min; o Vigia mede ao fim da janela e grava melhorou/neutro/piorou/inconclusivo. Só `piorou` em métrica
de guarda abre a reversão (item do roteiro → PR → CI → revisor); `neutro` põe a métrica em descanso."""
import json
import time

import pytest

from circulo import experimentos as ex
from circulo.planejador import Planejador

EXP = {"hipotese": "o lead time cai com o cache", "metrica": "lead_time_h", "baseline": 1.2, "alvo": 0.8,
       "margem": 0.1, "janela_h": 48, "n_min": 3}


class LLMItem:
    def __init__(self, item):
        self.item = item

    def complete(self, system, prompt, max_tokens):
        return json.dumps(self.item), 400


def _planejar(circle, item):
    t = time.time()
    pid = circle.store.x("INSERT INTO perguntas(chave,persona,texto,status,cerebro,score,created_at,updated_at) "
                         "VALUES('k','arquiteto','q?','valida','loop',0.5,?,?)", (t, t))
    circle.ctx.dl.llm = LLMItem(item)
    Planejador(circle.ctx, None).run(autorizado=True)
    return circle.store.one("SELECT status, item_id FROM perguntas WHERE id=?", (pid,))


@pytest.mark.parametrize("falta", [None, "hipotese", "metrica", "margem", "janela_h", "n_min", "desconhecida", "alvo_ao_contrario"])
def test_planejador_recusa_item_sem_experimento_completo(circle, falta):
    exp = dict(EXP)
    if falta == "desconhecida":
        exp["metrica"] = "felicidade"
    elif falta == "alvo_ao_contrario":
        exp["alvo"] = 2.0                       # lead_time_h é "menor": alvo acima do baseline não é hipótese de melhora
    elif falta:
        exp.pop(falta)
    item = {"titulo": "Cache do planejador", "detalhe": "mudar x", "sucesso": "y"}
    if falta is not None:
        item["experimento"] = exp
    r = _planejar(circle, item)
    assert r["status"] == "descartada" and r["item_id"] is None
    assert circle.store.one("SELECT COUNT(*) n FROM experimentos")["n"] == 0


def test_item_novo_do_planejador_grava_metrica_e_janela(circle):
    r = _planejar(circle, {"titulo": "Cache do planejador", "detalhe": "mudar x", "sucesso": "y", "experimento": EXP})
    assert r["status"] == "virou_item"
    e = circle.store.one("SELECT * FROM experimentos WHERE item_id=?", (r["item_id"],))
    assert e["metrica"] == "lead_time_h" and e["janela_s"] == 48 * 3600 and e["n_min"] == 3
    assert e["margem_nao_inferioridade"] == 0.1 and e["hipotese"] and e["veredito"] is None


def test_metrica_em_descanso_recusa_item_novo(circle):
    circle.store.set(ex.DESCANSO, {"lead_time_h": time.time() + 3600})
    r = _planejar(circle, {"titulo": "Cache do planejador", "detalhe": "mudar x", "sucesso": "y", "experimento": EXP})
    assert r["status"] == "descartada"


def _item(s, titulo, criado):
    return s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) "
               "VALUES(?,?,'loop','pendente','',1,?,?)", (titulo, "d", criado, criado))


def _pr(s, n, item_id, quando, consertos=0):
    s.x("INSERT INTO prs(number,titulo,branch,status,item_id,arquivos,consertos,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)", (n, "t", "b", "mergeado", item_id, "[]", consertos, quando - 60, quando))


def _jardim(s, quando, except_exception):
    j = s.get("jardim") or {"historico": []}
    total = {"except_exception": except_exception, "noqa": 0, "funcoes_longas": 0, "modulos_grandes": 0, "todo": 0}
    s.set("jardim", {"em": quando, "total": total, "historico": j["historico"] + [{"em": quando, "total": total}]})


def test_ponta_a_ponta_norte_e_jardim_cobre_os_tres_vereditos_e_inconclusivo(circle):
    s, H = circle.store, 3600.0
    t0 = time.time() - 30 * H
    falas = []
    reply = lambda msg, kind="": falas.append(msg)  # noqa: E731

    def exp(titulo, **kw):
        iid = _item(s, titulo, t0 - 10 * H)
        ex.gravar(s, iid, ex.Experimento.de({**EXP, "janela_h": 2, **kw}), t0 - 9 * H)
        s.x("UPDATE roadmap SET status='feito' WHERE id=?", (iid,))
        return iid

    _jardim(s, t0 - 9.5 * H, 10)                              # o jardim antes da mudança: 10 except Exception
    lead = exp("Lead time cai", metrica="lead_time_h", baseline=5.0, alvo=1.0, margem=0.5, n_min=2)
    conserto = exp("Merge sem conserto", metrica="merge_sem_conserto", baseline=0.5, alvo=0.9, margem=0.1, n_min=2)
    jardim = exp("Menos except", metrica="except_exception", baseline=99, alvo=5, margem=1, n_min=1)
    seco = exp("Sem eventos", metrica="prs_produto_semana", baseline=1, alvo=3, margem=1, n_min=50)
    assert s.one("SELECT baseline FROM experimentos WHERE item_id=?", (jardim,))["baseline"] == 10   # medido, não o chute

    ex.avaliar(s, reply, t0)                                  # o Vigia abre a janela dos itens feitos
    # dentro da janela: PRs com lead time de ~1 h (melhorou), todos com conserto (piorou, guarda); jardim parado (neutro)
    for k in range(3):
        quando = t0 + (k + 1) * 0.5 * H
        filho = _item(s, f"filho {k}", quando - 1 * H)
        _pr(s, 100 + k, filho, quando, consertos=1)
    _jardim(s, t0 + 1 * H, 10.5)

    ex.avaliar(s, reply, t0 + 2 * H + 1)
    v = {r["item_id"]: dict(r) for r in s.q("SELECT * FROM experimentos")}
    assert v[lead]["veredito"] == "melhorou" and v[conserto]["veredito"] == "piorou" and v[jardim]["veredito"] == "neutro"
    assert v[seco]["veredito"] == ex.INCONCLUSIVO and v[seco]["estendida"] == 1 and v[seco]["decidido_em"] is None
    assert v[seco]["fim"] == pytest.approx(t0 + 4 * H)       # a janela estende uma vez

    # só a guarda que estourou a margem abre a reversão, presa ao PR do item
    reversoes = s.q("SELECT * FROM roadmap WHERE titulo LIKE 'Reverter%'")
    assert len(reversoes) == 1 and f"#{conserto}" in reversoes[0]["titulo"]
    assert v[conserto]["reversao_item"] == reversoes[0]["id"] and v[lead]["reversao_item"] is None
    assert "except_exception" in (s.get(ex.DESCANSO) or {})  # neutro: o tema descansa

    ex.avaliar(s, reply, t0 + 4 * H + 1)                     # estendida e ainda sem amostra: inconclusivo final
    r = s.one("SELECT * FROM experimentos WHERE item_id=?", (seco,))
    assert r["veredito"] == ex.INCONCLUSIVO and r["decidido_em"] is not None and r["fim"] == pytest.approx(t0 + 4 * H)
    assert len(s.q("SELECT * FROM roadmap WHERE titulo LIKE 'Reverter%'")) == 1


def test_piorou_fora_da_guarda_nao_reverte_sozinho(circle):
    s, H = circle.store, 3600.0
    t0 = time.time() - 10 * H
    iid = _item(s, "Lead time cai", t0 - 10 * H)
    ex.gravar(s, iid, ex.Experimento.de({**EXP, "baseline": 1.0, "alvo": 0.5, "janela_h": 2, "n_min": 1}), t0 - 9 * H)
    s.x("UPDATE roadmap SET status='feito' WHERE id=?", (iid,))
    ex.avaliar(s, None, t0)
    filho = _item(s, "filho", t0 - 20 * H)                    # lead time de ~21 h: piorou muito além da margem
    _pr(s, 7, filho, t0 + H)
    ex.avaliar(s, None, t0 + 2 * H + 1)
    assert s.one("SELECT veredito FROM experimentos WHERE item_id=?", (iid,))["veredito"] == "piorou"
    assert not s.q("SELECT 1 FROM roadmap WHERE titulo LIKE 'Reverter%'")


def test_veredito_usa_a_margem_e_o_sentido_da_metrica():
    assert ex.veredito("menor", 1.2, 1.0, 0.1) == "melhorou"
    assert ex.veredito("menor", 1.2, 1.25, 0.1) == "neutro"
    assert ex.veredito("menor", 1.2, 1.4, 0.1) == "piorou"
    assert ex.veredito("maior", 0.5, 0.4, 0.2) == "neutro"
    assert ex.veredito("maior", 0.5, 0.2, 0.2) == "piorou"


def test_vigia_avalia_os_experimentos_a_cada_passagem():
    import inspect

    from circulo import vigia
    assert "experimentos.avaliar(" in inspect.getsource(vigia.Vigia.rodar)

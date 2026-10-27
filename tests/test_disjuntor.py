"""Disjuntor de LLM: a conta sem crédito ("credit balance is too low") abre uma pausa com backoff e um único aviso;
nenhuma chamada sai durante a pausa, o meio-aberto libera um teste só e um sucesso fecha o circuito."""
import time

import pytest

from circulo.disjuntor import ABERTO, FECHADO, MEIO_ABERTO, CircuitoAberto, LLMProtegida, classificar, transicao
from circulo.reparo import DeveloperComReparo

from test_self_dev import FakeGH, repo  # noqa: F401 — fixture do repositório

CREDITO = 'claude -p: {"is_error": true, "api_error_status": 400, "result": "Credit balance is too low"}'


class LLMSemCredito:
    def __init__(self):
        self.chamadas, self.falhar = 0, True

    def generate(self, **kw):
        self.chamadas += 1
        if self.falhar:
            raise RuntimeError(CREDITO)
        return "ok"


class Kv(dict):
    def get(self, k, default=None):
        return super().get(k, default)

    def set(self, k, v):
        self[k] = v

    def x(self, sql, params):
        self.setdefault("alertas", []).append(params[0])


def test_so_credito_baixo_e_externa():
    assert classificar(CREDITO) == "externa"
    assert classificar("HTTP Error 529: overloaded") == "falha"
    assert classificar("Claude AI usage limit reached|1760000000") == "falha"


def test_cinco_falhas_externas_um_aviso_zero_chamadas_na_pausa_e_um_sucesso_fecha():
    estado, avisos = None, 0
    for i in range(5):
        estado, pode, _, avisar = transicao(estado, "externa", 1000.0 + i)
        avisos += avisar
        assert not pode
    assert avisos == 1 and estado["estado"] == ABERTO
    chamadas = 0
    for t in range(1001, int(estado["proxima"])):
        estado, pode, proxima, _ = transicao(estado, "consulta", float(t))
        chamadas += pode
        assert proxima == estado["proxima"]
    assert chamadas == 0
    estado, pode, _, _ = transicao(estado, "consulta", estado["proxima"])
    assert pode and estado["estado"] == MEIO_ABERTO
    estado, pode, proxima, avisar = transicao(estado, "sucesso", estado["proxima"] + 1)
    assert estado["estado"] == FECHADO and pode and proxima is None and not avisar


def test_meio_aberto_libera_um_teste_e_a_falha_reabre_com_backoff_maior():
    estado, _, _, _ = transicao(None, "externa", 0.0, jitter=0.9)
    pausa1 = estado["proxima"]
    estado, pode, _, _ = transicao(estado, "consulta", pausa1)
    assert pode and estado["estado"] == MEIO_ABERTO
    estado, pode, _, _ = transicao(estado, "consulta", pausa1 + 1)
    assert not pode                                                   # um único teste por vez
    estado, pode, proxima, avisar = transicao(estado, "externa", pausa1 + 2, jitter=0.0)
    assert estado["estado"] == ABERTO and not pode and not avisar
    assert proxima - (pausa1 + 2) > pausa1                            # backoff maior, mesmo com o jitter menor


def test_backoff_tem_teto():
    from circulo.disjuntor import TETO_S
    estado = None
    for _ in range(30):
        estado, _, _, _ = transicao(estado, "externa", 0.0, jitter=1.0)
        estado["estado"] = MEIO_ABERTO
    assert estado["proxima"] <= TETO_S


def test_llm_protegida_nao_chama_durante_a_pausa_e_persiste(tmp_path):
    kv, llm = Kv(), LLMSemCredito()
    relogio = [1000.0]
    p = LLMProtegida(llm, kv, agora=lambda: relogio[0])
    for _ in range(5):
        with pytest.raises((RuntimeError, CircuitoAberto)):
            p.generate(system="s", prompt="p", model="m", max_tokens=5)
    assert llm.chamadas == 1 and len(kv["alertas"]) == 1
    # outro processo (reinício do loop) lê o mesmo estado: continua sem chamar
    p2 = LLMProtegida(llm, kv, agora=lambda: relogio[0])
    with pytest.raises(CircuitoAberto):
        p2.generate(system="s", prompt="p", model="m", max_tokens=5)
    assert llm.chamadas == 1
    relogio[0] = kv.get("disjuntor_llm")["proxima"]
    llm.falhar = False
    assert p2.generate(system="s", prompt="teste do meio-aberto", model="m", max_tokens=5) == "ok"
    assert kv.get("disjuntor_llm")["estado"] == FECHADO and llm.chamadas == 2


class AgenteSemCredito:
    def __init__(self):
        self.tasks = []

    def run(self, task, workdir):
        self.tasks.append(task)
        return {"ok": False, "tokens": 0, "log": CREDITO}


def test_developer_sem_credito_nao_chama_o_agente_na_pausa(circle, repo):  # noqa: F811
    s = circle.store
    agora = time.time()
    item = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at,estudo) "
               "VALUES('Item sem crédito','consertar a soma','loop','pendente','x',999,?,?,'estudado')", (agora, agora))
    agente = AgenteSemCredito()
    dev = DeveloperComReparo(circle.ctx, repo, agente, FakeGH(), test_cmd=["true"], lint_cmd=[], fix_cmds=[])
    assert dev.run_once(item, autorizado=True).status == "agente_falhou"
    for _ in range(4):
        assert dev.run_once(item, autorizado=True).status == "pausa_llm"
    assert len(agente.tasks) == 1
    assert s.get("disjuntor_llm")["estado"] == ABERTO
    assert s.one("SELECT COUNT(*) n FROM alerts WHERE message LIKE 'LLM em pausa%'")["n"] == 1


def test_o_loop_consulta_o_disjuntor_antes_de_cada_chamada(tmp_path):
    from circulo.loop import Circle
    from circulo.decision import LocalJev
    llm = LLMSemCredito()
    c = Circle(tmp_path, jev=LocalJev(), llm=llm)
    for _ in range(3):
        with pytest.raises((RuntimeError, CircuitoAberto)):
            c.ctx.dl.llm.generate(system="s", prompt="p", model="m", max_tokens=5)
    assert llm.chamadas == 1
    assert c.store.get("disjuntor_llm")["estado"] == ABERTO
    assert c.store.one("SELECT COUNT(*) n FROM alerts WHERE message LIKE '%crédito%'")["n"] == 1

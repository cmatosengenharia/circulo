"""Revisão dupla independente (Santa, ECC-2 do ADR 0001): o Validador LLM e a rubrica do Jev precisam aprovar.

O Jev pontua o diff contra a MESMA rubrica do Validador (um Score por critério) sem ver o veredito dele. Qualquer um
reprovando = rodada de correção; 2 rodadas sem acordo no mesmo item = o portão do PR devolve o item com a lista de
achados. `medir` conta quantos PRs a segunda opinião barrou e quantos desses o CI depois confirmou."""
import subprocess
import time

from circulo import revisao_dupla, validador
from circulo.decision import Decision
from circulo.neuronios import ABRIR_PR, avaliar_aprendidos

APROVA = '{"aprovado": true, "problemas": [], "risco": "baixo"}'


class JevFalso:
    """Cliente Jev remoto de mentira (contrato `decision.JevClient`: devolve `(decisões, tokens)`). Entra em
    `ctx.dl.jev`; quem `revisao_dupla.opinar` chama é o `DecisionLayer.ask_many`, que desempacota a tupla e devolve
    o dict de decisões. Guarda a nota por critério da rubrica e o estado que recebeu."""
    source = "jev"

    def __init__(self, notas: dict[str, float]):
        self.notas, self.estados = notas, []

    def ask_many(self, state, questions):
        self.estados.append(dict(state))
        return {q: Decision(q, "score", self.notas.get(q.removeprefix(revisao_dupla.PREFIXO), 2.0), 0.9, "jev")
                for q in questions}, 10


def _wt(tmp_path, nome="wt"):
    wt = tmp_path / nome
    wt.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=wt, check=True)
    (wt / "app.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=wt, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base"], cwd=wt, check=True)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, capture_output=True, text=True).stdout.strip()
    (wt / "app.py").write_text("x = 2\n")
    return wt, base


ITEM = {"id": 7, "titulo": "Somar certo", "detalhe": "d"}


def test_validador_e_jev_usam_a_mesma_rubrica():
    for _, problema in revisao_dupla.RUBRICA:
        assert problema in validador.SYSTEM


def test_jev_barra_o_que_o_validador_aprovou_sem_ver_o_veredito_dele(circle, tmp_path):
    wt, base = _wt(tmp_path)
    jev = circle.ctx.dl.jev = JevFalso({"teste": 0.0})
    v = validador.revisar_pr(circle.ctx, wt, base, ITEM, chamar=lambda s, p: APROVA)
    assert jev.estados                                                            # passou pela camada até o cliente
    assert not v["aprovado"] and v["revisao_dupla"] == "corrigir"
    assert any("Jev" in p and "teste" in p for p in v["problemas"])
    estado = jev.estados[-1]
    assert "x = 2" in estado["diff"] and "aprovado" not in str(estado)            # sem contexto compartilhado
    jev.notas = {}
    v = validador.revisar_pr(circle.ctx, wt, base, ITEM, chamar=lambda s, p: APROVA)
    assert v["aprovado"] and v["revisao_dupla"] == "acordo"


def test_jev_local_nao_opina_e_nao_barra(circle, tmp_path):
    wt, base = _wt(tmp_path)                                    # LocalJev do conftest: Score desconhecido sai 0.0
    v = validador.revisar_pr(circle.ctx, wt, base, ITEM, chamar=lambda s, p: APROVA)
    assert v["aprovado"] and v["revisao_dupla"] == "acordo"


def test_duas_rodadas_sem_acordo_devolvem_o_item_pelo_portao_do_pr(circle, tmp_path):
    wt1, base1 = _wt(tmp_path, "wt1")
    circle.ctx.dl.jev = JevFalso({"escopo": 0.0})
    assert validador.revisar_pr(circle.ctx, wt1, base1, ITEM, chamar=lambda s, p: APROVA)["revisao_dupla"] == "corrigir"
    assert revisao_dupla.portao(circle.store, 7, wt1) is None                     # 1ª rodada: corrige e segue
    wt2, base2 = _wt(tmp_path, "wt2")
    v = validador.revisar_pr(circle.ctx, wt2, base2, ITEM, chamar=lambda s, p: APROVA)
    assert not v["aprovado"] and v["revisao_dupla"] == "devolver"
    res = avaliar_aprendidos(circle.store, ABRIR_PR, wt2, {}, {}, 7)
    barrado = [r for r in res if r.portao == revisao_dupla.PORTAO]
    assert barrado and not barrado[0].ok and "escopo" in barrado[0].motivo        # o item volta com a lista de achados
    assert revisao_dupla.portao(circle.store, 7, wt1) is None                     # só o worktree da rodada que estourou
    assert revisao_dupla.portao(circle.store, 8, wt2) is None


def test_medir_conta_barrados_e_os_que_o_ci_confirmou(circle, tmp_path):
    wt, base = _wt(tmp_path)
    circle.ctx.dl.jev = JevFalso({"regressao": 0.0})
    validador.revisar_pr(circle.ctx, wt, base, ITEM, chamar=lambda s, p: APROVA)
    validador.revisar_pr(circle.ctx, wt, base, {**ITEM, "id": 8}, chamar=lambda s, p: APROVA)
    validador.revisar_pr(circle.ctx, wt, base, {**ITEM, "id": 9},
                         chamar=lambda s, p: '{"aprovado": false, "problemas": ["regressão"], "risco": "alto"}')
    agora = time.time()
    circle.store.x("INSERT INTO prs(number, titulo, status, created_at, updated_at, item_id) VALUES(41,'a','fechado',?,?,7)", (agora, agora))
    circle.store.x("INSERT INTO merges(pr, sha, merged, reason, details, created_at) VALUES(41,'s',0,'checks falhando: testes','{}',?)", (agora,))
    m = revisao_dupla.medir(circle.store)
    assert m == {"barrados": 2, "confirmados_ci": 1, "rodadas": 3, "acordos": 0}  # o item 9 o Validador já barrava

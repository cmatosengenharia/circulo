"""Lição #15 (rastro:cadeia): item do loop gravado no roteiro sem a pergunta do conselho que o originou.

A checagem só no planejador (#96) era contornada: o Vigia e o Jardineiro gravavam origem='loop' direto no roadmap, sem
pergunta, e cada um desses itens virava a lacuna "item planejado pelo loop sem a pergunta do conselho que o originou".
Agora há um ponto único de gravação, `roadmap.gravar_item`, que recusa item sem pergunta existente; os testes abaixo
gravam por cada origem (planejador, vigia, jardineiro) e um teste estrutural impede um caminho novo de gravação.
"""
import re
import time
from pathlib import Path

import pytest

from circulo import jardineiro, planejador, rastro, roadmap, vigia

RAIZ = Path(__file__).resolve().parent.parent / "circulo"
# quem grava no roadmap sem passar por roadmap.gravar_item, e por quê pode: nenhum deles grava origem='loop'
OUTRAS_ORIGENS = {"medico.py": "erro", "incidents.py": "erro", "licoes.py": "erro", "fatiador.py": "sub_item",
                  "loop.py": "pedido_cassio", "projects.py": "pedido_cassio",
                  "mercado.py": "referencia", "autonomia.py": "erro", "skills.py": "referencia"}      # 1.72: técnica de repositório de referência; Médico escalado assumido


def _sem_lacuna(circle, item_id: int) -> None:
    assert circle.store.one("SELECT 1 FROM perguntas WHERE item_id=?", (item_id,)), f"item #{item_id} sem pergunta de origem"
    assert rastro.LACUNA_SEM_PERGUNTA not in rastro.cadeia_item(circle.store, item_id)["lacunas"]


@pytest.mark.parametrize("pid", [None, 0, -1, 987654])
def test_ponto_unico_recusa_item_sem_pergunta_licao_15(circle, pid):
    """Lição #15: gravar no roteiro sem pergunta (ou com uma que não existe) levanta erro e não grava nada."""
    s = circle.store
    antes = s.one("SELECT COUNT(*) n FROM roadmap")["n"]
    with pytest.raises(ValueError):
        roadmap.gravar_item(s, pid, "Título", "Detalhe", "evidência")
    with pytest.raises(planejador.SemPerguntaOrigem):        # o planejador grava pelo mesmo ponto
        planejador.gravar_item(s, pid, "Título", "Detalhe", "evidência")
    assert s.one("SELECT COUNT(*) n FROM roadmap")["n"] == antes


def test_vigia_grava_item_preso_a_pergunta_licao_15(circle):
    """Lição #15: a trava que o Vigia vira item nasce com a pergunta de origem (persona vigia)."""
    v = vigia.Vigia(circle.ctx)
    v._agir({"acao": "abrir_item", "titulo": "pergunta válida parada há 3 h", "chave": "pergunta_valida_parada",
             "conf": 0.9, "evidencia": {"base": "medido"}, "sugestao": "drenar a fila"}, time.time())
    item = circle.store.one("SELECT id, origem FROM roadmap WHERE titulo LIKE 'Vigia:%'")
    assert item["origem"] == "loop"
    _sem_lacuna(circle, item["id"])


def test_vigia_porteiro_grava_item_preso_a_pergunta_licao_15(circle):
    """Lição #15: a revisão do limiar do porteiro também nasce com a pergunta de origem."""
    s, agora = circle.store, time.time()
    recusada = s.x("INSERT INTO perguntas(chave,persona,texto,status,created_at,updated_at) VALUES('k','operador','?','valida',?,?)",
                   (agora, agora))
    s.set(planejador.PORTEIRO, {"ultimo": {"decisao": "recusou", "pergunta_id": recusada, "seguidas": vigia.RECUSAS_PORTEIRO,
                                           "motivo": "abaixo_do_limiar", "valor": 0.3, "limiar": 0.4, "fonte": "jev"}})
    vigia.Vigia(circle.ctx)._recusada_pelo_porteiro(agora)
    item = s.one("SELECT id FROM roadmap WHERE titulo LIKE 'Vigia: revisar o limiar%'")
    _sem_lacuna(circle, item["id"])


def test_jardineiro_grava_item_preso_a_pergunta_licao_15(circle):
    """Lição #15: o padrão que o Jardineiro mede nasce como pergunta e o item fica preso a ela."""
    jardineiro._item(circle.store, "except Exception: 3 → 8 (b.py (5))")
    item = circle.store.one("SELECT id FROM roadmap WHERE titulo LIKE 'Jardineiro:%'")
    _sem_lacuna(circle, item["id"])


def test_nenhum_caminho_novo_grava_no_roteiro_por_fora_licao_15():
    """Lição #15: só roadmap.py grava item do loop; um INSERT novo no roadmap em outro módulo precisa entrar aqui
    com a origem que ele grava (e nunca 'loop')."""
    gravam = {p.name for p in RAIZ.glob("*.py") if re.search(r"INSERT\s+(OR\s+\w+\s+)?INTO\s+roadmap\b", p.read_text())}
    assert gravam - {"roadmap.py"} <= set(OUTRAS_ORIGENS), f"grava no roadmap por fora de roadmap.gravar_item: {sorted(gravam - {'roadmap.py'} - set(OUTRAS_ORIGENS))}"
    assert "loop" not in OUTRAS_ORIGENS.values()

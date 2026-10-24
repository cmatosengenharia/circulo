"""Canário de falha: ponto de verificação que nunca falhou pode estar quebrado sem ninguém saber.

Para cada ponto que só passou, o ciclo de saúde injeta a falha de propósito num estado temporário e compara com um
controle sem falha (fault injection com grupo de controle): a falha tem de ser acusada e o controle tem de passar.
O resultado vira um evento em `canarios`; o auditor do conselho só conta como "nunca exercitado" o ponto sem canário
verde recente.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from . import confianca
from .state import Store

INTERVALO = 86400          # um canário por ponto por dia
VALIDADE = 7 * 86400       # canário verde mais velho que isso não prova mais nada


def _ok_do_ultimo(s: Store, ponto: str) -> bool:
    r = s.one("SELECT ok FROM verificacoes WHERE ponto=? ORDER BY id DESC LIMIT 1", (ponto,))
    return bool(r and r["ok"])


def _painel_frescor(velho: bool) -> bool:
    s = Store(":memory:")
    dado_em = time.time() - (60 if velho else 0.2)               # o painel velho mostra um dado de um minuto atrás
    atraso = (time.time() - dado_em) * 1000
    for _ in range(99):                                           # o SLO só julga com 100 amostras na janela
        s.x("INSERT INTO frescor(atraso_ms, em) VALUES(?,?)", (atraso, time.time()))
    confianca.registrar_frescor(s, atraso)
    return _ok_do_ultimo(s, "painel:frescor")


_CODIGO = {"filename": "circulo/a.py", "additions": 3, "deletions": 0}
_TESTE = {"filename": "tests/test_a.py", "additions": 1, "deletions": 0}
_CONFLITO = ["<" * 7 + " HEAD", "x = 1", "=" * 7, "x = 2", ">" * 7 + " main"]


def _portao_abrir_pr(ponto: str, causa: str, com_falha: tuple, controle: tuple) -> Callable[[bool], bool]:
    """O portão nato do abrir_pr julga o diff pela mesma sinapse do Developer; só conta como barrado no ponto certo
    e com a causa certa."""
    def passa(falha: bool) -> bool:
        from types import SimpleNamespace

        from . import neuronios
        from .licoes import Licoes
        s = Store(":memory:")
        arquivos, adicionadas = com_falha if falha else controle
        neuronios.registrar(SimpleNamespace(licoes=Licoes(s)), neuronios.ABRIR_PR,
                            neuronios.portoes_natos_pr(arquivos, adicionadas))
        r = s.one("SELECT ok, motivo FROM verificacoes WHERE ponto=? ORDER BY id DESC LIMIT 1", (ponto,))
        return not r or bool(r["ok"]) or r["motivo"] != causa
    return passa


class _GitHubSimulado:
    def __init__(self, runs: list[dict], atras: int):
        self.runs, self.atras = runs, atras

    def open_prs(self):
        return [{"number": 1, "head_sha": "abc", "head_ref": "circulo/canario", "draft": False, "title": "canário"}]

    def pr_files(self, n):
        return [_CODIGO, _TESTE]

    def check_runs(self, sha):
        return self.runs

    def label_events(self, n):
        return []

    def atras_da_main(self, sha):
        return self.atras

    def update_branch(self, n):
        pass

    def merge(self, n, sha, title):
        return True, "merged"


def _gate_merge(falha: bool) -> bool:
    """O portão do merge julga PRs simulados pela interface pública (`MergeGate.run`). Com falha (check vermelho,
    check pendente, branch atrás da main) só conta como barrado se cada PR ficou com merged=0 e a razão certa."""
    from .agents import Ctx
    from .budget import Budget
    from .decision import DecisionLayer, LocalJev
    from .merge_gate import MergeGate, required_checks
    from .policy import PolicyStore
    verdes = [{"id": i, "name": n, "status": "completed", "conclusion": "success"} for i, n in enumerate(required_checks())]
    um = required_checks()[0]
    casos = [(verdes, 0, "todos os gates passaram")] if not falha else [
        ([{**r, "conclusion": "failure"} if r["name"] == um else r for r in verdes], 0, f"checks falhando: {um}"),
        ([{**r, "status": "in_progress", "conclusion": None} if r["name"] == um else r for r in verdes], 0,
         f"checks em andamento: {um}"),
        (verdes, 3, "branch 3 commit(s) atrás da main: atualizada, o CI roda de novo")]
    for runs, atras, razao in casos:
        s = Store(":memory:")
        policies = PolicyStore(s)
        budget = Budget(s, policies.get)
        ctx = Ctx(s, policies, budget, DecisionLayer(s, policies.get, budget, jev=LocalJev()), Path("."), budget.now)
        MergeGate(ctx, _GitHubSimulado(runs, atras), human="").run()
        r = s.one("SELECT merged, reason FROM merges WHERE pr=1 ORDER BY id DESC LIMIT 1")
        if not r or r["reason"] != razao or bool(r["merged"]) != (not falha):
            return falha
    return not falha


INJECOES: dict[str, Callable[[bool], bool]] = {
    "gate:merge": _gate_merge,
    "painel:frescor": _painel_frescor,
    "developer:abrir_pr:sem_marcador_de_conflito": _portao_abrir_pr(
        "developer:abrir_pr:sem_marcador_de_conflito", "marcadores de conflito em: circulo/a.py",
        ([_CODIGO, _TESTE], {"circulo/a.py": _CONFLITO}), ([_CODIGO, _TESTE], {"circulo/a.py": ["x = 1"]})),
    "developer:abrir_pr:teste_novo": _portao_abrir_pr(
        "developer:abrir_pr:teste_novo", "nenhum teste novo em tests/", ([_CODIGO], {}), ([_CODIGO, _TESTE], {})),
}


def injetar(ponto: str) -> dict:
    passa = INJECOES[ponto]
    velho_falhou, fresco_passou = not passa(True), passa(False)
    return {"ponto": ponto, "velho_falhou": velho_falhou, "fresco_passou": fresco_passou,
            "ok": velho_falhou and fresco_passou}


def _injetar_portao(portao: dict) -> dict:
    """O portão aprendido julga a assinatura da sua lição (tem de barrar) e o controle (tem de passar), num store e num
    worktree descartáveis: o portão real não conta avaliação nem bloqueio."""
    from .licoes import portoes_que_deixam_passar
    causa = next((r["causa"] for r in portoes_que_deixam_passar([portao])), "")
    return {"ponto": f"portao:{portao['id']}", "velho_falhou": causa in ("", "barrou também o controle"),
            "fresco_passou": causa != "barrou também o controle", "ok": not causa}


def _portoes_que_nunca_barraram(s: Store, now: float) -> list[dict]:
    return [dict(r) for r in s.q("SELECT * FROM portoes WHERE ativo=1 AND bloqueios=0 AND created_at < ?",
                                 (now - INTERVALO,))]


def portoes_sem_prova(s: Store, now: float | None = None) -> int:
    """Portões aprendidos que nunca barraram nada e não têm canário verde provando que ainda recusam a própria lição."""
    now = now or time.time()
    provados = com_canario(s, now)
    return sum(f"portao:{p['id']}" not in provados for p in _portoes_que_nunca_barraram(s, now))


def com_canario(s: Store, now: float | None = None) -> set[str]:
    """Pontos com canário verde dentro da validade."""
    desde = (now or time.time()) - VALIDADE
    return {r["ponto"] for r in s.q("SELECT ponto FROM canarios WHERE em>=? GROUP BY ponto "
                                     "HAVING MAX(id) = MAX(CASE WHEN ok=1 THEN id END)", (desde,))}


def rodar(s: Store, reply=None, now: float | None = None) -> list[dict]:
    """Ciclo de saúde: injeta a falha em cada ponto que nunca falhou e tem injeção conhecida, e a assinatura da lição
    em cada portão aprendido que nunca barrou nada; no máximo 1x por dia cada."""
    now = now or time.time()
    pontos = [r["ponto"] for r in s.q("SELECT ponto FROM verificacoes GROUP BY ponto HAVING SUM(ok=0)=0")]
    alvos = [(p, lambda p=p: injetar(p)) for p in pontos if p in INJECOES]
    alvos += [(f"portao:{p['id']}", lambda p=p: _injetar_portao(p)) for p in _portoes_que_nunca_barraram(s, now)]
    out = []
    for p, injetor in alvos:
        if s.one("SELECT 1 FROM canarios WHERE ponto=? AND em>?", (p, now - INTERVALO)):
            continue
        r = injetor()
        s.x("INSERT INTO canarios(ponto, ok, velho_falhou, fresco_passou, em) VALUES(?,?,?,?,?)",
            (p, int(r["ok"]), int(r["velho_falhou"]), int(r["fresco_passou"]), now))
        if not r["ok"] and reply:
            reply(f"Canário de {p} falhou: a falha injetada {'não foi acusada' if not r['velho_falhou'] else 'acusou também o controle'}.",
                  "saude")
        out.append(r)
    return out

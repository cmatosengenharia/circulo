"""Rodadas de comentário de revisão até o merge (pergunta do conselho #446): contadas por PR, mediana e p90 na evidência."""
import time

from circulo import rodadas_revisao
from circulo.planejador import Planejador

H = 3600.0


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _humano(t: float, chave: str = "created_at") -> dict:
    return {chave: _iso(t), "user": {"login": "revisora", "type": "User"}}


def _commit(t: float) -> dict:
    return {"commit": {"committer": {"date": _iso(t)}}}


class GitHubFalso:
    """Responde as rotas de revisão, comentário e commit de cada PR sintético; conta as chamadas."""

    def __init__(self, prs: dict[int, dict[str, list]]):
        self.prs, self.chamadas = prs, 0

    def _req(self, method, path, body=None, tolerar=()):
        self.chamadas += 1
        _, recurso, n, sub = path.split("?")[0].split("/")
        return self.prs[int(n)].get(f"{recurso}/{sub}", [])


def _pr(t0: float, rodadas: int) -> dict[str, list]:
    """Abre com um commit; cada rodada é um comentário humano seguido de commit de correção."""
    reviews, commits = [], [_commit(t0)]
    for i in range(rodadas):
        reviews.append(_humano(t0 + (2 * i + 1) * H, "submitted_at"))
        commits.append(_commit(t0 + (2 * i + 2) * H))
    return {"pulls/reviews": reviews, "pulls/commits": commits}


def _mergeado(s, pr: int, em: float) -> None:
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(?,?,1,'ok','{}',?)", (pr, f"sha{pr}", em))


def test_conta_comentario_seguido_de_commit_como_rodada():
    t = 1_800_000_000.0
    comentarios = [t + 1, t + 2, t + 10]          # dois comentários antes do mesmo commit são uma rodada só
    commits = [t, t + 5, t + 6]                   # o comentário em t+10 não teve correção: não conta
    assert rodadas_revisao.contar(comentarios, commits) == 1
    assert rodadas_revisao.contar([], [t]) == 0
    assert rodadas_revisao.contar([t + 1, t + 3], [t + 2, t + 4]) == 2


def test_mediana_e_p90_de_prs_sinteticos_com_0_1_e_3_rodadas(circle):
    s, agora = circle.store, time.time()
    t0 = agora - 3 * 86400
    gh = GitHubFalso({101: _pr(t0, 0), 102: _pr(t0, 1), 103: _pr(t0, 3)})
    for pr in gh.prs:
        _mergeado(s, pr, agora - 86400)
    assert rodadas_revisao.resumo_7d(s, agora)["mediana"] is None     # hoje: indefinido

    assert rodadas_revisao.sincronizar(s, gh, agora) == 3
    r = rodadas_revisao.resumo_7d(s, agora)
    assert (r["mediana"], r["p90"], r["prs"], r["mergeados_7d"], r["iterados"]) == (1, 3, 3, 3, 1)
    assert Planejador(circle.ctx).evidencia()["rodadas_revisao_7d"]["mediana"] == 1

    chamadas = gh.chamadas
    assert rodadas_revisao.sincronizar(s, gh, agora) == 0             # PR já medido não volta à API
    assert gh.chamadas == chamadas


def test_bot_e_pr_fora_da_janela_nao_contam(circle):
    s, agora = circle.store, time.time()
    t0 = agora - 3 * 86400
    bot = {"created_at": _iso(t0 + H), "user": {"login": "github-actions[bot]", "type": "Bot"}}
    gh = GitHubFalso({201: {"issues/comments": [bot], "pulls/commits": [_commit(t0), _commit(t0 + 2 * H)]},
                      202: _pr(t0, 3),
                      203: {"pulls/comments": [_humano(t0 + H)], "pulls/commits": [_commit(t0), _commit(t0 + 2 * H)]}})
    _mergeado(s, 201, agora - 86400)
    _mergeado(s, 203, agora - 86400)
    _mergeado(s, 202, agora - 8 * 86400)
    rodadas_revisao.sincronizar(s, gh, agora)
    r = rodadas_revisao.resumo_7d(s, agora)
    assert (r["prs"], r["mergeados_7d"], r["mediana"], r["p90"]) == (2, 2, 0.5, 1)


def test_sem_cliente_rest_nao_mede_nem_quebra(circle):
    _mergeado(circle.store, 301, time.time())
    assert rodadas_revisao.sincronizar(circle.store, None) == 0
    assert rodadas_revisao.resumo_7d(circle.store)["mergeados_7d"] == 1

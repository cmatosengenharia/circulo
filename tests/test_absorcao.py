"""01/11: absorção de repositórios — ADR por fonte, técnicas com prova, semeadura por prioridade, evidência e varredura."""
import re
import subprocess
import time
from pathlib import Path

import pytest

from circulo import absorcao, garimpo
from circulo.absorcao_fontes import FONTES, PREREQUISITOS
from circulo.decision import Decision

RAIZ = Path(__file__).resolve().parent.parent

RANKING = """[Github Ranking](../README.md)
==========

## Top 100 Stars in Claude

| Ranking | Project Name | Stars | Forks | Language | Open Issues | Description | Last Commit |
| ------- | ------------ | ----- | ----- | -------- | ----------- | ----------- | ----------- |
| 1 | [ECC](https://github.com/affaan-m/ECC) | 294331 | 43581 | JavaScript | 78 | The agent harness performance optimization system. | 2026-10-30T03:06:42Z |
| 2 | [hermes-agent](https://github.com/NousResearch/hermes-agent) | 259319 | 57041 | Python | 17994 | The agent that grows with you | 2026-11-01T06:44:06Z |
| 3 | [andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) | 227698 | 22715 | None | 0 | A single CLAUDE.md | with a pipe inside | 2026-04-01T00:00:00Z |
| 4 | [video-seo](https://github.com/x/video-seo) | 1,200 | 10 | TypeScript | 1 | SEO and marketing copy for YouTube shorts | 2026-10-01T00:00:00Z |
"""

CSV = '''ID,Display Name,Category,Sub-Category,Link,Author Name,Author Link,Active,Date Added,Last Checked,Description,Stale
a,Orq,Agent Orchestration,,https://github.com/o/orq,o,https://github.com/o,TRUE,,,"Runs agents, with ""quotes""",FALSE
b,Velho,Agent Orchestration,,https://github.com/o/velho,o,https://github.com/o,TRUE,,,stale one,TRUE
c,Inativo,Skills,,https://github.com/o/inativo,o,https://github.com/o,FALSE,,,off,FALSE
d,Doc,Documentation,,https://docs.example.com/x,o,https://github.com/o,TRUE,,,not github,FALSE
e,Status,Status Lines,,https://github.com/o/status,o,https://github.com/o,TRUE,,,a status line,FALSE
'''


def _tecnicas():
    return [t for f in FONTES for t in f["tecnicas"]] + list(PREREQUISITOS)


# ------------------------------------------------------------------ catálogo e ADR (a validação que pediu o Cássio)
def test_catalogo_cada_tecnica_tem_frente_alvo_prioridade_e_prova():
    ids = [t["id"] for t in _tecnicas()]
    assert len(ids) == len(set(ids)), "id de técnica repetido"
    for t in _tecnicas():
        assert t["frente"] in absorcao.FRENTES and t["alvo"] in absorcao.ALVOS and t["prio"] in absorcao.PRIORIDADES, t["id"]
        assert re.search(r"\.(py|cs|ts)$", t["prova"].split("::")[0]), f"{t['id']}: prova precisa ser um arquivo de teste"
        assert len(t["detalhe"]) > 80 and t["origem"], f"{t['id']}: técnica sem como-entra ou sem origem na fonte"
    for f in FONTES:
        assert f["descartes"], f"{f['slug']}: ADR sem descarte (o que ficou de fora e por quê)"
        assert set(f["frentes"]) <= set(absorcao.FRENTES) and f["licenca"]
        assert {t["frente"] for t in f["tecnicas"]} <= set(f["frentes"]), f"{f['slug']}: técnica de frente não declarada na fonte"
    assert len({f["adr"] for f in FONTES}) == len(FONTES)


def test_todo_repo_absorvido_tem_adr_atualizado_no_repositorio():
    for f in FONTES:
        p = RAIZ / absorcao.adr_caminho(f)
        assert p.exists(), f"falta {p}: rode `python -m circulo.absorcao adr`"
        assert p.read_text(encoding="utf-8") == absorcao.adr_texto(f), f"{p.name} desatualizado: rode `python -m circulo.absorcao adr`"
        txt = p.read_text(encoding="utf-8")
        assert "## Decisão — o que entrou" in txt and "## Descartado" in txt
        assert all(t["id"] in txt for t in f["tecnicas"]) and all(d["o_que"] in txt for d in f["descartes"])
    assert (RAIZ / absorcao.PASTA_ADR / "README.md").exists()


def test_entregue_nesta_versao_tem_a_prova_no_repositorio():
    for t in _tecnicas():
        if t.get("entregue"):
            assert (RAIZ / t["prova"]).exists(), f"{t['id']} marcada como entregue sem o teste {t['prova']}"


def test_prioridade_mvp_antes_de_venda_antes_de_loop_e_prerequisito_primeiro():
    ts = absorcao.tecnicas()
    ordem = [absorcao.PRIORIDADES.index(t["prio"]) for t in ts]
    assert ordem == sorted(ordem) and ts[0]["id"] == "PRE-1"


# ------------------------------------------------------------------ Jev first
class _DL:
    def __init__(self, valor, fonte="jev", conf=0.9, erro=False):
        self.valor, self.fonte, self.conf, self.erro, self.perguntas = valor, fonte, conf, erro, []

    def ask(self, nome, q, state):
        self.perguntas.append((nome, q, state))
        if self.erro:
            raise OSError("fora do ar")
        return Decision(nome, "choice", self.valor, self.conf, self.fonte)


def test_classificar_pergunta_ao_jev_e_cai_na_regra_quando_fora_ou_em_duvida():
    dl = _DL("venda")
    assert absorcao.classificar("qualquer coisa", dl) == ("venda", "jev")
    assert dl.perguntas[0][0] == "absorcao_frente" and set(dl.perguntas[0][1].criteria) == set(absorcao.FRENTES)
    assert absorcao.classificar("SEO and marketing copy", _DL("loop", conf=0.1)) == ("venda", "local")
    assert absorcao.classificar("remotion video captions", _DL("loop", erro=True)) == ("produto", "local")
    assert absorcao.classificar("claude code hooks and subagents", None) == ("loop", "local")
    assert absorcao.regra_frente("") == "loop"


# ------------------------------------------------------------------ semeadura e evidência
def test_semear_cria_itens_do_loop_em_ordem_e_espera_a_esteira_sem_registro(circle):
    s = circle.store
    r = absorcao.semear(s, time.time())
    alvo_loop = [t for t in absorcao.tecnicas() if t["alvo"] == "circulo" and not t.get("entregue")]
    assert len(r["itens"]) == len(alvo_loop) and r["pedidos"] == []
    assert set(r["aguardando_esteira"]) == {t["id"] for t in absorcao.tecnicas() if t["alvo"] == "esteira"}
    titulos = [row["titulo"] for row in s.q(f"SELECT titulo FROM roadmap WHERE id IN ({','.join('?' * len(r['itens']))}) ORDER BY ordem", r["itens"])]
    assert titulos[0].startswith("Fábrica: o Developer trabalha os pedidos")
    assert all(row["origem"] == "referencia" for row in s.q("SELECT origem FROM roadmap WHERE id IN (%s)" % ",".join(map(str, r["itens"]))))
    assert absorcao.semear(s, time.time())["itens"] == []                                   # idempotente
    ev = absorcao.evidencias(s, RAIZ)
    assert ev["tecnicas"]["PRE-1"]["estado"] == "pendente" and ev["tecnicas"]["VID-1"]["estado"] == "aguardando_esteira"
    assert ev["tecnicas"]["RANK-1"]["estado"] == "validada"                                 # entregue com a prova no repo


def test_evidencia_so_valida_com_pr_mergeado_e_o_teste_no_repositorio(circle, tmp_path):
    s = circle.store
    absorcao.semear(s, time.time())
    item = s.get(absorcao.KV)["tecnicas"]["ECC-2"]["item"]
    agora = time.time()
    s.x("INSERT INTO prs(number,item_id,status,titulo,created_at,updated_at) VALUES(?,?,?,?,?,?)", (901, item, "aberto", "x", agora, agora))
    assert absorcao.evidencias(s, tmp_path)["tecnicas"]["ECC-2"]["estado"] == "em_andamento"
    s.x("UPDATE prs SET status='mergeado' WHERE number=901")
    ev = absorcao.evidencias(s, tmp_path)
    assert ev["tecnicas"]["ECC-2"] == {**ev["tecnicas"]["ECC-2"], "estado": "sem_prova", "pr": 901} and "ECC-2" in ev["sem_prova"]
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_revisao_dupla.py").write_text("def test_x(): pass\n")
    assert absorcao.evidencias(s, tmp_path)["tecnicas"]["ECC-2"]["estado"] == "validada"
    ecc = s.get(absorcao.KV_EVIDENCIAS)["fontes"]["ecc"]
    assert ecc["validada"] == 1 and ecc["sem_prova"] == 1          # ECC-1 diz "entregue", mas neste repositório falta o teste: não conta


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_esteira_ao_lado_vira_cliente_e_recebe_pedidos_pela_caixa_com_vagas(circle, tmp_path, monkeypatch):
    s = circle.store
    loop_dir, est = tmp_path / "circulo", tmp_path / "esteira"
    loop_dir.mkdir()
    est.mkdir()
    _git(est, "init", "-q", "-b", "main")
    (est / "README.md").write_text("esteira\n")
    _git(est, "add", ".")
    _git(est, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x")
    _git(est, "remote", "add", "origin", "https://github.com/cmatosengenharia/esteira.git")
    from circulo import repo_cliente
    monkeypatch.setattr(repo_cliente, "_base", lambda pasta, remoto: "main")
    dados = tmp_path / "dados"
    r = absorcao.semear(s, time.time(), data_dir=dados, repo_dir=str(loop_dir))
    pid = absorcao.esteira_projeto(s)
    assert pid is not None and len(r["pedidos"]) == absorcao.ESTEIRA_ABERTOS_MAX
    arq = sorted((dados / "caixa").glob("absorcao-*.md"))
    assert len(arq) == absorcao.ESTEIRA_ABERTOS_MAX
    texto = arq[0].read_text(encoding="utf-8")
    assert texto.startswith(f"---\nprojeto: {pid}\n") and "Prova exigida" in texto and "THIRD_PARTY_NOTICES" in texto
    mvp_esteira = [t["id"] for t in absorcao.tecnicas() if t["alvo"] == "esteira"][:absorcao.ESTEIRA_ABERTOS_MAX]
    assert r["pedidos"] == mvp_esteira and all(absorcao.tecnicas()[0]["prio"] == "mvp" for _ in r["pedidos"])
    assert absorcao.evidencias(s)["tecnicas"][mvp_esteira[0]]["estado"] == "pedido_na_esteira"


# ------------------------------------------------------------------ varredura periódica
def test_parse_ranking_ancora_nas_pontas_e_aguenta_pipe_na_descricao():
    rs = absorcao.parse_ranking(RANKING)
    assert [r["posicao"] for r in rs] == [1, 2, 3, 4]
    assert rs[0]["url"] == "https://github.com/affaan-m/ECC" and rs[0]["estrelas"] == 294331
    assert rs[2]["descricao"] == "A single CLAUDE.md | with a pipe inside" and rs[2]["linguagem"] == "" and rs[2]["ultimo_commit"].startswith("2026-04")
    assert rs[3]["estrelas"] == 1200


def test_parse_awesome_so_ativo_nao_obsoleto_e_do_github():
    rs = absorcao.parse_awesome(CSV)
    assert [r["url"] for r in rs] == ["https://github.com/o/orq", "https://github.com/o/status"]
    assert rs[0]["util"] and not rs[1]["util"] and rs[0]["descricao"] == 'Runs agents, with "quotes"'


def test_varrer_ranking_manda_so_o_novo_para_o_garimpo_e_mede_quem_subiu(circle):
    s = circle.store
    agora = time.time()
    avisos = []
    r = absorcao.varrer_ranking(s, agora, baixar=lambda: RANKING, baixar_lista=lambda: CSV, reply=lambda m, k: avisos.append(m))
    urls = [n["url"] for n in r["novos"]]
    assert "https://github.com/affaan-m/ECC" not in urls                                       # já absorvido (alias do ECC)
    assert urls[:3] == ["https://github.com/NousResearch/hermes-agent", "https://github.com/multica-ai/andrej-karpathy-skills",
                        "https://github.com/x/video-seo"]
    assert urls[3] == "https://github.com/o/orq"                                               # da lista, categoria útil primeiro
    frentes = {n["url"]: n["frente"] for n in r["novos"]}
    assert frentes["https://github.com/x/video-seo"] == "venda"
    fila = {f["url"]: f for f in s.get(garimpo.KV)["fila"]}
    assert set(urls) <= set(fila) and fila["https://github.com/x/video-seo"]["motivo"].startswith("em alta no ranking Claude (#4")
    assert avisos and not absorcao.ranking_devido(s, agora) and absorcao.ranking_devido(s, agora + absorcao.A_CADA_RANKING)
    mais = RANKING.replace("| 1,200 |", "| 9,200 |").replace("| 259319 |", "| 259419 |")
    r2 = absorcao.varrer_ranking(s, agora + 86400, baixar=lambda: mais, baixar_lista=lambda: CSV)
    assert r2["novos"] == [] and r2["subindo"][0] == {"url": "https://github.com/x/video-seo", "ganho": 8000}


def test_varrer_ranking_fora_do_ar_nao_derruba_nem_apaga(circle):
    s = circle.store
    absorcao.varrer_ranking(s, 1.0, baixar=lambda: RANKING, baixar_lista=lambda: CSV)
    antes = s.get(absorcao.KV_RANKING)["estrelas"]

    def falha():
        raise OSError("403")
    r = absorcao.varrer_ranking(s, 2.0, baixar=falha, baixar_lista=falha)
    assert r["novos"] == [] and "ranking: 403" in r["erro"] and s.get(absorcao.KV_RANKING)["estrelas"] == antes


@pytest.mark.parametrize("modulo", ["absorcao", "absorcao_fontes", "escudo"])
def test_modulos_novos_nao_chamam_llm(modulo):
    txt = (RAIZ / "circulo" / f"{modulo}.py").read_text(encoding="utf-8")
    assert ".generate(" not in txt and "pick_model" not in txt

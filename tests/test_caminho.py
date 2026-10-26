"""Pedido em uma frase pelo console e o caminho dele até o merge: pedido → item → estudo → PR → CI → merge,
com o tempo de cada etapa e o que está esperando agora (reaproveita a caixa de entrada e o fio do rastro)."""
import json
import time

from circulo import caminho
from circulo.cli import main as cli
from circulo.rastro import elo


def _etapas(c):
    return {e["etapa"]: e for e in c["etapas"]}


def test_pedido_do_console_e_acompanhado_ate_o_merge_com_tempo_por_etapa(circle, tmp_path):
    s = circle.store
    t0 = float(int(time.time()) - 5 * 3600)
    arq = caminho.pedir(tmp_path, "Quero ver o caminho do meu pedido até o merge", agora=t0)
    assert arq.parent == tmp_path / "caixa" and arq.exists()
    assert s.one("SELECT COUNT(*) n FROM events")["n"] == 0           # o console nunca toca o banco

    c = caminho.caminho(s, arq.name, tmp_path, now=t0 + 60)
    assert c["texto"].startswith("Quero ver o caminho") and [e["etapa"] for e in c["etapas"]] == list(caminho.ETAPAS)
    assert _etapas(c)["pedido"]["em"] == t0 and c["esperando"]["etapa"] == "item"
    assert c["esperando"]["ha_s"] == 60

    circle.tick()                                                       # o loop lê a caixa e o pedido vira item
    item = s.one("SELECT id FROM roadmap WHERE titulo LIKE 'Quero ver o caminho%'")["id"]
    c = caminho.caminho(s, arq.name, tmp_path)
    assert c["item"] == item and _etapas(c)["item"]["em"] and c["esperando"]["etapa"] == "estudo"

    s.x("UPDATE roadmap SET estudo=? WHERE id=?", (json.dumps({"veredito": "adotar", "fontes": []}), item))
    elo(s, f"item:{item}", f"estudo:{item}", "estudou")
    estudo_em = s.one("SELECT em FROM elos WHERE relacao='estudou'")["em"]
    assert caminho.caminho(s, arq.name, tmp_path)["esperando"]["etapa"] == "pr"

    pr_em = estudo_em + 600
    s.x("INSERT INTO prs(number,project_id,titulo,branch,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
        (77, None, "t", f"circulo/fix-{item}-{int(pr_em)}", "aberto", pr_em, pr_em))
    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(77,'a',0,'checks em andamento: test','{}',?)", (pr_em + 60,))
    c = caminho.caminho(s, arq.name, tmp_path, now=pr_em + 300)
    assert c["esperando"]["etapa"] == "ci" and c["esperando"]["ha_s"] == 300
    assert _etapas(c)["pr"]["dur_s"] == 600                             # do estudo ao PR

    s.x("INSERT INTO merges(pr,sha,merged,reason,details,created_at) VALUES(77,'a',1,'checks verdes',  '{}',?)", (pr_em + 900,))
    c = caminho.caminho(s, arq.name, tmp_path, now=pr_em + 1000)
    assert c["esperando"] is None and _etapas(c)["merge"]["em"] == pr_em + 900
    assert _etapas(c)["ci"]["dur_s"] == 900 and abs(c["total_s"] - (pr_em + 900 - t0)) < 0.01

    tela = caminho.texto(c)
    assert "PR #77" in tela and f"item #{item}" in tela and "mergeado" in tela.lower()


def test_cli_pedir_e_caminho(circle, tmp_path, capsys):
    cli(["--data", str(tmp_path), "pedir", "Quero", "um", "atalho", "de", "busca"])
    nome = next((tmp_path / "caixa").iterdir()).name
    assert nome in capsys.readouterr().out
    cli(["--data", str(tmp_path), "caminho"])                          # sem referência: o último pedido do console
    out = capsys.readouterr().out
    assert "Quero um atalho de busca" in out and "Esperando agora" in out


def test_pedido_curto_demais_e_recusado_no_console(tmp_path):
    try:
        caminho.pedir(tmp_path, "oi")
    except ValueError:
        pass
    else:
        raise AssertionError("pedido curto deveria ser recusado")
    assert not (tmp_path / "caixa").exists()

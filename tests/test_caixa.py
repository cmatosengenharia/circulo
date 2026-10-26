"""Caixa de entrada por arquivo (26/10): pedido de fora do painel nunca toca o banco; vira arquivo e o loop o lê."""
import json

from circulo import caixa


def test_arquivos_da_caixa_viram_eventos_e_sao_arquivados(circle, tmp_path):
    s = circle.store
    pasta = tmp_path / "caixa"
    pasta.mkdir()
    (pasta / "b-pedido.md").write_text("Quero a pauta da daily às 8h, por assunto.\n", encoding="utf-8")
    (pasta / "a-missao.md").write_text("---\ntipo: missao\n---\nMigrar os chatbots da Blip para o Amazon Connect: plano.\n", encoding="utf-8")
    (pasta / "c-financas.txt").write_text("---\nprojeto: 1\n---\n38,90 ifood almoço\n", encoding="utf-8")
    (pasta / "vazio.md").write_text("oi\n", encoding="utf-8")
    (pasta / "ignorado.png").write_bytes(b"x")
    ids = caixa.ler(s, tmp_path, agora=1_700_000_000.0)
    assert len(ids) == 3
    evs = {r["id"]: (r["kind"], json.loads(r["payload"])) for r in s.q("SELECT id, kind, payload FROM events WHERE id IN (?,?,?)", ids)}
    kinds = sorted(k for k, _ in evs.values())
    assert kinds == ["mensagem", "mensagem", "novo_projeto"]
    missao = next(p for k, p in evs.values() if k == "novo_projeto")
    assert missao["pedido"].startswith("Migrar os chatbots") and missao["origem"] == "caixa"
    fin = next(p for k, p in evs.values() if k == "mensagem" and p.get("projeto") == 1)
    assert fin["text"] == "38,90 ifood almoço"
    loop_pid = s.one("SELECT id FROM projects WHERE kit='circulo'")["id"]
    daily = next(p for k, p in evs.values() if k == "mensagem" and p.get("projeto") == loop_pid)
    assert daily["text"].startswith("Quero a pauta")
    assert not [p for p in pasta.iterdir() if p.is_file() and p.suffix == ".md"]
    assert len(list((pasta / "lidos").iterdir())) == 3 and (pasta / "invalidos" / "vazio.md").exists()
    assert (pasta / "ignorado.png").exists()                                    # só .md/.txt entram
    assert caixa.ler(s, tmp_path) == [] and s.get("caixa_ultima")["eventos"] == ids


def test_sem_pasta_caixa_nada_acontece(circle, tmp_path):
    assert caixa.ler(circle.store, tmp_path) == []

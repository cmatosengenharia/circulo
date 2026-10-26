"""Pastas padrão por assunto no Mac (docs, decisões, links, notas, prompts), espelhando os assuntos do console."""
from circulo import assuntos, pastas


def test_cada_assunto_do_console_ganha_as_pastas_padrao(circle, tmp_path):
    s = circle.store
    assuntos.criar(s, "Squad", "minha squad: time, cerimônias e entregas")
    assuntos.criar(s, "Migração Blip / Amazon Connect", "migração dos chatbots")
    raiz = tmp_path / "Assuntos"
    pastas.manter(s, raiz)
    for nome in ("Squad", "Migração Blip - Amazon Connect"):
        assert sorted(p.name for p in (raiz / nome).iterdir() if p.is_dir()) == sorted(pastas.SUBPASTAS)
    indice = (raiz / pastas.INDICE).read_text(encoding="utf-8")
    assert "[Squad](<Squad/README.md>) — minha squad: time, cerimônias e entregas" in indice
    assert "[Migração Blip / Amazon Connect](<Migração Blip - Amazon Connect/README.md>) — migração dos chatbots" in indice


def test_mantida_assunto_novo_entra_e_arquivo_do_humano_fica(circle, tmp_path):
    s = circle.store
    assuntos.criar(s, "Squad")
    raiz = tmp_path / "Assuntos"
    pastas.manter(s, raiz)
    meu = raiz / "Squad" / "notas" / "2026-10-25-retro.md"
    meu.write_text("- [ ] cobrar o deploy", encoding="utf-8")
    assuntos.criar(s, "Tribo")
    pastas.manter(s, raiz)
    assert (raiz / "Tribo" / "decisoes").is_dir()
    assert meu.read_text(encoding="utf-8") == "- [ ] cobrar o deploy"
    assert "Tribo" in (raiz / pastas.INDICE).read_text(encoding="utf-8")


def test_vigia_mantem_as_pastas_em_cada_passagem(circle, monkeypatch):
    from circulo import vigia
    monkeypatch.delenv("CIRCULO_PASTA_ASSUNTOS", raising=False)
    assuntos.criar(circle.store, "Squad")
    vigia.Vigia(circle.ctx).rodar()
    assert (circle.ctx.data_dir / pastas.PASTA / "Squad" / "prompts").is_dir()

"""EXPO-1 (ADR 0006): as skills da Expo entram no catálogo com área `mobile`, só viram item de instalação quando um
produto pendente pede app móvel, o Jev só as escolhe quando a tarefa fala de app, iOS, Android ou Expo, e o prompt
registra a regra do futuro app da esteira: strangler fig (casca nativa, telas web trocadas uma a uma)."""

from circulo import skills

EXPO = ("expo-overview", "expo-router", "expo-ui", "expo-data-fetching", "expo-web-to-native")


def _skill(repo, nome, desc):
    p = repo / ".claude" / "skills" / nome
    p.mkdir(parents=True)
    (p / "SKILL.md").write_text(f"---\nname: {nome}\ndescription: {desc}\n---\n# {nome}\n", encoding="utf-8")


def _titulos(s, ids):
    return [s.one("SELECT titulo FROM roadmap WHERE id=?", (i,))["titulo"] for i in ids]


def test_expo_esta_no_catalogo_com_area_mobile_e_licenca_mit(circle):
    cat = {c["nome"]: c for c in skills.catalogo(circle.store)}
    for nome in EXPO:
        assert cat[nome]["area"] == "mobile" and cat[nome]["repo"] == "https://github.com/expo/skills" and cat[nome]["licenca"] == "MIT"
    assert "mobile" in skills.AREAS


def test_expo_so_e_pedida_quando_um_produto_pendente_pede_app_movel(circle, tmp_path):
    s = circle.store
    s.x("UPDATE roadmap SET status='feito'")
    ids = skills.pedir_instalacao(s, tmp_path, maximo=100)
    assert len(ids) == len(skills.CATALOGO) - len(EXPO) and not any("expo-" in t for t in _titulos(s, ids))
    assert not any("expo-" in t for t in _titulos(s, skills.pedir_instalacao(s, tmp_path, maximo=100)))   # itens de referência não contam
    s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,estudo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        ("Aprovar o vídeo pelo celular: app iOS e Android da esteira", "casca nativa", "pedido_cassio", "pendente", "", 1, "", 1.0, 1.0))
    ids2 = skills.pedir_instalacao(s, tmp_path, maximo=100)
    assert sorted(t.split()[3] for t in _titulos(s, ids2)) == sorted(EXPO)
    assert all("app móvel" in t and "expo/skills" in t for t in _titulos(s, ids2))


def test_jev_so_escolhe_expo_quando_a_tarefa_fala_de_app_e_o_prompt_registra_o_strangler_fig(circle, tmp_path):
    _skill(tmp_path, "expo-router", "navegação por arquivos em app Expo (React Native) para iOS e Android")
    _skill(tmp_path, "frontend-design", "interfaces com direção visual, tipografia e layout")
    dl = circle.ctx.dl
    e = skills.para_tarefa(dl, {"titulo": "Aprovação do vídeo no app Android da esteira", "detalhe": "fluxo entre telas"}, tmp_path)
    assert [x["nome"] for x in e] == ["expo-router"]
    txt = skills.texto_para_prompt(e)
    assert "strangler fig" in txt and "casca nativa" in txt and "/expo-router" in txt
    # divide palavras com a skill (navegação, arquivos) mas não fala de app, iOS, Android nem Expo: nenhuma
    assert skills.para_tarefa(dl, {"titulo": "Navegação por arquivos entre páginas do site", "detalhe": "navegação"}, tmp_path) == []
    assert "strangler" not in skills.texto_para_prompt([{"nome": "frontend-design", "descricao": "interfaces"}])

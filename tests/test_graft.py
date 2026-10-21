"""Graft (memória semântica local) ao lado do FTS: espelho na escrita, fusão RRF na busca, cache verificado para
item/estudo repetido, supersessão e manutenção. Sem o binário, tudo degrada para o índice lexical."""
import json
import os
import stat
import time

import pytest

from circulo import graft
from circulo.memoria import Memoria
from circulo.state import Store


@pytest.fixture
def graft_falso(tmp_path, monkeypatch):
    """Um `graft` de mentira no PATH: guarda os nós num JSON e responde aos subcomandos que o círculo usa.
    `retrieve` devolve os nós cujo título compartilha uma palavra com a consulta OU que estão marcados como
    'semanticamente próximos' pela palavra-chave `perto:<termo>`; `query` é STRONG quando um nó tem `forte:<termo>`."""
    pasta, db = tmp_path / "bin", tmp_path / "graft.json"
    pasta.mkdir()
    db.write_text("{}")
    (pasta / "graft").write_text(f'''#!/usr/bin/env python3
import json, sys, hashlib
DB = {str(db)!r}
d = json.load(open(DB)); d.setdefault("nos", {{}}); d.setdefault("log", []); d.setdefault("resolvidos", [])
a = sys.argv[1:]
def opt(nome, tudo=False):
    vs = [a[i+1] for i, x in enumerate(a) if x == nome and i + 1 < len(a)]
    return vs if tudo else (vs[0] if vs else None)
def out(r): print(json.dumps({{"status": 0, "result": r}})); json.dump(d, open(DB, "w"))
def palavras(t): return set(w.lower().strip('.,:;') for w in t.split() if len(w) > 3)
if a[0] == "insert":
    kws = opt("--keyword", True); h = hashlib.sha256((opt("--title") + opt("--body") + ",".join(sorted(kws))).encode()).hexdigest()[:16]
    dup = h in d["nos"]; d["nos"].setdefault(h, {{"title": opt("--title"), "body": opt("--body"), "keywords": kws, "state": "active"}})
    out({{"id_hex": h, "duplicate": dup, "n_kw_edges": len(kws), "n_sem_edges": 0}})
elif a[0] == "get":
    n = d["nos"].get(a[1]); out({{"id_hex": a[1], **n}} if n else {{}})
elif a[0] == "retrieve":
    q = palavras(a[1]); res = []
    for h, n in d["nos"].items():
        if n["state"] != "active": continue
        perto = any(k.startswith("perto:") and k[6:] in a[1].lower() for k in n["keywords"])
        if perto or q & palavras(n["title"]): res.append({{"id_hex": h, "title": n["title"], "score": 0.03 if perto else 0.02, "keywords": n["keywords"]}})
    out({{"results": sorted(res, key=lambda x: -x["score"]), "distinct_keywords": []}})
elif a[0] == "query":
    for h, n in d["nos"].items():
        if n["state"] == "active" and any(k.startswith("forte:") and k[6:] in a[1].lower() for k in n["keywords"]):
            out({{"hit": "STRONG", "id_hex": h, "title": n["title"], "body": n["body"], "signals": {{"s_vec": 0.9, "s_lex": 0.3}}}}); sys.exit(0)
    out({{"hit": "MISS", "signals": {{"s_vec": 0.1}}, "fallback_retrieve": {{"results": []}}}})
elif a[0] == "explore":
    out({{"nodes": [{{"id_hex": h, "title": n["title"], "score": 1.0, "depth_reached": 1}} for h, n in d["nos"].items() if n["state"] == "active"][:4], "edges": []}})
elif a[0] == "stats":
    out({{"n_nodes": len(d["nos"]), "n_edges": 0, "n_keywords": 0}})
elif a[0] == "maintain" and a[1] == "resolve":
    d["resolvidos"].append(a[2:])
    alvo = opt("--node") or (a[2] if not a[2].startswith("--") else None)
    if opt("--action") == "supersede" and alvo in d["nos"]: d["nos"][alvo]["state"] = "superseded"
    if opt("--action") == "supersede_a": d["nos"][d["cands"][alvo][0]]["state"] = "superseded"
    out({{"nodes": []}})
elif a[0] == "maintain" and a[1] == "apply-safe":
    out({{"purged_retired": 0, "graph": {{"n_nodes": len(d["nos"]), "n_edges": 0, "n_keywords": 0}}}})
elif a[0] == "maintain" and a[1] == "scan":
    cands, vistos = [], {{}}
    ativos = [(h, n) for h, n in d["nos"].items() if n["state"] == "active"]
    for i, (h1, n1) in enumerate(ativos):
        for h2, n2 in ativos[i+1:]:
            if palavras(n1["title"]) == palavras(n2["title"]):
                cid = hashlib.sha256((h1 + h2).encode()).hexdigest()[:16]; vistos[cid] = [h1, h2]
                cands.append({{"id": cid, "kind": "near_duplicate", "score": 0.99, "nodes": [{{"id_hex": h1, "title": n1["title"]}}, {{"id_hex": h2, "title": n2["title"]}}]}})
    d["cands"] = vistos
    out({{"summary": {{"pending": len(cands)}}, "candidates": cands}})
else:
    print(json.dumps({{"status": 1, "error": "desconhecido"}})); sys.exit(3)
''')
    (pasta / "graft").chmod((pasta / "graft").stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{pasta}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CIRCULO_GRAFT", "1")
    graft._estado.update(falhou_em=0.0, aquecido=False, chamadas=0)
    return db


def _nos(db):
    return json.load(open(db))["nos"]


def _marcar(db, gid, keyword):
    """Simula o que os vetores fariam: marca um nó como semanticamente próximo (`perto:`) ou idêntico (`forte:`)."""
    d = json.load(open(db))
    d["nos"][gid]["keywords"].append(keyword)
    json.dump(d, open(db, "w"))


def test_sem_graft_tudo_degrada_para_o_fts(monkeypatch):
    monkeypatch.setenv("CIRCULO_GRAFT", "0")
    assert not graft.ligado() and graft.inserir("licao", 1, "t", "c") is None and graft.recuperar("x") == [] and graft.consultar("x") is None
    m = Memoria(Store(":memory:"))
    assert m.graft is False and m.entorno("qualquer coisa") == [] and m.espelhar_pendentes() == 0


def test_escrita_espelha_no_graft_e_conteudo_novo_supersede_o_antigo(graft_falso):
    s = Store(":memory:")
    m = Memoria(s)
    assert m.graft
    m._gravar("licao", 7, "Limite da conta do Claude Code", "espera o reset", "aberta", time.time())
    row = s.one("SELECT graft_id FROM memoria WHERE tipo='licao' AND ref='7'")
    nos = _nos(graft_falso)
    assert row["graft_id"] in nos and "circulo:licao:7" in nos[row["graft_id"]]["keywords"] and "tipo:licao" in nos[row["graft_id"]]["keywords"]
    m._gravar("licao", 7, "Limite da conta do Claude Code", "espera o reset e avisa", "validada", time.time())
    nos = _nos(graft_falso)
    novo = s.one("SELECT graft_id FROM memoria WHERE tipo='licao' AND ref='7'")["graft_id"]
    assert novo != row["graft_id"] and nos[row["graft_id"]]["state"] == "superseded" and nos[novo]["state"] == "active"
    assert "resultado:validada" in nos[novo]["keywords"]


def test_busca_funde_lexical_e_semantica_por_rrf(graft_falso):
    s = Store(":memory:")
    m = Memoria(s)
    agora = time.time()
    m._gravar("licao", 1, "Developer: limite de uso da conta", "esperar o reset", "validada", agora)
    m._gravar("licao", 2, "Gate: CI demorou", "esperar", "aberta", agora)
    # só o graft "sabe" que 'token estourou' fala do limite da conta: marca a proximidade semântica no nó
    gid = s.one("SELECT graft_id FROM memoria WHERE ref='1'")["graft_id"]
    _marcar(graft_falso, gid, "perto:token estourou")
    hits = m.buscar("token estourou")
    assert hits and hits[0]["tipo"] == "licao" and hits[0]["ref"] == "1"           # o FTS sozinho não acharia nada
    hits = m.buscar("CI demorou")
    assert hits[0]["ref"] == "2"                                                  # lexical continua mandando quando é o caso


def test_item_repetido_dito_com_outras_palavras_e_pego_pelo_cache_verificado(graft_falso):
    s = Store(":memory:")
    m = Memoria(s)
    agora = time.time()
    iid = s.x("INSERT INTO roadmap(titulo,detalhe,origem,status,evidencia,ordem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
              ("Pausar o Developer quando a cota da assinatura acabar", "d", "loop", "pendente", "", 1, agora, agora))
    m._gravar("item", iid, "Pausar o Developer quando a cota da assinatura acabar", "d", "pendente", agora)
    gid = s.one("SELECT graft_id FROM memoria WHERE tipo='item'")["graft_id"]
    _marcar(graft_falso, gid, "forte:esperar o reset")
    par = m.item_parecido("Fazer o loop esperar o reset do limite de uso")
    assert par and par["id"] == iid and par["semantico"] and par["parecido"] >= 0.9
    assert m.item_parecido("Fazer o loop esperar o reset do limite de uso", ignorar=iid) is None   # o próprio item não é repetição


def test_manutencao_resolve_duplicata_do_mesmo_registro_e_deixa_o_resto_para_o_medico(graft_falso):
    s = Store(":memory:")
    graft.inserir("licao", 9, "Ruff reclamou de import", "v1")
    graft.inserir("licao", 9, "Ruff reclamou de import", "v2 com mais detalhe")      # mesmo registro, conteúdo novo sem supersede
    graft.inserir("licao", 10, "Pytest sem alvo", "a")
    graft.inserir("item", 3, "Pytest sem alvo", "b")                                 # registros diferentes, título igual: humano decide
    st = graft.manter(s, a_cada=0)
    assert st["resolvidos"] == 1 and len(st["pendentes"]) == 1 and st["pendentes"][0]["kind"] == "near_duplicate"
    nos = _nos(graft_falso)
    assert sum(1 for n in nos.values() if n["state"] == "superseded") == 1
    assert graft.manter(s, agora=time.time() + 10, a_cada=3600) is None            # dentro do intervalo não roda de novo


def test_espelha_linhas_antigas_aos_poucos_e_entorno_vem_do_grafo(graft_falso):
    s = Store(":memory:")
    m = Memoria(s)
    agora = time.time()
    for i in range(3):
        s.x("INSERT INTO memoria(tipo,ref,titulo,texto,resultado,peso,em,atualizado) VALUES('licao',?,?,?,'aberta',1,?,?)", (100 + i, f"Lição antiga {i}", "t", agora, agora))
    assert m.espelhar_pendentes(limite=2) == 2 and m.espelhar_pendentes() == 1 and m.espelhar_pendentes() == 0
    assert s.one("SELECT COUNT(*) n FROM memoria WHERE graft_id IS NULL")["n"] == 0
    ent = m.entorno("Lição antiga")
    assert ent and all(e["tipo"] == "licao" for e in ent) and ent[0]["profundidade"] == 1
    assert m.resumo()["graft"]["ligado"] and m.resumo()["graft"]["chamadas"] > 0


def test_graft_caido_pausa_e_nunca_derruba_a_memoria(tmp_path, monkeypatch):
    pasta = tmp_path / "bin"
    pasta.mkdir()
    (pasta / "graft").write_text("#!/bin/sh\nexit 1\n")
    (pasta / "graft").chmod(0o755)
    monkeypatch.setenv("PATH", f"{pasta}{os.pathsep}{os.environ['PATH']}")
    graft._estado.update(falhou_em=0.0, aquecido=True, chamadas=0)
    m = Memoria(Store(":memory:"))
    m._gravar("licao", 1, "Ruff reclamou de import", "no worktree", "aberta", time.time())
    assert m.s.one("SELECT graft_id FROM memoria")["graft_id"] is None
    assert graft.resumo(m.s)["pausado_ate"] and graft.recuperar("ruff") == [] and m.buscar("ruff reclamou")  # busca lexical segue
